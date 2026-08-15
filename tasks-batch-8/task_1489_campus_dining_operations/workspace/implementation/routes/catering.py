"""CateringOrder endpoints with the C2 quote and C7 budget ledger."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

from db import DB, logical_now_dt, new_id, next_seq
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok
from services import (
    TIME_SLOTS,
    c2_quote,
    c7_recompute,
    event_start_dt,
    get_catering_order,
    get_department,
    get_hall,
    get_recipe,
    has_open_critical_action,
    ser,
    stamp,
    touch,
)
from util import as_enum, as_int, as_iso_date, as_list, as_str, body, required, rhu_int
from routes.common import list_endpoint

bp = Blueprint("catering", __name__)


def _own_order_or_forbid(user_id, role, order):
    if role == "DepartmentUser" and order["department_id"] != user_id:
        raise ApiError(
            "ERR_FORBIDDEN", 403, "DepartmentUser may only act on their own orders"
        )


@bp.post("/catering-orders")
def create_order():
    user_id, role = auth(["DepartmentUser"])
    data = body()
    # Tier 2 ownership runs before existence: the body's department_id must be
    # the caller's own department id.
    department_id = data.get("department_id")
    if department_id is not None and department_id != user_id:
        raise ApiError(
            "ERR_FORBIDDEN", 403, "DepartmentUser may only order for their own department"
        )
    # Tier 3 existence in declared input order: dining_hall_id -> department_id
    # -> menu_lines recipe ids -> revised_from_id.
    dining_hall_id = required(data, "dining_hall_id")
    if isinstance(dining_hall_id, str):
        get_hall(dining_hall_id)
    if department_id is None:
        raise ApiError("ERR_VALIDATION", 400, "Missing required field: department_id")
    if isinstance(department_id, str):
        get_department(department_id)
    menu_lines_raw = required(data, "menu_lines")
    recipes = []
    if isinstance(menu_lines_raw, list):
        for line in menu_lines_raw:
            if isinstance(line, dict) and isinstance(line.get("recipe_id"), str):
                recipes.append(get_recipe(line["recipe_id"]))
    revised_from_id = data.get("revised_from_id")
    revised_from = None
    if revised_from_id is not None and isinstance(revised_from_id, str):
        revised_from = get_catering_order(revised_from_id)
    # Tier 10 field shape.
    if not isinstance(dining_hall_id, str):
        raise ApiError("ERR_VALIDATION", 400, "dining_hall_id must be a string")
    if not isinstance(department_id, str):
        raise ApiError("ERR_VALIDATION", 400, "department_id must be a string")
    event_date = as_iso_date(required(data, "event_date"), "event_date")
    time_slot = as_enum(required(data, "time_slot"), "time_slot", TIME_SLOTS)
    covers = as_int(required(data, "guaranteed_covers"), "guaranteed_covers")
    if covers <= 0:
        raise ApiError("ERR_VALIDATION", 400, "guaranteed_covers must be > 0")
    menu_lines = as_list(menu_lines_raw, "menu_lines")
    norm_lines = []
    for i, line in enumerate(menu_lines):
        if not isinstance(line, dict):
            raise ApiError("ERR_VALIDATION", 400, "Each menu line must be an object")
        recipe = recipes[i] if i < len(recipes) else None
        portions = as_int(required(line, "portions"), "menu_lines[].portions")
        if portions <= 0:
            raise ApiError("ERR_VALIDATION", 400, "portions must be > 0")
        if recipe is None:
            raise ApiError("ERR_VALIDATION", 400, "recipe_id must be a string")
        if recipe["status"] != "ACTIVE" or recipe["dining_hall_id"] != dining_hall_id:
            raise ApiError(
                "ERR_VALIDATION",
                400,
                "Each recipe must be ACTIVE at the order's hall",
            )
        norm_lines.append(
            {
                "recipe_id": recipe["id"],
                "portions": portions,
                "_unit_cost_cents": recipe["unit_cost_cents"],
            }
        )
    dietary_plates = data.get("dietary_plates", 0)
    if dietary_plates is None:
        dietary_plates = 0
    dietary_plates = as_int(dietary_plates, "dietary_plates")
    if dietary_plates < 0:
        raise ApiError("ERR_VALIDATION", 400, "dietary_plates must be >= 0")
    if revised_from_id is not None:
        if revised_from is None:
            raise ApiError("ERR_VALIDATION", 400, "revised_from_id must be a string")
        if revised_from["approval_status"] != "REJECTED":
            raise ApiError(
                "ERR_VALIDATION", 400, "revised_from_id must reference a REJECTED order"
            )
    quoted = c2_quote(norm_lines, covers, dietary_plates)
    rec = {
        "id": new_id(),
        "dining_hall_id": dining_hall_id,
        "department_id": department_id,
        "revised_from_id": revised_from_id,
        "event_date": event_date,
        "time_slot": time_slot,
        "guaranteed_covers": covers,
        "menu_lines": [
            {"recipe_id": l["recipe_id"], "portions": l["portions"]} for l in norm_lines
        ],
        "dietary_plates": dietary_plates,
        "quoted_total_cents": quoted,
        "final_total_cents": None,
        "cancellation_fee_cents": 0,
        "approval_status": "DRAFT",
        "fulfillment_status": "NONE",
        "_seq": next_seq(),
    }
    stamp(rec)
    DB["catering_orders"][rec["id"]] = rec
    return ok(ser(rec), status=201)


@bp.get("/catering-orders")
def list_orders():
    return list_endpoint(
        "catering_orders",
        [
            ("dining_hall_id", "dining_hall_id"),
            ("department_id", "department_id"),
            ("approval_status", "approval_status"),
            ("fulfillment_status", "fulfillment_status"),
            ("revised_from_id", "revised_from_id"),
        ],
    )


@bp.get("/catering-orders/<oid>")
def get_one_order(oid):
    auth(ALL_ROLES)
    return ok(ser(get_catering_order(oid)))


@bp.post("/catering-orders/<oid>/submit")
def submit_order(oid):
    user_id, role = auth(["DepartmentUser"])
    order = get_catering_order(oid)
    _own_order_or_forbid(user_id, role, order)
    if order["approval_status"] not in ("DRAFT", "REJECTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Order is not DRAFT or REJECTED")
    hall = get_hall(order["dining_hall_id"])
    if hall["status"] != "ACTIVE":
        raise ApiError("ERR_HALL_SUSPENDED", 409, "Dining hall is not ACTIVE")
    # Tier 8: slot start must be at least 48h after logical now (inclusive).
    if event_start_dt(order) - logical_now_dt() < timedelta(hours=48):
        raise ApiError(
            "ERR_LEAD_TIME_VIOLATION", 422, "Event starts less than 48 hours from now"
        )
    department = get_department(order["department_id"])
    # Tier 9: budget covers the frozen quote (exact equality allowed).
    if department["available_cents"] < order["quoted_total_cents"]:
        raise ApiError(
            "ERR_INSUFFICIENT_BUDGET", 402, "Department budget cannot cover the quote"
        )
    order["approval_status"] = "SUBMITTED"
    c7_recompute(department)
    touch(department)
    touch(order)
    return ok(ser(order))


@bp.post("/catering-orders/<oid>/approve")
def approve_order(oid):
    auth(["HallManager"])
    order = get_catering_order(oid)
    if order["approval_status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order is not SUBMITTED")
    data = body()
    department = get_department(order["department_id"])
    # OCC: checked immediately after from-state validation.
    expected = required(data, "expected_department_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(
            "ERR_VALIDATION", 400, "expected_department_version must be an integer"
        )
    if expected != department["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            412,
            "expected_department_version does not match the department version",
        )
    # Tier 6: no open CRITICAL corrective action at the order's hall.
    if has_open_critical_action(order["dining_hall_id"]):
        raise ApiError(
            "ERR_CRITICAL_VIOLATION_OPEN",
            422,
            "A CRITICAL corrective action is still open at this hall",
        )
    # Tier 7: (hall, event_date, time_slot) capacity pool.
    hall = get_hall(order["dining_hall_id"])
    pool = sum(
        o["guaranteed_covers"]
        for o in DB["catering_orders"].values()
        if o["id"] != order["id"]
        and o["dining_hall_id"] == order["dining_hall_id"]
        and o["event_date"] == order["event_date"]
        and o["time_slot"] == order["time_slot"]
        and o["approval_status"] == "APPROVED"
    )
    if pool + order["guaranteed_covers"] > hall["catering_kitchen_capacity"]:
        raise ApiError(
            "ERR_CATERING_CAPACITY_EXCEEDED",
            409,
            "Approving would exceed the catering kitchen capacity",
        )
    order["approval_status"] = "APPROVED"
    c7_recompute(department)
    touch(department)
    touch(order)
    return ok(ser(order))


@bp.post("/catering-orders/<oid>/reject")
def reject_order(oid):
    auth(["HallManager"])
    order = get_catering_order(oid)
    if order["approval_status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order is not SUBMITTED")
    order["approval_status"] = "REJECTED"
    department = get_department(order["department_id"])
    c7_recompute(department)
    touch(department)
    touch(order)
    return ok(ser(order))


@bp.post("/catering-orders/<oid>/schedule")
def schedule_order(oid):
    auth(["HallManager"])
    order = get_catering_order(oid)
    if order["approval_status"] != "APPROVED" or order["fulfillment_status"] != "NONE":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Order is not APPROVED with fulfillment NONE"
        )
    order["fulfillment_status"] = "SCHEDULED"
    touch(order)
    return ok(ser(order))


@bp.post("/catering-orders/<oid>/fulfill")
def fulfill_order(oid):
    auth(["KitchenLead"])
    order = get_catering_order(oid)
    if order["fulfillment_status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order fulfillment is not SCHEDULED")
    order["fulfillment_status"] = "FULFILLED"
    touch(order)
    return ok(ser(order))


@bp.post("/catering-orders/<oid>/invoice")
def invoice_order(oid):
    auth(["HallManager"])
    order = get_catering_order(oid)
    if order["fulfillment_status"] != "FULFILLED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order fulfillment is not FULFILLED")
    data = body()
    final_total = as_int(required(data, "final_total_cents"), "final_total_cents")
    quoted = order["quoted_total_cents"]
    low = rhu_int(Decimal(quoted) * Decimal("0.80"))
    high = rhu_int(Decimal(quoted) * Decimal("1.20"))
    if not low <= final_total <= high:
        raise ApiError(
            "ERR_VALIDATION",
            400,
            "final_total_cents must be within [80%, 120%] of the quoted total",
        )
    order["final_total_cents"] = final_total
    order["fulfillment_status"] = "INVOICED"
    touch(order)
    return ok(ser(order))


@bp.post("/catering-orders/<oid>/pay")
def pay_order(oid):
    auth(["DiningAdmin"])
    order = get_catering_order(oid)
    if order["fulfillment_status"] != "INVOICED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order fulfillment is not INVOICED")
    order["fulfillment_status"] = "PAID"
    department = get_department(order["department_id"])
    c7_recompute(department)
    touch(department)
    touch(order)
    return ok(ser(order))


@bp.post("/catering-orders/<oid>/cancel")
def cancel_order(oid):
    user_id, role = auth(["DepartmentUser", "HallManager"])
    order = get_catering_order(oid)
    _own_order_or_forbid(user_id, role, order)
    approval = order["approval_status"]
    fulfillment = order["fulfillment_status"]
    department = get_department(order["department_id"])
    if approval == "DRAFT" and fulfillment == "NONE":
        order["approval_status"] = "CANCELLED"
        order["cancellation_fee_cents"] = 0
        touch(order)
        return ok(ser(order))
    if approval == "SUBMITTED" and fulfillment == "NONE":
        order["approval_status"] = "CANCELLED"
        order["cancellation_fee_cents"] = 0
        c7_recompute(department)
        touch(department)
        touch(order)
        return ok(ser(order))
    if approval == "APPROVED" and fulfillment in ("NONE", "SCHEDULED"):
        # Fee: 1000 bps when the event is >= 72h away (inclusive), else 2500.
        fee_bps = (
            1000
            if event_start_dt(order) - logical_now_dt() >= timedelta(hours=72)
            else 2500
        )
        fee = rhu_int(Decimal(order["quoted_total_cents"] * fee_bps) / Decimal(10000))
        order["cancellation_fee_cents"] = fee
        order["approval_status"] = "CANCELLED"
        order["fulfillment_status"] = "CANCELLED"
        c7_recompute(department)
        touch(department)
        touch(order)
        return ok(ser(order))
    raise ApiError("ERR_INVALID_STATE", 409, "Order cannot be cancelled")
