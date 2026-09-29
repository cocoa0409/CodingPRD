"""The service-day case plan: lines, publication, fills, markdowns and shrink.

PRD §3.6, §3.7 (suspend/resume hops), §2.9.
"""

from flask import Blueprint

import errors
import middleware as mw
import validation as v
from calc import (FILL_OVERAGE_CAP, markdown_floor_cents, markdown_give_up_cents,
                 required_fill_lb, rhu)
from db import db, make, mark, sort_rows, today
from errors import ApiError
from response import list_response, object_response
from services import case, pricing

bp = Blueprint("case_plans", __name__)

PLAN_ACTION_ROLES = {
    "PUBLISH": (mw.MEAT_MANAGER,),
    "SUSPEND": (mw.MEAT_MANAGER,),
    "RESUME": (mw.MEAT_MANAGER,),
    "CLOSE": (mw.MEAT_MANAGER,),
}

DECLARED_TRANSITIONS = {
    "PUBLISH": ("DRAFT",),
    "SUSPEND": ("PUBLISHED",),
    "RESUME": ("SUSPENDED",),
    "CLOSE": ("PUBLISHED",),
}


@bp.route("/meat-ops/case-plans", methods=["POST"])
def create_case_plan():
    mw.authenticate((mw.MEAT_MANAGER,))
    payload = v.body()

    department_id = v.field_id(payload, "department_id", required=True)
    service_date_raw, _ = v.field_date(payload, "service_date", required=True)

    v.resolve("department", department_id)

    for existing in db.case_plans.values():
        if (existing["department_id"] == department_id
                and existing["service_date"] == service_date_raw):
            raise ApiError(errors.ERR_DUPLICATE_RESOURCE, 409,
                           "A plan already exists for this service_date")

    plan = make("CasePlan", {
        "department_id": department_id,
        "service_date": service_date_raw,
        "plan_status": "DRAFT",
        "fill_status": "UNFILLED",
        "total_expected_movement_lb": rhu(0, 2),
        "total_required_fill_lb": rhu(0, 2),
        "total_actual_fill_lb": rhu(0, 2),
        "price_stale_line_count": 0,
        "published_by_user_id": None,
    })
    db.case_plans[plan["id"]] = plan
    return object_response(plan, 201)


@bp.route("/meat-ops/case-plans/<plan_id>", methods=["GET"])
def get_case_plan(plan_id):
    mw.authenticate(mw.NO_SERVICE_CLERK)
    return object_response(v.resolve("case_plan", plan_id))


@bp.route("/meat-ops/departments/<department_id>/case-plans", methods=["GET"])
def list_department_plans(department_id):
    mw.authenticate(mw.NO_SERVICE_CLERK)
    v.resolve("department", department_id)
    limit, offset = v.pagination()
    plan_status = v.query_filter("plan_status")
    fill_status = v.query_filter("fill_status")
    rows = []
    for row in db.case_plans.values():
        if row["department_id"] != department_id:
            continue
        if plan_status is not None and row["plan_status"] != plan_status:
            continue
        if fill_status is not None and row["fill_status"] != fill_status:
            continue
        rows.append(row)
    return list_response(sort_rows(rows), limit, offset)


# --------------------------------------------------------------------------
# plan lines
# --------------------------------------------------------------------------

@bp.route("/meat-ops/case-plans/<plan_id>/lines", methods=["POST"])
def create_plan_line(plan_id):
    mw.authenticate((mw.MEAT_MANAGER,))
    plan = v.resolve("case_plan", plan_id)
    payload = v.body()

    retail_item_id = v.field_id(payload, "retail_item_id", required=True)
    line_seq = v.field_int(payload, "line_seq", required=True, minimum=1, maximum=60)
    facings = v.field_int(payload, "facings", required=True, minimum=1, maximum=12)
    expected_movement_lb = v.field_num(payload, "expected_movement_lb", required=True,
                                       gt=0, places=2)

    item = v.resolve("retail_item", retail_item_id)

    if plan["plan_status"] not in ("DRAFT", "PUBLISHED"):
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION, 409,
                       "Lines may not be added to a %s plan" % plan["plan_status"])

    if item["price_status"] not in pricing.PRICEABLE_STATUSES:
        raise ApiError(errors.ERR_ITEM_NOT_PRICED, 409,
                       "The retail item is %s" % item["price_status"])

    department = db.departments[plan["department_id"]]
    if department["case_posture"] == "SALES_HALTED":
        raise ApiError(errors.ERR_POSTURE_SALES_HALTED, 409,
                       "The department is SALES_HALTED")

    if item["department_id"] != plan["department_id"]:
        raise ApiError(errors.ERR_DEPARTMENT_MISMATCH, 422,
                       "The retail item belongs to another department")

    for existing in case.lines_of_plan(plan["id"]):
        if existing["line_seq"] == line_seq:
            raise ApiError(errors.ERR_DUPLICATE_RESOURCE, 409,
                           "line_seq is already used on this plan")

    required = required_fill_lb(facings, expected_movement_lb,
                                item["product_class"], item["shelf_life_days"],
                                department["case_posture"])

    line = make("CasePlanLine", {
        "case_plan_id": plan["id"],
        "retail_item_id": retail_item_id,
        "line_seq": line_seq,
        "facings": facings,
        "expected_movement_lb": expected_movement_lb,
        "required_fill_lb": required,
        "actual_fill_lb": rhu(0, 2),
        "staged_lb": rhu(0, 2),
        "pack_date": None,
        "sell_by_date": None,
        "markdown_lb": rhu(0, 2),
        "markdown_price_per_lb_cents": 0,
        "markdown_dollars_cents": 0,
        "shrink_lb": rhu(0, 2),
        "price_stale": False,
        "held_from_status": None,
        "line_status": "PLANNED",
    })
    db.case_plan_lines[line["id"]] = line

    case.recompute_plan_totals(plan)
    return object_response(line, 201)


@bp.route("/meat-ops/case-plan-lines/<line_id>", methods=["GET"])
def get_plan_line(line_id):
    mw.authenticate(mw.ALL_ROLES)
    return object_response(v.resolve("case_plan_line", line_id))


@bp.route("/meat-ops/case-plan-lines", methods=["GET"])
def list_plan_lines():
    mw.authenticate(mw.ALL_ROLES)
    limit, offset = v.pagination()
    case_plan_id = v.query_filter("case_plan_id")
    retail_item_id = v.query_filter("retail_item_id")
    line_status = v.query_filter("line_status")
    price_stale = v.query_bool("price_stale")
    rows = []
    for row in db.case_plan_lines.values():
        if case_plan_id is not None and row["case_plan_id"] != case_plan_id:
            continue
        if retail_item_id is not None and row["retail_item_id"] != retail_item_id:
            continue
        if line_status is not None and row["line_status"] != line_status:
            continue
        if price_stale is not None and row["price_stale"] is not price_stale:
            continue
        rows.append(row)
    return list_response(sort_rows(rows), limit, offset)


# --------------------------------------------------------------------------
# plan transitions
# --------------------------------------------------------------------------

@bp.route("/meat-ops/case-plans/<plan_id>/transitions", methods=["POST"])
def plan_transition(plan_id):
    user_id, role = mw.authenticate((mw.MEAT_MANAGER,))
    plan = v.resolve("case_plan", plan_id)
    payload = v.body()

    action = v.field_enum(payload, "action", tuple(PLAN_ACTION_ROLES), required=True)
    mw.check_action_role(role, action, PLAN_ACTION_ROLES)

    if plan["plan_status"] not in DECLARED_TRANSITIONS[action]:
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION, 409,
                       "%s is not a declared transition out of %s"
                       % (action, plan["plan_status"]))

    department = db.departments[plan["department_id"]]
    lines = case.lines_of_plan(plan["id"])

    if action == "PUBLISH":
        if not lines:
            raise ApiError(errors.ERR_INVALID_STATE_TRANSITION, 409,
                           "A plan needs at least one line before publication")
        for line in lines:
            item = db.retail_items.get(line["retail_item_id"])
            if item is None or item["price_status"] not in pricing.PRICEABLE_STATUSES:
                raise ApiError(errors.ERR_ITEM_NOT_PRICED, 409,
                               "A line's retail item is not priced")
        if department["case_posture"] == "SALES_HALTED":
            raise ApiError(errors.ERR_POSTURE_SALES_HALTED, 409,
                           "The department is SALES_HALTED")
        plan["published_by_user_id"] = user_id
        plan["plan_status"] = "PUBLISHED"
        mark(plan)
        case.recompute_plan_totals(plan)

    elif action == "SUSPEND":
        if plan["service_date"] < today().isoformat():
            raise ApiError(errors.ERR_INVALID_STATE_TRANSITION, 409,
                           "A past service_date plan may not be suspended")
        case.suspend_plan(plan)

    elif action == "RESUME":
        if department["case_posture"] == "SALES_HALTED":
            raise ApiError(errors.ERR_POSTURE_SALES_HALTED, 409,
                           "The department is SALES_HALTED")
        case.resume_plan(plan)

    else:                                          # CLOSE
        for line in lines:
            if line["line_status"] == "PLANNED":
                raise ApiError(errors.ERR_CASE_PLAN_HAS_UNFILLED_LINES, 422,
                               "A line is still PLANNED")
        plan["plan_status"] = "CLOSED"
        mark(plan)

    return object_response(plan)


# --------------------------------------------------------------------------
# fills
# --------------------------------------------------------------------------

@bp.route("/meat-ops/case-plan-lines/<line_id>/fills", methods=["POST"])
def create_fill(line_id):
    mw.authenticate((mw.MEAT_CUTTER,))
    line = v.resolve("case_plan_line", line_id)
    payload = v.body()
    filled_lb = v.field_num(payload, "filled_lb", required=True, gt=0, places=2)

    if line["line_status"] not in ("PLANNED", "FILLED"):
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION, 409,
                       "A %s line may not be filled" % line["line_status"])

    plan = db.case_plans[line["case_plan_id"]]
    if plan["plan_status"] != "PUBLISHED":
        raise ApiError(errors.ERR_CASE_PLAN_NOT_PUBLISHED, 409,
                       "The owning plan is not PUBLISHED")

    department = db.departments[plan["department_id"]]
    if department["case_posture"] == "SALES_HALTED":
        raise ApiError(errors.ERR_POSTURE_SALES_HALTED, 409,
                       "The department is SALES_HALTED")

    if (line["actual_fill_lb"] + filled_lb) > (line["required_fill_lb"]
                                               * FILL_OVERAGE_CAP):
        raise ApiError(errors.ERR_FILL_EXCEEDS_REQUIRED, 422,
                       "The fill exceeds the overage cap on required_fill_lb")

    case.apply_fill(line, filled_lb)
    return object_response(line, 201)


# --------------------------------------------------------------------------
# markdowns
# --------------------------------------------------------------------------

@bp.route("/meat-ops/case-plan-lines/<line_id>/markdowns", methods=["POST"])
def create_markdown(line_id):
    mw.authenticate((mw.PRICING_ANALYST,))
    line = v.resolve("case_plan_line", line_id)
    payload = v.body()
    markdown_lb = v.field_num(payload, "markdown_lb", required=True, gt=0, places=2)
    markdown_price = v.field_int(payload, "markdown_price_per_lb_cents",
                                 required=True, minimum=0)

    # HELD deliberately falls through to rung 20 so ERR_LINE_ON_HOLD can fire.
    if line["line_status"] not in ("FILLED", "MARKED_DOWN", "HELD"):
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION, 409,
                       "A %s line may not be marked down" % line["line_status"])

    plan = db.case_plans[line["case_plan_id"]]
    if plan["plan_status"] != "PUBLISHED":
        raise ApiError(errors.ERR_CASE_PLAN_NOT_PUBLISHED, 409,
                       "The owning plan is not PUBLISHED")

    if (line["sell_by_date"] is not None
            and line["sell_by_date"] < today().isoformat()):
        raise ApiError(errors.ERR_SELL_BY_EXPIRED, 422,
                       "The line's sell_by_date has passed")

    if line["line_status"] == "HELD":
        raise ApiError(errors.ERR_LINE_ON_HOLD, 409, "The case line is HELD")

    item = db.retail_items[line["retail_item_id"]]
    department = db.departments[plan["department_id"]]
    floor = markdown_floor_cents(item["yield_adjusted_cost_per_lb_cents"],
                                 department["markdown_floor_pct"])
    if markdown_price < floor:
        raise ApiError(errors.ERR_MARKDOWN_BELOW_FLOOR, 422,
                       "markdown_price_per_lb_cents is below the %d cent floor" % floor)

    committed = (line["markdown_lb"] + line["shrink_lb"] + line["staged_lb"]
                 + markdown_lb)
    if committed > line["actual_fill_lb"]:
        raise ApiError(errors.ERR_LINE_POUNDS_UNAVAILABLE, 422,
                       "The line does not hold that many available pounds")

    line["markdown_lb"] = rhu(line["markdown_lb"] + markdown_lb, 2)
    line["markdown_price_per_lb_cents"] = markdown_price
    line["markdown_dollars_cents"] = line["markdown_dollars_cents"] + \
        markdown_give_up_cents(markdown_lb, item["active_price_per_lb_cents"],
                               markdown_price)
    line["line_status"] = "MARKED_DOWN"
    mark(line)
    return object_response(line, 201)


# --------------------------------------------------------------------------
# shrink events
# --------------------------------------------------------------------------

@bp.route("/meat-ops/case-plan-lines/<line_id>/shrink-events", methods=["POST"])
def create_shrink_event(line_id):
    mw.authenticate((mw.MEAT_MANAGER,))
    line = v.resolve("case_plan_line", line_id)
    payload = v.body()
    shrink_lb = v.field_num(payload, "shrink_lb", required=True, gt=0, places=2)

    if line["line_status"] not in ("FILLED", "MARKED_DOWN"):
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION, 409,
                       "A %s line may not take a shrink event" % line["line_status"])

    plan = db.case_plans[line["case_plan_id"]]
    if plan["plan_status"] != "PUBLISHED":
        raise ApiError(errors.ERR_CASE_PLAN_NOT_PUBLISHED, 409,
                       "The owning plan is not PUBLISHED")

    available = line["actual_fill_lb"] - line["staged_lb"]
    accumulated = line["shrink_lb"] + shrink_lb
    # Rung 39: markdown_lb, shrink_lb and staged pounds together never exceed
    # actual_fill_lb, on top of the narrower shrink-versus-unstaged ceiling.
    if (accumulated > available
            or (line["markdown_lb"] + accumulated + line["staged_lb"])
            > line["actual_fill_lb"]):
        raise ApiError(errors.ERR_LINE_POUNDS_UNAVAILABLE, 422,
                       "The line does not hold that many available pounds")

    line["shrink_lb"] = rhu(accumulated, 2)
    if line["shrink_lb"] == available:
        line["line_status"] = "SHRUNK_OUT"
    mark(line)
    case.recompute_plan_totals(plan)
    return object_response(line, 201)
