"""Separation case endpoints."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    ERR_OPEN_CASE_EXISTS,
    ERR_PARTICIPANT_STATE_INVALID,
    ERR_CASE_STATE_INVALID,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SERVICE_RECORD_GAP,
    ERR_SERVICE_RECORD_OVERLAP,
    ERR_FRACTION_CONTRADICTS,
    ERR_CASE_REOPEN_LIMIT,
    ERR_REOPEN_WINDOW_EXPIRED,
    ERR_CASE_HAS_PAID,
    raise_err,
)
from middleware import user_context, require_role
from response import ok_object
from routes.plans import _list_response
from services.core import (
    body,
    req_date,
    req_int,
    req_enum,
    get_or_404,
    stamp_new,
    touch,
    recompute_avg_fraction,
    void_open_elections_for_participant,
    compute_scheduled_payment_date,
)
from util import CLOCK, fmt_date, parse_date

bp = Blueprint("separation_cases", __name__)

TRIGGER_REASONS = {"RESIGNATION", "TERMINATION", "RETIREMENT", "SERVICE_REDUCTION"}


def case_view(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "participant_id": c["participant_id"],
        "alleged_separation_date": c["alleged_separation_date"],
        "trigger_reason": c["trigger_reason"],
        "opened_by_user_id": c["opened_by_user_id"],
        "service_records": list(c["service_records"]),
        "computed_avg_fraction_bp": c["computed_avg_fraction_bp"],
        "determination_threshold_bp": c["determination_threshold_bp"],
        "status": c["status"],
        "determined_by_user_id": c["determined_by_user_id"],
        "determined_at": c["determined_at"],
        "reopen_count": c["reopen_count"],
    }


@bp.post("/api/separation-cases")
def create_case():
    data = body()
    from errors import ERR_INVALID_REQUEST

    participant_id = data.get("participant_id")
    if not isinstance(participant_id, str) or not participant_id:
        raise_err(ERR_INVALID_REQUEST, "participant_id is required and must be a string")
    alleged = req_date(data, "alleged_separation_date")
    reason = req_enum(data, "trigger_reason", TRIGGER_REASONS)

    user_id, role = user_context()
    require_role(role, {"BenefitsAdministrator"})
    participant = get_or_404(db.participants, participant_id, "Participant")

    # PRD §3.4 pins ERR_OPEN_CASE_EXISTS to "a second attempt" — which can only
    # occur while the participant is non-ACTIVE (an open case implies
    # SEPARATION_REVIEW) — so the open-case check must precede the generic
    # ACTIVE guard, else the named error would be unreachable.
    for c in db.separation_cases.values():
        if c["participant_id"] == participant_id and c["status"] in ("OPEN", "EVIDENCE_SUBMITTED", "REOPENED"):
            raise_err(ERR_OPEN_CASE_EXISTS, "Participant already has an open separation case")
    if participant["status"] != "ACTIVE":
        raise_err(ERR_PARTICIPANT_STATE_INVALID, "Separation case requires an ACTIVE participant")

    case = stamp_new(
        {
            "participant_id": participant_id,
            "alleged_separation_date": fmt_date(alleged),
            "trigger_reason": reason,
            "opened_by_user_id": user_id,
            "service_records": [],
            "computed_avg_fraction_bp": None,
            "determination_threshold_bp": None,
            "status": "OPEN",
            "determined_by_user_id": None,
            "determined_at": None,
            "reopen_count": 0,
        }
    )
    db.separation_cases[case["id"]] = case
    participant["status"] = "SEPARATION_REVIEW"
    touch(participant)
    return ok_object(case_view(case), 201)


@bp.get("/api/separation-cases")
def list_cases():
    user_context()
    items = list(db.separation_cases.values())
    participant_id = request.args.get("participant_id")
    if participant_id is not None:
        items = [c for c in items if c["participant_id"] == participant_id]
    return _list_response([case_view(c) for c in items], request.args)


@bp.get("/api/separation-cases/<caseId>")
def get_case(caseId):
    user_context()
    c = get_or_404(db.separation_cases, caseId, "SeparationCase")
    return ok_object(case_view(c))


@bp.post("/api/separation-cases/<caseId>/service-records")
def append_service_record(caseId):
    data = body()
    p_start = req_date(data, "period_start")
    p_end = req_date(data, "period_end")
    fraction = req_int(data, "service_fraction_bp", 0, 10000)
    if p_start >= p_end:
        from errors import ERR_INVALID_DATE_RANGE

        raise_err(ERR_INVALID_DATE_RANGE, "period_start must be before period_end")

    user_id, role = user_context()
    require_role(role, {"BenefitsAdministrator"})
    case = get_or_404(db.separation_cases, caseId, "SeparationCase")

    if case["status"] not in ("OPEN", "REOPENED", "EVIDENCE_SUBMITTED"):
        raise_err(ERR_CASE_STATE_INVALID, "Service records require an OPEN, REOPENED, or EVIDENCE_SUBMITTED case")

    # Tiling: half-open, contiguous, no gap/overlap
    records = sorted(case["service_records"], key=lambda r: r["period_start"])
    if records:
        last = records[-1]
        last_end = parse_date(last["period_end"])
        if p_start < last_end:
            raise_err(ERR_SERVICE_RECORD_OVERLAP, "Service record overlaps the previous record")
        if p_start > last_end:
            raise_err(ERR_SERVICE_RECORD_GAP, "Service record leaves a gap against the previous record")

    case["service_records"].append(
        {
            "period_start": fmt_date(p_start),
            "period_end": fmt_date(p_end),
            "service_fraction_bp": fraction,
        }
    )
    recompute_avg_fraction(case)
    if case["status"] in ("OPEN", "REOPENED"):
        case["status"] = "EVIDENCE_SUBMITTED"
    touch(case)
    return ok_object(case_view(case), 201)


@bp.post("/api/separation-cases/<caseId>/determine")
def determine_case(caseId):
    data = body()
    outcome = req_enum(data, "outcome", {"CONFIRMED_SEPARATION", "REBUTTED_CONTINUED_SERVICE"})

    user_id, role = user_context()
    require_role(role, {"ComplianceOfficer"})
    case = get_or_404(db.separation_cases, caseId, "SeparationCase")

    if case["status"] not in ("EVIDENCE_SUBMITTED", "REOPENED") or not case["service_records"]:
        raise_err(ERR_CASE_STATE_INVALID, "Determine requires EVIDENCE_SUBMITTED or REOPENED with at least one record")

    if user_id == case["opened_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "Determiner must differ from the case opener")

    participant = db.participants[case["participant_id"]]
    plan = db.plans[participant["plan_id"]]
    threshold = 5000 if plan["separation_fraction_test"] == "DEFAULT_50" else 2000
    avg = case["computed_avg_fraction_bp"]

    if outcome == "CONFIRMED_SEPARATION":
        if not (avg < threshold):
            raise_err(ERR_FRACTION_CONTRADICTS, "CONFIRMED_SEPARATION requires avg fraction below threshold")
    else:
        if not (avg >= threshold):
            raise_err(ERR_FRACTION_CONTRADICTS, "REBUTTED_CONTINUED_SERVICE requires avg fraction at or above threshold")

    case["determination_threshold_bp"] = threshold
    case["determined_by_user_id"] = user_id
    case["determined_at"] = CLOCK.stamp()

    if outcome == "CONFIRMED_SEPARATION":
        case["status"] = "DETERMINED_SEPARATED"
        participant["status"] = "SEPARATED"
        participant["separation_date"] = case["alleged_separation_date"]
        touch(participant)
        void_open_elections_for_participant(participant["id"])
        # Re-determination path: linked ON_HOLD requests return to SCHEDULED
        for req in db.distribution_requests.values():
            if req.get("separation_case_id") == case["id"] and req["status"] == "ON_HOLD":
                req["status"] = "SCHEDULED"
                req["scheduled_payment_date"] = fmt_date(compute_scheduled_payment_date(req))
                touch(req)
    else:
        case["status"] = "DETERMINED_NOT_SEPARATED"
        if participant["status"] == "SEPARATION_REVIEW":
            participant["status"] = "ACTIVE"
            touch(participant)
        for req in db.distribution_requests.values():
            if req.get("separation_case_id") == case["id"] and req["status"] == "ON_HOLD":
                req["status"] = "DENIED"
                touch(req)

    touch(case)
    return ok_object(case_view(case))


@bp.post("/api/separation-cases/<caseId>/reopen")
def reopen_case(caseId):
    body()
    user_id, role = user_context()
    require_role(role, {"BenefitsAdministrator"})
    case = get_or_404(db.separation_cases, caseId, "SeparationCase")

    if case["status"] not in ("DETERMINED_SEPARATED", "DETERMINED_NOT_SEPARATED"):
        raise_err(ERR_CASE_STATE_INVALID, "Reopen requires a determined case")
    if case["reopen_count"] >= 1:
        raise_err(ERR_CASE_REOPEN_LIMIT, "Case may be reopened at most once")
    determined_date = parse_date(case["determined_at"][:10])
    if CLOCK.date() > determined_date + timedelta(days=30):
        raise_err(ERR_REOPEN_WINDOW_EXPIRED, "Reopen window has expired")
    for req in db.distribution_requests.values():
        if req.get("separation_case_id") == case["id"] and req["status"] == "PAID":
            raise_err(ERR_CASE_HAS_PAID, "Case has a linked PAID distribution")

    was_separated = case["status"] == "DETERMINED_SEPARATED"
    case["status"] = "REOPENED"
    case["reopen_count"] += 1

    if was_separated:
        participant = db.participants[case["participant_id"]]
        participant["status"] = "SEPARATION_REVIEW"
        participant["separation_date"] = None
        touch(participant)
        for req in db.distribution_requests.values():
            if req.get("separation_case_id") == case["id"] and req["status"] == "SCHEDULED":
                req["status"] = "ON_HOLD"
                touch(req)

    touch(case)
    return ok_object(case_view(case))
