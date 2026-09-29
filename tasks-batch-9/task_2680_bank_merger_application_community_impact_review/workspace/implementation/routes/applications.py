"""Merger applications: structuring, filing, acceptance, amendment, recommendation."""
from flask import Blueprint

import aggregates
import calc
from db import db, new_record, now_str, serialize, set_fields, touch
from errors import ApiError
from helpers import (
    compute_closes_at,
    ensure_application_filer,
    fetch,
    fetch_fk,
    list_and_respond,
    now,
    period_closes_dt,
    require_usd,
    set_earliest_decision_at,
    window_contains,
)
from middleware import (
    ALL_ROLES,
    READ_ROLES_NO_COMMENTER,
    ROLE_ANALYST,
    ROLE_FILER,
    actor_id,
    get_body,
    opt_enum,
    opt_int,
    present,
    req_enum,
    req_str,
    require_roles,
)
from response import object_response

applications_bp = Blueprint("applications", __name__)

STRUCTURES = ("STATUTORY_MERGER", "PURCHASE_AND_ASSUMPTION", "HOLDCO_ACQUISITION")
CONSIDERATION_TYPES = ("ALL_CASH", "ALL_STOCK", "MIXED")
RECOMMENDATIONS = ("APPROVE", "APPROVE_WITH_CONDITIONS", "DENY")
SCORE_FIELDS = (
    "officer_experience_score",
    "risk_management_score",
    "compliance_history_score",
    "integration_readiness_score",
)
ACCEPTABLE_CRA_RATINGS = ("OUTSTANDING", "SATISFACTORY")


def _apply_scores(application):
    composite = calc.management_composite(
        application["officer_experience_score"],
        application["risk_management_score"],
        application["compliance_history_score"],
        application["integration_readiness_score"],
    )
    application["management_composite_score"] = float(composite)
    application["management_rating"] = calc.management_rating(composite)


@applications_bp.post("/merger-applications")
@require_roles(ROLE_FILER)
def create_application():
    body = get_body(required=True)
    acquirer_id = req_str(body, "acquirer_id")
    target_id = req_str(body, "target_id")
    structure = req_enum(body, "structure", STRUCTURES)
    consideration_type = req_enum(body, "consideration_type", CONSIDERATION_TYPES)
    total_consideration_usd = require_usd(body, "total_consideration_usd", minimum=1)
    scores = {
        field: opt_int(body, field, minimum=0, maximum=100, default=0) for field in SCORE_FIELDS
    }

    acquirer = fetch_fk("institutions", acquirer_id)
    target = fetch_fk("institutions", target_id)
    if acquirer["id"] == target["id"]:
        raise ApiError("ERR_SELF_MERGER", "the acquirer and the target must differ")

    fields = {
        "acquirer_id": acquirer["id"],
        "target_id": target["id"],
        "structure": structure,
        "consideration_type": consideration_type,
        "total_consideration_usd": total_consideration_usd,
    }
    fields.update(scores)
    fields.update(
        {
            "management_composite_score": 0.00,
            "management_rating": "UNSATISFACTORY",
            "filing_status": "DRAFT",
            "public_review_status": "NOT_OPEN",
            "competitive_posture": "NOT_ANALYZED",
            "substantive_protest_count": 0,
            "unresolved_protest_count": 0,
            "earliest_decision_at": None,
            "recommended_by_user_id": None,
            "recommendation": None,
            "amendment_round": 0,
            "post_closing_monitoring_status": "NOT_APPLICABLE",
        }
    )
    record = new_record(fields)
    _apply_scores(record)
    db.applications[record["id"]] = record
    return object_response(serialize(record), 201)


@applications_bp.get("/merger-applications/<record_id>")
@require_roles(*ALL_ROLES)
def get_application(record_id):
    return object_response(serialize(fetch("applications", record_id)))


@applications_bp.get("/merger-applications")
@require_roles(*ALL_ROLES)
def list_applications():
    return list_and_respond("applications", ("acquirer_id", "target_id", "filing_status"))


@applications_bp.patch("/merger-applications/<record_id>")
@require_roles(ROLE_FILER, ROLE_ANALYST)
def amend_application(record_id):
    application = fetch("applications", record_id)
    body = get_body(required=False)
    structure = opt_enum(body, "structure", STRUCTURES, default=None)
    consideration_type = opt_enum(body, "consideration_type", CONSIDERATION_TYPES, default=None)
    total_consideration_usd = (
        require_usd(body, "total_consideration_usd", minimum=1)
        if present(body, "total_consideration_usd")
        else None
    )
    scores = {}
    for field in SCORE_FIELDS:
        if present(body, field):
            scores[field] = opt_int(body, field, minimum=0, maximum=100)

    ensure_application_filer(application)

    if application["filing_status"] in ("DECIDED", "CONSUMMATED", "DENIED"):
        raise ApiError(
            "ERR_INVALID_APPLICATION_STATE",
            "a decided application can no longer be amended",
        )

    if structure is not None:
        application["structure"] = structure
    if consideration_type is not None:
        application["consideration_type"] = consideration_type
    if total_consideration_usd is not None:
        application["total_consideration_usd"] = total_consideration_usd
    if scores:
        application.update(scores)
        _apply_scores(application)
    touch(application)
    return object_response(serialize(application))


def _submission_gate(application):
    acquirer = db.institutions.get(application["acquirer_id"])
    target = db.institutions.get(application["target_id"])
    if (
        acquirer is None
        or target is None
        or acquirer["status"] != "ACTIVE"
        or target["status"] != "ACTIVE"
    ):
        raise ApiError("ERR_INSTITUTION_NOT_ACTIVE", "both parties must be ACTIVE")
    if acquirer["latest_cra_rating"] not in ACCEPTABLE_CRA_RATINGS:
        raise ApiError(
            "ERR_CRA_RATING_INSUFFICIENT",
            "the acquirer's CRA record is %s" % acquirer["latest_cra_rating"],
        )
    if application["management_rating"] == "UNSATISFACTORY":
        raise ApiError(
            "ERR_MANAGEMENT_ASSESSMENT_UNSATISFACTORY", "the management rating is UNSATISFACTORY"
        )
    schedule = aggregates.current_schedule(application["id"], "REGULATORY_ADJUSTED")
    if schedule is None:
        raise ApiError(
            "ERR_PRO_FORMA_SCHEDULE_MISSING",
            "no CURRENT REGULATORY_ADJUSTED pro forma schedule exists",
        )
    if schedule["capital_adequacy_flag"] != "WELL_CAPITALIZED":
        raise ApiError(
            "ERR_PRO_FORMA_CAPITAL_INSUFFICIENT",
            "the current regulatory schedule is %s" % schedule["capital_adequacy_flag"],
        )


@applications_bp.post("/merger-applications/<record_id>/submit")
@require_roles(ROLE_FILER)
def submit_application(record_id):
    application = fetch("applications", record_id)
    get_body(required=False)
    ensure_application_filer(application)
    if application["filing_status"] not in ("DRAFT", "RETURNED_FOR_AMENDMENT"):
        raise ApiError(
            "ERR_INVALID_APPLICATION_STATE",
            "an application in %s cannot be filed" % application["filing_status"],
        )
    _submission_gate(application)

    re_filing = application["filing_status"] == "RETURNED_FOR_AMENDMENT"
    application["filing_status"] = "SUBMITTED"
    if re_filing:
        application["amendment_round"] = int(application["amendment_round"]) + 1
    touch(application)
    return object_response(serialize(application))


@applications_bp.post("/merger-applications/<record_id>/accept")
@require_roles(ROLE_ANALYST)
def accept_application(record_id):
    application = fetch("applications", record_id)
    get_body(required=False)
    if application["filing_status"] != "SUBMITTED":
        raise ApiError(
            "ERR_INVALID_APPLICATION_STATE",
            "only a SUBMITTED application can be accepted for review",
        )
    instant = now()
    for period in aggregates.application_periods(application["id"]):
        if window_contains(period, instant):
            raise ApiError(
                "ERR_COMMENT_PERIOD_OVERLAP",
                "a public comment window of this application is already live",
            )

    period = new_record(
        {
            "application_id": application["id"],
            "opens_at": now_str(),
            "duration_days": calc.DEFAULT_COMMENT_DURATION_DAYS,
            "closes_at": None,
            "extension_count": 0,
            "extended_days_total": 0,
            "status": "OPEN",
            "comment_count": 0,
            "substantive_protest_count": 0,
        }
    )
    period["closes_at"] = compute_closes_at(period)
    db.periods[period["id"]] = period

    application["filing_status"] = "UNDER_REVIEW"
    if application["public_review_status"] == "NOT_OPEN":
        application["public_review_status"] = "OPEN_FOR_COMMENT"
    application["earliest_decision_at"] = None
    touch(application)
    set_earliest_decision_at(application, period_closes_dt(period))
    return object_response(serialize(application))


@applications_bp.post("/merger-applications/<record_id>/return-for-amendment")
@require_roles(ROLE_ANALYST)
def return_application(record_id):
    application = fetch("applications", record_id)
    body = get_body(required=True)
    reason = req_str(body, "reason", min_len=1)
    if application["filing_status"] not in ("SUBMITTED", "UNDER_REVIEW"):
        raise ApiError(
            "ERR_INVALID_APPLICATION_STATE",
            "only a SUBMITTED or UNDER_REVIEW application can be returned",
        )
    from_under_review = application["filing_status"] == "UNDER_REVIEW"
    if from_under_review and aggregates.has_pending_hearing(application["id"]):
        raise ApiError(
            "ERR_HEARING_REQUEST_PENDING", "a hearing request on this application is PENDING"
        )

    application["filing_status"] = "RETURNED_FOR_AMENDMENT"
    touch(application)
    if from_under_review:
        for period in aggregates.application_periods(application["id"]):
            if period["status"] in ("OPEN", "EXTENDED"):
                set_fields(period, status="CLOSED")
        set_fields(application, public_review_status="COMMENT_CLOSED")
    del reason
    return object_response(serialize(application))


@applications_bp.post("/merger-applications/<record_id>/recommend")
@require_roles(ROLE_ANALYST)
def recommend_application(record_id):
    application = fetch("applications", record_id)
    body = get_body(required=True)
    recommendation = req_enum(body, "recommendation", RECOMMENDATIONS)

    if application["filing_status"] != "UNDER_REVIEW":
        raise ApiError(
            "ERR_INVALID_APPLICATION_STATE",
            "only an UNDER_REVIEW application can be recommended",
        )
    if application["public_review_status"] != "COMMENT_CLOSED":
        raise ApiError(
            "ERR_INVALID_APPLICATION_STATE",
            "the public review record is not COMMENT_CLOSED",
        )
    from db import parse_dt

    earliest = parse_dt(application.get("earliest_decision_at"))
    if earliest is None or now() < earliest:
        raise ApiError(
            "ERR_INVALID_APPLICATION_STATE",
            "the post-comment review period has not elapsed",
        )
    if aggregates.has_pending_hearing(application["id"]):
        raise ApiError(
            "ERR_HEARING_REQUEST_PENDING", "a hearing request on this application is PENDING"
        )
    if application["management_rating"] == "UNSATISFACTORY":
        raise ApiError(
            "ERR_MANAGEMENT_ASSESSMENT_UNSATISFACTORY", "the management rating is UNSATISFACTORY"
        )
    if application["competitive_posture"] == "BLOCKED":
        raise ApiError("ERR_COMPETITIVE_POSTURE_BLOCKED", "the competitive posture is BLOCKED")
    analyzed = {a["market_id"] for a in aggregates.analyses_for_application(application["id"])}
    for market_id in aggregates.overlap_market_ids(application):
        if market_id not in analyzed:
            raise ApiError(
                "ERR_MARKET_ANALYSIS_MISSING",
                "an overlapping deposit market has not been analyzed",
            )

    application["filing_status"] = "RECOMMENDED"
    application["recommendation"] = recommendation
    application["recommended_by_user_id"] = actor_id()
    touch(application)
    if int(application["unresolved_protest_count"]) == 0:
        set_fields(application, public_review_status="CLEARED")
    return object_response(serialize(application))


@applications_bp.get("/merger-applications/<record_id>/clearance-summary")
@require_roles(*READ_ROLES_NO_COMMENTER)
def clearance_summary(record_id):
    application = fetch("applications", record_id)
    analyses = aggregates.analyses_for_application(application["id"])

    worst = None
    for analysis in analyses:
        result = analysis["screen_result"]
        if worst is None or calc.SCREEN_SEVERITY[result] < calc.SCREEN_SEVERITY[worst]:
            worst = result

    schedule = aggregates.current_schedule(application["id"], "REGULATORY_ADJUSTED")
    max_delta = aggregates.max_hhi_delta(application["id"])
    hearing_granted = aggregates.granted_hearing_count(application["id"]) > 0
    expedited = calc.expedited_eligible(
        application["unresolved_protest_count"],
        hearing_granted,
        max_delta,
        application["management_rating"],
    )
    projected = calc.waiting_period_days(
        application["structure"],
        hearing_granted,
        application["unresolved_protest_count"],
        expedited,
    )
    summary = {
        "application_id": application["id"],
        "competitive_posture": application["competitive_posture"],
        "worst_screen_result": worst,
        "max_hhi_delta_unmitigated": max_delta,
        "total_required_divestiture_usd": sum(
            int(a["required_divestiture_deposits_usd"]) for a in analyses
        ),
        "total_designated_divestiture_usd": sum(
            int(a["designated_divestiture_deposits_usd"]) for a in analyses
        ),
        "all_markets_mitigated": all(bool(a["mitigation_satisfied"]) for a in analyses),
        "current_regulatory_cet1_pct": (
            schedule["pro_forma_cet1_ratio_pct"] if schedule else None
        ),
        "current_regulatory_capital_flag": (
            schedule["capital_adequacy_flag"] if schedule else None
        ),
        "substantive_protest_count": int(application["substantive_protest_count"]),
        "unresolved_protest_count": int(application["unresolved_protest_count"]),
        "granted_hearing_count": aggregates.granted_hearing_count(application["id"]),
        "earliest_decision_at": application["earliest_decision_at"],
        "expedited_eligible": expedited,
        "projected_waiting_period_days": projected,
    }
    return object_response(summary)
