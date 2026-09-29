"""Screening, session booking and the three ways a session ends (PRD 3.5)."""
from datetime import timedelta

from flask import Blueprint

import serializers
from auth import ALL_ROLES, require_roles
from calc import (
    SCREEN_IN_MIN,
    SESSION_BUFFER,
    RESCHEDULE_LIMIT,
    recompute_participant,
    recompute_pool,
    recompute_recruitment_status,
    recompute_study_counters,
    screen_score,
    set_field,
)
from clock import clock
from envelope import ok, paged_listing
from errors import ApiError
from store import by_created, db
from validators import (
    body,
    filter_enum,
    participant_or_404,
    recruitment_or_404,
    req_datetime,
    req_str,
    req_int,
    study_or_404,
)

bp = Blueprint("recruitments", __name__)

RECRUITMENT_STATUSES = (
    "INVITED", "SCREENED_IN", "SCREENED_OUT", "SCHEDULED", "COMPLETED", "NO_SHOW", "WITHDRAWN",
)
INCENTIVE_STATES = ("RESERVED", "PAID", "FORFEITED", "RELEASED")


def _context(recruitment):
    study = db.studies.get(recruitment["study_id"])
    participant = db.participants.get(recruitment["participant_id"])
    pool = db.pools.get(study["participant_pool_id"]) if study else None
    return study, participant, pool


@bp.post("/recruitments/<recruitment_id>/screen")
@require_roles("Researcher", "ResearchLead", "ResearchOpsAdmin")
def screen(recruitment_id):
    recruitment = recruitment_or_404(recruitment_id)
    study, _participant, _pool = _context(recruitment)
    if recruitment["status"] != "INVITED":
        raise ApiError("ERR_INVALID_STATE", "Only an INVITED recruitment can be screened.")
    if study["execution_status"] != "FIELDING":
        raise ApiError("ERR_INVALID_STATE", "The study is not FIELDING.")
    score = screen_score(recruitment, study)
    set_field(recruitment, "screen_score", score)
    if score >= SCREEN_IN_MIN:
        set_field(recruitment, "status", "SCREENED_IN")
    else:
        set_field(recruitment, "status", "SCREENED_OUT")
    recompute_study_counters(study)
    return ok(serializers.recruitment(recruitment))


@bp.post("/recruitments/<recruitment_id>/schedule")
@require_roles("Researcher", "ResearchLead")
def schedule(recruitment_id):
    recruitment = recruitment_or_404(recruitment_id)
    study, participant, _pool = _context(recruitment)
    data = body()
    start = req_datetime(data, "scheduled_start")
    end = req_datetime(data, "scheduled_end")
    moderator = req_str(data, "moderator_user_id")
    if not end > start:
        raise ApiError("ERR_INVALID_REQUEST", "scheduled_end must be strictly after scheduled_start.")
    if recruitment["status"] not in ("SCREENED_IN", "SCHEDULED"):
        raise ApiError("ERR_INVALID_STATE", "Only a SCREENED_IN or SCHEDULED recruitment can be booked.")
    if study["execution_status"] != "FIELDING":
        raise ApiError("ERR_INVALID_STATE", "The study is not FIELDING.")
    rescheduling = recruitment["status"] == "SCHEDULED"
    if rescheduling and recruitment["reschedule_count"] >= RESCHEDULE_LIMIT:
        raise ApiError("ERR_INVALID_STATE", "The reschedule limit has been reached.")
    if not _granted_consent(participant, study):
        raise ApiError("ERR_CONSENT_MISSING", "No GRANTED consent record covers this session.")
    if start < study["fielding_start"] or end > study["fielding_end"] + timedelta(days=1):
        raise ApiError(
            "ERR_SESSION_WINDOW_OUTSIDE_FIELDING",
            "The session must sit inside the study's fielding window.",
        )
    lower = start - SESSION_BUFFER
    upper = end + SESSION_BUFFER
    for other in db.recruitments.values():
        if other["id"] == recruitment["id"]:
            continue
        if other["participant_id"] != recruitment["participant_id"]:
            continue
        if other["status"] != "SCHEDULED":
            continue
        if other["scheduled_start"] is None or other["scheduled_end"] is None:
            continue
        if other["scheduled_start"] < upper and other["scheduled_end"] > lower:
            raise ApiError(
                "ERR_PARTICIPANT_SESSION_CONFLICT",
                "The participant already has a session inside the buffered window.",
            )
    set_field(recruitment, "scheduled_start", start)
    set_field(recruitment, "scheduled_end", end)
    set_field(recruitment, "moderator_user_id", moderator)
    if rescheduling:
        set_field(recruitment, "reschedule_count", recruitment["reschedule_count"] + 1)
    else:
        set_field(recruitment, "status", "SCHEDULED")
    recompute_recruitment_status(study)
    return ok(serializers.recruitment(recruitment))


def _granted_consent(participant, study):
    for consent in db.consents.values():
        if consent["status"] != "GRANTED":
            continue
        if consent["participant_id"] == participant["id"] and consent["study_id"] == study["id"]:
            return consent
    return None


@bp.post("/recruitments/<recruitment_id>/complete")
@require_roles("Researcher", "ResearchLead")
def complete(recruitment_id):
    recruitment = recruitment_or_404(recruitment_id)
    study, _participant, _pool = _context(recruitment)
    data = body()
    duration = req_int(data, "actual_duration_min")
    if recruitment["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED session can be completed.")
    if study["execution_status"] != "FIELDING":
        raise ApiError("ERR_INVALID_STATE", "The study is not FIELDING.")
    set_field(recruitment, "actual_duration_min", duration)
    set_field(recruitment, "status", "COMPLETED")
    recompute_study_counters(study)
    recompute_recruitment_status(study)
    return ok(serializers.recruitment(recruitment))


@bp.post("/recruitments/<recruitment_id>/no-show")
@require_roles("Researcher", "ResearchLead")
def no_show(recruitment_id):
    recruitment = recruitment_or_404(recruitment_id)
    study, participant, pool = _context(recruitment)
    data = body()
    reason = req_str(data, "reason")
    if recruitment["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED session can be a no-show.")
    if study["execution_status"] != "FIELDING":
        raise ApiError("ERR_INVALID_STATE", "The study is not FIELDING.")
    set_field(recruitment, "status", "NO_SHOW")
    set_field(recruitment, "closure_reason", reason)
    # Hop one - the reservation is forfeited and a strike lands.
    set_field(recruitment, "incentive_state", "FORFEITED")
    set_field(participant, "no_show_strikes", participant["no_show_strikes"] + 1)
    # Hop two - the forfeiture leaves the pool's reserved bucket.
    set_field(pool, "incentive_reserved_cents", pool["incentive_reserved_cents"] - recruitment["reserved_cents"])
    recompute_pool(pool)
    # Hop three - the strike re-derives the participant's posture, which may
    # suppress them and move the pool's posture a second time.
    recompute_participant(participant)
    recompute_pool(pool)
    recompute_study_counters(study)
    recompute_recruitment_status(study)
    return ok(serializers.recruitment(recruitment))


@bp.post("/recruitments/<recruitment_id>/withdraw")
@require_roles("Researcher", "ResearchLead", "ResearchOpsAdmin")
def withdraw(recruitment_id):
    recruitment = recruitment_or_404(recruitment_id)
    study, _participant, pool = _context(recruitment)
    data = body()
    reason = req_str(data, "reason")
    previous = recruitment["status"]
    if previous not in ("INVITED", "SCREENED_IN", "SCHEDULED"):
        raise ApiError("ERR_INVALID_STATE", "A %s recruitment cannot be withdrawn." % previous)
    set_field(recruitment, "status", "WITHDRAWN")
    set_field(recruitment, "closure_reason", reason)
    set_field(recruitment, "incentive_state", "RELEASED")
    set_field(pool, "incentive_reserved_cents", pool["incentive_reserved_cents"] - recruitment["reserved_cents"])
    recompute_pool(pool)
    recompute_study_counters(study)
    if previous in ("SCREENED_IN", "SCHEDULED"):
        recompute_recruitment_status(study)
    return ok(serializers.recruitment(recruitment))


@bp.get("/recruitments/<recruitment_id>")
@require_roles(*ALL_ROLES)
def read_recruitment(recruitment_id):
    return ok(serializers.recruitment(recruitment_or_404(recruitment_id)))


@bp.get("/recruitments")
@require_roles(*ALL_ROLES)
def list_recruitments():
    participant = participant_or_404(_filter_id("participant_id"))
    study = study_or_404(_filter_id("study_id"))
    status = filter_enum("status", RECRUITMENT_STATUSES)
    incentive_state = filter_enum("incentive_state", INCENTIVE_STATES)
    rows = list(db.recruitments.values())
    if study is not None:
        rows = [r for r in rows if r["study_id"] == study["id"]]
    if participant is not None:
        rows = [r for r in rows if r["participant_id"] == participant["id"]]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if incentive_state is not None:
        rows = [r for r in rows if r["incentive_state"] == incentive_state]
    return paged_listing(by_created(rows), serializers.recruitment)


def _filter_id(name):
    from flask import request as flask_request
    raw = flask_request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw
