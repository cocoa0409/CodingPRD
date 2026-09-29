"""Compliance sweeps, breach remedies and the logical-clock capability."""

from flask import Blueprint

import calc
import lookups
import serializers
import services
import validators as v
from auth import ALL_ROLES, authorize, current_user_id
from envelope import respond_object
from errors import ApiError
from store import db, iso, now, parse_dt, sort_key, touch

bp = Blueprint("compliance", __name__)

REMEDY_BASES = ("BREACH_DAY_BASIS", "MISSED_SERVICE_BASIS")
SWEEPABLE_POSTURES = ("ON_TRACK", "AT_RISK", "BREACHED")
CLOSED_ASSESSMENT_STATUSES = ("REPORT_FINAL", "CANCELLED")


@bp.post("/psych-services/timeline-breaches/<breach_id>/propose-remedy")
@authorize("ComplianceOfficer")
def propose_remedy(breach_id):
    body = v.body()
    remedy_basis = v.req_enum(body, "remedy_basis", REMEDY_BASES)
    additional_minutes = v.opt_int(body, "additional_minutes", 0, minimum=0)
    corrective_action_note = v.req_str(body, "corrective_action_note")

    breach = lookups.breach(breach_id)
    if breach["status"] != "DETECTED":
        raise ApiError("ERR_BREACH_STATE_INVALID",
                       "A remedy may only be proposed on a DETECTED breach.")

    basis_minutes = (
        breach["minutes_breach_day_basis"] if remedy_basis == "BREACH_DAY_BASIS"
        else breach["minutes_missed_service_basis"]
    )
    awarded = basis_minutes + additional_minutes
    if awarded > calc.REMEDY_MINUTES_CAP:
        raise ApiError("ERR_REMEDY_MINUTES_EXCEED_CAP",
                       "The compensatory award may not exceed %d minutes."
                       % calc.REMEDY_MINUTES_CAP)

    breach["status"] = "REMEDY_PROPOSED"
    breach["remedy_basis"] = remedy_basis
    breach["additional_minutes"] = additional_minutes
    breach["corrective_action_note"] = corrective_action_note
    breach["proposed_by_user_id"] = current_user_id()
    breach["remedy_minutes_awarded"] = awarded
    touch(breach)
    return respond_object(serializers.timeline_breach(breach))


@bp.post("/psych-services/timeline-breaches/<breach_id>/approve-remedy")
@authorize("DistrictAdmin")
def approve_remedy(breach_id):
    breach = lookups.breach(breach_id)
    if breach["status"] != "REMEDY_PROPOSED":
        raise ApiError("ERR_BREACH_STATE_INVALID",
                       "Only a REMEDY_PROPOSED breach may be approved.")

    breach["status"] = "REMEDY_APPROVED"
    breach["approved_by_user_id"] = current_user_id()
    touch(breach)

    evaluation = db.evaluations.get(breach["evaluation_id"])
    if evaluation is not None and evaluation["compliance_status"] == "BREACHED":
        services.freeze_clock(evaluation)
        evaluation["compliance_status"] = "BREACH_CLOSED_REMEDIED"
        touch(evaluation)
        services.recompute_psychologist(evaluation["psychologist_id"])

    return respond_object(serializers.timeline_breach(breach))


@bp.post("/psych-services/compliance-runs")
@authorize("ComplianceOfficer", "DistrictAdmin")
def run_compliance_sweep():
    run_at = now()
    evaluated_count = 0
    at_risk_ids = []
    breached_ids = []
    breach_ids = []

    for evaluation in sorted(db.evaluations.values(), key=sort_key):
        if evaluation["compliance_status"] not in SWEEPABLE_POSTURES:
            continue
        evaluated_count += 1
        clock = services.resolve_clock(evaluation)
        days_remaining = clock["days_remaining"]
        previous = evaluation["compliance_status"]
        posture = calc.compliance_posture(days_remaining)

        work_is_over = evaluation["assessment_status"] in CLOSED_ASSESSMENT_STATUSES
        if posture != previous:
            if work_is_over and posture in ("AT_RISK", "BREACHED"):
                posture = previous
            else:
                evaluation["compliance_status"] = posture
                touch(evaluation)
                if posture == "AT_RISK":
                    at_risk_ids.append(evaluation["id"])
                elif posture == "BREACHED":
                    breached_ids.append(evaluation["id"])

        if evaluation["compliance_status"] == "BREACHED" and \
                not services.has_live_breach(evaluation["id"]):
            breach = services.create_breach(evaluation, days_remaining)
            breach_ids.append(breach["id"])

    sessions_completed_count = 0
    for session in sorted(db.sessions.values(), key=sort_key):
        if session["status"] == "SCHEDULED" and session["_end_at"] <= run_at:
            session["status"] = "COMPLETED"
            touch(session)
            sessions_completed_count += 1

    for psychologist in sorted(db.psychologists.values(), key=sort_key):
        if psychologist["status"] != "ACTIVE":
            continue
        if services.apply_caseload(psychologist):
            touch(psychologist)

    return respond_object({
        "run_at": iso(run_at),
        "evaluated_count": evaluated_count,
        "at_risk_evaluation_ids": at_risk_ids,
        "breached_evaluation_ids": breached_ids,
        "breach_ids": breach_ids,
        "sessions_completed_count": sessions_completed_count,
    })


@bp.post("/_clock/set_current_utc")
@authorize(*ALL_ROLES)
def set_current_utc():
    body = v.body()
    raw = v.req_str(body, "current_utc")
    parsed = parse_dt(raw)
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST", "current_utc must be an ISO 8601 UTC instant.")
    db.clock = parsed
    # Setting the clock mutates no entity: no updated_at is refreshed anywhere.
    return respond_object({"current_utc": raw})
