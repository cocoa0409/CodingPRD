"""Store plans, configured lines, pricing, approval and fabrication (PRD 3.6 / 3.7)."""

from flask import Blueprint

import serialize
from calculations import (
    case_unit_price_cents,
    store_plan_commercial_total,
)
from db import db, new_row, rows
from errors import (
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_DUPLICATE_CODE,
    ERR_INVALID_STATE_TRANSITION,
    ERR_LENGTH_NOT_OFFERED,
    ERR_MODEL_NOT_CERTIFIED,
    ERR_OPTION_NOT_COMPATIBLE,
    ERR_PLAN_ON_COMPLIANCE_HOLD,
    ERR_REWORK_LIMIT_EXCEEDED,
    ERR_SCRAP_NOT_PERMITTED,
    ERR_SEGREGATION_OF_DUTIES,
    fail,
)
from middleware import ALL_ROLES, roles_required, user_id
from response import created, ok, ok_list
from services import (
    get_case_model,
    get_store_plan,
    get_store_plan_line,
    get_work_order,
    plan_lines,
    recompute_line_counters,
    recompute_unit_counters,
    recompute_warranty_accrual,
    recompute_warranty_incurred,
    touch,
)
from routes.design import check_charge_limit
from validation import (
    filter_enum,
    filter_value,
    get_body,
    opt_array,
    opt_enum,
    opt_string,
    paginate,
    pagination,
    req_datetime,
    req_enum,
    req_int,
    req_string,
)

bp = Blueprint("plans", __name__)

END_CAPS = ["NONE", "LEFT", "RIGHT", "BOTH"]
OPTIONS = [
    "LED_CANOPY", "NIGHT_CURTAIN", "GLASS_DOOR_UPGRADE", "SHELF_LIGHTING",
    "DIGITAL_PRICE_RAIL",
]
LENGTHS = [4, 6, 8, 12]
WORK_ORDER_STATUSES = [
    "QUEUED", "SHEET_METAL", "FOAM_INJECTION", "DOOR_ASSEMBLY", "FINAL_QA",
    "COMPLETE", "REWORK", "HELD", "SHIPPED", "SCRAPPED",
]
PRICING_FIELDS = [
    "subtotal_cents", "volume_discount_bps", "volume_discount_cents", "net_cents",
    "freight_cents", "install_allowance_cents", "total_cents",
]
REWORK_LIMIT = 2


def check_no_hold(plan):
    """Rank 16."""
    if plan["held_line_count"] != 0:
        fail(ERR_PLAN_ON_COMPLIANCE_HOLD,
             "The plan carries %d held line(s)" % plan["held_line_count"])
    for line in plan_lines(plan["id"]):
        if line["compliance_hold"]:
            fail(ERR_PLAN_ON_COMPLIANCE_HOLD, "The plan carries a held line")


def check_lines_certified(plan):
    """Rank 15 over every line of a plan."""
    for line in plan_lines(plan["id"]):
        model = db.case_models.get(line["case_model_id"])
        if model is None or model["status"] != "CERTIFIED":
            fail(ERR_MODEL_NOT_CERTIFIED,
                 "Case model on line %s is not CERTIFIED" % line["id"])


# --------------------------------------------------------------------------
@bp.post("/store-plans")
@roles_required("SalesEngineer")
def create_store_plan():
    body = get_body()
    banner_name = req_string(body, "banner_name")
    store_number = req_string(body, "store_number")
    region_code = req_string(body, "region_code")
    window_start_raw, window_start = req_datetime(body, "remodel_window_start")
    window_end_raw, window_end = req_datetime(body, "remodel_window_end")
    credit_limit_cents = req_int(body, "credit_limit_cents", minimum=0)

    for existing in db.store_plans.values():  # rank 21
        if existing["store_number"] == store_number \
                and existing["banner_name"] == banner_name:
            fail(ERR_DUPLICATE_CODE,
                 "store_number '%s' already exists for banner '%s'"
                 % (store_number, banner_name))

    row = new_row()
    row.update({
        "banner_name": banner_name,
        "store_number": store_number,
        "region_code": region_code,
        "remodel_window_start": window_start_raw,
        "remodel_window_end": window_end_raw,
        "_remodel_window_start": window_start,
        "_remodel_window_end": window_end,
        "credit_limit_cents": credit_limit_cents,
        "commercial_status": "DRAFT",
        "production_status": "NOT_RELEASED",
        "priced_by_user_id": None,
        "approved_by_user_id": None,
        "line_count": 0,
        "unit_count": 0,
        "held_line_count": 0,
        "units_completed_count": 0,
        "units_shipped_count": 0,
        "warranty_reserve_accrual_cents": 0,
        "warranty_reserve_incurred_cents": 0,
    })
    for field in PRICING_FIELDS:
        row[field] = None
    db.store_plans[row["id"]] = row
    return created(serialize.dump("StorePlan", row))


@bp.post("/store-plans/<plan_id>/lines")
@roles_required("SalesEngineer")
def add_store_plan_line(plan_id):
    body = get_body()
    case_model_id = req_string(body, "case_model_id")
    length_ft = req_int(body, "length_ft", choices=LENGTHS)
    quantity = req_int(body, "quantity", minimum=1)
    end_cap = opt_enum(body, "end_cap", END_CAPS, default="NONE")
    merchandising_options = opt_array(
        body, "merchandising_options", default=[], allowed=OPTIONS, non_empty=False
    )

    plan = get_store_plan(plan_id)                 # rank 5
    model = get_case_model(case_model_id)          # rank 6

    if plan["commercial_status"] not in ("DRAFT", "PRICED"):  # rank 7
        fail(ERR_INVALID_STATE_TRANSITION,
             "Lines may not be added while the plan is %s" % plan["commercial_status"])

    refrigerant = db.refrigerants.get(model["refrigerant_id"])
    check_charge_limit(model, refrigerant)         # rank 11

    if model["status"] != "CERTIFIED":             # rank 15
        fail(ERR_MODEL_NOT_CERTIFIED,
             "Case model %s is %s, not CERTIFIED" % (model["model_code"], model["status"]))

    if length_ft != model["nominal_length_ft"]:    # rank 19
        fail(ERR_LENGTH_NOT_OFFERED,
             "Model %s is offered at %d ft" % (model["model_code"], model["nominal_length_ft"]))

    # rank 20
    if "GLASS_DOOR_UPGRADE" in merchandising_options and model["door_type"] != "GLASS_DOOR":
        fail(ERR_OPTION_NOT_COMPATIBLE,
             "GLASS_DOOR_UPGRADE requires a GLASS_DOOR model")
    if "NIGHT_CURTAIN" in merchandising_options and model["door_type"] != "OPEN":
        fail(ERR_OPTION_NOT_COMPATIBLE, "NIGHT_CURTAIN requires an OPEN model")

    row = new_row()
    row.update({
        "store_plan_id": plan_id,
        "case_model_id": case_model_id,
        "length_ft": length_ft,
        "quantity": quantity,
        "end_cap": end_cap,
        "merchandising_options": merchandising_options,
        "unit_price_cents": None,
        "extended_price_cents": None,
        "compliance_hold": False,
    })
    db.store_plan_lines[row["id"]] = row

    recompute_line_counters(plan)
    if plan["commercial_status"] == "PRICED":
        plan["commercial_status"] = "DRAFT"
        for field in PRICING_FIELDS:
            plan[field] = None
        plan["priced_by_user_id"] = None
    touch(plan)

    return created(serialize.dump("StorePlanLine", row))


@bp.post("/store-plans/<plan_id>/price")
@roles_required("SalesEngineer")
def price_store_plan(plan_id):
    get_body()
    plan = get_store_plan(plan_id)

    lines = plan_lines(plan_id)
    if plan["commercial_status"] != "DRAFT" or len(lines) == 0:  # rank 7
        fail(ERR_INVALID_STATE_TRANSITION,
             "Only a DRAFT plan carrying at least one line may be priced")

    check_lines_certified(plan)  # rank 15
    check_no_hold(plan)          # rank 16

    for line in lines:
        model = db.case_models.get(line["case_model_id"])
        case_unit_price_cents(line, model)
        touch(line)

    store_plan_commercial_total(plan, lines)
    plan["commercial_status"] = "PRICED"
    plan["priced_by_user_id"] = user_id()
    touch(plan)
    return ok(serialize.dump("StorePlan", plan))


@bp.post("/store-plans/<plan_id>/approve")
@roles_required("SalesEngineer")
def approve_store_plan(plan_id):
    get_body()
    plan = get_store_plan(plan_id)

    if plan["commercial_status"] != "PRICED":  # rank 7
        fail(ERR_INVALID_STATE_TRANSITION, "Only a PRICED plan may be approved")

    if plan.get("priced_by_user_id") is not None \
            and plan["priced_by_user_id"] == user_id():  # rank 9
        fail(ERR_SEGREGATION_OF_DUTIES,
             "The approver may not be the engineer who priced the plan")

    check_no_hold(plan)  # rank 16

    if plan["total_cents"] > plan["credit_limit_cents"]:  # rank 39
        fail(ERR_CREDIT_LIMIT_EXCEEDED,
             "Plan total %d exceeds the credit limit %d"
             % (plan["total_cents"], plan["credit_limit_cents"]))

    plan["commercial_status"] = "APPROVED"
    plan["approved_by_user_id"] = user_id()
    touch(plan)
    return ok(serialize.dump("StorePlan", plan))


@bp.post("/store-plans/<plan_id>/release")
@roles_required("PlantSupervisor")
def release_store_plan(plan_id):
    get_body()
    plan = get_store_plan(plan_id)

    if plan["commercial_status"] != "APPROVED" \
            or plan["production_status"] != "NOT_RELEASED":  # rank 7
        fail(ERR_INVALID_STATE_TRANSITION,
             "Only an APPROVED, NOT_RELEASED plan may be released")

    check_lines_certified(plan)  # rank 15
    check_no_hold(plan)          # rank 16

    lines = plan_lines(plan_id)
    for rank, line in enumerate(lines, start=1):
        for sequence in range(1, line["quantity"] + 1):
            wo = new_row()
            wo.update({
                "store_plan_id": plan_id,
                "store_plan_line_id": line["id"],
                "case_model_id": line["case_model_id"],
                "shipment_id": None,
                "unit_sequence": sequence,
                "serial_number": "%s-%d-%d" % (plan["store_number"], rank, sequence),
                "unit_price_cents": line["unit_price_cents"],
                "rework_count": 0,
                "warranty_start_date": None,
                "status": "QUEUED",
            })
            db.work_orders[wo["id"]] = wo

    plan["production_status"] = "IN_PRODUCTION"
    recompute_warranty_accrual(plan)
    recompute_warranty_incurred(plan)
    touch(plan)
    return ok(serialize.dump("StorePlan", plan))


@bp.get("/store-plans/<plan_id>")
@roles_required(*ALL_ROLES)
def read_store_plan(plan_id):
    return ok(serialize.dump("StorePlan", get_store_plan(plan_id)))


@bp.get("/store-plan-lines/<line_id>")
@roles_required(*ALL_ROLES)
def read_store_plan_line(line_id):
    return ok(serialize.dump("StorePlanLine", get_store_plan_line(line_id)))


@bp.get("/store-plan-lines")
@roles_required(*ALL_ROLES)
def list_store_plan_lines():
    limit, offset = pagination()
    store_plan_id = filter_value("store_plan_id")
    case_model_id = filter_value("case_model_id")

    items = rows(db.store_plan_lines)
    if store_plan_id is not None:
        items = [r for r in items if r["store_plan_id"] == store_plan_id]
    if case_model_id is not None:
        items = [r for r in items if r["case_model_id"] == case_model_id]

    page, total = paginate(items, limit, offset)
    return ok_list(serialize.dump_many("StorePlanLine", page), limit, offset, total)


# --------------------------------------------------------------------------
# fabrication
# --------------------------------------------------------------------------
@bp.post("/work-orders/<work_order_id>/advance")
@roles_required("PlantSupervisor")
def advance_work_order(work_order_id):
    get_body()
    wo = get_work_order(work_order_id)
    plan = db.store_plans.get(wo["store_plan_id"])
    model = db.case_models.get(wo["case_model_id"])

    status = wo["status"]
    if status == "QUEUED":
        if plan is None or plan["production_status"] != "IN_PRODUCTION":
            fail(ERR_INVALID_STATE_TRANSITION,
                 "The owning plan must be IN_PRODUCTION to start fabrication")
        wo["status"] = "SHEET_METAL"
    elif status == "SHEET_METAL":
        wo["status"] = "FOAM_INJECTION"
    elif status == "FOAM_INJECTION":
        wo["status"] = "DOOR_ASSEMBLY" if model["door_type"] == "GLASS_DOOR" else "FINAL_QA"
    elif status == "DOOR_ASSEMBLY":
        wo["status"] = "FINAL_QA"
    elif status == "REWORK":
        wo["status"] = "SHEET_METAL"
    else:
        fail(ERR_INVALID_STATE_TRANSITION, "A %s unit cannot be advanced" % status)

    touch(wo)
    return ok(serialize.dump("WorkOrder", wo))


@bp.post("/work-orders/<work_order_id>/qa-result")
@roles_required("PlantSupervisor")
def record_qa_result(work_order_id):
    body = get_body()
    result = req_enum(body, "result", ["PASS", "FAIL", "SCRAP"])
    defect_note = opt_string(body, "defect_note")

    wo = get_work_order(work_order_id)

    if wo["status"] != "FINAL_QA":  # rank 7
        fail(ERR_INVALID_STATE_TRANSITION, "A QA result is only admissible from FINAL_QA")

    if result == "FAIL" and wo["rework_count"] >= REWORK_LIMIT:   # rank 25
        fail(ERR_REWORK_LIMIT_EXCEEDED,
             "The unit has exhausted its rework allowance of %d" % REWORK_LIMIT)
    if result == "SCRAP" and wo["rework_count"] != REWORK_LIMIT:  # rank 26
        fail(ERR_SCRAP_NOT_PERMITTED,
             "The unit still has rework attempts remaining")

    if defect_note is not None:
        wo["defect_note"] = defect_note

    if result == "PASS":
        wo["status"] = "COMPLETE"
    elif result == "FAIL":
        wo["status"] = "REWORK"
        wo["rework_count"] = wo["rework_count"] + 1
    else:
        wo["status"] = "SCRAPPED"
    touch(wo)

    plan = db.store_plans.get(wo["store_plan_id"])
    if plan is not None:
        before = plan["units_completed_count"]
        recompute_unit_counters(plan)
        if plan["units_completed_count"] != before:
            touch(plan)

    return ok(serialize.dump("WorkOrder", wo))


@bp.get("/work-orders/<work_order_id>")
@roles_required(*ALL_ROLES)
def read_work_order(work_order_id):
    return ok(serialize.dump("WorkOrder", get_work_order(work_order_id)))


@bp.get("/work-orders")
@roles_required(*ALL_ROLES)
def list_work_orders():
    limit, offset = pagination()
    store_plan_id = filter_value("store_plan_id")
    store_plan_line_id = filter_value("store_plan_line_id")
    case_model_id = filter_value("case_model_id")
    shipment_id = filter_value("shipment_id")
    status = filter_enum("status", WORK_ORDER_STATUSES)

    items = rows(db.work_orders)
    if store_plan_id is not None:
        items = [r for r in items if r["store_plan_id"] == store_plan_id]
    if store_plan_line_id is not None:
        items = [r for r in items if r["store_plan_line_id"] == store_plan_line_id]
    if case_model_id is not None:
        items = [r for r in items if r["case_model_id"] == case_model_id]
    if shipment_id is not None:
        items = [r for r in items if r["shipment_id"] == shipment_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]

    page, total = paginate(items, limit, offset)
    return ok_list(serialize.dump_many("WorkOrder", page), limit, offset, total)
