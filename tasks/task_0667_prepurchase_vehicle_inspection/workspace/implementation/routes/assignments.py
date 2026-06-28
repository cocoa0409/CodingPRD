"""DispatchAssignment endpoints (PRD §3.4).

Offering is OCC-guarded on the order's version (PRD §2.7).
Acceptance runs the scheduling battery: inspector availability, tier
certification, inspector overlap (half-open), vehicle double-booking (closed),
and the daily cap.
"""
from flask import Blueprint, g, request

from db import db, stamp_create, touch
from errors import err
from helpers import (get_json_body, iso_from_dt, paginate, parse_iso8601,
                     parse_pagination, require_fields, serialize, sort_by_created)
from middleware import require_roles
from response import success
from services import calculations as calc
from services.lookups import get_assignment, get_inspector, get_order

bp = Blueprint("assignments", __name__)


def serialize_assignment(a):
    out = serialize(a)
    out.pop("window_start_dt", None)
    out.pop("window_end_dt", None)
    return out


def _requote_estimated(order):
    fs = db.fee_schedules[order["fee_schedule_id"]]
    acct = db.accounts[order["account_id"]]
    order["estimated_fee_cents"] = calc.fee_estimated(
        fs,
        order["include_vin_history"],
        order.get("dispatch_miles"),
        order["rush_tier"],
        acct.get("rush_discount_pct", 0),
    )


@bp.route("/dispatch-assignments", methods=["POST"])
@require_roles("OpsAdmin")
def create_assignment():
    body = get_json_body()
    require_fields(body, ["order_id", "inspector_id", "window_start", "window_end",
                          "dispatch_miles", "expected_order_version"])
    # existence (body FKs)
    order = get_order(body["order_id"])
    inspector = get_inspector(body["inspector_id"])

    # body well-formedness (priority 5)
    window_start = parse_iso8601(body["window_start"], "window_start")
    window_end = parse_iso8601(body["window_end"], "window_end")
    dispatch_miles = body["dispatch_miles"]
    if not isinstance(dispatch_miles, (int, float)) or isinstance(dispatch_miles, bool) \
            or dispatch_miles < 0:
        raise err("ERR_INVALID_REQUEST", "dispatch_miles must be a non-negative number")
    expected_version = body["expected_order_version"]
    if not isinstance(expected_version, int) or isinstance(expected_version, bool):
        raise err("ERR_INVALID_REQUEST", "expected_order_version must be an integer")

    # OCC (priority 6)
    if expected_version != order["version"]:
        raise err("ERR_STALE_VERSION", "expected_order_version does not match current order version")

    # state (priority 7): offer drives DRAFT order; order must be DRAFT
    if order["workflow_status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Order is not in DRAFT state")

    # business safety: account ACTIVE
    account = db.accounts[order["account_id"]]
    if account["status"] != "ACTIVE":
        raise err("ERR_ACCOUNT_SUSPENDED", "Account is suspended")

    a = {
        "order_id": order["id"],
        "inspector_id": inspector["id"],
        "window_start": iso_from_dt(window_start),
        "window_start_dt": window_start,
        "window_end": iso_from_dt(window_end),
        "window_end_dt": window_end,
        "status": "OFFERED",
    }
    stamp_create(a)
    db.assignments[a["id"]] = a

    # side effects: record dispatch_miles, re-quote estimate, bump order version
    order["dispatch_miles"] = dispatch_miles
    _requote_estimated(order)
    touch(order)

    return success(serialize_assignment(a), status=201)


@bp.route("/dispatch-assignments/<assignment_id>", methods=["GET"])
@require_roles("OpsAdmin", "Inspector")
def get_assignment_ep(assignment_id):
    a = get_assignment(assignment_id)
    return success(serialize_assignment(a), status=200)


@bp.route("/dispatch-assignments", methods=["GET"])
@require_roles("OpsAdmin", "AccountHolder", "Inspector")
def list_assignments():
    limit, offset = parse_pagination()
    order_id = request.args.get("order_id")
    inspector_id = request.args.get("inspector_id")
    items = list(db.assignments.values())
    if order_id is not None:
        items = [a for a in items if a["order_id"] == order_id]
    if inspector_id is not None:
        items = [a for a in items if a["inspector_id"] == inspector_id]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success([serialize_assignment(a) for a in page], status=200, pagination=meta)


def _inspector_overlap(inspector_id, exclude_id, ws, we):
    """Half-open overlap: touching endpoints (a.end == b.start) do NOT collide."""
    for a in db.assignments.values():
        if a["id"] == exclude_id:
            continue
        if a["inspector_id"] != inspector_id or a["status"] != "ACCEPTED":
            continue
        # overlap iff a.start < we and ws < a.end  (half-open [start, end))
        if a["window_start_dt"] < we and ws < a["window_end_dt"]:
            return True
    return False


def _vehicle_double_booked(vehicle_id, exclude_id, ws, we):
    """Closed-interval collision: touching endpoints (a.end == b.start) DO collide."""
    for a in db.assignments.values():
        if a["id"] == exclude_id:
            continue
        if a["status"] != "ACCEPTED":
            continue
        other_order = db.orders.get(a["order_id"])
        if other_order is None or other_order["vehicle_id"] != vehicle_id:
            continue
        # closed-interval collision iff a.start <= we and ws <= a.end
        if a["window_start_dt"] <= we and ws <= a["window_end_dt"]:
            return True
    return False


def _daily_count(inspector_id, exclude_id, window_start_dt):
    """Count ACCEPTED assignments whose window_start is on the same UTC date."""
    date = window_start_dt.date()
    count = 0
    for a in db.assignments.values():
        if a["id"] == exclude_id:
            continue
        if a["inspector_id"] != inspector_id or a["status"] != "ACCEPTED":
            continue
        if a["window_start_dt"].date() == date:
            count += 1
    return count


@bp.route("/dispatch-assignments/<assignment_id>/accept", methods=["POST"])
@require_roles("Inspector")
def accept_assignment(assignment_id):
    a = get_assignment(assignment_id)
    # ownership (priority 4): acting inspector == assignment.inspector_id
    if a["inspector_id"] != g.user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting inspector does not own this assignment")
    # state (priority 7)
    if a["status"] != "OFFERED":
        raise err("ERR_INVALID_STATE", "Assignment is not OFFERED")

    inspector = db.inspectors[a["inspector_id"]]
    order = db.orders[a["order_id"]]
    fee_schedule = db.fee_schedules[order["fee_schedule_id"]]

    # business safety
    if inspector["status"] != "AVAILABLE":
        raise err("ERR_INSPECTOR_OFFLINE", "Inspector is offline")
    if fee_schedule["tier_code"] not in inspector["certified_tiers"]:
        raise err("ERR_TIER_NOT_CERTIFIED", "Inspector not certified for this tier")

    ws = a["window_start_dt"]
    we = a["window_end_dt"]
    # inspector overlap (half-open)
    if _inspector_overlap(a["inspector_id"], a["id"], ws, we):
        raise err("ERR_WINDOW_OVERLAP", "Window overlaps another accepted assignment")
    # vehicle double-booking (closed)
    if _vehicle_double_booked(order["vehicle_id"], a["id"], ws, we):
        raise err("ERR_VEHICLE_DOUBLE_BOOKED", "Vehicle is double-booked")
    # daily cap
    if _daily_count(a["inspector_id"], a["id"], ws) >= inspector["max_daily_jobs"]:
        raise err("ERR_DAILY_CAP_EXCEEDED", "Inspector daily cap exceeded")

    a["status"] = "ACCEPTED"
    touch(a)
    # cascade: order DRAFT -> DISPATCHED, bump version
    if order["workflow_status"] == "DRAFT":
        order["workflow_status"] = "DISPATCHED"
        touch(order)
    return success(serialize_assignment(a), status=200)


@bp.route("/dispatch-assignments/<assignment_id>/decline", methods=["POST"])
@require_roles("Inspector")
def decline_assignment(assignment_id):
    a = get_assignment(assignment_id)
    if a["inspector_id"] != g.user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting inspector does not own this assignment")
    if a["status"] != "OFFERED":
        raise err("ERR_INVALID_STATE", "Assignment is not OFFERED")
    a["status"] = "DECLINED"
    touch(a)
    return success(serialize_assignment(a), status=200)


@bp.route("/dispatch-assignments/<assignment_id>/release", methods=["POST"])
@require_roles("OpsAdmin")
def release_assignment(assignment_id):
    a = get_assignment(assignment_id)
    if a["status"] != "ACCEPTED":
        raise err("ERR_INVALID_STATE", "Assignment is not ACCEPTED")
    order = db.orders[a["order_id"]]
    # release permitted only while order DISPATCHED or CANCELLED
    if order["workflow_status"] not in ("DISPATCHED", "CANCELLED"):
        raise err("ERR_INVALID_STATE", "Cannot release once order has progressed")

    a["status"] = "RELEASED"
    touch(a)
    # direct release while DISPATCHED reverts order to DRAFT and bumps version
    if order["workflow_status"] == "DISPATCHED":
        order["workflow_status"] = "DRAFT"
        touch(order)
    return success(serialize_assignment(a), status=200)
