"""Evaluator routing, the testing/report workflow and timeline exclusions."""

from flask import Blueprint, request

import calc
import lookups
import serializers
import services
import validators as v
from auth import ALL_ROLES, authorize, current_role, current_user_id
from envelope import paginate, pagination, respond_array, respond_object
from errors import ApiError
from store import base_record, db, iso, now, sort_key, touch

bp = Blueprint("evaluations", __name__)

CONSENT_ON_FILE = ("CONSENTED", "CONSENT_WAIVED")
POSTURE_RANK = {"ON_TRACK": 0, "AT_RISK": 1, "BREACHED": 2}


def _referral_of(evaluation):
    return db.referrals.get(evaluation["referral_id"])


def _require_consent(evaluation):
    """Validation ladder position 9."""
    referral = _referral_of(evaluation)
    if referral is None or referral["status"] not in CONSENT_ON_FILE:
        raise ApiError("ERR_CONSENT_NOT_ON_FILE",
                       "The parent referral does not hold consent to evaluate.")
    return referral


def _require_owner(evaluation):
    """Validation ladder position 6 — only meaningful for SchoolPsychologist."""
    if current_role() == "SchoolPsychologist" and \
            evaluation["psychologist_id"] != current_user_id():
        raise ApiError("ERR_PSYCH_NOT_OWNER",
                       "Only the evaluation's assigned psychologist may take this step.")


def _require_assessment_status(evaluation, *allowed):
    if evaluation["assessment_status"] not in allowed:
        raise ApiError("ERR_EVALUATION_STATE_INVALID",
                       "Assessment status %s does not permit this transition."
                       % evaluation["assessment_status"])


# ---------------------------------------------------------------- assignment

@bp.post("/psych-services/evaluations/<evaluation_id>/assign")
@authorize("PsychServicesSupervisor")
def assign_evaluator(evaluation_id):
    body = v.body()
    expected_version = v.req_int(body, "expected_evaluation_version", minimum=0)
    requested_psychologist_id = v.opt_str(body, "psychologist_id", None, allow_empty=False)

    evaluation = lookups.evaluation(evaluation_id)
    target = None
    if requested_psychologist_id is not None:
        target = lookups.psychologist(requested_psychologist_id)

    # ladder 7 — optimistic concurrency control
    if expected_version != evaluation["version"]:
        raise ApiError("ERR_STALE_EVALUATION_VERSION",
                       "expected_evaluation_version %s does not match the current version %s."
                       % (expected_version, evaluation["version"]))

    # ladder 8 — state
    _require_assessment_status(evaluation, "PENDING_ASSIGNMENT", "ASSIGNED")
    was_assigned = evaluation["assessment_status"] == "ASSIGNED"
    if target is not None:
        if target["status"] != "ACTIVE":
            raise ApiError("ERR_PSYCHOLOGIST_STATE_INVALID",
                           "The named psychologist is ON_LEAVE.")
        if was_assigned and target["id"] == evaluation["psychologist_id"]:
            raise ApiError("ERR_EVALUATION_STATE_INVALID",
                           "The evaluation is already routed to that psychologist.")

    # ladder 9 — consent gate
    referral = _require_consent(evaluation)

    if target is not None:
        # ladder 14 — building coverage
        if referral["school_id"] not in target["assigned_school_ids"]:
            raise ApiError("ERR_PSYCH_BUILDING_MISMATCH",
                           "The referring building is not in the psychologist's assigned_school_ids.")
        # ladder 15 — bilingual coverage
        if referral["bilingual_evaluation_required"] and \
                referral["primary_language"] not in target["languages_certified"]:
            raise ApiError("ERR_LANGUAGE_CERT_MISSING",
                           "The psychologist is not certified in the family's primary language.")
        # ladder 16 — credential scope
        if target["credential_type"] == "INTERN" and \
                evaluation["referral_type"] != "REEVALUATION":
            raise ApiError("ERR_INTERN_SCOPE_VIOLATION",
                           "An INTERN may only take REEVALUATION evaluations.")
        # ladder 27 — caseload ceiling
        if target["open_case_points"] + evaluation["caseload_points"] > \
                target["weekly_capacity_points"]:
            raise ApiError("ERR_PSYCH_CASELOAD_OVER_CAP",
                           "The assignment would push the psychologist past weekly_capacity_points.")
    else:
        # ladder 28 — the selector must find a candidate
        target = services.select_psychologist(evaluation, referral)
        if target is None:
            raise ApiError("ERR_NO_ELIGIBLE_PSYCHOLOGIST",
                           "No eligible psychologist could be selected for this evaluation.")
        if was_assigned and target["id"] == evaluation["psychologist_id"]:
            raise ApiError("ERR_EVALUATION_STATE_INVALID",
                           "The evaluation is already routed to that psychologist.")

    outgoing_id = evaluation["psychologist_id"]
    evaluation["psychologist_id"] = target["id"]
    evaluation["assessment_status"] = "ASSIGNED"
    if was_assigned:
        evaluation["reassignment_count"] += 1
    touch(evaluation)

    if outgoing_id and outgoing_id != target["id"]:
        services.recompute_psychologist(outgoing_id)
    services.recompute_psychologist(target["id"])

    return respond_object(serializers.evaluation(evaluation))


# ---------------------------------------------------------------- testing and reporting

@bp.post("/psych-services/evaluations/<evaluation_id>/testing-start")
@authorize("SchoolPsychologist")
def start_testing(evaluation_id):
    body = v.body()
    instrument_id = v.req_str(body, "instrument_id")

    evaluation = lookups.evaluation(evaluation_id)
    instrument = lookups.instrument(instrument_id)

    _require_owner(evaluation)
    _require_assessment_status(evaluation, "ASSIGNED")
    _require_consent(evaluation)

    # ladder 12 — scoring-software licensing
    seat_held = any(
        s["instrument_id"] == instrument["id"]
        and s["psychologist_id"] == current_user_id()
        and s["status"] == "ASSIGNED"
        for s in db.seats.values()
    )
    if services.license_status(instrument) != "ACTIVE" or not seat_held:
        raise ApiError("ERR_SCORING_LICENSE_INVALID",
                       "An ACTIVE licence and an ASSIGNED scoring seat for this psychologist are required.")

    # ladder 17 — interpreter support
    if evaluation["interpreter_required"]:
        supported = any(
            s["evaluation_id"] == evaluation["id"] and s["status"] in ("SCHEDULED", "COMPLETED")
            for s in db.sessions.values()
        )
        if not supported:
            raise ApiError("ERR_INTERPRETER_SESSION_MISSING",
                           "This evaluation requires a scheduled or completed interpreter session.")

    # ladder 29 — protocol inventory
    units = instrument["protocol_units_per_administration"] * len(evaluation["evaluation_domains"])
    if instrument["protocol_stock_count"] < units:
        raise ApiError("ERR_PROTOCOL_STOCK_INSUFFICIENT",
                       "The instrument holds fewer than %d protocol units." % units)

    evaluation["assessment_status"] = "IN_TESTING"
    evaluation["testing_instrument_id"] = instrument["id"]
    evaluation["protocol_units_consumed"] = units
    touch(evaluation)

    instrument["protocol_stock_count"] -= units
    touch(instrument)

    return respond_object(serializers.evaluation(evaluation))


@bp.post("/psych-services/evaluations/<evaluation_id>/scores")
@authorize("SchoolPsychologist")
def record_scores(evaluation_id):
    body = v.body()
    score_summary = v.req_str(body, "score_summary")
    evaluation = lookups.evaluation(evaluation_id)
    _require_owner(evaluation)
    _require_assessment_status(evaluation, "IN_TESTING")
    _require_consent(evaluation)

    evaluation["assessment_status"] = "SCORED"
    evaluation["score_summary"] = score_summary
    touch(evaluation)
    return respond_object(serializers.evaluation(evaluation))


@bp.post("/psych-services/evaluations/<evaluation_id>/report-draft")
@authorize("SchoolPsychologist")
def submit_report_draft(evaluation_id):
    body = v.body()
    report_narrative = v.req_str(body, "report_narrative")
    evaluation = lookups.evaluation(evaluation_id)
    _require_owner(evaluation)
    _require_assessment_status(evaluation, "SCORED")
    _require_consent(evaluation)

    evaluation["assessment_status"] = "REPORT_DRAFTED"
    evaluation["report_narrative"] = report_narrative
    evaluation["report_drafted_by_psychologist_id"] = current_user_id()
    touch(evaluation)
    return respond_object(serializers.evaluation(evaluation))


@bp.post("/psych-services/evaluations/<evaluation_id>/report-review")
@authorize("SchoolPsychologist", "PsychServicesSupervisor")
def review_report(evaluation_id):
    body = v.body()
    decision = v.req_enum(body, "decision", ("APPROVE", "RETURN"))
    evaluation = lookups.evaluation(evaluation_id)

    reviewer = None
    if current_role() == "SchoolPsychologist":
        reviewer = lookups.psychologist(current_user_id())

    _require_assessment_status(evaluation, "REPORT_DRAFTED")
    if reviewer is not None and reviewer["status"] != "ACTIVE":
        raise ApiError("ERR_PSYCHOLOGIST_STATE_INVALID", "The reviewing psychologist is ON_LEAVE.")

    _require_consent(evaluation)

    # ladder 11 — segregation of duties
    if evaluation["report_drafted_by_psychologist_id"] is not None and \
            current_user_id() == evaluation["report_drafted_by_psychologist_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The drafting psychologist may not review their own report.")

    if decision == "APPROVE":
        evaluation["assessment_status"] = "REPORT_FINAL"
        touch(evaluation)
        services.recompute_psychologist(evaluation["psychologist_id"])
    else:
        evaluation["assessment_status"] = "SCORED"
        evaluation["report_narrative"] = None
        evaluation["report_drafted_by_psychologist_id"] = None
        touch(evaluation)

    return respond_object(serializers.evaluation(evaluation))


# ---------------------------------------------------------------- timeline exclusions

@bp.post("/psych-services/timeline-exclusions")
@authorize("SchoolPsychologist")
def claim_exclusion():
    body = v.body()
    evaluation_id = v.req_str(body, "evaluation_id")
    exclusion_type = v.req_enum(body, "exclusion_type", calc.EXCLUSION_TYPES)
    start_date = v.req_date(body, "start_date")
    end_date = v.req_date(body, "end_date")
    if end_date < start_date:
        raise ApiError("ERR_INVALID_REQUEST", "end_date must be on or after start_date.")
    claim_note = v.opt_str(body, "claim_note", "")

    evaluation = lookups.evaluation(evaluation_id)
    _require_owner(evaluation)
    _require_consent(evaluation)

    record = base_record()
    record.update({
        "evaluation_id": evaluation["id"],
        "exclusion_type": exclusion_type,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "claim_note": claim_note,
        "status": "CLAIMED",
        "days_claimed": (end_date - start_date).days + 1,
        "days_credited": 0,
        "decided_by_user_id": None,
        "decided_at": None,
    })
    db.exclusions[record["id"]] = record
    return respond_object(serializers.timeline_exclusion(record), 201)


@bp.post("/psych-services/timeline-exclusions/<exclusion_id>/decision")
@authorize("PsychServicesSupervisor")
def decide_exclusion(exclusion_id):
    body = v.body()
    decision = v.req_enum(body, "decision", ("APPROVE", "REJECT"))
    exclusion = lookups.exclusion(exclusion_id)

    if exclusion["status"] != "CLAIMED":
        raise ApiError("ERR_EXCLUSION_ALREADY_DECIDED",
                       "This exclusion claim has already been decided.")

    evaluation = db.evaluations.get(exclusion["evaluation_id"])

    if decision == "REJECT":
        exclusion["status"] = "REJECTED"
        exclusion["decided_by_user_id"] = current_user_id()
        exclusion["decided_at"] = iso(now())
        touch(exclusion)
        return respond_object(serializers.timeline_exclusion(exclusion))

    if evaluation is None or evaluation["compliance_status"] in calc.CLOSED_COMPLIANCE_STATUSES:
        raise ApiError("ERR_EVALUATION_STATE_INVALID",
                       "The evaluation's compliance clock is closed; no credit may be applied.")

    credit = services.exclusion_day_credit(exclusion, evaluation)
    if credit < 1:
        raise ApiError("ERR_EXCLUSION_ZERO_DAYS",
                       "The claimed window earns no days inside the base statutory window.")

    # level 1 — the claim itself
    exclusion["status"] = "APPROVED"
    exclusion["days_credited"] = credit
    exclusion["decided_by_user_id"] = current_user_id()
    exclusion["decided_at"] = iso(now())
    touch(exclusion)

    # levels 2 and 3 — the evaluation's clock and posture
    previous_posture = evaluation["compliance_status"]
    new_posture = calc.compliance_posture(services.days_remaining_of(evaluation))
    if POSTURE_RANK.get(new_posture, 0) < POSTURE_RANK.get(previous_posture, 0):
        evaluation["compliance_status"] = new_posture
    touch(evaluation)

    # level 4 — a breach cured by a legitimate exclusion no longer counts
    if previous_posture == "BREACHED" and evaluation["compliance_status"] != "BREACHED":
        services.vacate_open_breaches(evaluation["id"])

    services.recompute_psychologist(evaluation["psychologist_id"])

    return respond_object(serializers.timeline_exclusion(exclusion))


# ---------------------------------------------------------------- reads

@bp.get("/psych-services/evaluations/<evaluation_id>")
@authorize(*ALL_ROLES)
def get_evaluation(evaluation_id):
    record = lookups.evaluation(evaluation_id)
    return respond_object(serializers.evaluation(record))


@bp.get("/psych-services/evaluations")
@authorize(*ALL_ROLES)
def list_evaluations():
    limit, offset = pagination(request.args)
    rows = list(db.evaluations.values())
    for field in ("referral_id", "psychologist_id", "prior_evaluation_id",
                  "testing_instrument_id", "report_drafted_by_psychologist_id",
                  "assessment_status", "compliance_status"):
        wanted = request.args.get(field)
        if wanted:
            rows = [r for r in rows if r[field] == wanted]
    rows.sort(key=sort_key)
    page, total = paginate(rows, limit, offset)
    return respond_array([serializers.evaluation(r) for r in page], limit, offset, total)


def _sub_collection(evaluation_id, collection, serializer):
    evaluation = lookups.evaluation(evaluation_id)
    limit, offset = pagination(request.args)
    status = request.args.get("status")
    rows = [r for r in collection.values() if r["evaluation_id"] == evaluation["id"]]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=sort_key)
    page, total = paginate(rows, limit, offset)
    return respond_array([serializer(r) for r in page], limit, offset, total)


@bp.get("/psych-services/evaluations/<evaluation_id>/timeline-exclusions")
@authorize("SchoolPsychologist", "PsychServicesSupervisor", "ComplianceOfficer", "DistrictAdmin")
def list_evaluation_exclusions(evaluation_id):
    return _sub_collection(evaluation_id, db.exclusions, serializers.timeline_exclusion)


@bp.get("/psych-services/evaluations/<evaluation_id>/interpreter-sessions")
@authorize(*ALL_ROLES)
def list_evaluation_sessions(evaluation_id):
    return _sub_collection(evaluation_id, db.sessions, serializers.interpreter_session)


@bp.get("/psych-services/evaluations/<evaluation_id>/timeline-breaches")
@authorize("SchoolPsychologist", "PsychServicesSupervisor", "ComplianceOfficer", "DistrictAdmin")
def list_evaluation_breaches(evaluation_id):
    return _sub_collection(evaluation_id, db.breaches, serializers.timeline_breach)
