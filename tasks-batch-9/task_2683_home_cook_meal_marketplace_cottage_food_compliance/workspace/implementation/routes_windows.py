"""Weekly production windows: cutoffs, effective capacity and the close cascade."""
from flask import Blueprint

import calc
import services
import validation as v
from auth import COOK, DINER, FINANCE_OPERATOR, PLATFORM_ADMIN, guard, require_owner
from core import ApiError, created, db, new_row, ok, parse_dt, public, touch
from listing import list_rows

bp = Blueprint("windows", __name__)

WINDOW_READ_ROLES = [COOK, DINER, FINANCE_OPERATOR, PLATFORM_ADMIN]
WINDOW_STATUSES = ["OPEN", "CUTOFF_PASSED", "IN_PRODUCTION", "CLOSED", "CANCELLED"]


def find_window(window_id):
    window = db.windows.get(window_id)
    if window is None:
        raise ApiError("ERR_WINDOW_NOT_FOUND")
    return window


@bp.route("/production-windows", methods=["POST"])
@guard([COOK, PLATFORM_ADMIN])
def create_window():
    body = v.body()
    cook_id = v.s_id(body, "cook_id")
    week_start_raw, _ = v.s_date(body, "week_start_date")
    cutoff_raw, cutoff = v.s_dt(body, "order_cutoff_at")
    start_raw, start = v.s_dt(body, "handoff_start_at")
    end_raw, end = v.s_dt(body, "handoff_end_at")
    capacity = v.s_int(body, "capacity_meals")

    cook = db.cooks.get(cook_id)
    if cook is None:
        raise ApiError("ERR_COOK_NOT_FOUND")
    require_owner(cook_id)

    if cook["onboarding_status"] != "ACTIVE":
        raise ApiError("ERR_COOK_NOT_ACTIVE", "only an ACTIVE cook may open a window")
    if cook["compliance_standing"] not in ("CLEAR", "WARNED"):
        raise ApiError("ERR_COOK_SUSPENDED", "a suspended or revoked cook may not open a window")
    if not (cutoff < start < end):
        raise ApiError(
            "ERR_CUTOFF_AFTER_HANDOFF",
            "order_cutoff_at, handoff_start_at and handoff_end_at must strictly increase",
        )
    for other in calc.cook_windows(cook_id):
        if other["status"] not in ("OPEN", "CUTOFF_PASSED", "IN_PRODUCTION"):
            continue
        other_start = parse_dt(other["handoff_start_at"])
        other_end = parse_dt(other["handoff_end_at"])
        # Half-open comparison: exact adjacency is legal.
        if start < other_end and other_start < end:
            raise ApiError("ERR_WINDOW_OVERLAP", "the handoff interval overlaps another window")
    if capacity < 1 or capacity > int(cook["weekly_capacity_meals"]):
        raise ApiError(
            "ERR_WINDOW_CAPACITY_ABOVE_COOK_LIMIT",
            "capacity_meals must be between 1 and the cook's weekly_capacity_meals",
        )

    row = new_row(
        db.windows,
        {
            "cook_id": cook_id,
            "week_start_date": week_start_raw,
            "order_cutoff_at": cutoff_raw,
            "handoff_start_at": start_raw,
            "handoff_end_at": end_raw,
            "capacity_meals": capacity,
            "committed_meals": 0,
            "spoilage_reserve_meals": 0,
            "effective_capacity_meals": capacity,
            "status": "OPEN",
            "cancelled_reason": None,
            "closed_at": None,
        },
    )
    calc.derive_window_capacity(row)
    return created(public(row))


@bp.route("/production-windows/<window_id>", methods=["GET"])
@guard(WINDOW_READ_ROLES)
def get_window(window_id):
    return ok(public(find_window(window_id)))


@bp.route("/production-windows", methods=["GET"])
@guard(WINDOW_READ_ROLES)
def list_windows():
    return list_rows(list(db.windows.values()), ["cook_id", "status", "week_start_date"])


@bp.route("/production-windows/<window_id>/advance", methods=["POST"])
@guard([COOK, FINANCE_OPERATOR, PLATFORM_ADMIN])
def advance_window(window_id):
    body = v.body()
    to_status = v.s_enum(body, "to_status", WINDOW_STATUSES)
    cancelled_reason = v.s_enum(body, "cancelled_reason", v.CANCELLED_REASONS, required=False)

    window = find_window(window_id)
    require_owner(window["cook_id"])
    cook = db.cooks[window["cook_id"]]
    status = window["status"]

    if to_status == "CUTOFF_PASSED":
        if status != "OPEN":
            raise ApiError("ERR_INVALID_WINDOW_TRANSITION", "CUTOFF_PASSED is reachable from OPEN")
        if db.now() < parse_dt(window["order_cutoff_at"]):
            raise ApiError("ERR_CUTOFF_NOT_REACHED", "the order cutoff has not been reached")
        window["status"] = "CUTOFF_PASSED"
        touch(window)
        return ok(public(window))

    if to_status == "IN_PRODUCTION":
        if status != "CUTOFF_PASSED":
            raise ApiError(
                "ERR_INVALID_WINDOW_TRANSITION", "IN_PRODUCTION is reachable from CUTOFF_PASSED"
            )
        if cook["compliance_standing"] in ("SUSPENDED", "REVOKED"):
            raise ApiError(
                "ERR_INVALID_WINDOW_TRANSITION", "a suspended or revoked cook cannot produce"
            )
        window["status"] = "IN_PRODUCTION"
        touch(window)
        for order in calc.ordered_window_orders(window_id):
            if order["fulfillment_status"] == "PLACED":
                services.cancel_order(order, "WINDOW_CANCELLED")
        return ok(public(window))

    if to_status == "CLOSED":
        if status != "IN_PRODUCTION":
            raise ApiError(
                "ERR_INVALID_WINDOW_TRANSITION", "CLOSED is reachable from IN_PRODUCTION"
            )
        if db.now() < parse_dt(window["handoff_end_at"]):
            raise ApiError("ERR_HANDOFF_NOT_FINISHED", "the handoff interval has not finished")
        window["status"] = "CLOSED"
        touch(window)
        services.window_close_cascade(window)
        return ok(public(window))

    if to_status == "CANCELLED":
        if status not in ("OPEN", "CUTOFF_PASSED"):
            raise ApiError(
                "ERR_INVALID_WINDOW_TRANSITION", "cancellation is reachable from OPEN or CUTOFF_PASSED"
            )
        if cancelled_reason != "COOK_REQUEST":
            raise ApiError(
                "ERR_INVALID_WINDOW_TRANSITION", "cancellation requires cancelled_reason COOK_REQUEST"
            )
        window["status"] = "CANCELLED"
        window["cancelled_reason"] = "COOK_REQUEST"
        touch(window)
        for order in calc.ordered_window_orders(window_id):
            if order["fulfillment_status"] in ("PLACED", "ROUTED"):
                services.cancel_order(order, "WINDOW_CANCELLED")
        return ok(public(window))

    raise ApiError("ERR_INVALID_WINDOW_TRANSITION", "%s is not reachable" % to_status)
