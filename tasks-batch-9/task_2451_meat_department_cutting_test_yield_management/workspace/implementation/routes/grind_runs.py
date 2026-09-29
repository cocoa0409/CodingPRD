"""Grinder scheduling, trim commitment and blend completion (PRD §3.5)."""

from decimal import Decimal

from flask import Blueprint

import errors
import middleware as mw
import validation as v
from calc import rhu
from db import db, make, mark, now_iso, sort_rows
from errors import ApiError
from response import list_response, object_response
from services import case, grind, pricing

bp = Blueprint("grind_runs", __name__)

DECLARED_COOS = ("USA", "CAN", "MEX", "AUS", "MULTIPLE")
OPEN_STATUSES = ("SCHEDULED", "IN_PROGRESS")
COMMITTABLE = ("AVAILABLE", "PARTIALLY_COMMITTED")

RUN_ACTION_ROLES = {
    "START": (mw.MEAT_CUTTER,),
    "COMPLETE": (mw.MEAT_CUTTER,),
    "ABORT": (mw.MEAT_MANAGER,),
}

DECLARED_TRANSITIONS = {
    "START": ("SCHEDULED",),
    "COMPLETE": ("IN_PROGRESS",),
    "ABORT": ("SCHEDULED", "IN_PROGRESS"),
}


@bp.route("/meat-ops/grind-runs", methods=["POST"])
def create_grind_run():
    mw.authenticate((mw.MEAT_CUTTER, mw.MEAT_MANAGER))
    payload = v.body()

    department_id = v.field_id(payload, "department_id", required=True)
    target_retail_item_id = v.field_id(payload, "target_retail_item_id", required=True)
    declared_coo = v.field_enum(payload, "declared_coo", DECLARED_COOS, required=True)
    start_raw, start_at = v.field_instant(payload, "scheduled_start_at", required=True)
    end_raw, end_at = v.field_instant(payload, "scheduled_end_at", required=True)
    if not (end_at > start_at):
        v.bad("'scheduled_end_at' must be strictly after 'scheduled_start_at'")
    target_lean_pct = v.field_num(payload, "target_lean_pct", required=True,
                                 minimum=Decimal("60.0"), maximum=Decimal("95.0"),
                                 places=1)
    lean_tolerance_pct = v.field_num(payload, "lean_tolerance_pct", gt=Decimal("0.0"),
                                     maximum=Decimal("10.0"),
                                     default=Decimal("2.0"), places=1)
    fill_case_plan_line_id = v.field_id(payload, "fill_case_plan_line_id")

    department = v.resolve("department", department_id)
    item = v.resolve("retail_item", target_retail_item_id)
    fill_line = v.resolve_optional("case_plan_line", fill_case_plan_line_id)

    if item["department_id"] != department_id:
        raise ApiError(errors.ERR_DEPARTMENT_MISMATCH, 422,
                       "The target retail item belongs to another department")
    if fill_line is not None:
        fill_plan = db.case_plans.get(fill_line["case_plan_id"])
        if fill_plan is None or fill_plan["department_id"] != department_id:
            raise ApiError(errors.ERR_DEPARTMENT_MISMATCH, 422,
                           "The fill case line belongs to another department")

    if item["product_class"] != "GROUND":
        raise ApiError(errors.ERR_PRODUCT_CLASS_MISMATCH, 422,
                       "A grind run must target a GROUND retail item")

    neighbours = [row for row in db.grind_runs.values()
                  if row["department_id"] == department_id
                  and row["status"] in OPEN_STATUSES]

    # rung 24 — half-open windows, so touching endpoints do not overlap
    for other in neighbours:
        if start_at < other["_end"] and other["_start"] < end_at:
            raise ApiError(errors.ERR_GRINDER_WINDOW_CONFLICT, 409,
                           "The grinder window overlaps another run")

    # rung 25 — country-of-origin changeover buffer
    buffer_min = department["grind_sanitation_buffer_min"]
    predecessor = None
    successor = None
    for other in neighbours:
        if other["_end"] <= start_at:
            if predecessor is None or other["_end"] > predecessor["_end"]:
                predecessor = other
        if other["_start"] >= end_at:
            if successor is None or other["_start"] < successor["_start"]:
                successor = other
    for neighbour, gap in ((predecessor,
                            None if predecessor is None
                            else (start_at - predecessor["_end"]).total_seconds() / 60.0),
                           (successor,
                            None if successor is None
                            else (successor["_start"] - end_at).total_seconds() / 60.0)):
        if neighbour is None:
            continue
        if neighbour["declared_coo"] == declared_coo:
            continue
        if gap < buffer_min:
            raise ApiError(errors.ERR_SANITATION_BUFFER_REQUIRED, 409,
                           "A country-of-origin changeover needs %s minutes of idle "
                           "time" % buffer_min)

    run = make("GrindRun", {
        "department_id": department_id,
        "target_retail_item_id": target_retail_item_id,
        "fill_case_plan_line_id": fill_case_plan_line_id,
        "declared_coo": declared_coo,
        "coo_label": "PENDING",
        "scheduled_start_at": start_raw,
        "scheduled_end_at": end_raw,
        "target_lean_pct": target_lean_pct,
        "lean_tolerance_pct": lean_tolerance_pct,
        "batch_weight_lb": rhu(0, 2),
        "blended_lean_pct": rhu(0, 2),
        "blend_cost_per_lb_cents": rhu(0, 4),
        "started_by_user_id": None,
        "completed_at": None,
        "abort_reason": None,
        "status": "SCHEDULED",
        "_start": start_at,
        "_end": end_at,
    })
    db.grind_runs[run["id"]] = run
    return object_response(run, 201)


@bp.route("/meat-ops/grind-runs/<run_id>", methods=["GET"])
def get_grind_run(run_id):
    mw.authenticate(mw.NO_SERVICE_CLERK)
    return object_response(v.resolve("grind_run", run_id))


@bp.route("/meat-ops/grind-runs", methods=["GET"])
def list_grind_runs():
    mw.authenticate(mw.NO_SERVICE_CLERK)
    limit, offset = v.pagination()
    department_id = v.query_filter("department_id")
    target_retail_item_id = v.query_filter("target_retail_item_id")
    fill_case_plan_line_id = v.query_filter("fill_case_plan_line_id")
    status = v.query_filter("status")
    rows = []
    for row in db.grind_runs.values():
        if department_id is not None and row["department_id"] != department_id:
            continue
        if (target_retail_item_id is not None
                and row["target_retail_item_id"] != target_retail_item_id):
            continue
        if (fill_case_plan_line_id is not None
                and row.get("fill_case_plan_line_id") != fill_case_plan_line_id):
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return list_response(sort_rows(rows), limit, offset)


# --------------------------------------------------------------------------
# grind inputs
# --------------------------------------------------------------------------

@bp.route("/meat-ops/grind-runs/<run_id>/inputs", methods=["POST"])
def create_grind_input(run_id):
    mw.authenticate((mw.MEAT_CUTTER,))
    run = v.resolve("grind_run", run_id)
    payload = v.body()

    trim_lot_id = v.field_id(payload, "trim_lot_id", required=True)
    input_seq = v.field_int(payload, "input_seq", required=True, minimum=1, maximum=20)
    weight_lb = v.field_num(payload, "weight_lb", required=True, gt=0, places=2)

    lot = v.resolve("trim_lot", trim_lot_id)

    if run["status"] not in OPEN_STATUSES:
        raise ApiError(errors.ERR_GRIND_RUN_NOT_OPEN, 409,
                       "The grind run is %s" % run["status"])

    if lot["status"] not in COMMITTABLE:
        raise ApiError(errors.ERR_TRIM_LOT_NOT_AVAILABLE, 409,
                       "The trim lot is %s" % lot["status"])

    if lot["department_id"] != run["department_id"]:
        raise ApiError(errors.ERR_DEPARTMENT_MISMATCH, 422,
                       "The trim lot belongs to another department")

    for existing in grind.inputs_of_run(run["id"]):
        if existing["input_seq"] == input_seq:
            raise ApiError(errors.ERR_DUPLICATE_RESOURCE, 409,
                           "input_seq is already used on this run")
        if existing["trim_lot_id"] == trim_lot_id:
            raise ApiError(errors.ERR_DUPLICATE_RESOURCE, 409,
                           "That trim lot is already committed to this run")

    if weight_lb > lot["remaining_lb"]:
        raise ApiError(errors.ERR_TRIM_INSUFFICIENT, 422,
                       "The lot does not hold that many remaining pounds")

    grind_input = make("GrindInput", {
        "grind_run_id": run["id"],
        "trim_lot_id": trim_lot_id,
        "input_seq": input_seq,
        "weight_lb": weight_lb,
        "consumed": False,
    })
    db.grind_inputs[grind_input["id"]] = grind_input

    grind.commit_pounds(lot, weight_lb)
    grind.derive_blend(run)
    return object_response(grind_input, 201)


@bp.route("/meat-ops/grind-inputs/<input_id>", methods=["GET"])
def get_grind_input(input_id):
    mw.authenticate(mw.ADMIN_MANAGER_CUTTER)
    return object_response(v.resolve("grind_input", input_id))


@bp.route("/meat-ops/grind-inputs", methods=["GET"])
def list_grind_inputs():
    mw.authenticate(mw.ADMIN_MANAGER_CUTTER)
    limit, offset = v.pagination()
    grind_run_id = v.query_filter("grind_run_id")
    trim_lot_id = v.query_filter("trim_lot_id")
    consumed = v.query_bool("consumed")
    rows = []
    for row in db.grind_inputs.values():
        if grind_run_id is not None and row["grind_run_id"] != grind_run_id:
            continue
        if trim_lot_id is not None and row["trim_lot_id"] != trim_lot_id:
            continue
        if consumed is not None and row["consumed"] is not consumed:
            continue
        rows.append(row)
    return list_response(sort_rows(rows), limit, offset)


# --------------------------------------------------------------------------
# run transitions
# --------------------------------------------------------------------------

@bp.route("/meat-ops/grind-runs/<run_id>/transitions", methods=["POST"])
def run_transition(run_id):
    user_id, role = mw.authenticate((mw.MEAT_CUTTER, mw.MEAT_MANAGER))
    run = v.resolve("grind_run", run_id)
    payload = v.body()

    action = v.field_enum(payload, "action", tuple(RUN_ACTION_ROLES), required=True)
    abort_reason = v.field_str(payload, "abort_reason", required=(action == "ABORT"),
                              min_len=1, max_len=280)

    mw.check_action_role(role, action, RUN_ACTION_ROLES)

    if run["status"] not in DECLARED_TRANSITIONS[action]:
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION, 409,
                       "%s is not a declared transition out of %s"
                       % (action, run["status"]))

    department = db.departments[run["department_id"]]
    item = db.retail_items.get(run["target_retail_item_id"])

    if action == "START":
        if run["batch_weight_lb"] <= 0:
            raise ApiError(errors.ERR_INVALID_STATE_TRANSITION, 409,
                           "The run holds no committed trim pounds")
        if item is None or item["price_status"] not in pricing.PRICEABLE_STATUSES:
            raise ApiError(errors.ERR_ITEM_NOT_PRICED, 409,
                           "The target retail item is not priced")
        if department["case_posture"] == "SALES_HALTED":
            raise ApiError(errors.ERR_POSTURE_SALES_HALTED, 409,
                           "The department is SALES_HALTED")
        run["started_by_user_id"] = user_id
        run["status"] = "IN_PROGRESS"
        mark(run)
        grind.derive_blend(run)

    elif action == "COMPLETE":
        if run["coo_label"] != run["declared_coo"]:
            raise ApiError(errors.ERR_COO_LABEL_MISMATCH, 422,
                           "The derived coo_label does not equal declared_coo")
        if abs(run["blended_lean_pct"] - run["target_lean_pct"]) > run["lean_tolerance_pct"]:
            raise ApiError(errors.ERR_LEAN_OUT_OF_TOLERANCE, 422,
                           "The blended lean is outside the tolerance")

        run["completed_at"] = now_iso()
        run["status"] = "COMPLETED"
        mark(run)

        for row in grind.inputs_of_run(run["id"]):
            lot = db.trim_lots.get(row["trim_lot_id"])
            if lot is not None:
                grind.consume_pounds(lot, row["weight_lb"])
            row["consumed"] = True
            mark(row)

        if item is not None:
            item["yield_adjusted_cost_per_lb_cents"] = run["blend_cost_per_lb_cents"]
            item["country_of_origin_label"] = run["coo_label"]
            mark(item)
            item_department = db.departments.get(item["department_id"]) or department
            pricing.recompute_final_after_cost_change(item, item_department)

        if run.get("fill_case_plan_line_id"):
            fill_line = db.case_plan_lines.get(run["fill_case_plan_line_id"])
            if fill_line is not None:
                case.apply_fill(fill_line, run["batch_weight_lb"])

    else:                                          # ABORT
        for row in grind.inputs_of_run(run["id"]):
            lot = db.trim_lots.get(row["trim_lot_id"])
            if lot is not None:
                grind.restore_pounds(lot, row["weight_lb"])
        run["abort_reason"] = abort_reason
        run["status"] = "ABORTED"
        mark(run)

    return object_response(run)
