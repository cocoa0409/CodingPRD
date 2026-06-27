"""Live session routes: fetch, complete, cancel, no-show, credits."""
from datetime import timedelta

from flask import Blueprint, request

from db import db, touch
from clock import clock, parse_iso
from errors import err, ERR_INVALID_STATE
from middleware import get_auth, require_role
from lookup import get_or_404, check_client_owner, check_therapist_owner, paginate
import serialize
from response import success, list_success

bp = Blueprint("live_sessions", __name__)

CANCEL_WINDOW = timedelta(hours=24)


def _match_for_session(session):
    return db.matches.get(session["match_id"])


def _credit_for_session(session):
    cid = session.get("session_credit_id")
    return db.session_credits.get(cid) if cid else None


@bp.route("/live-sessions/<sid>", methods=["GET"])
def get_session(sid):
    user_id, role = get_auth()
    require_role(role, {"Client", "Therapist", "ClinicalAdmin"})
    session = get_or_404(db.live_sessions, sid)
    match = _match_for_session(session)
    if match:
        check_client_owner(role, user_id, match["client_id"])
        check_therapist_owner(role, user_id, match["therapist_id"])
    return success(serialize.live_session_out(session))


@bp.route("/live-sessions/<sid>/session-credits", methods=["GET"])
def list_session_credits(sid):
    user_id, role = get_auth()
    require_role(role, {"Client", "Therapist", "ClinicalAdmin", "BillingAdmin"})
    session = get_or_404(db.live_sessions, sid)
    match = _match_for_session(session)
    if match:
        check_client_owner(role, user_id, match["client_id"])
        check_therapist_owner(role, user_id, match["therapist_id"])
    items = [c for c in db.session_credits.values() if c.get("live_session_id") == sid]
    items.sort(key=lambda c: (c["created_at"], c["_seq"]))
    page, lim, off, total = paginate(items, request.args)
    return list_success([serialize.session_credit_out(c) for c in page], lim, off, total)


@bp.route("/live-sessions/<sid>/complete", methods=["POST"])
def complete_session(sid):
    user_id, role = get_auth()
    require_role(role, {"Therapist"})
    session = get_or_404(db.live_sessions, sid)
    match = _match_for_session(session)
    if match:
        check_therapist_owner(role, user_id, match["therapist_id"])
    if session["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Session not in SCHEDULED")
    if clock.now() < parse_iso(session["starts_at"]):
        raise err(ERR_INVALID_STATE, "Cannot complete before starts_at")
    credit = _credit_for_session(session)
    if credit is None or credit["status"] != "RESERVED":
        raise err(ERR_INVALID_STATE, "Reserved credit not in RESERVED state")
    session["status"] = "COMPLETED"
    touch(session)
    credit["status"] = "CONSUMED"
    return success(serialize.live_session_out(session))


@bp.route("/live-sessions/<sid>/cancel", methods=["POST"])
def cancel_session(sid):
    user_id, role = get_auth()
    require_role(role, {"Client", "Therapist"})
    session = get_or_404(db.live_sessions, sid)
    match = _match_for_session(session)
    if match:
        check_client_owner(role, user_id, match["client_id"])
        check_therapist_owner(role, user_id, match["therapist_id"])
    if session["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Session not in SCHEDULED")
    starts_at = parse_iso(session["starts_at"])
    within_window = (starts_at - clock.now()) < CANCEL_WINDOW
    session["status"] = "CANCELLED"
    session["cancelled_within_window"] = within_window
    touch(session)
    credit = _credit_for_session(session)
    if credit is not None:
        if within_window:
            credit["status"] = "CONSUMED"
        else:
            credit["status"] = "AVAILABLE"
    return success(serialize.live_session_out(session))


@bp.route("/live-sessions/<sid>/no-show", methods=["POST"])
def no_show_session(sid):
    user_id, role = get_auth()
    require_role(role, {"Therapist"})
    session = get_or_404(db.live_sessions, sid)
    match = _match_for_session(session)
    if match:
        check_therapist_owner(role, user_id, match["therapist_id"])
    if session["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Session not in SCHEDULED")
    if clock.now() < parse_iso(session["ends_at"]):
        raise err(ERR_INVALID_STATE, "Cannot mark no-show before ends_at")
    session["status"] = "NO_SHOW"
    touch(session)
    credit = _credit_for_session(session)
    if credit is not None:
        credit["status"] = "CONSUMED"
    return success(serialize.live_session_out(session))
