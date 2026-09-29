"""Complaints, appeals and the compensating reinstatement of PRD 3.9."""
from flask import Blueprint

import db
import response
import validation as v
from errors import ApiError
from routes.common import (CASE_STATUSES, CASE_TYPES, DECISIONS,
                           PROGRAM_ADMINISTRATOR, PROVIDER_AGENT, ROLES_ALL,
                           SUBSCRIBER, authenticate, get_case, get_enrollment,
                           get_subscriber, require_subscriber_owner)
from services import cascades, derive

bp = Blueprint("cases", __name__)

MAX_REVIEW_ROUNDS = 3


@bp.post("/lifeline/subscriber-cases")
def open_case():
    caller = authenticate((SUBSCRIBER, PROVIDER_AGENT, PROGRAM_ADMINISTRATOR))

    body = v.get_body()
    subscriber_id = v.string_field(body, "subscriber_id")
    enrollment_id = v.string_field(body, "enrollment_id")
    case_type = v.enum_field(body, "case_type", CASE_TYPES)
    narrative = v.string_field(body, "narrative", min_len=1, max_len=2000)

    get_subscriber(subscriber_id)
    enrollment = get_enrollment(enrollment_id)

    require_subscriber_owner(caller, subscriber_id)

    now = db.now()
    if case_type == "DE_ENROLLMENT_APPEAL":
        deadline = enrollment["appeal_deadline_at"]
        if deadline is not None and now > deadline:
            raise ApiError("ERR_APPEAL_WINDOW_EXPIRED",
                           "The 30-day de-enrollment appeal window has closed")
        if enrollment["benefit_status"] != "DE_ENROLLED":
            raise ApiError("ERR_APPEAL_NOT_APPLICABLE",
                           "Only a de-enrolled benefit can be appealed")
    else:
        if enrollment["benefit_status"] != "ACTIVE":
            raise ApiError("ERR_APPEAL_NOT_APPLICABLE",
                           "Only a live benefit can be complained about")

    row = db.base_row()
    row.update({
        "subscriber_id": subscriber_id,
        "enrollment_id": enrollment_id,
        "case_type": case_type,
        "narrative": narrative,
        "status": "SUBMITTED",
        "reviewer_ref": None,
        "review_round": 0,
        "decision": None,
        "decision_rationale": None,
        "decided_at": None,
        "decided_by_ref": None,
        "reinstated_enrollment_flag": False,
        "_remand_count": 0,
    })
    db.db.cases[row["id"]] = row
    return response.ok(derive.case_json(row), 201)


@bp.get("/lifeline/subscriber-cases/<case_id>")
def read_case(case_id):
    authenticate(ROLES_ALL)
    return response.ok(derive.case_json(get_case(case_id)))


@bp.get("/lifeline/subscriber-cases")
def list_cases():
    authenticate(ROLES_ALL)
    subscriber_id = response.filter_str("subscriber_id")
    enrollment_id = response.filter_str("enrollment_id")
    case_type = response.filter_enum("case_type", CASE_TYPES)
    status = response.filter_enum("status", CASE_STATUSES)
    rows = list(db.db.cases.values())
    if subscriber_id is not None:
        rows = [r for r in rows if r["subscriber_id"] == subscriber_id]
    if enrollment_id is not None:
        rows = [r for r in rows if r["enrollment_id"] == enrollment_id]
    if case_type is not None:
        rows = [r for r in rows if r["case_type"] == case_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return response.paginate(db.by_created(rows), derive.case_json)


@bp.post("/lifeline/subscriber-cases/<case_id>/assign-review")
def assign_review(case_id):
    authenticate((PROGRAM_ADMINISTRATOR,))
    case = get_case(case_id)

    body = v.get_body()
    reviewer_ref = v.string_field(body, "reviewer_ref", min_len=1, max_len=64)

    if case["status"] not in ("SUBMITTED", "REMANDED"):
        raise ApiError("ERR_CASE_NOT_ASSIGNABLE",
                       "The case is not awaiting assignment")
    if (case["review_round"] or 0) >= MAX_REVIEW_ROUNDS:
        raise ApiError("ERR_REVIEW_ROUND_LIMIT",
                       "The case has exhausted its review rounds")

    case["reviewer_ref"] = reviewer_ref
    case["review_round"] = (case["review_round"] or 0) + 1
    case["status"] = "UNDER_REVIEW"
    db.touch(case)
    return response.ok(derive.case_json(case))


@bp.post("/lifeline/subscriber-cases/<case_id>/decide")
def decide_case(case_id):
    caller = authenticate((PROGRAM_ADMINISTRATOR,))
    case = get_case(case_id)

    body = v.get_body()
    decision = v.enum_field(body, "decision", DECISIONS)
    rationale = v.string_field(body, "decision_rationale", min_len=1, max_len=2000)

    enrollment = db.db.enrollments.get(case["enrollment_id"])

    # Segregation of duties, ahead of every state and business check.
    if (case["case_type"] == "DE_ENROLLMENT_APPEAL" and enrollment is not None
            and enrollment["de_enrolled_by_ref"] is not None
            and caller.user_id == enrollment["de_enrolled_by_ref"]):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The operator that stopped the benefit may not decide the appeal")
    if ((case.get("_remand_count") or 0) >= 1
            and case["reviewer_ref"] is not None
            and caller.user_id == case["reviewer_ref"]):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "A reviewer that remanded the case may not decide its next round")

    if case["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_CASE_NOT_UNDER_REVIEW", "The case is not under review")

    if decision == "GRANT_REINSTATE" and case["case_type"] != "DE_ENROLLMENT_APPEAL":
        raise ApiError("ERR_APPEAL_NOT_APPLICABLE",
                       "GRANT_REINSTATE is only legal on a de-enrollment appeal")
    if decision == "RESOLVE_WITH_CREDIT" and case["case_type"] != "SERVICE_COMPLAINT":
        raise ApiError("ERR_APPEAL_NOT_APPLICABLE",
                       "RESOLVE_WITH_CREDIT is only legal on a service complaint")
    if decision == "GRANT_REINSTATE" and (
            enrollment is None or enrollment["benefit_status"] != "DE_ENROLLED"):
        raise ApiError("ERR_APPEAL_NOT_APPLICABLE",
                       "The appealed benefit is not de-enrolled")

    case["decision"] = decision
    case["decision_rationale"] = rationale
    case["decided_at"] = db.now()
    case["decided_by_ref"] = caller.user_id

    if decision == "REMAND":
        case["status"] = "REMANDED"
        case["_remand_count"] = (case.get("_remand_count") or 0) + 1
        db.touch(case)
    elif decision == "DENY":
        case["status"] = "DENIED"
        db.touch(case)
    elif decision == "RESOLVE_WITH_CREDIT":
        case["status"] = "RESOLVED"
        db.touch(case)
    else:
        # A granted appeal restores the benefit and unwinds any audit money.
        case["status"] = "GRANTED"
        case["reinstated_enrollment_flag"] = True
        db.touch(case)
        cascades.reinstate(enrollment, caller.user_id)

    return response.ok(derive.case_json(case))
