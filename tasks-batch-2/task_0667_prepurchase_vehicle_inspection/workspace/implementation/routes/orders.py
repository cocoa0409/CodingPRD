"""InspectionOrder endpoints (PRD §3.2, §3.3, §3.7).

Parallel state axes: workflow_status x payment_status.
"""
from flask import Blueprint, g, request

from db import db, stamp_create, touch
from errors import err
from helpers import (check_enum, get_json_body, iso_from_dt, paginate,
                     parse_pagination, require_fields, serialize, sort_by_created)
from middleware import require_roles
from response import success
from services import calculations as calc
from services.lookups import (get_account, get_fee_schedule, get_order,
                              get_vehicle)
from clock import clock

bp = Blueprint("orders", __name__)

RUSH_TIERS = {"NONE", "EXPRESS", "SAME_DAY"}


def serialize_order(o):
    out = serialize(o)
    out.pop("ordered_at_dt", None)
    out.pop("sla_deadline_dt", None)
    return out


def _require_account_owner(account):
    """Ownership: AccountHolder must act on its own account; OpsAdmin exempt."""
    if g.user_role == "AccountHolder" and account["id"] != g.user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting account does not own this resource")


def _quote_estimated(order):
    fs = db.fee_schedules[order["fee_schedule_id"]]
    acct = db.accounts[order["account_id"]]
    return calc.fee_estimated(
        fs,
        order["include_vin_history"],
        order.get("dispatch_miles"),
        order["rush_tier"],
        acct.get("rush_discount_pct", 0),
    )


@bp.route("/inspection-orders", methods=["POST"])
@require_roles("AccountHolder")
def create_order():
    body = get_json_body()
    require_fields(body, ["account_id", "vehicle_id", "fee_schedule_id",
                          "location_lat", "location_lng"])
    # existence: body FKs (path has none here)
    account = get_account(body["account_id"])
    vehicle = get_vehicle(body["vehicle_id"])
    fee_schedule = get_fee_schedule(body["fee_schedule_id"])

    # ownership (priority 4) before body well-formedness (priority 5)
    _require_account_owner(account)

    loc_lat = body["location_lat"]
    loc_lng = body["location_lng"]
    if not isinstance(loc_lat, (int, float)) or isinstance(loc_lat, bool):
        raise err("ERR_INVALID_REQUEST", "location_lat must be numeric")
    if not isinstance(loc_lng, (int, float)) or isinstance(loc_lng, bool):
        raise err("ERR_INVALID_REQUEST", "location_lng must be numeric")

    include_vin = body.get("include_vin_history", False)
    if include_vin is None:
        include_vin = False
    if not isinstance(include_vin, bool):
        raise err("ERR_INVALID_REQUEST", "include_vin_history must be a boolean")

    rush_tier = body.get("rush_tier", "NONE")
    if rush_tier is None:
        rush_tier = "NONE"
    check_enum(rush_tier, RUSH_TIERS, "rush_tier")

    # business safety (priority 8): account ACTIVE
    if account["status"] != "ACTIVE":
        raise err("ERR_ACCOUNT_SUSPENDED", "Account is suspended")

    ordered_at_dt = clock.now()
    sla_dt = calc.sla_deadline(ordered_at_dt, rush_tier)

    order = {
        "account_id": account["id"],
        "vehicle_id": vehicle["id"],
        "fee_schedule_id": fee_schedule["id"],
        "location_lat": loc_lat,
        "location_lng": loc_lng,
        "dispatch_miles": None,
        "include_vin_history": include_vin,
        "rush_tier": rush_tier,
        "ordered_at": iso_from_dt(ordered_at_dt),
        "ordered_at_dt": ordered_at_dt,
        "sla_deadline": iso_from_dt(sla_dt),
        "sla_deadline_dt": sla_dt,
        "workflow_status": "DRAFT",
        "payment_status": "UNPAID",
        "estimated_fee_cents": 0,
        "fee_total_cents": 0,
        "late_delivery": False,
        "refunded_cents": 0,
    }
    stamp_create(order)
    # estimated fee at creation: dispatch component is 0 (miles unknown yet)
    order["estimated_fee_cents"] = calc.fee_estimated(
        fee_schedule, include_vin, None, rush_tier, account.get("rush_discount_pct", 0)
    )
    db.orders[order["id"]] = order
    return success(serialize_order(order), status=201)


@bp.route("/inspection-orders/<order_id>", methods=["GET"])
@require_roles("OpsAdmin", "AccountHolder")
def get_order_ep(order_id):
    order = get_order(order_id)
    return success(serialize_order(order), status=200)


@bp.route("/inspection-orders", methods=["GET"])
@require_roles("OpsAdmin", "AccountHolder")
def list_orders():
    limit, offset = parse_pagination()
    account_id = request.args.get("account_id")
    vehicle_id = request.args.get("vehicle_id")
    fee_schedule_id = request.args.get("fee_schedule_id")
    items = list(db.orders.values())
    if account_id is not None:
        items = [o for o in items if o["account_id"] == account_id]
    if vehicle_id is not None:
        items = [o for o in items if o["vehicle_id"] == vehicle_id]
    if fee_schedule_id is not None:
        items = [o for o in items if o["fee_schedule_id"] == fee_schedule_id]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success([serialize_order(o) for o in page], status=200, pagination=meta)


@bp.route("/inspection-orders/<order_id>/pay", methods=["POST"])
@require_roles("AccountHolder")
def pay_order(order_id):
    order = get_order(order_id)
    account = db.accounts[order["account_id"]]
    _require_account_owner(account)
    # state checks
    if order["workflow_status"] == "CANCELLED":
        raise err("ERR_INVALID_STATE", "Cannot pay a cancelled order")
    if order["payment_status"] != "UNPAID":
        raise err("ERR_INVALID_STATE", "Order is not UNPAID")
    order["payment_status"] = "PAID"
    touch(order)
    return success(serialize_order(order), status=200)


@bp.route("/inspection-orders/<order_id>/invoice", methods=["POST"])
@require_roles("OpsAdmin")
def invoice_order(order_id):
    order = get_order(order_id)
    account = db.accounts[order["account_id"]]
    # state check first (priority 7), then fiscal eligibility (business)
    if order["workflow_status"] == "CANCELLED":
        raise err("ERR_INVALID_STATE", "Cannot invoice a cancelled order")
    if order["payment_status"] != "UNPAID":
        raise err("ERR_INVALID_STATE", "Order is not UNPAID")
    if account.get("net_terms_days", 0) <= 0:
        raise err("ERR_INVOICE_NOT_ELIGIBLE", "Account is not eligible for net-terms invoicing")
    order["payment_status"] = "INVOICED"
    touch(order)
    # outstanding balance += estimated fee (trued up to final at delivery)
    account["outstanding_balance_cents"] = account.get("outstanding_balance_cents", 0) + \
        order["estimated_fee_cents"]
    touch(account)
    return success(serialize_order(order), status=200)


@bp.route("/inspection-orders/<order_id>/deliver", methods=["POST"])
@require_roles("OpsAdmin")
def deliver_order(order_id):
    order = get_order(order_id)
    # state (priority 7)
    if order["workflow_status"] != "REPORTED":
        raise err("ERR_INVALID_STATE", "Order is not in REPORTED state")
    # payment required (business fiscal)
    if order["payment_status"] not in ("PAID", "INVOICED"):
        raise err("ERR_PAYMENT_REQUIRED", "Order must be PAID or INVOICED to deliver")
    # VIN report prerequisite
    if order["include_vin_history"]:
        has_vin = any(vr["order_id"] == order["id"] for vr in db.vin_reports.values())
        if not has_vin:
            raise err("ERR_VIN_REPORT_MISSING", "A compiled VIN report is required")

    now = clock.now()
    late = calc.is_late(now, order["sla_deadline_dt"])
    fee_schedule = db.fee_schedules[order["fee_schedule_id"]]
    account = db.accounts[order["account_id"]]
    final_fee = calc.fee_final(
        fee_schedule,
        order["include_vin_history"],
        order.get("dispatch_miles"),
        order["rush_tier"],
        account.get("rush_discount_pct", 0),
        late,
    )
    prev_estimated = order["estimated_fee_cents"]
    order["workflow_status"] = "DELIVERED"
    order["late_delivery"] = late
    order["fee_total_cents"] = final_fee
    touch(order)

    # INVOICED: adjust outstanding balance by (final - previously booked estimate)
    if order["payment_status"] == "INVOICED":
        delta = final_fee - prev_estimated
        account["outstanding_balance_cents"] = account.get("outstanding_balance_cents", 0) + delta
        touch(account)

    return success(serialize_order(order), status=200)


@bp.route("/inspection-orders/<order_id>/cancel", methods=["POST"])
@require_roles("AccountHolder")
def cancel_order(order_id):
    order = get_order(order_id)
    account = db.accounts[order["account_id"]]
    _require_account_owner(account)
    if order["workflow_status"] not in ("DRAFT", "DISPATCHED"):
        raise err("ERR_INVALID_STATE", "Order can only be cancelled from DRAFT or DISPATCHED")

    was_dispatched = order["workflow_status"] == "DISPATCHED"
    order["workflow_status"] = "CANCELLED"

    # cascade: release the ACCEPTED assignment for a dispatched order
    if was_dispatched:
        for a in db.assignments.values():
            if a["order_id"] == order["id"] and a["status"] == "ACCEPTED":
                a["status"] = "RELEASED"
                touch(a)

    # refund if PAID
    if order["payment_status"] == "PAID":
        order["payment_status"] = "REFUNDED"
        finalized = order["fee_total_cents"] if order["fee_total_cents"] else order["estimated_fee_cents"]
        order["refunded_cents"] = finalized

    touch(order)
    return success(serialize_order(order), status=200)
