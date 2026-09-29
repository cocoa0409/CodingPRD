"""Customer special orders, pickup windows and deposit settlement (PRD §3.8)."""

from flask import Blueprint

import errors
import middleware as mw
import validation as v
from calc import AMEND_LIMIT, cancel_refund_cents, deposit_cents, rhu
from db import db, make, mark, now, sort_rows, today
from errors import ApiError
from response import list_response, object_response
from services import case, pricing

bp = Blueprint("pre_orders", __name__)

ORDER_ACTION_ROLES = {
    "CONFIRM": (mw.SERVICE_CLERK,),
    "AMEND": (mw.SERVICE_CLERK,),
    "STAGE": (mw.MEAT_CUTTER,),
    "PICK_UP": (mw.SERVICE_CLERK,),
    "CANCEL": (mw.SERVICE_CLERK,),
    "FORFEIT": (mw.MEAT_MANAGER,),
}

DECLARED_TRANSITIONS = {
    "CONFIRM": ("REQUESTED",),
    "AMEND": ("CONFIRMED",),
    # HELD is admitted so rung 20 (ERR_LINE_ON_HOLD) can own it.
    "STAGE": ("CONFIRMED",),
    "PICK_UP": ("STAGED", "HELD"),
    "CANCEL": ("REQUESTED", "CONFIRMED", "STAGED"),
    "FORFEIT": ("STAGED",),
}

STAGEABLE_LINE_STATUSES = ("FILLED", "MARKED_DOWN")


@bp.route("/meat-ops/pre-orders", methods=["POST"])
def create_pre_order():
    mw.authenticate((mw.SERVICE_CLERK, mw.MEAT_MANAGER))
    payload = v.body()

    department_id = v.field_id(payload, "department_id", required=True)
    retail_item_id = v.field_id(payload, "retail_item_id", required=True)
    customer_name = v.field_str(payload, "customer_name", required=True,
                                min_len=1, max_len=120)
    customer_phone = v.field_str(payload, "customer_phone", required=True,
                                 min_len=7, max_len=20)
    requested_weight_lb = v.field_num(payload, "requested_weight_lb", required=True,
                                      gt=0, places=2)
    start_raw, start_at = v.field_instant(payload, "pickup_window_start_at",
                                          required=True)
    end_raw, end_at = v.field_instant(payload, "pickup_window_end_at", required=True)
    if not (end_at > start_at):
        v.bad("'pickup_window_end_at' must be strictly after "
              "'pickup_window_start_at'")
    staged_line_id = v.field_id(payload, "staged_case_plan_line_id")

    v.resolve("department", department_id)
    item = v.resolve("retail_item", retail_item_id)
    staged_line = v.resolve_optional("case_plan_line", staged_line_id)

    if item["price_status"] == "SUSPENDED":
        raise ApiError(errors.ERR_ITEM_NOT_PRICED, 409,
                       "A SUSPENDED item may not be ordered")

    if item["department_id"] != department_id:
        raise ApiError(errors.ERR_DEPARTMENT_MISMATCH, 422,
                       "The ordered retail item belongs to another department")
    if staged_line is not None:
        plan = db.case_plans.get(staged_line["case_plan_id"])
        if plan is None or plan["department_id"] != department_id:
            raise ApiError(errors.ERR_DEPARTMENT_MISMATCH, 422,
                           "The named case line belongs to another department")

    order = make("PreOrder", {
        "department_id": department_id,
        "retail_item_id": retail_item_id,
        "staged_case_plan_line_id": staged_line_id,
        "customer_name": customer_name,
        "customer_phone": customer_phone,
        "requested_weight_lb": requested_weight_lb,
        "pickup_window_start_at": start_raw,
        "pickup_window_end_at": end_raw,
        "quoted_price_per_lb_cents": 0,
        "pinned_retail_item_version": 0,
        "deposit_cents": 0,
        "deposit_applied_cents": 0,
        "deposit_refund_cents": 0,
        "deposit_forfeited_cents": 0,
        "amend_count": 0,
        "status": "REQUESTED",
        "_pickup_start": start_at,
        "_pickup_end": end_at,
    })
    db.pre_orders[order["id"]] = order
    return object_response(order, 201)


@bp.route("/meat-ops/pre-orders/<order_id>", methods=["GET"])
def get_pre_order(order_id):
    mw.authenticate(mw.COLD_CHAIN_READERS)
    return object_response(v.resolve("pre_order", order_id))


@bp.route("/meat-ops/pre-orders", methods=["GET"])
def list_pre_orders():
    mw.authenticate(mw.COLD_CHAIN_READERS)
    limit, offset = v.pagination()
    department_id = v.query_filter("department_id")
    retail_item_id = v.query_filter("retail_item_id")
    staged_line_id = v.query_filter("staged_case_plan_line_id")
    status = v.query_filter("status")
    rows = []
    for row in db.pre_orders.values():
        if department_id is not None and row["department_id"] != department_id:
            continue
        if retail_item_id is not None and row["retail_item_id"] != retail_item_id:
            continue
        if (staged_line_id is not None
                and row.get("staged_case_plan_line_id") != staged_line_id):
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return list_response(sort_rows(rows), limit, offset)


def _intersecting_count(order):
    """CONFIRMED/STAGED orders whose closed pickup interval meets this one."""
    total = 0
    for other in db.pre_orders.values():
        if other["id"] == order["id"]:
            continue
        if other["department_id"] != order["department_id"]:
            continue
        if other["status"] not in ("CONFIRMED", "STAGED"):
            continue
        if (other["_pickup_start"] <= order["_pickup_end"]
                and order["_pickup_start"] <= other["_pickup_end"]):
            total += 1
    return total


@bp.route("/meat-ops/pre-orders/<order_id>/transitions", methods=["POST"])
def order_transition(order_id):
    _, role = mw.authenticate((mw.SERVICE_CLERK, mw.MEAT_CUTTER, mw.MEAT_MANAGER))
    order = v.resolve("pre_order", order_id)
    payload = v.body()

    action = v.field_enum(payload, "action", tuple(ORDER_ACTION_ROLES), required=True)
    staged_line_id = v.field_id(payload, "staged_case_plan_line_id",
                                required=(action == "STAGE"))
    staged_line = v.resolve_optional("case_plan_line", staged_line_id)

    mw.check_action_role(role, action, ORDER_ACTION_ROLES)

    if order["status"] not in DECLARED_TRANSITIONS[action]:
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION, 409,
                       "%s is not a declared transition out of %s"
                       % (action, order["status"]))

    department = db.departments[order["department_id"]]
    item = db.retail_items.get(order["retail_item_id"])

    if action == "CONFIRM":
        if item is None or item["price_status"] not in pricing.PRICEABLE_STATUSES:
            raise ApiError(errors.ERR_ITEM_NOT_PRICED, 409,
                           "The ordered retail item is not priced")
        if _intersecting_count(order) >= department["pickup_slot_capacity"]:
            raise ApiError(errors.ERR_PICKUP_SLOT_CAPACITY_EXCEEDED, 409,
                           "The pickup slot capacity is already committed")
        order["quoted_price_per_lb_cents"] = item["active_price_per_lb_cents"]
        order["pinned_retail_item_version"] = item["version"]
        order["deposit_cents"] = deposit_cents(item["active_price_per_lb_cents"],
                                               order["requested_weight_lb"],
                                               department["deposit_rate"])
        order["status"] = "CONFIRMED"
        mark(order)

    elif action == "AMEND":
        if order["amend_count"] >= AMEND_LIMIT:
            raise ApiError(errors.ERR_REVISION_LIMIT_REACHED, 422,
                           "The amendment budget is exhausted")
        order["amend_count"] = order["amend_count"] + 1
        order["quoted_price_per_lb_cents"] = 0
        order["pinned_retail_item_version"] = 0
        order["deposit_cents"] = 0
        order["status"] = "REQUESTED"
        mark(order)

    elif action == "STAGE":
        if (staged_line["sell_by_date"] is not None
                and staged_line["sell_by_date"] < today().isoformat()):
            raise ApiError(errors.ERR_SELL_BY_EXPIRED, 422,
                           "The case line's sell_by_date has passed")
        if staged_line["line_status"] == "HELD":
            raise ApiError(errors.ERR_LINE_ON_HOLD, 409, "The case line is HELD")
        if staged_line["line_status"] not in STAGEABLE_LINE_STATUSES:
            raise ApiError(errors.ERR_INVALID_STATE_TRANSITION, 409,
                           "A %s case line may not carry a staged order"
                           % staged_line["line_status"])
        if staged_line["retail_item_id"] != order["retail_item_id"]:
            raise ApiError(errors.ERR_PRODUCT_CLASS_MISMATCH, 422,
                           "The case line does not carry the ordered item")
        available = (staged_line["actual_fill_lb"] - staged_line["staged_lb"]
                     - staged_line["markdown_lb"] - staged_line["shrink_lb"])
        if order["requested_weight_lb"] > available:
            raise ApiError(errors.ERR_LINE_POUNDS_UNAVAILABLE, 422,
                           "The case line does not hold that many available pounds")

        staged_line["staged_lb"] = rhu(staged_line["staged_lb"]
                                       + order["requested_weight_lb"], 2)
        mark(staged_line)
        order["staged_case_plan_line_id"] = staged_line["id"]
        order["status"] = "STAGED"
        mark(order)

    elif action == "PICK_UP":
        if order["status"] == "HELD":
            raise ApiError(errors.ERR_LINE_ON_HOLD, 409, "The pre-order is HELD")
        current = now()
        if not (order["_pickup_start"] <= current <= order["_pickup_end"]):
            raise ApiError(errors.ERR_PICKUP_WINDOW_CLOSED, 422,
                           "The logical clock sits outside the pickup window")
        order["deposit_applied_cents"] = order["deposit_cents"]
        order["deposit_refund_cents"] = 0
        order["deposit_forfeited_cents"] = 0
        order["status"] = "PICKED_UP"
        mark(order)
        line = db.case_plan_lines.get(order.get("staged_case_plan_line_id"))
        if line is not None:
            case.release_pounds_from_fill(line, order["requested_weight_lb"])

    elif action == "CANCEL":
        from_status = order["status"]
        if from_status == "REQUESTED":
            order["deposit_refund_cents"] = 0
            order["deposit_forfeited_cents"] = 0
        elif now() < order["_pickup_start"]:
            order["deposit_refund_cents"] = order["deposit_cents"]
            order["deposit_forfeited_cents"] = 0
        else:
            refund = cancel_refund_cents(order["deposit_cents"])
            order["deposit_refund_cents"] = refund
            order["deposit_forfeited_cents"] = order["deposit_cents"] - refund
        order["status"] = "CANCELLED"
        mark(order)
        if from_status == "STAGED":
            line = db.case_plan_lines.get(order.get("staged_case_plan_line_id"))
            if line is not None:
                case.release_staged_pounds(line, order["requested_weight_lb"])

    else:                                          # FORFEIT
        if now() <= order["_pickup_end"]:
            raise ApiError(errors.ERR_PICKUP_WINDOW_CLOSED, 422,
                           "The pickup window has not closed yet")
        order["deposit_forfeited_cents"] = order["deposit_cents"]
        order["deposit_refund_cents"] = 0
        order["status"] = "FORFEITED"
        mark(order)
        line = db.case_plan_lines.get(order.get("staged_case_plan_line_id"))
        if line is not None:
            case.release_staged_pounds(line, order["requested_weight_lb"])

    return object_response(order)
