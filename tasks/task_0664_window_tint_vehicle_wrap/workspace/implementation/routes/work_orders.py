"""Work orders: scheduling, install lifecycle, payment dimension, wrap proofs."""
from flask import Blueprint, request

import db
import errors
from errors import ApiError
from middleware import get_identity, require_role, get_json_body, parse_pagination
from models import stamp_create, serialize, touch
from response import success, success_list
from services import common
from services import calculations
from services import fleet as fleet_svc
from services import quote as quote_svc
from services import workorder as wo_svc

bp = Blueprint("work_orders", __name__)


def _installer_owns(role, user_id, work_order):
    """Installer self-action: X-User-ID must equal the assigned installer's
    installer_user_id."""
    if role == "Installer":
        installer = db.installers.get(work_order["installer_id"])
        common.check_installer_self(role, user_id, installer)


# ---- schedule ---------------------------------------------------------------
@bp.route("/work-orders", methods=["POST"])
def schedule_work_order():
    user_id, role = get_identity()
    require_role(role, {"ShopManager"})
    body = get_json_body()
    quote_id = common.require_string(body, "quote_id")
    bay_id = common.require_string(body, "bay_id")
    installer_id = common.require_string(body, "installer_id")
    scheduled_start_raw = common.require_string(body, "scheduled_start")

    # Existence: body FKs left to right.
    quote = common.get_or_404(db.quotes, quote_id)
    bay = common.get_or_404(db.bays, bay_id)
    installer = common.get_or_404(db.installers, installer_id)

    scheduled_start = db.parse_iso(scheduled_start_raw)
    if scheduled_start is None:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "scheduled_start must be an ISO 8601 datetime.")

    # Observe TTL expiry on the quote (priced-but-aged).
    quote_svc.observe_ttl_expiry(quote)

    # OCC version check (priority 21) before quote-expiry/quote-accepted.
    _check_quote_version(quote, body)

    # Quote-expiry guard (priority 22).
    if quote["status"] == "EXPIRED":
        raise ApiError(errors.ERR_QUOTE_EXPIRED, 409, "Quote is expired.")

    # Quote must be ACCEPTED (priority 50).
    if quote["status"] != "ACCEPTED":
        raise ApiError(errors.ERR_QUOTE_NOT_ACCEPTED, 409, "Quote is not ACCEPTED.")

    # Derive order attributes from the source quote.
    primary_service_type, _pkg = wo_svc.primary_service_type_and_package(quote_id)
    duration_minutes = wo_svc.aggregate_duration(quote_id)
    cure_buffer_minutes = wo_svc.aggregate_cure_buffer(quote_id)
    cure_hours = wo_svc.max_cure_hours(quote_id)
    fleet_account_id = quote.get("fleet_account_id")
    total_due_cents = quote["total_due_cents"]

    # Installer certification (priority 41).
    if primary_service_type not in installer["certified_service_types"]:
        raise ApiError(errors.ERR_INSTALLER_NOT_CERTIFIED, 422,
                       "Installer is not certified for the order's primary_service_type.")

    # Bay overlap (priority 42).
    bay_start = scheduled_start
    bay_end = wo_svc._add_minutes(scheduled_start, duration_minutes + cure_buffer_minutes)
    for s, e in wo_svc.bay_intervals(bay_id):
        if wo_svc.overlaps(bay_start, bay_end, s, e):
            raise ApiError(errors.ERR_BAY_TIME_CONFLICT, 409, "Bay interval overlaps an existing booking.")

    # Installer overlap (priority 43).
    inst_start = wo_svc._add_minutes(scheduled_start, -calculations.INSTALLER_REST_BUFFER_MINUTES)
    inst_end = wo_svc._add_minutes(scheduled_start, duration_minutes)
    for s, e in wo_svc.installer_intervals(installer_id):
        if wo_svc.overlaps(inst_start, inst_end, s, e):
            raise ApiError(errors.ERR_INSTALLER_TIME_CONFLICT, 409,
                           "Installer interval overlaps an existing booking.")

    # Fleet credit (priority 60).
    if fleet_account_id:
        fleet = db.fleet_accounts.get(fleet_account_id)
        held = fleet_svc.held_credit_cents(fleet_account_id)
        provisional_available = fleet["credit_limit_cents"] - held
        if provisional_available < total_due_cents:
            raise ApiError(errors.ERR_FLEET_CREDIT_EXCEEDED, 409,
                           "Scheduling would push fleet held credit above the limit.")

    # All gates pass — create the WorkOrder.
    cure_complete_at = calculations.estimated_cure_complete_at(
        scheduled_start, duration_minutes, cure_hours)

    rec = {
        "quote_id": quote_id,
        "bay_id": bay_id,
        "installer_id": installer_id,
        "fleet_account_id": fleet_account_id,
        "primary_service_type": primary_service_type,
        "scheduled_start": db.iso(scheduled_start),
        "duration_minutes": duration_minutes,
        "cure_buffer_minutes": cure_buffer_minutes,
        "total_due_cents": total_due_cents,
        "install_status": "SCHEDULED",
        "payment_status": "DEPOSIT_DUE",
        "actual_started_at": None,
        "actual_completed_at": None,
        "cure_complete_at": db.iso(cure_complete_at),
        "warranty_expires_at": None,
    }
    stamp_create(rec)
    db.work_orders[rec["id"]] = rec

    # Side effects: reserve bay minutes; hold fleet credit; convert quote.
    bay["reserved_minutes"] += duration_minutes + cure_buffer_minutes
    touch(bay)

    if fleet_account_id:
        fleet = db.fleet_accounts[fleet_account_id]
        fleet["held_credit_cents"] += total_due_cents
        touch(fleet)

    quote["status"] = "CONVERTED"
    touch(quote)

    return success(serialize(rec), 201)


def _check_quote_version(quote, body):
    expected = common.require_field(body, "expected_quote_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "expected_quote_version must be an integer.")
    if expected != quote["version"]:
        raise ApiError(errors.ERR_STALE_VERSION, 412, "expected_quote_version does not match the quote.")


def _check_wo_version(work_order, body):
    expected = common.require_field(body, "expected_work_order_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "expected_work_order_version must be an integer.")
    if expected != work_order["version"]:
        raise ApiError(errors.ERR_STALE_VERSION, 412, "expected_work_order_version does not match the work order.")


# ---- read / list ------------------------------------------------------------
@bp.route("/work-orders", methods=["GET"])
def list_work_orders():
    user_id, role = get_identity()
    require_role(role, {"ShopManager", "FleetManager", "Installer"})
    limit, offset = parse_pagination()
    items = list(db.work_orders.values())

    fa = request.args.get("fleet_account_id")
    by = request.args.get("bay_id")
    inst = request.args.get("installer_id")
    qid = request.args.get("quote_id")
    if fa is not None:
        items = [w for w in items if w.get("fleet_account_id") == fa]
    if by is not None:
        items = [w for w in items if w["bay_id"] == by]
    if inst is not None:
        items = [w for w in items if w["installer_id"] == inst]
    if qid is not None:
        items = [w for w in items if w["quote_id"] == qid]

    if role == "FleetManager":
        owned = {f["id"] for f in db.fleet_accounts.values() if f["fleet_manager_user_id"] == user_id}
        items = [w for w in items if w.get("fleet_account_id") in owned]
    elif role == "Installer":
        owned = {i["id"] for i in db.installers.values() if i["installer_user_id"] == user_id}
        items = [w for w in items if w["installer_id"] in owned]

    items.sort(key=lambda w: (w["created_at"], w["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(w) for w in page], limit, offset, total, 200)


@bp.route("/work-orders/<rid>", methods=["GET"])
def get_work_order(rid):
    user_id, role = get_identity()
    require_role(role, {"ShopManager", "Installer", "Customer", "FleetManager"})
    wo = common.get_or_404(db.work_orders, rid)
    if role == "Customer":
        quote = db.quotes.get(wo["quote_id"])
        vehicle = db.vehicle_profiles.get(quote["vehicle_profile_id"]) if quote else None
        common.check_customer_owns_vehicle(role, user_id, vehicle)
    elif role == "FleetManager":
        fleet = db.fleet_accounts.get(wo.get("fleet_account_id"))
        if fleet is None:
            raise ApiError(errors.ERR_NOT_RESOURCE_OWNER, 403, "FleetManager does not own this work order.")
        common.check_fleet_manager_owns(role, user_id, fleet)
    elif role == "Installer":
        _installer_owns(role, user_id, wo)
    return success(serialize(wo), 200)


# ---- install lifecycle ------------------------------------------------------
@bp.route("/work-orders/<rid>/start", methods=["POST"])
def start_install(rid):
    user_id, role = get_identity()
    require_role(role, {"Installer"})
    wo = common.get_or_404(db.work_orders, rid)
    _installer_owns(role, user_id, wo)

    if wo["install_status"] != "SCHEDULED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "WorkOrder is not SCHEDULED.")

    # Proof gate (priority 32): if primary package requires_proof, an APPROVED
    # WrapProof must exist for this order.
    _st, pkg = wo_svc.primary_service_type_and_package(wo["quote_id"])
    if pkg is not None and pkg["requires_proof"]:
        has_approved = any(p["work_order_id"] == rid and p["status"] == "APPROVED"
                           for p in db.wrap_proofs.values())
        if not has_approved:
            raise ApiError(errors.ERR_PROOF_NOT_APPROVED, 409, "No APPROVED WrapProof for this order.")

    # Clock must have reached scheduled_start.
    if db.now() < db.parse_iso(wo["scheduled_start"]):
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Logical clock has not reached scheduled_start.")

    wo["install_status"] = "IN_PROGRESS"
    wo["actual_started_at"] = db.iso(db.now())
    touch(wo)
    return success(serialize(wo), 200)


@bp.route("/work-orders/<rid>/complete-install", methods=["POST"])
def complete_install(rid):
    user_id, role = get_identity()
    require_role(role, {"Installer"})
    wo = common.get_or_404(db.work_orders, rid)
    _installer_owns(role, user_id, wo)

    if wo["install_status"] != "IN_PROGRESS":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "WorkOrder is not IN_PROGRESS.")

    completed = db.now()
    wo["actual_completed_at"] = db.iso(completed)
    wo["install_status"] = "CURING"

    cure_hours = wo_svc.max_cure_hours(wo["quote_id"])
    wo["cure_complete_at"] = db.iso(calculations.actual_cure_complete_at(completed, cure_hours))

    warranty_days = wo_svc.max_warranty_days(wo["quote_id"])
    wo["warranty_expires_at"] = db.iso(calculations.warranty_expires_at(completed, warranty_days))

    touch(wo)
    return success(serialize(wo), 200)


@bp.route("/work-orders/<rid>/release", methods=["POST"])
def release(rid):
    user_id, role = get_identity()
    require_role(role, {"ShopManager"})
    wo = common.get_or_404(db.work_orders, rid)

    if wo["install_status"] != "CURING":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "WorkOrder is not CURING.")

    if db.now() < db.parse_iso(wo["cure_complete_at"]):
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Logical clock has not reached cure_complete_at.")

    wo["install_status"] = "COMPLETED"
    # Release bay capacity (held credit stays until invoiced).
    bay = db.bays.get(wo["bay_id"])
    if bay is not None:
        bay["reserved_minutes"] -= (wo["duration_minutes"] + wo["cure_buffer_minutes"])
        touch(bay)
    touch(wo)
    return success(serialize(wo), 200)


@bp.route("/work-orders/<rid>/cancel", methods=["POST"])
def cancel(rid):
    user_id, role = get_identity()
    require_role(role, {"ShopManager"})
    wo = common.get_or_404(db.work_orders, rid)
    body = get_json_body()

    if wo["install_status"] not in ("SCHEDULED", "IN_PROGRESS"):
        raise ApiError(errors.ERR_INVALID_STATE, 409, "WorkOrder is not SCHEDULED or IN_PROGRESS.")

    _check_wo_version(wo, body)

    wo["install_status"] = "CANCELLED"

    # Compensating release: bay minutes.
    bay = db.bays.get(wo["bay_id"])
    if bay is not None:
        bay["reserved_minutes"] -= (wo["duration_minutes"] + wo["cure_buffer_minutes"])
        touch(bay)

    # Compensating release: fleet credit.
    if wo.get("fleet_account_id"):
        fleet = db.fleet_accounts.get(wo["fleet_account_id"])
        if fleet is not None:
            fleet["held_credit_cents"] -= wo["total_due_cents"]
            touch(fleet)

    # Source quote reverts to ACCEPTED so it can be scheduled afresh.
    quote = db.quotes.get(wo["quote_id"])
    if quote is not None:
        quote["status"] = "ACCEPTED"
        touch(quote)

    touch(wo)
    return success(serialize(wo), 200)


# ---- payment dimension ------------------------------------------------------
@bp.route("/work-orders/<rid>/pay-deposit", methods=["POST"])
def pay_deposit(rid):
    user_id, role = get_identity()
    require_role(role, {"Customer"})
    wo = common.get_or_404(db.work_orders, rid)
    # Ownership: customer owning the underlying vehicle.
    quote = db.quotes.get(wo["quote_id"])
    vehicle = db.vehicle_profiles.get(quote["vehicle_profile_id"]) if quote else None
    common.check_customer_owns_vehicle(role, user_id, vehicle)
    body = get_json_body()

    if wo["payment_status"] != "DEPOSIT_DUE":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "WorkOrder payment_status is not DEPOSIT_DUE.")

    amount_cents = common.require_int(body, "amount_cents")
    required = quote["deposit_required_cents"]
    if amount_cents != required:
        raise ApiError(errors.ERR_DEPOSIT_AMOUNT_MISMATCH, 422,
                       "amount_cents must equal the source quote's deposit_required_cents.")

    wo["payment_status"] = "DEPOSIT_PAID"
    touch(wo)
    return success(serialize(wo), 200)


@bp.route("/work-orders/<rid>/invoice", methods=["POST"])
def invoice(rid):
    user_id, role = get_identity()
    require_role(role, {"ShopManager"})
    wo = common.get_or_404(db.work_orders, rid)

    if wo["payment_status"] != "DEPOSIT_PAID":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "WorkOrder payment_status is not DEPOSIT_PAID.")
    # Cross-dimension guard: requires install_status COMPLETED.
    if wo["install_status"] != "COMPLETED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "WorkOrder install_status is not COMPLETED.")

    wo["payment_status"] = "INVOICED"
    touch(wo)
    return success(serialize(wo), 200)


@bp.route("/work-orders/<rid>/settle", methods=["POST"])
def settle(rid):
    user_id, role = get_identity()
    require_role(role, {"ShopManager"})
    wo = common.get_or_404(db.work_orders, rid)

    if wo["payment_status"] != "INVOICED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "WorkOrder payment_status is not INVOICED.")

    wo["payment_status"] = "SETTLED"
    # Release held fleet credit for good.
    if wo.get("fleet_account_id"):
        fleet = db.fleet_accounts.get(wo["fleet_account_id"])
        if fleet is not None:
            fleet["held_credit_cents"] -= wo["total_due_cents"]
            touch(fleet)
    touch(wo)
    return success(serialize(wo), 200)


# ---- wrap proofs ------------------------------------------------------------
@bp.route("/work-orders/<rid>/proofs", methods=["POST"])
def submit_proof(rid):
    user_id, role = get_identity()
    require_role(role, {"Installer"})
    wo = common.get_or_404(db.work_orders, rid)
    _installer_owns(role, user_id, wo)
    body = get_json_body()
    design_ref = common.require_string(body, "design_ref")

    # The order's primary package must require_proof, else ERR_PROOF_NOT_REQUIRED.
    _st, pkg = wo_svc.primary_service_type_and_package(wo["quote_id"])
    if pkg is None or not pkg["requires_proof"]:
        raise ApiError(errors.ERR_PROOF_NOT_REQUIRED, 409,
                       "Order's primary package does not require a proof.")

    # Determine the latest proof for this order (max revision_round; tie-break
    # latest created_at).
    order_proofs = [p for p in db.wrap_proofs.values() if p["work_order_id"] == rid]
    latest = None
    for p in order_proofs:
        if latest is None:
            latest = p
        elif p["revision_round"] > latest["revision_round"]:
            latest = p
        elif p["revision_round"] == latest["revision_round"]:
            if (p["created_at"], p["id"]) > (latest["created_at"], latest["id"]):
                latest = p

    if latest is None:
        # First proof on the order: revision_round 1.
        revision_round = 1
    else:
        # Resubmission only when the latest proof is CHANGES_REQUESTED.
        if latest["status"] != "CHANGES_REQUESTED":
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Latest proof is not CHANGES_REQUESTED; cannot resubmit.")
        revision_round = latest["revision_round"] + 1

    rec = {
        "work_order_id": rid,
        "design_ref": design_ref,
        "revision_round": revision_round,
        "status": "PROOF_SUBMITTED",
    }
    stamp_create(rec)
    db.wrap_proofs[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.route("/work-orders/<rid>/proofs", methods=["GET"])
def list_proofs(rid):
    user_id, role = get_identity()
    require_role(role, {"ShopManager", "Installer", "Customer"})
    wo = common.get_or_404(db.work_orders, rid)
    if role == "Customer":
        quote = db.quotes.get(wo["quote_id"])
        vehicle = db.vehicle_profiles.get(quote["vehicle_profile_id"]) if quote else None
        common.check_customer_owns_vehicle(role, user_id, vehicle)
    elif role == "Installer":
        _installer_owns(role, user_id, wo)
    limit, offset = parse_pagination()
    items = [p for p in db.wrap_proofs.values() if p["work_order_id"] == rid]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(p) for p in page], limit, offset, total, 200)
