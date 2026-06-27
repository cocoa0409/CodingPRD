"""Match routes: propose, accept, request-switch, reassign, thread, live-sessions."""
from datetime import timedelta

from flask import Blueprint, request

from db import db, common_create_fields, light_create_fields, touch
from clock import clock, parse_iso
from errors import (
    err, ERR_INVALID_STATE, ERR_REFERENCED_NOT_FOUND, ERR_INTAKE_NOT_CLEARED,
    ERR_LICENSE_STATE_MISMATCH, ERR_CLIENT_RISK_BLOCKED, ERR_NO_ELIGIBLE_THERAPIST,
    ERR_STALE_VERSION, ERR_SESSION_OVERLAP, ERR_THERAPIST_DOUBLE_BOOKED, ERR_NO_CREDIT,
)
from middleware import get_auth, require_role
from lookup import get_or_404, check_client_owner, check_therapist_owner, paginate
from validate import require_body, require_string, require_enum, require_datetime, require_int, SWITCH_REASONS
from services.calc import match_score as calc_match_score
from services.domain import (
    therapist_has_valid_license, therapist_increment_caseload, therapist_decrement_caseload,
    create_thread_for_match, thread_for_match,
)
import serialize
from response import success, list_success

bp = Blueprint("matches", __name__)

THERAPIST_BUFFER = timedelta(minutes=15)


def _client_intake(client_id):
    for i in db.intakes.values():
        if i["client_id"] == client_id:
            return i
    return None


@bp.route("/matches", methods=["POST"])
def propose_match():
    user_id, role = get_auth()
    require_role(role, {"ClinicalAdmin"})
    data = require_body(request.get_json(silent=True))
    client_id = require_string(data, "client_id")
    therapist_id = require_string(data, "therapist_id")
    # body FK existence
    client = db.clients.get(client_id)
    if client is None:
        raise err(ERR_REFERENCED_NOT_FOUND, "client_id not found")
    therapist = db.therapists.get(therapist_id)
    if therapist is None:
        raise err(ERR_REFERENCED_NOT_FOUND, "therapist_id not found")
    intake = _client_intake(client_id)
    # intake safety gate: severity>=8 or crisis_indicator==true, uncleared
    if intake is not None:
        gate = intake["crisis_indicator"] or intake["severity_score"] >= 8
        if gate and client["status"] == "PENDING_INTAKE":
            raise err(ERR_INTAKE_NOT_CLEARED, "Client intake not cleared")
    # license coverage
    if not therapist_has_valid_license(therapist_id, client["state_code"]):
        raise err(ERR_LICENSE_STATE_MISMATCH, "Therapist holds no VALID license for client's state")
    # compute match_score
    concerns = intake["presenting_concerns"] if intake else []
    severity = intake["severity_score"] if intake else 0
    score = calc_match_score(
        concerns, therapist["specialties"],
        therapist_has_valid_license(therapist_id, client["state_code"]),
        severity,
    )
    match = {
        **common_create_fields(),
        "client_id": client_id,
        "therapist_id": therapist_id,
        "status": "PROPOSED",
        "match_score": score,
        "switch_reason": None,
        "superseded_by_match_id": None,
    }
    db.matches[match["id"]] = match
    return success(serialize.match_out(match), status=201)


@bp.route("/matches/<mid>", methods=["GET"])
def get_match(mid):
    user_id, role = get_auth()
    require_role(role, {"Client", "Therapist", "ClinicalAdmin"})
    match = get_or_404(db.matches, mid)
    check_client_owner(role, user_id, match["client_id"])
    check_therapist_owner(role, user_id, match["therapist_id"])
    return success(serialize.match_out(match))


@bp.route("/matches", methods=["GET"])
def list_matches():
    user_id, role = get_auth()
    require_role(role, {"ClinicalAdmin"})
    client_id = request.args.get("client_id")
    therapist_id = request.args.get("therapist_id")
    status = request.args.get("status")
    superseded = request.args.get("superseded_by_match_id")
    items = list(db.matches.values())
    if client_id is not None:
        items = [m for m in items if m["client_id"] == client_id]
    if therapist_id is not None:
        items = [m for m in items if m["therapist_id"] == therapist_id]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    if superseded is not None:
        items = [m for m in items if m["superseded_by_match_id"] == superseded]
    items.sort(key=lambda m: (m["created_at"], m["_seq"]))
    page, lim, off, total = paginate(items, request.args)
    return list_success([serialize.match_out(m) for m in page], lim, off, total)


@bp.route("/matches/<mid>/accept", methods=["POST"])
def accept_match(mid):
    user_id, role = get_auth()
    require_role(role, {"Client"})
    match = get_or_404(db.matches, mid)
    check_client_owner(role, user_id, match["client_id"])
    # state
    if match["status"] != "PROPOSED":
        raise err(ERR_INVALID_STATE, "Match not in PROPOSED")
    client = db.clients.get(match["client_id"])
    therapist = db.therapists.get(match["therapist_id"])
    # risk block
    if client["risk_flag"] == "ACUTE":
        raise err(ERR_CLIENT_RISK_BLOCKED, "Client risk posture is ACUTE")
    # license coverage
    if not therapist_has_valid_license(therapist["id"], client["state_code"]):
        raise err(ERR_LICENSE_STATE_MISMATCH, "Therapist holds no VALID license for client's state")
    # therapist accepting + caseload
    if therapist["status"] != "ACCEPTING":
        raise err(ERR_INVALID_STATE, "Therapist is not ACCEPTING")
    if therapist["active_caseload"] >= therapist["max_active_caseload"]:
        raise err(ERR_INVALID_STATE, "Therapist caseload is full")
    # fire cascade
    match["status"] = "ACTIVE"
    touch(match)
    therapist_increment_caseload(therapist)
    create_thread_for_match(match["id"])
    if client["status"] == "AWAITING_MATCH":
        client["status"] = "ACTIVE"
        touch(client)
    return success(serialize.match_out(match))


@bp.route("/matches/<mid>/request-switch", methods=["POST"])
def request_switch(mid):
    user_id, role = get_auth()
    require_role(role, {"Client", "Therapist"})
    match = get_or_404(db.matches, mid)
    check_client_owner(role, user_id, match["client_id"])
    check_therapist_owner(role, user_id, match["therapist_id"])
    data = require_body(request.get_json(silent=True))
    switch_reason = require_enum(data, "switch_reason", SWITCH_REASONS)
    if match["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Match not in ACTIVE")
    match["status"] = "SWITCH_REQUESTED"
    match["switch_reason"] = switch_reason
    touch(match)
    thread = thread_for_match(match["id"])
    if thread and thread["status"] == "OPEN":
        thread["status"] = "FROZEN"
        touch(thread)
    return success(serialize.match_out(match))


@bp.route("/matches/<mid>/reassign", methods=["POST"])
def reassign_match(mid):
    user_id, role = get_auth()
    require_role(role, {"ClinicalAdmin"})
    match = get_or_404(db.matches, mid)
    if match["status"] != "SWITCH_REQUESTED":
        raise err(ERR_INVALID_STATE, "Match not in SWITCH_REQUESTED")
    client = db.clients.get(match["client_id"])
    # select eligible candidate
    candidate = _select_reassign_candidate(client, match["therapist_id"])
    if candidate is None:
        raise err(ERR_NO_ELIGIBLE_THERAPIST, "No eligible candidate therapist")
    # create successor ACTIVE match
    intake = _client_intake(client["id"])
    concerns = intake["presenting_concerns"] if intake else []
    severity = intake["severity_score"] if intake else 0
    score = calc_match_score(
        concerns, candidate["specialties"],
        therapist_has_valid_license(candidate["id"], client["state_code"]),
        severity,
    )
    successor = {
        **common_create_fields(),
        "client_id": client["id"],
        "therapist_id": candidate["id"],
        "status": "ACTIVE",
        "match_score": score,
        "switch_reason": None,
        "superseded_by_match_id": None,
    }
    db.matches[successor["id"]] = successor
    # successor's own ACTIVE side effects
    therapist_increment_caseload(candidate)
    create_thread_for_match(successor["id"])
    if client["status"] == "AWAITING_MATCH":
        client["status"] = "ACTIVE"
        touch(client)
    # old match cascade
    match["superseded_by_match_id"] = successor["id"]
    match["status"] = "ENDED"
    touch(match)
    old_therapist = db.therapists.get(match["therapist_id"])
    if old_therapist:
        therapist_decrement_caseload(old_therapist)
    old_thread = thread_for_match(match["id"])
    if old_thread and old_thread["status"] in ("OPEN", "FROZEN"):
        old_thread["status"] = "ARCHIVED"
        touch(old_thread)
    return success(serialize.match_out(successor), status=201)


def _select_reassign_candidate(client, old_therapist_id):
    candidates = []
    for t in db.therapists.values():
        if t["id"] == old_therapist_id:
            continue
        if t["status"] != "ACCEPTING":
            continue
        if t["active_caseload"] >= t["max_active_caseload"]:
            continue
        if not therapist_has_valid_license(t["id"], client["state_code"]):
            continue
        intake = _client_intake(client["id"])
        concerns = intake["presenting_concerns"] if intake else []
        severity = intake["severity_score"] if intake else 0
        score = calc_match_score(concerns, t["specialties"], True, severity)
        candidates.append((score, t))
    if not candidates:
        return None
    # rank match_score DESC, tie-break therapist created_at ASC (then _seq)
    candidates.sort(key=lambda pair: (-pair[0], pair[1]["created_at"], pair[1]["_seq"]))
    return candidates[0][1]


@bp.route("/matches/<mid>/thread", methods=["GET"])
def get_match_thread(mid):
    user_id, role = get_auth()
    require_role(role, {"Client", "Therapist", "ClinicalAdmin"})
    match = get_or_404(db.matches, mid)
    check_client_owner(role, user_id, match["client_id"])
    check_therapist_owner(role, user_id, match["therapist_id"])
    thread = thread_for_match(mid)
    items = [thread] if thread else []
    return success([serialize.thread_out(t) for t in items], response_type="array")


@bp.route("/matches/<mid>/live-sessions", methods=["GET"])
def list_match_sessions(mid):
    user_id, role = get_auth()
    require_role(role, {"Client", "Therapist", "ClinicalAdmin"})
    match = get_or_404(db.matches, mid)
    check_client_owner(role, user_id, match["client_id"])
    check_therapist_owner(role, user_id, match["therapist_id"])
    status = request.args.get("status")
    items = [s for s in db.live_sessions.values()
             if s["match_id"] == mid and (status is None or s["status"] == status)]
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    page, lim, off, total = paginate(items, request.args)
    return list_success([serialize.live_session_out(s) for s in page], lim, off, total)


_NON_TERMINAL_SESSION = {"SCHEDULED"}


@bp.route("/matches/<mid>/live-sessions", methods=["POST"])
def schedule_live_session(mid):
    user_id, role = get_auth()
    require_role(role, {"Client", "Therapist"})
    match = get_or_404(db.matches, mid)
    check_client_owner(role, user_id, match["client_id"])
    check_therapist_owner(role, user_id, match["therapist_id"])
    data = require_body(request.get_json(silent=True))
    starts_at = require_datetime(data, "starts_at")
    ends_at = require_datetime(data, "ends_at")
    expected_version = require_int(data, "expected_match_version")
    if ends_at <= starts_at:
        from errors import ERR_INVALID_REQUEST
        raise err(ERR_INVALID_REQUEST, "ends_at must be after starts_at")
    # state: match must be ACTIVE
    if match["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Match not in ACTIVE")
    client = db.clients.get(match["client_id"])
    # business_safety: risk block (priority 8, before OCC per validation table)
    if client["risk_flag"] == "ACUTE":
        raise err(ERR_CLIENT_RISK_BLOCKED, "Client risk posture is ACUTE")
    # OCC (priority 11)
    if expected_version != match["version"]:
        raise err(ERR_STALE_VERSION, "expected_match_version is stale")
    # overlap on same match (priority 12)
    for s in db.live_sessions.values():
        if s["match_id"] == mid and s["status"] in _NON_TERMINAL_SESSION:
            s_start = parse_iso(s["starts_at"])
            s_end = parse_iso(s["ends_at"])
            if starts_at < s_end and s_start < ends_at:
                raise err(ERR_SESSION_OVERLAP, "Session overlaps an existing session on this match")
    # therapist double-book buffer (priority 13)
    therapist_id = match["therapist_id"]
    therapist_match_ids = {m["id"] for m in db.matches.values() if m["therapist_id"] == therapist_id}
    for s in db.live_sessions.values():
        if s["match_id"] in therapist_match_ids and s["status"] in _NON_TERMINAL_SESSION:
            s_start = parse_iso(s["starts_at"])
            s_end = parse_iso(s["ends_at"])
            # sessions must be >= 15 min apart: gap between the two intervals must be >= buffer
            # violation when the intervals are closer than buffer (including overlap)
            if starts_at < s_end + THERAPIST_BUFFER and s_start < ends_at + THERAPIST_BUFFER:
                raise err(ERR_THERAPIST_DOUBLE_BOOKED, "Therapist double-booked within 15-minute buffer")
    # credit availability (priority 14): >= 1 AVAILABLE non-expired credit for client
    available = _available_credits(client["id"])
    if not available:
        raise err(ERR_NO_CREDIT, "No available session credit to reserve")
    credit = available[0]
    # create session
    session = {
        **common_create_fields(),
        "match_id": mid,
        "session_credit_id": None,
        "starts_at": data["starts_at"],
        "ends_at": data["ends_at"],
        "status": "SCHEDULED",
        "cancelled_within_window": False,
    }
    db.live_sessions[session["id"]] = session
    # reserve credit
    credit["status"] = "RESERVED"
    credit["live_session_id"] = session["id"]
    session["session_credit_id"] = credit["id"]
    # bump match version
    touch(match)
    return success(serialize.live_session_out(session), status=201)


def _available_credits(client_id):
    now = clock.now()
    result = []
    for c in db.session_credits.values():
        if c["client_id"] != client_id:
            continue
        if c["status"] != "AVAILABLE":
            continue
        if c.get("expires_on") and parse_iso(c["expires_on"]) <= now:
            continue
        result.append(c)
    result.sort(key=lambda c: (c["created_at"], c["_seq"]))
    return result
