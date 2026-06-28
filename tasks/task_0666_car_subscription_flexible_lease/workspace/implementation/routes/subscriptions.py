"""Subscription lifecycle + billing axis routes (PRD §3.4, §3.5, §3.11, §3.12, §3.13)."""
from flask import Blueprint, request

import errors
from clock import clock
from db import db, stamp_create, touch
from middleware import get_identity, require_roles, parse_pagination
from response import object_response, array_response
from services import calc, serialize, common
from services import invoices as inv_svc

bp = Blueprint("subscriptions", __name__)

ELIGIBLE = {"APPROVED", "CONDITIONAL"}


def _check_owner(role, user_id, subscription):
    """Priority 3: entity_backed Member must own the subscription (PRD §2.1)."""
    if role == "Member" and user_id != subscription["applicant_id"]:
        raise errors.not_resource_owner()


# --------------------------- create / read ---------------------------
@bp.route("/subscriptions", methods=["POST"])
def create_subscription():
    _, role = get_identity()
    require_roles(role, {"Member", "PlatformAdmin"})  # shared (PRD §3.4)
    body = common.get_body()
    applicant_id = common.require_str(body, "applicant_id")
    plan_id = common.require_str(body, "plan_id")
    common.resolve(db.applicants, applicant_id)
    common.resolve(db.subscription_plans, plan_id)

    rec = {
        "applicant_id": applicant_id,
        "plan_id": plan_id,
        "active_vehicle_id": None,
        "lifecycle_status": "DRAFT",      # PRD §3.4 defaults
        "billing_status": "CURRENT",
        "deposit_held_cents": 0,
        "swaps_used": 0,
        "cycle_start_iso": None,
        "term_start_iso": None,
    }
    stamp_create(rec)
    db.subscriptions[rec["id"]] = rec
    return object_response(serialize.serialize_subscription(rec), 201)


@bp.route("/subscriptions/<sid>", methods=["GET"])
def get_subscription(sid):
    _, role = get_identity()
    require_roles(role, {"PlatformAdmin", "FleetOperator", "BillingAdmin", "Member"})
    rec = common.resolve(db.subscriptions, sid)
    return object_response(serialize.serialize_subscription(rec))


@bp.route("/subscriptions", methods=["GET"])
def list_subscriptions():
    _, role = get_identity()
    require_roles(role, {"PlatformAdmin", "FleetOperator", "BillingAdmin", "Member"})
    limit, offset = parse_pagination()
    records = list(db.subscriptions.values())
    records = common.filter_equals(records, "applicant_id", request.args.get("applicant_id"))
    records = common.filter_equals(records, "plan_id", request.args.get("plan_id"))
    records = common.filter_equals(records, "active_vehicle_id", request.args.get("active_vehicle_id"))
    records = common.filter_equals(records, "lifecycle_status", request.args.get("lifecycle_status"))
    records = common.filter_equals(records, "billing_status", request.args.get("billing_status"))
    page, total = common.paginate_sorted(records, limit, offset)
    return array_response([serialize.serialize_subscription(r) for r in page], limit, offset, total)


# --------------------------- assign-vehicle ---------------------------
@bp.route("/subscriptions/<sid>/assign-vehicle", methods=["POST"])
def assign_vehicle(sid):
    _, role = get_identity()
    require_roles(role, {"FleetOperator"})  # exclusive (PRD §3.4)
    sub = common.resolve(db.subscriptions, sid)
    body = common.get_body()
    vehicle_id = common.require_str(body, "vehicle_id")
    expected_version = common.require_int(body, "expected_vehicle_version")
    vehicle = common.resolve(db.vehicles, vehicle_id)

    # priority 6: state — DRAFT only.
    if sub["lifecycle_status"] != "DRAFT":
        raise errors.invalid_state("Subscription must be DRAFT to assign a vehicle.")
    # priority 7: plan-tier match (ERR_PLAN_MISMATCH) — enforced only on initial assign.
    if vehicle["plan_id"] != sub["plan_id"]:
        raise errors.plan_mismatch()
    # priority 8: applicant eligibility (ERR_NOT_ELIGIBLE).
    applicant = db.applicants[sub["applicant_id"]]
    if applicant["eligibility_status"] not in ELIGIBLE:
        raise errors.not_eligible()
    # vehicle must be AVAILABLE (state of target — ERR_INVALID_STATE).
    if vehicle["status"] != "AVAILABLE":
        raise errors.invalid_state("Target vehicle must be AVAILABLE.")
    # priority 15: OCC on Vehicle.version (ERR_STALE_VEHICLE_VERSION).
    if expected_version != vehicle["version"]:
        raise errors.stale_vehicle_version()

    # Cascade: Vehicle AVAILABLE->RESERVED (PRD §3.4).
    vehicle["status"] = "RESERVED"
    vehicle["active_subscription_id"] = sub["id"]
    touch(vehicle)
    sub["active_vehicle_id"] = vehicle["id"]
    sub["deposit_held_cents"] = applicant["required_deposit_cents"] or 0
    sub["lifecycle_status"] = "PENDING_DELIVERY"
    touch(sub)
    common.recompute_fleet(vehicle["fleet_id"])
    return object_response(serialize.serialize_subscription(sub))


# --------------------------- activate ---------------------------
@bp.route("/subscriptions/<sid>/activate", methods=["POST"])
def activate(sid):
    _, role = get_identity()
    require_roles(role, {"FleetOperator"})  # exclusive (PRD §3.5)
    sub = common.resolve(db.subscriptions, sid)
    if sub["lifecycle_status"] != "PENDING_DELIVERY":
        raise errors.invalid_state("Subscription must be PENDING_DELIVERY to activate.")
    vehicle = db.vehicles.get(sub["active_vehicle_id"])
    if vehicle is None or vehicle["status"] != "RESERVED":
        raise errors.invalid_state("Active vehicle must be RESERVED.")
    # A DELIVERY DeliverySlot for this subscription in SCHEDULED state must exist (PRD §3.5).
    slot = None
    for ds in db.delivery_slots.values():
        if (ds["subscription_id"] == sub["id"] and ds["kind"] == "DELIVERY"
                and ds["status"] == "SCHEDULED"):
            slot = ds
            break
    if slot is None:
        raise errors.invalid_state("A SCHEDULED DELIVERY slot is required to activate.")

    # Cascade (PRD §3.5).
    vehicle["status"] = "ASSIGNED"
    touch(vehicle)
    slot["status"] = "FULFILLED"
    touch(slot)
    now = clock.now_iso()
    sub["term_start_iso"] = now
    sub["cycle_start_iso"] = now
    sub["lifecycle_status"] = "ACTIVE"
    touch(sub)
    # Open BillingCycle #1 (PRD §3.5).
    cycle = {
        "subscription_id": sub["id"],
        "vehicle_id": vehicle["id"],
        "cycle_index": 1,
        "cycle_start_iso": now,
        "cycle_end_iso": None,
        "odometer_start_miles": vehicle["odometer_miles"],
        "odometer_end_miles": None,
        "status": "OPEN",
        "overage_cents": 0,
    }
    stamp_create(cycle)
    db.billing_cycles[cycle["id"]] = cycle
    # utilization unchanged (RESERVED and ASSIGNED both in_use) but recompute for version bump.
    common.recompute_fleet(vehicle["fleet_id"])
    return object_response(serialize.serialize_subscription(sub))


# --------------------------- initiate-return ---------------------------
@bp.route("/subscriptions/<sid>/initiate-return", methods=["POST"])
def initiate_return(sid):
    user_id, role = get_identity()
    require_roles(role, {"Member"})  # exclusive (PRD §3.11)
    sub = common.resolve(db.subscriptions, sid)
    _check_owner(role, user_id, sub)
    if sub["lifecycle_status"] != "ACTIVE":
        raise errors.invalid_state("Subscription must be ACTIVE to initiate return.")
    # priority 9: blocked while PAST_DUE (ERR_BILLING_PAST_DUE).
    if sub["billing_status"] == "PAST_DUE":
        raise errors.billing_past_due()
    sub["lifecycle_status"] = "RETURN_PENDING"
    touch(sub)
    return object_response(serialize.serialize_subscription(sub))


# --------------------------- early-cancel ---------------------------
@bp.route("/subscriptions/<sid>/early-cancel", methods=["POST"])
def early_cancel(sid):
    user_id, role = get_identity()
    require_roles(role, {"Member"})  # exclusive (PRD §3.12)
    sub = common.resolve(db.subscriptions, sid)
    _check_owner(role, user_id, sub)
    body = common.get_body()
    expected_version = common.require_int(body, "expected_subscription_version")

    if sub["lifecycle_status"] != "ACTIVE":
        raise errors.invalid_state("Subscription must be ACTIVE to early-cancel.")
    # priority 9: PAST_DUE block.
    if sub["billing_status"] == "PAST_DUE":
        raise errors.billing_past_due()
    plan = db.subscription_plans[sub["plan_id"]]
    now = clock.now()
    # priority 10: min-term must NOT yet have elapsed (ERR_MIN_TERM_ELAPSED).
    if not _before_min_term(sub, plan, now):
        raise errors.min_term_elapsed()
    # priority 16: OCC on Subscription.version (ERR_STALE_SUBSCRIPTION_VERSION).
    if expected_version != sub["version"]:
        raise errors.stale_subscription_version()

    fee = calc.early_cancel_fee_forward(plan, sub["term_start_iso"], now)
    inv_svc.post_invoice(sub["id"], "EARLY_CANCEL", sub["id"], fee)
    touch(sub)  # increments Subscription.version (PRD §3.12)
    vehicle = db.vehicles.get(sub["active_vehicle_id"])
    if vehicle is not None and vehicle["status"] == "ASSIGNED":
        vehicle["status"] = "IN_INSPECTION"
        touch(vehicle)
        common.recompute_fleet(vehicle["fleet_id"])
    sub["lifecycle_status"] = "CLOSED"
    touch(sub)
    return object_response(serialize.serialize_subscription(sub))


def _before_min_term(sub, plan, now_dt):
    """clock.now < term_start_iso + min_term_months months (PRD §3.12)."""
    from clock import parse_iso
    import calendar as _cal
    start = parse_iso(sub["term_start_iso"])
    total_month = start.month - 1 + plan["min_term_months"]
    year = start.year + total_month // 12
    month = total_month % 12 + 1
    day = min(start.day, _cal.monthrange(year, month)[1])
    threshold = start.replace(year=year, month=month, day=day)
    return now_dt < threshold


# --------------------------- cancel-quote ---------------------------
@bp.route("/subscriptions/<sid>/cancel-quote", methods=["GET"])
def cancel_quote(sid):
    _, role = get_identity()
    require_roles(role, {"Member", "BillingAdmin", "PlatformAdmin"})  # shared (PRD §3.12)
    sub = common.resolve(db.subscriptions, sid)
    mode = request.args.get("mode", "FORWARD_LOOKING")
    plan = db.subscription_plans[sub["plan_id"]]
    now = clock.now()
    if mode == "CHRONOLOGICAL":
        fee = calc.early_cancel_fee_chronological(plan, sub["cycle_start_iso"], now)
    else:
        mode = "FORWARD_LOOKING"
        fee = calc.early_cancel_fee_forward(plan, sub["term_start_iso"], now)
    return object_response({"mode": mode, "fee_cents": fee})


# --------------------------- billing axis ---------------------------
@bp.route("/subscriptions/<sid>/mark-past-due", methods=["POST"])
def mark_past_due(sid):
    _, role = get_identity()
    require_roles(role, {"BillingAdmin"})  # exclusive (PRD §3.13)
    sub = common.resolve(db.subscriptions, sid)
    if sub["billing_status"] != "CURRENT":
        raise errors.invalid_state("billing_status must be CURRENT to mark PAST_DUE.")
    sub["billing_status"] = "PAST_DUE"
    touch(sub)
    return object_response(serialize.serialize_subscription(sub))


@bp.route("/subscriptions/<sid>/record-payment", methods=["POST"])
def record_payment(sid):
    _, role = get_identity()
    require_roles(role, {"BillingAdmin"})  # exclusive (PRD §3.13)
    sub = common.resolve(db.subscriptions, sid)
    if sub["billing_status"] != "PAST_DUE":
        raise errors.invalid_state("billing_status must be PAST_DUE to record payment.")
    sub["billing_status"] = "CURRENT"
    touch(sub)
    return object_response(serialize.serialize_subscription(sub))


# --------------------------- nested reads ---------------------------
@bp.route("/subscriptions/<sid>/billing-cycles", methods=["GET"])
def list_subscription_cycles(sid):
    _, role = get_identity()
    require_roles(role, {"PlatformAdmin", "FleetOperator", "BillingAdmin", "Member"})
    common.resolve(db.subscriptions, sid)
    limit, offset = parse_pagination()
    records = [c for c in db.billing_cycles.values() if c["subscription_id"] == sid]
    records = common.filter_equals(records, "status", request.args.get("status"))
    page, total = common.paginate_sorted(records, limit, offset)
    return array_response([serialize.serialize_billing_cycle(r) for r in page], limit, offset, total)


@bp.route("/subscriptions/<sid>/invoices", methods=["GET"])
def list_subscription_invoices(sid):
    _, role = get_identity()
    require_roles(role, {"PlatformAdmin", "BillingAdmin", "Member"})
    common.resolve(db.subscriptions, sid)
    limit, offset = parse_pagination()
    records = [i for i in db.invoices.values() if i["subscription_id"] == sid]
    records = common.filter_equals(records, "source_kind", request.args.get("source_kind"))
    page, total = common.paginate_sorted(records, limit, offset)
    return array_response([serialize.serialize_invoice(r) for r in page], limit, offset, total)


# --------------------------- swap-request creation (member) ---------------------------
@bp.route("/subscriptions/<sid>/swap-requests", methods=["POST"])
def create_swap_request(sid):
    user_id, role = get_identity()
    require_roles(role, {"Member"})  # exclusive (PRD §3.8)
    sub = common.resolve(db.subscriptions, sid)
    _check_owner(role, user_id, sub)
    body = common.get_body()
    to_vehicle_id = common.require_str(body, "to_vehicle_id")
    common.resolve(db.vehicles, to_vehicle_id)

    rec = {
        "subscription_id": sub["id"],
        "from_vehicle_id": sub["active_vehicle_id"],  # captured from active_vehicle_id
        "to_vehicle_id": to_vehicle_id,
        "status": "REQUESTED",
        "swap_fee_applied_cents": 0,
        "net_adjustment_cents": 0,
    }
    stamp_create(rec)
    db.swap_requests[rec["id"]] = rec
    return object_response(serialize.serialize_swap_request(rec), 201)
