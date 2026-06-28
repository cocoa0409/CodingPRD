from flask import Blueprint, request

from db import db
from clock import clock, parse_clock_field
from middleware import require_role
from response import object_response, array_response
from errors import (
    err, ERR_INVALID_REQUEST, ERR_STALE_MODEL_VERSION, ERR_ACCOUNT_SUSPENDED,
    ERR_RENTAL_CAP_EXCEEDED, ERR_NO_BIKES_AVAILABLE, ERR_INVALID_STATE,
    ERR_BIKE_RETIRED,
)
from services.common import (
    stamp_create, touch, get_json_body, require_fields, require_enum,
    require_string, parse_pagination, paginate,
)
from services.lookups import get_account, get_model, get_rental, check_rental_ownership
from services.reconcile import recompute_model_counts, recompute_active_rental_count
from services.bike_ops import select_available_bike
from services.serialize import rental_view, inspection_report_view
from services import calculations as calc

rentals_bp = Blueprint("rentals", __name__)

RENTAL_MODES = {"MONTHLY", "DAILY"}
VIEW_ROLES = {"OpsAdmin", "Subscriber", "FleetManager", "FieldTech"}
HOLDER_ROLES = {"Subscriber", "FleetManager"}
BIKE_CONDITIONS = {"GOOD", "WORN", "DAMAGED"}


# =============================================================================
# POST /rentals — reservation (OCC + ordered guards per PRD §3.3)
# =============================================================================
@rentals_bp.route("/rentals", methods=["POST"])
def create_rental():
    user_id, role = require_role(HOLDER_ROLES)
    body = get_json_body()

    # Existence (priority 3) — account then model, left to right.
    require_fields(body, ["account_id", "model_id", "rental_mode",
                          "return_due_clock", "expected_model_version"])
    account = get_account(body["account_id"])
    model = get_model(body["model_id"])

    # Ownership (priority 2): entity-backed caller must own the account.
    if account["id"] != user_id:
        from errors import ERR_FORBIDDEN_ROLE
        raise err(ERR_FORBIDDEN_ROLE, "Caller does not own this account.")

    # Body well-formedness (priority 15 / ERR_INVALID_REQUEST).
    require_enum(body["rental_mode"], RENTAL_MODES, "rental_mode")
    if not isinstance(body["expected_model_version"], int) or isinstance(body["expected_model_version"], bool):
        raise err(ERR_INVALID_REQUEST, "expected_model_version must be an integer.")
    try:
        return_due = parse_clock_field(body["return_due_clock"])
    except (ValueError, TypeError):
        raise err(ERR_INVALID_REQUEST, "return_due_clock must be an ISO-8601 instant.")

    with db.lock:
        # OCC (priority 5 / 412): expected_model_version == current version.
        if body["expected_model_version"] != model["version"]:
            raise err(ERR_STALE_MODEL_VERSION, "Model version is stale.")

        # Business guards in the PRD §3.3 order:
        # suspended -> rental_cap -> no bikes available.
        if account["status"] == "SUSPENDED":
            raise err(ERR_ACCOUNT_SUSPENDED, "Suspended account cannot reserve.")
        recompute_active_rental_count(account["id"])
        if account["active_rental_count"] >= account["rental_cap"]:
            raise err(ERR_RENTAL_CAP_EXCEEDED, "Active rental cap reached.")
        recompute_model_counts(model["id"])
        if model["available_count"] < 1:
            raise err(ERR_NO_BIKES_AVAILABLE, "No bikes available for this model.")

        bike = select_available_bike(model["id"], db.bikes)
        if bike is None:
            raise err(ERR_NO_BIKES_AVAILABLE, "No bikes available for this model.")

        now = clock.now()
        from db import iso_ms
        rental = {
            "account_id": account["id"],
            "bike_id": bike["id"],
            "model_id": model["id"],
            "rental_mode": body["rental_mode"],
            "lifecycle_status": "RESERVED",
            "billing_status": "DEPOSIT_HELD",
            "reserved_at_clock": iso_ms(now),
            "activated_at_clock": None,
            "return_due_clock": body["return_due_clock"],
            "returned_at_clock": None,
            "deposit_cents": model["deposit_cents"],
            "completed_cycles": 0,
            "accrued_charge_cents": 0,
        }
        stamp_create(rental)
        db.rentals[rental["id"]] = rental

        # Bike AVAILABLE -> RESERVED, point current_rental_id.
        bike["bike_status"] = "RESERVED"
        bike["current_rental_id"] = rental["id"]
        touch(bike)

        # Recompute counts; advance BikeModel.version by one.
        recompute_model_counts(model["id"])
        recompute_active_rental_count(account["id"])
        touch(model)

    return object_response(rental_view(rental), 201)


@rentals_bp.route("/rentals/<rental_id>", methods=["GET"])
def fetch_rental(rental_id):
    user_id, role = require_role(VIEW_ROLES)
    rental = get_rental(rental_id)
    check_rental_ownership(rental, user_id, role)
    return object_response(rental_view(rental), 200)


@rentals_bp.route("/rentals", methods=["GET"])
def list_rentals():
    user_id, role = require_role(VIEW_ROLES)
    limit, offset = parse_pagination()
    records = list(db.rentals.values())
    # Entity-backed roles see only their own rentals.
    if role in HOLDER_ROLES:
        records = [r for r in records if r["account_id"] == user_id]
    for field in ("account_id", "model_id", "bike_id", "rental_mode", "lifecycle_status"):
        val = request.args.get(field)
        if val:
            records = [r for r in records if r.get(field) == val]
    page, total = paginate(records, limit, offset)
    return array_response([rental_view(r) for r in page], limit, offset, total)


# =============================================================================
# POST /rentals/{id}/activate
# =============================================================================
@rentals_bp.route("/rentals/<rental_id>/activate", methods=["POST"])
def activate_rental(rental_id):
    user_id, role = require_role(HOLDER_ROLES)
    with db.lock:
        rental = get_rental(rental_id)
        check_rental_ownership(rental, user_id, role)
        if rental["lifecycle_status"] != "DELIVERED":
            raise err(ERR_INVALID_STATE, "Rental must be DELIVERED to activate.")
        from db import iso_ms
        rental["activated_at_clock"] = iso_ms(clock.now())
        rental["lifecycle_status"] = "ACTIVE"
        rental["billing_status"] = "BILLING_ACTIVE"
        model = db.bike_models[rental["model_id"]]
        if rental["rental_mode"] == "MONTHLY":
            reserved_at = parse_clock_field(rental["reserved_at_clock"])
            activated_at = parse_clock_field(rental["activated_at_clock"])
            rental["accrued_charge_cents"] = calc.monthly_first_cycle_charge(
                model, reserved_at, activated_at)
        # DAILY: begin accrual; accrued finalized at return.
        touch(rental)
        recompute_active_rental_count(rental["account_id"])
    return object_response(rental_view(rental), 200)


# =============================================================================
# POST /rentals/{id}/request-return
# =============================================================================
@rentals_bp.route("/rentals/<rental_id>/request-return", methods=["POST"])
def request_return(rental_id):
    user_id, role = require_role(HOLDER_ROLES)
    body = get_json_body()
    with db.lock:
        rental = get_rental(rental_id)
        check_rental_ownership(rental, user_id, role)
        # Business safety (priority 6): cannot request-return when bike RETIRED.
        bike = db.bikes.get(rental["bike_id"])
        if bike is not None and bike["bike_status"] == "RETIRED":
            raise err(ERR_BIKE_RETIRED, "Bike has been retired/written off.")
        if rental["lifecycle_status"] != "ACTIVE":
            raise err(ERR_INVALID_STATE, "Rental must be ACTIVE to request return.")
        require_fields(body, ["return_address"])
        require_string(body["return_address"], "return_address")

        rental["lifecycle_status"] = "RETURN_REQUESTED"
        touch(rental)

        # Create a SCHEDULED PICKUP delivery for this rental.
        now = clock.now()
        from db import iso_ms
        delivery = {
            "rental_id": rental["id"],
            "delivery_type": "PICKUP",
            "address": body["return_address"],
            "window_start_clock": iso_ms(now),
            "window_end_clock": iso_ms(now),
            "swap_to_bike_id": None,
            "status": "SCHEDULED",
        }
        stamp_create(delivery)
        db.deliveries[delivery["id"]] = delivery
        recompute_active_rental_count(rental["account_id"])
    return object_response(rental_view(rental), 200)


# =============================================================================
# POST /rentals/{id}/inspect — file InspectionReport, 3-hop cascade
# =============================================================================
@rentals_bp.route("/rentals/<rental_id>/inspect", methods=["POST"])
def inspect_rental(rental_id):
    require_role({"FieldTech"})
    body = get_json_body()
    with db.lock:
        rental = get_rental(rental_id)
        # Business safety (priority 6): bike retired/written off blocks inspect.
        bike = db.bikes.get(rental["bike_id"])
        if bike is not None and bike["bike_status"] == "RETIRED":
            raise err(ERR_BIKE_RETIRED, "Bike has been retired/written off.")
        if rental["lifecycle_status"] != "RETURN_REQUESTED":
            raise err(ERR_INVALID_STATE, "Rental must be RETURN_REQUESTED to inspect.")
        # No InspectionReport already exists for this rental.
        for r in db.inspection_reports.values():
            if r["rental_id"] == rental["id"]:
                raise err(ERR_INVALID_STATE, "Inspection report already exists.")

        require_fields(body, ["bike_condition", "damage_charge_cents", "cleaning_fee_cents"])
        require_enum(body["bike_condition"], BIKE_CONDITIONS, "bike_condition")
        damage = body["damage_charge_cents"]
        cleaning = body["cleaning_fee_cents"]
        if not isinstance(damage, int) or isinstance(damage, bool) or damage < 0:
            raise err(ERR_INVALID_REQUEST, "damage_charge_cents must be a non-negative integer.")
        if not isinstance(cleaning, int) or isinstance(cleaning, bool) or cleaning < 0:
            raise err(ERR_INVALID_REQUEST, "cleaning_fee_cents must be a non-negative integer.")

        from db import iso_ms
        now = clock.now()
        rental["returned_at_clock"] = iso_ms(now)

        # Late fee.
        return_due = parse_clock_field(rental["return_due_clock"])
        late_fee = calc.late_fee(return_due, now)

        # DAILY: recompute accrued charge at return.
        model = db.bike_models[rental["model_id"]]
        if rental["rental_mode"] == "DAILY" and rental["activated_at_clock"] is not None:
            activated_at = parse_clock_field(rental["activated_at_clock"])
            rental["accrued_charge_cents"] = calc.daily_tiered_charge(model, activated_at, now)

        # Settlement waterfall.
        settle = calc.return_settlement(
            rental["deposit_cents"], damage, cleaning, late_fee)

        report = {
            "rental_id": rental["id"],
            "bike_condition": body["bike_condition"],
            "damage_charge_cents": damage,
            "cleaning_fee_cents": cleaning,
            "late_fee_cents": late_fee,
            "total_assessed_cents": settle["total_assessed_cents"],
            "deposit_applied_cents": settle["deposit_applied_cents"],
            "deposit_refund_cents": settle["deposit_refund_cents"],
            "overflow_billed_cents": settle["overflow_billed_cents"],
        }
        stamp_create(report, common_fields=False)
        db.inspection_reports[report["id"]] = report

        # Settlement effects on account.
        account = db.accounts[rental["account_id"]]
        account["wallet_credit_cents"] += settle["deposit_refund_cents"]
        account["_overflow_billed_unpaid_cents"] += settle["overflow_billed_cents"]
        touch(account)

        rental["billing_status"] = "SETTLED"
        rental["lifecycle_status"] = "RETURNED"
        touch(rental)

        # Bike OUT -> AVAILABLE, clear current_rental_id; reconcile model counts.
        if bike is not None:
            bike["bike_status"] = "AVAILABLE"
            bike["current_rental_id"] = None
            touch(bike)
            recompute_model_counts(bike["model_id"])
        recompute_active_rental_count(rental["account_id"])

    return object_response(inspection_report_view(report), 201)


# =============================================================================
# POST /rentals/{id}/cancel — cancel a RESERVED rental
# =============================================================================
@rentals_bp.route("/rentals/<rental_id>/cancel", methods=["POST"])
def cancel_rental(rental_id):
    user_id, role = require_role(HOLDER_ROLES)
    with db.lock:
        rental = get_rental(rental_id)
        check_rental_ownership(rental, user_id, role)
        if rental["lifecycle_status"] != "RESERVED":
            raise err(ERR_INVALID_STATE, "Rental must be RESERVED to cancel.")

        rental["lifecycle_status"] = "CANCELLED"
        rental["billing_status"] = "SETTLED"

        # Bike RESERVED -> AVAILABLE, clear current_rental_id.
        bike = db.bikes.get(rental["bike_id"])
        if bike is not None:
            bike["bike_status"] = "AVAILABLE"
            bike["current_rental_id"] = None
            touch(bike)
            recompute_model_counts(bike["model_id"])

        # Refund full deposit to wallet.
        account = db.accounts[rental["account_id"]]
        account["wallet_credit_cents"] += rental["deposit_cents"]
        touch(account)

        # Cancel any SCHEDULED delivery for this rental.
        for d in db.deliveries.values():
            if d["rental_id"] == rental["id"] and d["status"] == "SCHEDULED":
                d["status"] = "CANCELLED"
                touch(d)

        touch(rental)
        recompute_active_rental_count(rental["account_id"])
    return object_response(rental_view(rental), 200)


# =============================================================================
# POST /rentals/{id}/advance-cycle
# =============================================================================
@rentals_bp.route("/rentals/<rental_id>/advance-cycle", methods=["POST"])
def advance_cycle(rental_id):
    require_role({"OpsAdmin"})
    with db.lock:
        rental = get_rental(rental_id)
        # Only when rental_mode==MONTHLY and lifecycle in {ACTIVE, IN_SERVICE}.
        if rental["rental_mode"] != "MONTHLY" or rental["lifecycle_status"] not in ("ACTIVE", "IN_SERVICE"):
            raise err(ERR_INVALID_STATE,
                      "advance-cycle only applies to ACTIVE/IN_SERVICE MONTHLY rentals.")
        rental["completed_cycles"] += 1
        touch(rental)
    return object_response(rental_view(rental), 200)
