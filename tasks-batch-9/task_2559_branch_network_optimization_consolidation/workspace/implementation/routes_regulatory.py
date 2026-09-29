"""Community impact assessments and regulatory closure notices (PRD 3.5)."""
from flask import Blueprint

import calc
import services as svc
from core import (DB, all_of, fail, new_record, public, touch, object_response,
                  list_response, clock_today_iso, day_diff, date_plus)
from validation import (authorize, json_body, pagination, filter_value, window,
                        req_int, req_str, req_enum, req_date, req_bool, req_miles)

bp = Blueprint("regulatory", __name__)

READ_GOVERNANCE = ("NetworkStrategist", "ConsolidationApprover", "ComplianceOfficer",
                   "NetworkOpsAdmin")
ASSESSMENT_STATUSES = ("DRAFT", "FINALIZED", "REOPENED", "SUPERSEDED")
IMPACT_TIERS = ("LOW", "MODERATE", "HIGH")
NOTICE_TYPES = ("REGULATOR", "CUSTOMER", "LOBBY_POSTING")
NOTICE_STATUSES = ("FILED", "EFFECTIVE", "WITHDRAWN")
WITHDRAWN_REASONS = ("REGULATOR_OBJECTION", "PLAN_REVISION", "COMMUNITY_PROTEST")


# --------------------------------------------------------------------------- #
# Community impact assessments
# --------------------------------------------------------------------------- #
@bp.post("/distribution/consolidation-cases/<case_id>/impact-assessments")
def create_assessment(case_id):
    authorize(("ComplianceOfficer",))
    body = json_body()
    lmi_tract = req_bool(body, "lmi_tract")
    distance = req_miles(body, "distance_to_nearest_remaining_miles")
    access_count = req_int(body, "alternative_access_count", minimum=0, maximum=20)
    senior_bps = req_int(body, "senior_household_pct_bps", minimum=0, maximum=10000)
    transit = req_bool(body, "public_transit_access")

    case = svc.path_lookup("consolidation_cases", case_id, "Consolidation case")

    closing = DB["branches"].get(case["closing_branch_id"])
    market = svc.market_of_branch(closing)
    tier_at_assessment = market["saturation_tier"] if market else None

    dragged = svc.supersede_live_assessment(case)

    score = calc.impact_score(lmi_tract, distance, access_count, senior_bps, transit,
                              tier_at_assessment)
    tier = calc.impact_tier(score)
    rec = new_record("impact_assessments", {
        "consolidation_case_id": case_id,
        "lmi_tract": lmi_tract,
        "distance_to_nearest_remaining_miles": distance,
        "alternative_access_count": access_count,
        "senior_household_pct_bps": senior_bps,
        "public_transit_access": transit,
        "market_saturation_tier_at_assessment": tier_at_assessment,
        "impact_score": score,
        "impact_tier": tier,
        "requires_public_comment": bool(tier == "HIGH" or lmi_tract),
        "notice_required_days": calc.notice_required_days(tier, lmi_tract, distance),
        "status": "DRAFT",
        "finalized_on": None,
    })
    if dragged:
        touch(case)
    return object_response(public(rec), 201)


@bp.get("/distribution/consolidation-cases/<case_id>/impact-assessments")
def list_case_assessments(case_id):
    authorize(READ_GOVERNANCE)
    limit, offset = pagination()
    status = filter_value("status", ASSESSMENT_STATUSES)
    svc.path_lookup("consolidation_cases", case_id, "Consolidation case")
    rows = svc.children_of("impact_assessments", "consolidation_case_id", case_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = svc.newest_first(rows)
    page, total = window(rows, limit, offset)
    return list_response([public(r) for r in page], limit, offset, total)


@bp.get("/distribution/impact-assessments/<assessment_id>")
def read_assessment(assessment_id):
    authorize(READ_GOVERNANCE)
    rec = svc.path_lookup("impact_assessments", assessment_id, "Impact assessment")
    return object_response(public(rec))


@bp.get("/distribution/impact-assessments")
def list_assessments():
    authorize(READ_GOVERNANCE)
    limit, offset = pagination()
    case_id = filter_value("consolidation_case_id")
    tier = filter_value("impact_tier", IMPACT_TIERS)
    status = filter_value("status", ASSESSMENT_STATUSES)
    rows = all_of("impact_assessments")
    if case_id is not None:
        rows = [r for r in rows if r["consolidation_case_id"] == case_id]
    if tier is not None:
        rows = [r for r in rows if r["impact_tier"] == tier]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = svc.oldest_first(rows)
    page, total = window(rows, limit, offset)
    return list_response([public(r) for r in page], limit, offset, total)


@bp.post("/distribution/impact-assessments/<assessment_id>/finalize")
def finalize_assessment(assessment_id):
    authorize(("ComplianceOfficer",))
    assessment = svc.path_lookup("impact_assessments", assessment_id, "Impact assessment")
    if assessment["status"] not in ("DRAFT", "REOPENED"):
        fail("ERR_ASSESSMENT_STATE_INVALID",
             "An assessment in %s status cannot be finalised." % assessment["status"])
    case = DB["consolidation_cases"].get(assessment["consolidation_case_id"])
    if assessment["status"] == "DRAFT":
        allowed = ("DRAFT", "SUBMITTED", "APPROVED")
    else:
        allowed = ("APPROVED",)
    if case is None or case["status"] not in allowed:
        fail("ERR_CASE_STATE_INVALID",
             "The case must stand in %s to finalise this assessment." % ", ".join(allowed))
    assessment["finalized_on"] = clock_today_iso()
    assessment["status"] = "FINALIZED"
    touch(assessment)
    case["impact_tier"] = assessment["impact_tier"]
    case["notice_required_days"] = assessment["notice_required_days"]
    touch(case)
    return object_response(public(assessment))


# --------------------------------------------------------------------------- #
# Closure notices
# --------------------------------------------------------------------------- #
@bp.post("/distribution/closure-notices")
def file_closure_notice():
    authorize(("ComplianceOfficer",))
    body = json_body()
    case_id = req_str(body, "consolidation_case_id")
    notice_type = req_enum(body, "notice_type", NOTICE_TYPES)
    effective_closure_date = req_date(body, "effective_closure_date")

    case = svc.ref_lookup("consolidation_cases", case_id, "consolidation case")
    if case["status"] != "APPROVED":
        fail("ERR_CASE_STATE_INVALID",
             "A closure notice may only be filed against an APPROVED case; the case is %s."
             % case["status"])

    assessment = svc.live_assessment(case_id)
    if assessment is None or assessment["status"] != "FINALIZED":
        fail("ERR_IMPACT_ASSESSMENT_NOT_FINALIZED",
             "The case has no FINALIZED community impact assessment.")

    today = clock_today_iso()
    if day_diff(effective_closure_date, today) < case["notice_required_days"]:
        fail("ERR_NOTICE_PERIOD_INSUFFICIENT",
             "The filing must observe at least %d days of lead time."
             % case["notice_required_days"])

    buffer_end_date = date_plus(effective_closure_date, calc.NOTICE_BUFFER_DAYS)
    if notice_type == "REGULATOR" and svc.notice_window_conflict(case, today, buffer_end_date):
        fail("ERR_NOTICE_WINDOW_CONFLICT",
             "Another regulatory notice already occupies this trade area's notice window.")

    if day_diff(case["planned_closure_date"], effective_closure_date) < 0:
        fail("ERR_PLANNED_DATE_BEFORE_EFFECTIVE",
             "The case's planned closure date falls earlier than the effective closure date.")

    rec = new_record("closure_notices", {
        "consolidation_case_id": case_id,
        "notice_type": notice_type,
        "filed_on": today,
        "effective_closure_date": effective_closure_date,
        "required_lead_days": case["notice_required_days"],
        "lead_days": day_diff(effective_closure_date, today),
        "buffer_end_date": buffer_end_date,
        "status": "FILED",
        "withdrawn_reason_code": None,
    })

    if notice_type == "REGULATOR":
        case["status"] = "NOTICE_FILED"
        touch(case)
        closing = DB["branches"].get(case["closing_branch_id"])
        if closing is not None and closing["status"] == "UNDER_REVIEW":
            closing["status"] = "CLOSURE_SCHEDULED"
            touch(closing)
    return object_response(public(rec), 201)


@bp.get("/distribution/consolidation-cases/<case_id>/closure-notices")
def list_case_notices(case_id):
    authorize(READ_GOVERNANCE)
    limit, offset = pagination()
    notice_type = filter_value("notice_type", NOTICE_TYPES)
    status = filter_value("status", NOTICE_STATUSES)
    svc.path_lookup("consolidation_cases", case_id, "Consolidation case")
    rows = svc.children_of("closure_notices", "consolidation_case_id", case_id)
    if notice_type is not None:
        rows = [r for r in rows if r["notice_type"] == notice_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = svc.newest_first(rows)
    page, total = window(rows, limit, offset)
    return list_response([public(r) for r in page], limit, offset, total)


@bp.get("/distribution/closure-notices/<notice_id>")
def read_closure_notice(notice_id):
    authorize(READ_GOVERNANCE)
    rec = svc.path_lookup("closure_notices", notice_id, "Closure notice")
    return object_response(public(rec))


@bp.get("/distribution/closure-notices")
def list_closure_notices():
    authorize(READ_GOVERNANCE)
    limit, offset = pagination()
    case_id = filter_value("consolidation_case_id")
    notice_type = filter_value("notice_type", NOTICE_TYPES)
    status = filter_value("status", NOTICE_STATUSES)
    rows = all_of("closure_notices")
    if case_id is not None:
        rows = [r for r in rows if r["consolidation_case_id"] == case_id]
    if notice_type is not None:
        rows = [r for r in rows if r["notice_type"] == notice_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = svc.oldest_first(rows)
    page, total = window(rows, limit, offset)
    return list_response([public(r) for r in page], limit, offset, total)


@bp.post("/distribution/closure-notices/<notice_id>/withdraw")
def withdraw_closure_notice(notice_id):
    authorize(("ComplianceOfficer",))
    body = json_body()
    reason = req_enum(body, "withdrawn_reason_code", WITHDRAWN_REASONS)
    notice = svc.path_lookup("closure_notices", notice_id, "Closure notice")
    if notice["status"] not in ("FILED", "EFFECTIVE"):
        fail("ERR_NOTICE_NOT_OPEN",
             "A notice in %s status cannot be withdrawn." % notice["status"])

    notice["status"] = "WITHDRAWN"
    notice["withdrawn_reason_code"] = reason
    touch(notice)

    case = DB["consolidation_cases"].get(notice["consolidation_case_id"])
    if (notice["notice_type"] == "REGULATOR" and case is not None
            and case["status"] == "NOTICE_FILED"):
        case["status"] = "APPROVED"
        touch(case)
        closing = DB["branches"].get(case["closing_branch_id"])
        if closing is not None and closing["status"] == "CLOSURE_SCHEDULED":
            closing["status"] = "UNDER_REVIEW"
            touch(closing)
        assessment = svc.live_assessment(case["id"])
        if assessment is not None and assessment["status"] == "FINALIZED":
            assessment["status"] = "REOPENED"
            touch(assessment)
        for c in svc.children_of("transition_campaigns", "consolidation_case_id", case["id"]):
            if c["status"] in ("PLANNED", "LAUNCHED"):
                c["status"] = "CANCELLED"
                touch(c)
    return object_response(public(notice))
