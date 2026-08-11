"""The shared condition rubric, cleaning routing and retirement (PRD 3.6)."""

from flask import Blueprint

import auth
import boxops
import calc
import constants as K
import derive
import envelope
import ledger
import listing
import lookup
import serialize
import shape
import store
import tradein_ops
from errors import ApiError

bp = Blueprint("grading", __name__)


def _latest_box_item_for_unit(unit_id):
    items = [i for i in store.all_rows("box_items") if i["unit_id"] == unit_id]
    if not items:
        return None
    return items[-1]


@bp.post("/kidswear/condition-assessments")
def open_assessment():
    auth.gate("GradingTechnician")
    body = shape.body_json()
    pipeline = shape.enum_in(body, "pipeline", K.PIPELINES)
    unit_id = shape.id_string(body, "unit_id", required=False)
    trade_in_item_id = shape.id_string(body, "trade_in_item_id", required=False)
    if (unit_id is None) == (trade_in_item_id is None):
        raise ApiError("ERR_ASSESSMENT_TARGET_MISMATCH")
    if pipeline == "RENTAL" and unit_id is None:
        raise ApiError("ERR_ASSESSMENT_TARGET_MISMATCH")
    if pipeline == "TRADE_IN" and trade_in_item_id is None:
        raise ApiError("ERR_ASSESSMENT_TARGET_MISMATCH")
    if unit_id is not None:
        lookup.unit(unit_id)
    if trade_in_item_id is not None:
        lookup.trade_in_item(trade_in_item_id)
    row = store.insert("assessments", {
        "unit_id": unit_id,
        "trade_in_item_id": trade_in_item_id,
        "pipeline": pipeline,
        "status": "DRAFT",
        "grade": None,
        "defect_codes": [],
        "regrade_count": 0,
        "graded_by_user_id": None,
        "confirmed_by_user_id": None,
        "dispute_reason": None,
    })
    return envelope.created(serialize.assessment(row))


@bp.get("/kidswear/condition-assessments")
def list_assessments():
    auth.gate("GradingTechnician", "MerchandisePlanner", "PlatformAdmin",
              "Member", "CleaningVendor", "WarehouseOperator")
    rows = store.all_rows("assessments")
    rows = listing.eq(rows, "unit_id", shape.query_str("unit_id"))
    rows = listing.eq(rows, "trade_in_item_id", shape.query_str("trade_in_item_id"))
    rows = listing.eq(rows, "pipeline", shape.query_member("pipeline", K.PIPELINES))
    rows = listing.eq(rows, "status", shape.query_member("status", K.ASSESSMENT_STATUSES))
    return envelope.listing(rows, serialize.assessment)


@bp.get("/kidswear/condition-assessments/<assessment_id>")
def read_assessment(assessment_id):
    auth.gate("GradingTechnician", "MerchandisePlanner", "PlatformAdmin",
              "Member", "CleaningVendor")
    return envelope.ok(serialize.assessment(lookup.assessment(assessment_id)))


@bp.post("/kidswear/condition-assessments/<assessment_id>/submit")
def submit_grade(assessment_id):
    caller = auth.gate("GradingTechnician")
    body = shape.body_json()
    grade = shape.enum_in(body, "grade", K.GRADE_LADDER)
    defect_codes = shape.str_list(body, "defect_codes", required=False, default=[])
    record = lookup.assessment(assessment_id)
    if record["status"] != "DRAFT":
        raise ApiError("ERR_ASSESSMENT_INVALID_STATE")
    record["status"] = "SUBMITTED"
    record["grade"] = grade
    record["defect_codes"] = list(defect_codes)
    record["graded_by_user_id"] = caller.user_id
    store.touch(record)
    if record["pipeline"] == "TRADE_IN":
        item = store.get("trade_in_items", record["trade_in_item_id"])
        submission = store.get("submissions", item["submission_id"]) if item else None
        if submission is not None and submission["status"] == "RECEIVED":
            submission["status"] = "GRADING"
            store.touch(submission)
    return envelope.ok(serialize.assessment(record))


@bp.post("/kidswear/condition-assessments/<assessment_id>/dispute")
def dispute_grade(assessment_id):
    auth.gate("Member", "MerchandisePlanner")
    body = shape.body_json()
    dispute_reason = shape.string(body, "dispute_reason")
    record = lookup.assessment(assessment_id)
    if record["status"] != "SUBMITTED":
        raise ApiError("ERR_ASSESSMENT_INVALID_STATE")
    if record["regrade_count"] >= K.REGRADE_MAX_ATTEMPTS:
        raise ApiError("ERR_RETRY_CAP_REACHED")
    record["status"] = "DISPUTED"
    record["dispute_reason"] = dispute_reason
    store.touch(record)
    return envelope.ok(serialize.assessment(record))


@bp.post("/kidswear/condition-assessments/<assessment_id>/regrade")
def regrade(assessment_id):
    caller = auth.gate("GradingTechnician")
    body = shape.body_json()
    grade = shape.enum_in(body, "grade", K.GRADE_LADDER)
    record = lookup.assessment(assessment_id)
    if record["status"] != "DISPUTED":
        raise ApiError("ERR_ASSESSMENT_INVALID_STATE")
    if record["regrade_count"] >= K.REGRADE_MAX_ATTEMPTS:
        raise ApiError("ERR_RETRY_CAP_REACHED")
    record["status"] = "SUBMITTED"
    record["grade"] = grade
    record["regrade_count"] += 1
    record["graded_by_user_id"] = caller.user_id
    store.touch(record)
    return envelope.ok(serialize.assessment(record))


@bp.post("/kidswear/condition-assessments/<assessment_id>/confirm")
def confirm_grade(assessment_id):
    caller = auth.gate("MerchandisePlanner")
    record = lookup.assessment(assessment_id)
    # rung 5 (G2): segregation of duties, against the MOST RECENT grader
    if record["graded_by_user_id"] is not None and caller.user_id == record["graded_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if record["pipeline"] == "RENTAL":
        return _confirm_rental(record, caller)
    return _confirm_trade_in(record, caller)


def _confirm_rental(record, caller):
    if record["unit_id"] is None:
        raise ApiError("ERR_PIPELINE_MISMATCH")
    unit = lookup.unit(record["unit_id"])
    item = _latest_box_item_for_unit(unit["id"])
    # rung 26 precedes rung 30
    if item is not None and item["settlement_status"] != "OPEN":
        raise ApiError("ERR_BOX_ITEM_ALREADY_SETTLED")
    if record["status"] not in ("SUBMITTED", "DISPUTED"):
        raise ApiError("ERR_ASSESSMENT_INVALID_STATE")

    grade = record["grade"]
    style = lookup.style(unit["style_id"])
    cycle = boxops.cycle_of_item(item) if item is not None else None
    member = boxops.member_of_item(item) if item is not None else None

    gross = calc.damage_fee_gross(grade, style["retail_price_cents"])
    ordinal = K.GRADE_ORDINALS[grade]
    enrolled = bool(member and member["protection_enrolled"])
    remaining_cap = calc.protection_waiver_remaining_cap(cycle) if cycle is not None else 0
    would_draw = enrolled and ordinal <= K.PROTECTION_WAIVER_GRADE_ORDINAL_MAX \
        and gross > 0 and remaining_cap > 0
    if would_draw:
        # rung 62 (G11)
        protection_charge = None
        for charge in derive.member_charges(member["id"]):
            if charge["cycle_id"] == cycle["id"] and charge["charge_type"] == "PROTECTION_FEE":
                protection_charge = charge
                break
        if protection_charge is None or protection_charge["status"] == "WAIVED":
            raise ApiError("ERR_WAIVER_NOT_AVAILABLE")

    record["status"] = "CONFIRMED"
    record["confirmed_by_user_id"] = caller.user_id
    store.touch(record)

    if item is not None:
        if not enrolled or ordinal > K.PROTECTION_WAIVER_GRADE_ORDINAL_MAX:
            waived = 0
        else:
            waived = min(gross, remaining_cap)
        fully_waived = (enrolled and ordinal <= K.PROTECTION_WAIVER_GRADE_ORDINAL_MAX
                        and gross > 0 and gross <= remaining_cap)
        item["assessed_grade"] = grade
        item["damage_fee_cents"] = 0 if fully_waived else gross - waived
        item["settlement_status"] = "WAIVED" if fully_waived else "SETTLED"
        store.touch(item)
        if cycle is not None and waived > 0:
            cycle["protection_waiver_used_cents"] += waived
            store.touch(cycle)
        if not fully_waived and item["damage_fee_cents"] > 0 and member is not None:
            ledger.new_charge(member, "DAMAGE_FEE", item["damage_fee_cents"],
                              cycle["id"] if cycle else None)

    store.insert("jobs", {
        "assessment_id": record["id"],
        "unit_id": unit["id"],
        "route": K.GRADE_ROUTE_MAP[grade],
        "status": "QUEUED",
        "attempt_count": 0,
        "cost_cents": 0,
        "post_repair_grade": None,
    })
    return envelope.ok(serialize.assessment(record))


def _confirm_trade_in(record, caller):
    if record["trade_in_item_id"] is None:
        raise ApiError("ERR_PIPELINE_MISMATCH")
    item = lookup.trade_in_item(record["trade_in_item_id"])
    if record["status"] not in ("SUBMITTED", "DISPUTED"):
        raise ApiError("ERR_ASSESSMENT_INVALID_STATE")
    if item["grading_status"] != "PENDING":
        raise ApiError("ERR_TRADE_IN_INVALID_STATE")
    record["status"] = "CONFIRMED"
    record["confirmed_by_user_id"] = caller.user_id
    store.touch(record)
    tradein_ops.apply_confirmed_grade(item, record["grade"])
    return envelope.ok(serialize.assessment(record))


# ---------- processing jobs ---------------------------------------------

@bp.get("/kidswear/processing-jobs")
def list_jobs():
    auth.gate("CleaningVendor", "MerchandisePlanner", "PlatformAdmin", "WarehouseOperator")
    rows = store.all_rows("jobs")
    rows = listing.eq(rows, "assessment_id", shape.query_str("assessment_id"))
    rows = listing.eq(rows, "unit_id", shape.query_str("unit_id"))
    rows = listing.eq(rows, "route", shape.query_member("route", K.JOB_ROUTES))
    rows = listing.eq(rows, "status", shape.query_member("status", K.JOB_STATUSES))
    return envelope.listing(rows, serialize.job)


@bp.get("/kidswear/processing-jobs/<job_id>")
def read_job(job_id):
    auth.gate("CleaningVendor", "MerchandisePlanner", "PlatformAdmin", "WarehouseOperator")
    return envelope.ok(serialize.job(lookup.job(job_id)))


@bp.post("/kidswear/processing-jobs/<job_id>/start")
def start_job(job_id):
    auth.gate("CleaningVendor")
    job = lookup.job(job_id)
    if job["status"] not in ("QUEUED", "FAILED"):
        raise ApiError("ERR_ASSESSMENT_INVALID_STATE")
    # PRD 3.6: scrapping "is the *only* path a RETIRE-routed job may ever take,
    # because such a job can never be started and never be passed."
    if job["route"] == "RETIRE":
        raise ApiError("ERR_ASSESSMENT_INVALID_STATE")
    unit = lookup.unit(job["unit_id"])
    if unit["state"] != "PROCESSING":
        raise ApiError("ERR_UNIT_INVALID_STATE")
    if job["attempt_count"] >= K.REWORK_MAX_ATTEMPTS:
        raise ApiError("ERR_RETRY_CAP_REACHED")
    if job["status"] == "QUEUED":
        job["cost_cents"] = K.ROUTE_BASE_COST_CENTS[job["route"]]
    else:
        job["cost_cents"] += calc.rework_increment(job["route"])
    job["attempt_count"] += 1
    job["status"] = "IN_PROGRESS"
    store.touch(job)
    return envelope.ok(serialize.job(job))


@bp.post("/kidswear/processing-jobs/<job_id>/fail")
def fail_job(job_id):
    auth.gate("CleaningVendor")
    job = lookup.job(job_id)
    if job["status"] != "IN_PROGRESS":
        raise ApiError("ERR_ASSESSMENT_INVALID_STATE")
    job["status"] = "FAILED"
    store.touch(job)
    return envelope.ok(serialize.job(job))


@bp.post("/kidswear/processing-jobs/<job_id>/pass")
def pass_job(job_id):
    auth.gate("CleaningVendor")
    body = shape.body_json()
    post_repair_grade = shape.enum_in(body, "post_repair_grade", K.POST_REPAIR_GRADES,
                                      required=False, default=None)
    job = lookup.job(job_id)
    if job["status"] != "IN_PROGRESS":
        raise ApiError("ERR_ASSESSMENT_INVALID_STATE")
    if job["route"] == "RETIRE":
        raise ApiError("ERR_ASSESSMENT_INVALID_STATE")
    record = lookup.assessment(job["assessment_id"])
    unit = lookup.unit(job["unit_id"])
    if post_repair_grade is not None and job["route"] != "REPAIR":
        raise ApiError("ERR_REPAIR_UPLIFT_EXCEEDED")
    effective = record["grade"]
    if job["route"] == "REPAIR" and post_repair_grade is not None:
        if record["grade"] == "RETIRE":
            effective = "RETIRE"
        else:
            uplift = K.GRADE_ORDINALS[record["grade"]] - K.GRADE_ORDINALS[post_repair_grade]
            if uplift > K.REPAIR_UPLIFT_MAX_STEPS:
                raise ApiError("ERR_REPAIR_UPLIFT_EXCEEDED")
            effective = post_repair_grade
    if unit["state"] == "RETIRED":
        effective = "RETIRE"

    job["status"] = "PASSED"
    job["post_repair_grade"] = post_repair_grade
    store.touch(job)

    total = 0
    for other in store.all_rows("jobs"):
        if other["unit_id"] == unit["id"] and other["status"] in ("PASSED", "SCRAPPED"):
            total += other["cost_cents"]
    unit["cumulative_cleaning_cost_cents"] = total
    unit["current_grade"] = effective
    eligible = (unit["cycles_completed"] >= K.UNIT_MAX_CYCLES
                or unit["cumulative_cleaning_cost_cents"] >= K.UNIT_MAX_CLEANING_COST_CENTS
                or unit["current_grade"] == "RETIRE")
    unit["retirement_eligible"] = eligible
    if eligible:
        unit["state"] = "RETIRED"
        if unit["cycles_completed"] >= K.UNIT_MAX_CYCLES:
            unit["retired_reason"] = "CYCLE_CAP"
        elif unit["cumulative_cleaning_cost_cents"] >= K.UNIT_MAX_CLEANING_COST_CENTS:
            unit["retired_reason"] = "COST_CAP"
        else:
            unit["retired_reason"] = "GRADE_RETIRE"
    else:
        unit["state"] = "IN_STOCK"
    store.touch(unit)
    return envelope.ok(serialize.job(job))


@bp.post("/kidswear/processing-jobs/<job_id>/scrap")
def scrap_job(job_id):
    auth.gate("MerchandisePlanner")
    job = lookup.job(job_id)
    if job["status"] == "FAILED":
        reason = "REWORK_FAILED"
    elif job["status"] == "QUEUED" and job["route"] == "RETIRE":
        reason = "GRADE_RETIRE"
    else:
        raise ApiError("ERR_ASSESSMENT_INVALID_STATE")
    job["status"] = "SCRAPPED"
    store.touch(job)
    unit = lookup.unit(job["unit_id"])
    if unit["state"] == "PROCESSING":
        unit["state"] = "RETIRED"
        unit["retired_reason"] = reason
        unit["retirement_eligible"] = True
        store.touch(unit)
    return envelope.ok(serialize.job(job))
