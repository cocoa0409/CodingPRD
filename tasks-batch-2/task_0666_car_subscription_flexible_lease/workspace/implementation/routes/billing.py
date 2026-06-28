"""Billing cycle & invoice routes (PRD §3.6, §3.14)."""
from flask import Blueprint, request

import errors
from clock import clock
from db import db, stamp_create, touch
from middleware import get_identity, require_roles, parse_pagination
from response import object_response, array_response
from services import calc, serialize, common
from services import invoices as inv_svc

bp = Blueprint("billing", __name__)


# --------------------------- billing-cycles ---------------------------
@bp.route("/billing-cycles/<cid>", methods=["GET"])
def get_cycle(cid):
    _, role = get_identity()
    require_roles(role, {"PlatformAdmin", "BillingAdmin", "Member"})
    rec = common.resolve(db.billing_cycles, cid)
    return object_response(serialize.serialize_billing_cycle(rec))


@bp.route("/billing-cycles", methods=["GET"])
def list_cycles():
    _, role = get_identity()
    require_roles(role, {"PlatformAdmin", "BillingAdmin", "Member"})
    limit, offset = parse_pagination()
    records = list(db.billing_cycles.values())
    records = common.filter_equals(records, "subscription_id", request.args.get("subscription_id"))
    records = common.filter_equals(records, "vehicle_id", request.args.get("vehicle_id"))
    records = common.filter_equals(records, "status", request.args.get("status"))
    page, total = common.paginate_sorted(records, limit, offset)
    return array_response([serialize.serialize_billing_cycle(r) for r in page], limit, offset, total)


@bp.route("/billing-cycles/<cid>/close", methods=["POST"])
def close_cycle(cid):
    _, role = get_identity()
    require_roles(role, {"BillingAdmin"})  # exclusive (PRD §3.6)
    cycle = common.resolve(db.billing_cycles, cid)
    body = common.get_body()
    odometer_end = common.require_int(body, "odometer_end_miles")

    # priority 6: state — OPEN only.
    if cycle["status"] != "OPEN":
        raise errors.invalid_state("Cycle must be OPEN to close.")
    # priority 14: odometer regression (ERR_ODOMETER_REGRESSION).
    if odometer_end < cycle["odometer_start_miles"]:
        raise errors.odometer_regression()

    sub = db.subscriptions[cycle["subscription_id"]]
    plan = db.subscription_plans[sub["plan_id"]]
    overage = calc.mileage_overage(plan, cycle["odometer_start_miles"], odometer_end)

    cycle["odometer_end_miles"] = odometer_end
    cycle["overage_cents"] = overage
    cycle["cycle_end_iso"] = clock.now_iso()
    cycle["status"] = "CLOSED"
    touch(cycle)

    # CYCLE invoice amount = monthly fee + overage (PRD §3.6).
    amount = plan["monthly_fee_cents"] + overage
    inv_svc.post_invoice(sub["id"], "CYCLE", cycle["id"], amount)

    # write reported reading back to the vehicle (PRD §3.6).
    vehicle = db.vehicles.get(cycle["vehicle_id"])
    if vehicle is not None:
        vehicle["odometer_miles"] = odometer_end
        touch(vehicle)

    # open next cycle if subscription still ACTIVE (PRD §3.6).
    if sub["lifecycle_status"] == "ACTIVE":
        next_cycle = {
            "subscription_id": sub["id"],
            "vehicle_id": cycle["vehicle_id"],
            "cycle_index": cycle["cycle_index"] + 1,
            "cycle_start_iso": clock.now_iso(),
            "cycle_end_iso": None,
            "odometer_start_miles": odometer_end,
            "odometer_end_miles": None,
            "status": "OPEN",
            "overage_cents": 0,
        }
        stamp_create(next_cycle)
        db.billing_cycles[next_cycle["id"]] = next_cycle
    return object_response(serialize.serialize_billing_cycle(cycle))


# --------------------------- invoices ---------------------------
@bp.route("/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    _, role = get_identity()
    require_roles(role, {"PlatformAdmin", "BillingAdmin", "Member"})
    rec = common.resolve(db.invoices, iid)
    return object_response(serialize.serialize_invoice(rec))


@bp.route("/invoices", methods=["GET"])
def list_invoices():
    _, role = get_identity()
    require_roles(role, {"PlatformAdmin", "BillingAdmin", "Member"})
    limit, offset = parse_pagination()
    records = list(db.invoices.values())
    records = common.filter_equals(records, "subscription_id", request.args.get("subscription_id"))
    records = common.filter_equals(records, "source_kind", request.args.get("source_kind"))
    page, total = common.paginate_sorted(records, limit, offset)
    return array_response([serialize.serialize_invoice(r) for r in page], limit, offset, total)
