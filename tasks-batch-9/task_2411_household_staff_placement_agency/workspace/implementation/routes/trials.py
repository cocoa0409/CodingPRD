"""Trial engagements and accommodation term negotiation (PRD 3.4, 3.5)."""

from datetime import timedelta

from flask import Blueprint, request

import db
from db import (
    ACCOMMODATION_STATUSES,
    CANCEL_REASONS,
    CANDIDATE_WEEKLY_TRIAL_CAP,
    ENGAGEMENT_TYPES,
    MAX_NEGOTIATION_ROUNDS,
    PRESENTATION_MIN_SCORE,
    TERMINAL_ACCOMMODATION,
    TERMINAL_TRIAL,
    TRIAL_BUFFER_MINUTES,
    TRIAL_STATUSES,
    serialize,
    store,
    touch,
)
from errors import fail
from middleware import (
    AGENCY_PRINCIPAL,
    CANDIDATE,
    CLIENT,
    COMPLIANCE_OFFICER,
    PLACEMENT_CONSULTANT,
    VETTING_SPECIALIST,
    authenticate,
)
from response import created_response, list_response, object_response
from services import domain
from timeutil import iso_week_key, parse_timestamp
from validation import (
    apply_filters,
    body_of,
    check_enum,
    check_int,
    check_timestamp,
    interval_fail,
    list_params,
    range_fail,
    require_bool,
    require_present,
    require_string,
)

bp = Blueprint("trials", __name__)

PRESENTABLE_VETTING = ("REFERENCES_VERIFIED", "BACKGROUND_PENDING", "CLEARED")


# ---------------------------------------------------------------------------
# Booking
# ---------------------------------------------------------------------------
@bp.post("/role-requisitions/<requisition_id>/trial-engagements")
def book_trial(requisition_id):
    authenticate({PLACEMENT_CONSULTANT})
    body = body_of(request)

    require_present(body, "candidate_id", "engagement_type", "start_at", "end_at", "day_rate_cents")
    engagement_type = check_enum(body, "engagement_type", ENGAGEMENT_TYPES)
    day_rate_cents = check_int(body, "day_rate_cents", minimum=0)
    if engagement_type == "WORKING_INTERVIEW" and day_rate_cents != 0:
        range_fail("day_rate_cents must be 0 for a WORKING_INTERVIEW")
    start_at = check_timestamp(body, "start_at")
    end_at = check_timestamp(body, "end_at")
    if end_at <= start_at:
        interval_fail("end_at must be strictly after start_at")

    requisition = domain.resolve("requisitions", requisition_id)
    candidate = domain.resolve("candidates", body["candidate_id"])

    if requisition["status"] not in ("SOURCING", "TRIALING"):
        fail("ERR_INVALID_STATE_TRANSITION")

    client = domain.resolve("clients", requisition["client_id"])
    domain.guard_client_not_suspended(client)

    if candidate["vetting_status"] not in PRESENTABLE_VETTING:
        fail("ERR_CANDIDATE_NOT_VETTED")
    if candidate["availability_status"] != "AVAILABLE":
        fail("ERR_CANDIDATE_UNAVAILABLE")

    # Household occupancy: an active trial occupies
    # [start_at - TRIAL_BUFFER_MINUTES, end_at + TRIAL_BUFFER_MINUTES).
    buffer = timedelta(minutes=TRIAL_BUFFER_MINUTES)
    for other in domain.children("trial_engagements", "client_id", client["id"]):
        if other["status"] not in db.ACTIVE_TRIAL_STATUSES:
            continue
        other_start = parse_timestamp(other["start_at"]) - buffer
        other_end = parse_timestamp(other["end_at"]) + buffer
        if start_at < other_end and other_start < end_at:
            fail("ERR_TRIAL_OVERLAP")

    week_key = iso_week_key(start_at)
    booked_this_week = len([
        t for t in domain.children("trial_engagements", "candidate_id", candidate["id"])
        if t["iso_week_key"] == week_key and t["status"] in db.WEEKLY_CAP_STATUSES
    ])
    if booked_this_week >= CANDIDATE_WEEKLY_TRIAL_CAP:
        fail("ERR_TRIAL_WEEKLY_CAP_EXCEEDED")

    if candidate["screening_score"] < PRESENTATION_MIN_SCORE:
        fail("ERR_CANDIDATE_SCORE_BELOW_THRESHOLD")

    domain.guard_credit_hold(client)

    row = {
        "requisition_id": requisition["id"],
        "candidate_id": candidate["id"],
        "client_id": client["id"],
        "engagement_type": engagement_type,
        "start_at": body["start_at"],
        "end_at": body["end_at"],
        "day_rate_cents": day_rate_cents,
        "iso_week_key": week_key,
        "status": "SCHEDULED",
        "cancel_reason": None,
        "outcome_note": None,
    }
    db.stamp_new(row)
    store.trial_engagements[row["id"]] = row

    candidate["availability_status"] = "ON_TRIAL"
    touch(candidate)

    if requisition["status"] == "SOURCING":
        requisition["status"] = "TRIALING"
        touch(requisition)
    domain.recompute_active_trial_count(requisition)

    return created_response(serialize(row))


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
@bp.get("/trial-engagements/<trial_id>")
def get_trial(trial_id):
    authenticate({
        AGENCY_PRINCIPAL, PLACEMENT_CONSULTANT, VETTING_SPECIALIST,
        COMPLIANCE_OFFICER, CLIENT, CANDIDATE,
    })
    row = domain.resolve("trial_engagements", trial_id)
    return object_response(serialize(row))


@bp.get("/trial-engagements")
def list_trials():
    authenticate({
        AGENCY_PRINCIPAL, PLACEMENT_CONSULTANT, VETTING_SPECIALIST,
        COMPLIANCE_OFFICER, CLIENT,
    })
    limit, offset, filters = list_params(
        request,
        enum_filters={"status": TRIAL_STATUSES, "engagement_type": ENGAGEMENT_TYPES},
        plain_filters=("requisition_id", "candidate_id", "client_id", "iso_week_key"),
    )
    rows = apply_filters(list(store.trial_engagements.values()), filters)
    data, total = domain.page(rows, limit, offset)
    return list_response(data, limit, offset, total)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
@bp.post("/trial-engagements/<trial_id>/start")
def start_trial(trial_id):
    authenticate({PLACEMENT_CONSULTANT})
    body_of(request)

    trial = domain.resolve("trial_engagements", trial_id)
    domain.guard_terminal(trial["status"], TERMINAL_TRIAL)
    if trial["status"] != "SCHEDULED":
        fail("ERR_TRIAL_NOT_SCHEDULED")

    candidate = domain.resolve("candidates", trial["candidate_id"])
    if candidate["vetting_status"] == "REJECTED":
        fail("ERR_CANDIDATE_NOT_VETTED")

    if store.now() < parse_timestamp(trial["start_at"]):
        fail("ERR_TRIAL_NOT_STARTED")

    trial["status"] = "IN_PROGRESS"
    touch(trial)
    return object_response(serialize(trial))


@bp.post("/trial-engagements/<trial_id>/record-outcome")
def record_trial_outcome(trial_id):
    authenticate({PLACEMENT_CONSULTANT})
    body = body_of(request)

    require_present(body, "outcome")
    outcome_note = require_string(body, "outcome_note", 0, 100000, required=False)
    outcome = check_enum(body, "outcome", ["PASSED", "FAILED"])

    trial = domain.resolve("trial_engagements", trial_id)
    domain.guard_terminal(trial["status"], TERMINAL_TRIAL)
    if trial["status"] != "IN_PROGRESS":
        fail("ERR_TRIAL_NOT_IN_PROGRESS")
    if store.now() < parse_timestamp(trial["end_at"]):
        fail("ERR_TRIAL_WINDOW_NOT_ELAPSED")

    trial["status"] = outcome
    if outcome_note is not None:
        trial["outcome_note"] = outcome_note
    touch(trial)

    requisition = store.requisitions.get(trial["requisition_id"])
    candidate = store.candidates.get(trial["candidate_id"])

    if outcome == "FAILED":
        if candidate is not None:
            domain.restore_candidate_after_trial(candidate)
        if requisition is not None:
            domain.fallback_trialing_to_sourcing(requisition)
    else:
        # A passed trial deliberately leaves the candidate ON_TRIAL and the
        # requisition in TRIALING so an offer can follow immediately.
        if requisition is not None:
            domain.recompute_active_trial_count(requisition)

    return object_response(serialize(trial))


@bp.post("/trial-engagements/<trial_id>/cancel")
def cancel_trial_endpoint(trial_id):
    authenticate({PLACEMENT_CONSULTANT, CLIENT})
    body = body_of(request)

    require_present(body, "cancel_reason")
    note = require_string(body, "note", 0, 100000, required=False)
    cancel_reason = check_enum(body, "cancel_reason", CANCEL_REASONS)

    trial = domain.resolve("trial_engagements", trial_id)
    domain.guard_terminal(trial["status"], TERMINAL_TRIAL)
    if trial["status"] not in db.ACTIVE_TRIAL_STATUSES:
        fail("ERR_INVALID_STATE_TRANSITION")

    domain.cancel_trial(trial, cancel_reason, note=note)

    requisition = store.requisitions.get(trial["requisition_id"])
    if requisition is not None:
        domain.fallback_trialing_to_sourcing(requisition)

    return object_response(serialize(trial))


# ---------------------------------------------------------------------------
# Accommodation terms
# ---------------------------------------------------------------------------
@bp.post("/role-requisitions/<requisition_id>/accommodation-terms")
def open_accommodation_term(requisition_id):
    authenticate({PLACEMENT_CONSULTANT, CLIENT})
    body = body_of(request)

    require_present(
        body, "candidate_id", "live_in", "weekly_hours", "days_off_per_week",
        "private_quarters", "imputed_accommodation_cents", "expected_requisition_version",
    )
    note = require_string(body, "note", 0, 100000, required=False)
    live_in = require_bool(body, "live_in")
    private_quarters = require_bool(body, "private_quarters")
    weekly_hours = check_int(body, "weekly_hours", minimum=1, maximum=80)
    days_off_per_week = check_int(body, "days_off_per_week", minimum=0, maximum=7)
    imputed_accommodation_cents = check_int(body, "imputed_accommodation_cents", minimum=0)
    if not live_in and imputed_accommodation_cents != 0:
        range_fail("imputed_accommodation_cents must be 0 when live_in is false")

    requisition = domain.resolve("requisitions", requisition_id)
    candidate = domain.resolve("candidates", body["candidate_id"])

    if body["expected_requisition_version"] != requisition["version"]:
        fail("ERR_STALE_REQUISITION_VERSION")

    domain.guard_terminal(requisition["status"], db.TERMINAL_REQUISITION)

    if live_in and not candidate["live_in_willing"]:
        fail("ERR_LIVE_IN_INCOMPATIBLE")

    # Opening a fresh negotiation supersedes every live term on the requisition.
    for existing in db.sort_rows(domain.children("accommodation_terms", "requisition_id", requisition["id"])):
        if existing["status"] in ("PROPOSED", "COUNTERED"):
            existing["status"] = "SUPERSEDED"
            touch(existing)

    row = {
        "requisition_id": requisition["id"],
        "candidate_id": candidate["id"],
        "round_no": 1,
        "live_in": live_in,
        "weekly_hours": weekly_hours,
        "days_off_per_week": days_off_per_week,
        "private_quarters": private_quarters,
        "imputed_accommodation_cents": imputed_accommodation_cents,
        "status": "PROPOSED",
        "last_responder_role": "AGENCY",
        "note": note,
    }
    db.stamp_new(row)
    store.accommodation_terms[row["id"]] = row

    touch(requisition)
    return created_response(serialize(row))


@bp.get("/accommodation-terms/<term_id>")
def get_accommodation_term(term_id):
    authenticate({AGENCY_PRINCIPAL, PLACEMENT_CONSULTANT, COMPLIANCE_OFFICER, CLIENT, CANDIDATE})
    row = domain.resolve("accommodation_terms", term_id)
    return object_response(serialize(row))


@bp.get("/accommodation-terms")
def list_accommodation_terms():
    authenticate({AGENCY_PRINCIPAL, PLACEMENT_CONSULTANT, COMPLIANCE_OFFICER, CLIENT, CANDIDATE})
    limit, offset, filters = list_params(
        request,
        enum_filters={"status": ACCOMMODATION_STATUSES},
        plain_filters=("requisition_id", "candidate_id"),
    )
    rows = apply_filters(list(store.accommodation_terms.values()), filters)
    data, total = domain.page(rows, limit, offset)
    return list_response(data, limit, offset, total)


@bp.post("/accommodation-terms/<term_id>/respond")
def respond_accommodation_term(term_id):
    _user_id, role = authenticate({CLIENT, CANDIDATE})
    body = body_of(request)

    require_present(body, "response")
    note = require_string(body, "note", 0, 100000, required=False)
    response_value = check_enum(body, "response", ["COUNTER", "ACCEPT", "REJECT"])
    live_in = require_bool(body, "live_in", required=False, default=None)
    private_quarters = require_bool(body, "private_quarters", required=False, default=None)
    weekly_hours = check_int(body, "weekly_hours", minimum=1, maximum=80, required=False)
    days_off_per_week = check_int(body, "days_off_per_week", minimum=0, maximum=7, required=False)
    imputed_accommodation_cents = check_int(
        body, "imputed_accommodation_cents", minimum=0, required=False
    )

    term = domain.resolve("accommodation_terms", term_id)
    domain.guard_terminal(term["status"], TERMINAL_ACCOMMODATION)

    candidate = domain.resolve("candidates", term["candidate_id"])
    party = "CLIENT" if role == CLIENT else "CANDIDATE"

    if response_value == "COUNTER":
        effective_live_in = term["live_in"] if live_in is None else live_in
        if effective_live_in and not candidate["live_in_willing"]:
            fail("ERR_LIVE_IN_INCOMPATIBLE")
        if term["round_no"] >= MAX_NEGOTIATION_ROUNDS:
            fail("ERR_NEGOTIATION_ROUND_LIMIT")
        if party == term["last_responder_role"]:
            fail("ERR_RESPONDER_MUST_ALTERNATE")

        term["status"] = "COUNTERED"
        term["round_no"] += 1
        if live_in is not None:
            term["live_in"] = live_in
        if weekly_hours is not None:
            term["weekly_hours"] = weekly_hours
        if days_off_per_week is not None:
            term["days_off_per_week"] = days_off_per_week
        if private_quarters is not None:
            term["private_quarters"] = private_quarters
        if imputed_accommodation_cents is not None:
            term["imputed_accommodation_cents"] = imputed_accommodation_cents
        term["last_responder_role"] = party
        if note is not None:
            term["note"] = note
        touch(term)

    elif response_value == "ACCEPT":
        if term["live_in"] and not candidate["live_in_willing"]:
            fail("ERR_LIVE_IN_INCOMPATIBLE")
        was_countered = term["status"] == "COUNTERED"
        if was_countered and party == term["last_responder_role"]:
            fail("ERR_RESPONDER_MUST_ALTERNATE")

        term["status"] = "ACCEPTED"
        if note is not None:
            term["note"] = note
        touch(term)

        if was_countered:
            # Acceptance out of a counter aligns the requisition's live-in
            # requirement to the settled term; schedule_pattern is untouched.
            requisition = store.requisitions.get(term["requisition_id"])
            if requisition is not None and requisition["live_in_required"] != term["live_in"]:
                requisition["live_in_required"] = term["live_in"]
                touch(requisition)

    else:
        term["status"] = "REJECTED"
        if note is not None:
            term["note"] = note
        touch(term)

    return object_response(serialize(term))
