"""Reclassification: pay-structure conversion and employee communication
(PRD 3.7)."""
from flask import Blueprint

import db
from constants import (
    ALL_ROLES,
    COMMUNICATION_ACTIONS,
    CONVERSION_METHODS,
    MAX_CONCURRENT_RECLASS_PER_FAMILY,
    RECLASS_WINDOW_BUFFER_DAYS,
    VOLUNTARY_CORRECTION_MANDATORY_CENTS,
)
from errors import fail
from middleware import body, endpoint, pagination
from response import success, success_list
from services import calculations, derive, lookup, serialize
from validation import opt_str, req_date, req_enum, req_num, req_str

bp = Blueprint("reclassification_cases", __name__)

UNREVERTED = ("PENDING", "CONVERTED")


def _window(case):
    return case["_start_date"], case["_end_date"]


def _intersects(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


def _separation_days(a_start, a_end, b_start, b_end):
    """Calendar days between two closed intervals; 0 when they touch or overlap."""
    if a_start > b_end:
        return (a_start - b_end).days
    if b_start > a_end:
        return (b_start - a_end).days
    return 0


@bp.post("/reclassification-cases")
@endpoint(["CompensationManager"])
def create_case():
    payload = body()
    position_id = req_str(payload, "position_id")
    raw_start = req_str(payload, "effective_date")
    raw_end = req_str(payload, "effective_end_date")
    start = req_date(payload, "effective_date")
    end = req_date(payload, "effective_end_date")
    conversion_method = req_enum(payload, "conversion_method", CONVERSION_METHODS)
    if end < start:
        fail("ERR_INVALID_REQUEST", "effective_end_date must be on or after effective_date.")
    if start < db.clock_date():
        fail("ERR_INVALID_REQUEST", "effective_date may not be in the past.")

    # rank 5: foreign key
    position = lookup.position(position_id)

    # rank 15: windows on the same position may not crowd each other
    for existing in db.reclassification_cases.values():
        if existing["position_id"] != position["id"]:
            continue
        e_start, e_end = _window(existing)
        # overlapping, abutting and near windows all separate by <= the buffer
        if _separation_days(start, end, e_start, e_end) <= RECLASS_WINDOW_BUFFER_DAYS:
            fail("ERR_RECLASS_WINDOW_CONFLICT")

    # rank 16: reclassification wave capacity inside one job family
    family_position_ids = {
        p["id"] for p in derive.positions_of_family(position["job_family_id"])
    }
    intersecting = 0
    for existing in db.reclassification_cases.values():
        if existing["position_id"] not in family_position_ids:
            continue
        if existing["pay_conversion_status"] not in UNREVERTED:
            continue
        e_start, e_end = _window(existing)
        if _intersects(start, end, e_start, e_end):
            intersecting += 1
    if intersecting >= MAX_CONCURRENT_RECLASS_PER_FAMILY:
        fail("ERR_RECLASS_WAVE_CAPACITY_EXCEEDED")

    row = db.make_row(
        position_id=position["id"],
        effective_date=raw_start,
        effective_end_date=raw_end,
        _start_date=start,
        _end_date=end,
        conversion_method=conversion_method,
        expected_weekly_hours=None,
        converted_hourly_rate_cents=None,
        projected_annual_cost_cents=None,
        cost_delta_cents=None,
        notice_channel=None,
        notice_sent_at=None,
        acknowledged_at=None,
        acknowledged_by_ref=None,
        escalation_reason=None,
        pay_conversion_status="PENDING",
        communication_status="NOT_STARTED",
    )
    db.reclassification_cases[row["id"]] = row
    return success(serialize.reclassification_case(row), 201)


@bp.get("/reclassification-cases/<case_id>")
@endpoint(ALL_ROLES)
def get_case(case_id):
    case = lookup.case(case_id)
    return success(serialize.reclassification_case(case), 200)


@bp.post("/reclassification-cases/<case_id>/pay-conversion")
@endpoint(["CompensationManager"])
def pay_conversion(case_id):
    case = lookup.case(case_id)
    payload = body()
    expected_weekly_hours = req_num(
        payload, "expected_weekly_hours", minimum=0, maximum=168
    )
    position = lookup.position(case["position_id"])

    # rank 8: declared transitions PENDING -> CONVERTED and REVERTED -> CONVERTED
    if case["pay_conversion_status"] not in ("PENDING", "REVERTED"):
        fail("ERR_INVALID_STATE_TRANSITION")

    # rank 12: cross-entity prerequisites
    if position["classification_status"] != "MISCLASSIFIED":
        fail("ERR_POSITION_NOT_MISCLASSIFIED")
    if derive.case_exposure_cents(case) >= VOLUNTARY_CORRECTION_MANDATORY_CENTS:
        approved = any(
            v["reclassification_case_id"] == case["id"] and v["status"] == "APPROVED"
            for v in db.voluntary_corrections.values()
        )
        if not approved:
            fail("ERR_VOLUNTARY_CORRECTION_REQUIRED")

    figures = calculations.pay_structure_conversion(
        position, case["conversion_method"], expected_weekly_hours
    )
    case["expected_weekly_hours"] = expected_weekly_hours
    case.update(figures)
    case["pay_conversion_status"] = "CONVERTED"
    db.touch(case)

    position["current_fls_status"] = "NONEXEMPT"
    position["classification_status"] = "RECLASSIFIED"
    lookup.touch_position_chain(position)
    return success(serialize.reclassification_case(case), 200)


@bp.post("/reclassification-cases/<case_id>/revert-pay-conversion")
@endpoint(["CompensationManager"])
def revert_pay_conversion(case_id):
    case = lookup.case(case_id)
    position = lookup.position(case["position_id"])

    # rank 8: only a converted case may be reverted, and not after acknowledgement
    if case["pay_conversion_status"] != "CONVERTED":
        fail("ERR_INVALID_STATE_TRANSITION")
    if case["communication_status"] == "ACKNOWLEDGED":
        fail("ERR_CASE_ALREADY_COMPLETED")

    case["converted_hourly_rate_cents"] = None
    case["projected_annual_cost_cents"] = None
    case["cost_delta_cents"] = None
    case["pay_conversion_status"] = "REVERTED"
    db.touch(case)

    position["current_fls_status"] = "EXEMPT"
    position["classification_status"] = "MISCLASSIFIED"
    lookup.touch_position_chain(position)
    return success(serialize.reclassification_case(case), 200)


@bp.post("/reclassification-cases/<case_id>/communication")
@endpoint(["EmployeeRelationsLead"])
def communication(case_id):
    case = lookup.case(case_id)
    payload = body()
    action = req_enum(payload, "action", COMMUNICATION_ACTIONS)
    notice_channel = opt_str(payload, "notice_channel", default=None)
    acknowledged_by_ref = opt_str(payload, "acknowledged_by_ref", default=None)
    escalation_reason = opt_str(payload, "escalation_reason", default=None)
    position = lookup.position(case["position_id"])
    current = case["communication_status"]

    # rank 8: declared transitions on the communication dimension
    if action == "SEND_NOTICE":
        if current not in ("NOT_STARTED", "ESCALATED"):
            fail("ERR_INVALID_STATE_TRANSITION")
    elif action == "ACKNOWLEDGE":
        if current not in ("NOTICE_SENT", "ESCALATED"):
            fail("ERR_INVALID_STATE_TRANSITION")
    else:  # ESCALATE
        if current != "NOTICE_SENT":
            fail("ERR_INVALID_STATE_TRANSITION")

    # rank 17: notice lead time
    if action == "SEND_NOTICE":
        rule = derive.state_rule_for(position["work_state_code"])
        required_days = rule["reclass_notice_days"] if rule else 0
        lead_days = (case["_start_date"] - db.clock_date()).days
        if lead_days < required_days:
            fail("ERR_NOTICE_WINDOW_TOO_SHORT")

    if action == "SEND_NOTICE":
        if notice_channel is not None:
            case["notice_channel"] = notice_channel
        case["notice_sent_at"] = db.now_iso()
        case["escalation_reason"] = None
        case["communication_status"] = "NOTICE_SENT"
    elif action == "ACKNOWLEDGE":
        case["acknowledged_at"] = db.now_iso()
        case["acknowledged_by_ref"] = acknowledged_by_ref
        case["escalation_reason"] = None
        case["communication_status"] = "ACKNOWLEDGED"
    else:
        case["escalation_reason"] = escalation_reason
        case["communication_status"] = "ESCALATED"
    db.touch(case)
    return success(serialize.reclassification_case(case), 200)


@bp.get("/reclassification-cases/<case_id>/back-wage-estimates")
@endpoint(ALL_ROLES)
def list_estimates(case_id):
    case = lookup.case(case_id)
    limit, offset = pagination()
    rows = derive.estimates_of_case(case["id"])
    items, total = serialize.paginate(rows, limit, offset, serialize.back_wage_estimate)
    return success_list(items, limit, offset, total)


@bp.get("/reclassification-cases/<case_id>/voluntary-corrections")
@endpoint(ALL_ROLES)
def list_corrections(case_id):
    case = lookup.case(case_id)
    limit, offset = pagination()
    rows = db.ordered(
        [
            v
            for v in db.voluntary_corrections.values()
            if v["reclassification_case_id"] == case["id"]
        ]
    )
    items, total = serialize.paginate(
        rows, limit, offset, serialize.voluntary_correction
    )
    return success_list(items, limit, offset, total)
