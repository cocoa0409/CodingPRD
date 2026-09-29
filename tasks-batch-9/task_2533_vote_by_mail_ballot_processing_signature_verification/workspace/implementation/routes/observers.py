"""Observer access sessions: scheduling, check-in, and revocation."""
from flask import Blueprint

import db
import lookups
import middleware as mw
import response
from constants import (
    OBSERVER_MAX_CONCURRENT_PER_PARTY,
    OBSERVER_MAX_CONCURRENT_TOTAL,
    PARTY_AFFILIATIONS,
    STATION_AREAS,
)
from errors import ApiError
from services import logbook, posture

bp = Blueprint("observers", __name__)

READ_ROLES = ("ElectionsAdmin", "ElectionsClerk", "CanvassSupervisor", "Observer")
OCCUPYING_STATUSES = ("SCHEDULED", "CHECKED_IN", "CLOSED")


def _overlaps(session, start_at, end_at):
    """Half-open geometry: touching endpoints do not collide."""
    return start_at < session["window_end_at"] and session["window_start_at"] < end_at


def _occupancy(election_rec, start_at, end_at):
    return [
        s for s in db.observer_sessions.values()
        if s["election_id"] == election_rec["id"]
        and s["status"] in OCCUPYING_STATUSES
        and _overlaps(s, start_at, end_at)
    ]


def _peak_occupancy(overlapping, start_at, end_at):
    """Aggregate floor occupancy at its busiest instant inside the new window.

    The new window itself counts as one occupant, so the returned figure is the
    number of observers on the floor at the worst instant if this booking were
    accepted.
    """
    instants = [start_at]
    for session in overlapping:
        if start_at < session["window_start_at"] < end_at:
            instants.append(session["window_start_at"])
    peak = 1
    for instant in instants:
        count = 1
        for session in overlapping:
            if session["window_start_at"] <= instant < session["window_end_at"]:
                count += 1
        if count > peak:
            peak = count
    return peak


@bp.post("/elections/<election_id>/observer-sessions")
def schedule_session(election_id):
    actor = mw.require_roles("ElectionsClerk", "Observer")
    payload = mw.body()
    observer_user_id = mw.require_string(payload, "observer_user_id")
    observer_name = mw.require_string(payload, "observer_name")
    organization = mw.require_string(payload, "organization")
    party_affiliation = mw.require_enum(payload, "party_affiliation", PARTY_AFFILIATIONS)
    station_area = mw.require_enum(payload, "station_area", STATION_AREAS)
    window_start_at = mw.require_datetime(payload, "window_start_at")
    window_end_at = mw.require_datetime(payload, "window_end_at")
    if window_end_at <= window_start_at:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'window_end_at' must be strictly later than 'window_start_at'.",
        )

    election_rec = lookups.election(election_id)
    posture.require_not_certified(election_rec)

    overlapping = _occupancy(election_rec, window_start_at, window_end_at)
    same_party = [
        s for s in overlapping if s["party_affiliation"] == party_affiliation
    ]
    if len(same_party) >= OBSERVER_MAX_CONCURRENT_PER_PARTY:
        raise ApiError("ERR_OBSERVER_PARTY_SLOT_CONFLICT")
    if _peak_occupancy(overlapping, window_start_at, window_end_at) > (
        OBSERVER_MAX_CONCURRENT_TOTAL
    ):
        raise ApiError("ERR_OBSERVER_FLOOR_CAPACITY")

    session = db.make_record(
        db.observer_sessions,
        {
            "election_id": election_rec["id"],
            "observer_user_id": observer_user_id,
            "observer_name": observer_name,
            "organization": organization,
            "party_affiliation": party_affiliation,
            "station_area": station_area,
            "window_start_at": window_start_at,
            "window_end_at": window_end_at,
            "status": "SCHEDULED",
            "revocation_reason_code": None,
        },
    )
    logbook.append(
        election_rec,
        "OBSERVER_SESSION_OPENED",
        actor.role,
        actor.user_id,
        "ObserverAccessSession",
        session["id"],
        "Observer access window scheduled at %s." % station_area,
    )
    return response.record_response(session, 201)


@bp.get("/observer-sessions/<session_id>")
def get_session(session_id):
    mw.require_roles(*READ_ROLES)
    return response.record_response(lookups.observer_session(session_id))


@bp.get("/observer-sessions")
def list_sessions():
    mw.require_roles(*READ_ROLES)
    limit, offset = mw.pagination()
    rows = mw.apply_filters(
        list(db.observer_sessions.values()),
        ["election_id", "party_affiliation", "station_area", "status"],
    )
    return response.list_response(db.ordered(rows), limit, offset)


@bp.post("/observer-sessions/<session_id>/check-in")
def check_in(session_id):
    actor = mw.require_roles("Observer")
    mw.body()
    session = lookups.observer_session(session_id)
    election_rec = db.elections.get(session["election_id"])
    posture.require_not_certified(election_rec)

    if session["status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_STATE_INVALID")
    if actor.user_id != session["observer_user_id"]:
        raise ApiError("ERR_ROLE_FORBIDDEN")

    now = db.now()
    if not (session["window_start_at"] <= now < session["window_end_at"]):
        raise ApiError("ERR_OBSERVER_WINDOW_NOT_ACTIVE")

    session["status"] = "CHECKED_IN"
    db.touch(session)
    logbook.append(
        election_rec,
        "OBSERVER_SESSION_OPENED",
        "Observer",
        actor.user_id,
        "ObserverAccessSession",
        session["id"],
        "Observer checked in at %s." % session["station_area"],
    )
    return response.record_response(session)


@bp.post("/observer-sessions/<session_id>/revoke")
def revoke_session(session_id):
    actor = mw.require_roles("ElectionsAdmin", "CanvassSupervisor")
    payload = mw.body()
    revocation_reason_code = mw.require_string(payload, "revocation_reason_code")

    session = lookups.observer_session(session_id)
    election_rec = db.elections.get(session["election_id"])
    posture.require_not_certified(election_rec)

    if session["status"] not in ("SCHEDULED", "CHECKED_IN"):
        raise ApiError("ERR_SESSION_STATE_INVALID")

    session["status"] = "REVOKED"
    session["revocation_reason_code"] = revocation_reason_code
    db.touch(session)
    logbook.append(
        election_rec,
        "OBSERVER_SESSION_REVOKED",
        actor.role,
        actor.user_id,
        "ObserverAccessSession",
        session["id"],
        "Observer access revoked (%s)." % revocation_reason_code,
    )
    return response.record_response(session)
