"""Survey instrument & response endpoints."""

import db
from middleware import require_roles
from response import success, parse_pagination, paginate_list
from routes import make_blueprint
from util import (
    get_payload, require_string, require_array, require_number,
    stamp_new, touch,
)
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_FORBIDDEN,
    ERR_INVALID_REQUEST, ERR_INSTRUMENT_ALREADY_PUBLISHED,
    ERR_DUPLICATE_RESPONSE, ERR_ATTENDANCE_REQUIRED, ERR_UNKNOWN_QUESTION,
)
from services.serializers import public
from services.calculations import survey_weighted_score

bp = make_blueprint("surveys")


def _get_instrument(iid):
    i = db.instruments.get(iid)
    if i is None:
        raise_error(ERR_NOT_FOUND, "Survey instrument not found")
    return i


def _get_response(rid):
    r = db.responses.get(rid)
    if r is None:
        raise_error(ERR_NOT_FOUND, "Survey response not found")
    return r


@bp.route("/playtests/survey-instruments", methods=["POST"])
def create_instrument():
    require_roles("Researcher")
    body = get_payload()
    study_id = require_string(body, "study_id")
    title = require_string(body, "title")
    questions = require_array(body, "questions")
    pass_threshold = require_number(body, "pass_threshold", minimum=0, maximum=100)
    if study_id not in db.studies:
        raise_error(ERR_NOT_FOUND, "Study not found")

    seen_keys = set()
    for q in questions:
        if not isinstance(q, dict):
            raise_error(ERR_INVALID_REQUEST, "Each question must be an object")
        qk = q.get("question_key")
        weight = q.get("weight")
        max_points = q.get("max_points")
        if not isinstance(qk, str) or not qk:
            raise_error(ERR_INVALID_REQUEST, "question_key must be a non-empty string")
        if qk in seen_keys:
            raise_error(ERR_INVALID_REQUEST, "question_key must be unique within the instrument")
        seen_keys.add(qk)
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or weight <= 0:
            raise_error(ERR_INVALID_REQUEST, "question weight must be > 0")
        if isinstance(max_points, bool) or not isinstance(max_points, (int, float)) or max_points < 1:
            raise_error(ERR_INVALID_REQUEST, "question max_points must be >= 1")

    rec = {
        "study_id": study_id,
        "title": title,
        "questions": [dict(q) for q in questions],
        "pass_threshold": pass_threshold,
        "status": "DRAFT",
    }
    stamp_new(rec)
    db.instruments[rec["id"]] = rec
    return success(public(rec, "instrument"), status=201)


@bp.route("/playtests/survey-instruments", methods=["GET"])
def list_instruments():
    require_roles("ResearchOpsAdmin", "Researcher", "Participant")
    from flask import request
    limit, offset = parse_pagination(request.args)
    items = list(db.instruments.values())
    for param in ("study_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [i for i in items if str(i.get(param)) == v]
    page, pagination = paginate_list(items, limit, offset)
    return success([public(i, "instrument") for i in page], status=200, pagination=pagination)


@bp.route("/playtests/survey-instruments/<iid>", methods=["GET"])
def get_instrument(iid):
    require_roles("ResearchOpsAdmin", "Researcher", "Participant")
    i = _get_instrument(iid)
    return success(public(i, "instrument"), status=200)


@bp.route("/playtests/survey-instruments/<iid>/publish", methods=["POST"])
def publish_instrument(iid):
    require_roles("Researcher")
    instrument = _get_instrument(iid)
    if instrument["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "Instrument must be DRAFT to publish")
    for other in db.instruments.values():
        if (other["study_id"] == instrument["study_id"] and other["id"] != instrument["id"]
                and other["status"] == "PUBLISHED"):
            raise_error(ERR_INSTRUMENT_ALREADY_PUBLISHED,
                        "Another instrument for this study is PUBLISHED")
    instrument["status"] = "PUBLISHED"
    touch(instrument)
    return success(public(instrument, "instrument"), status=200)


@bp.route("/playtests/survey-instruments/<iid>/retire", methods=["POST"])
def retire_instrument(iid):
    require_roles("Researcher")
    instrument = _get_instrument(iid)
    if instrument["status"] != "PUBLISHED":
        raise_error(ERR_INVALID_STATE, "Instrument must be PUBLISHED to retire")
    instrument["status"] = "RETIRED"
    touch(instrument)
    return success(public(instrument, "instrument"), status=200)


# ---------------------------------------------------------------------------
# Survey responses
# ---------------------------------------------------------------------------

@bp.route("/playtests/survey-responses", methods=["POST"])
def create_response():
    user_id, _role = require_roles("Participant")
    body = get_payload()
    instrument_id = require_string(body, "instrument_id")
    session_id = require_string(body, "session_id")
    answers = require_array(body, "answers")

    instrument = db.instruments.get(instrument_id)
    if instrument is None:
        raise_error(ERR_NOT_FOUND, "Survey instrument not found")
    session = db.sessions.get(session_id)
    if session is None:
        raise_error(ERR_NOT_FOUND, "Session not found")
    participant = db.participants.get(user_id)
    if participant is None:
        raise_error(ERR_NOT_FOUND, "Participant not found")

    q_by_key = {q["question_key"]: q for q in (instrument.get("questions") or [])}
    for a in answers:
        if not isinstance(a, dict):
            raise_error(ERR_INVALID_REQUEST, "Each answer must be an object")
        qk = a.get("question_key")
        points = a.get("points")
        if not isinstance(qk, str):
            raise_error(ERR_INVALID_REQUEST, "answer question_key must be a string")
        q = q_by_key.get(qk)
        if isinstance(points, bool) or not isinstance(points, (int, float)):
            raise_error(ERR_INVALID_REQUEST, "answer points must be a number")
        if q is not None and not (0 <= points <= q["max_points"]):
            raise_error(ERR_INVALID_REQUEST,
                        "answer points must be between 0 and the question's max_points")

    # Uniqueness: one response per (instrument, session, participant)
    for r in db.responses.values():
        if (r["instrument_id"] == instrument_id and r["session_id"] == session_id
                and r["participant_id"] == participant["id"]):
            raise_error(ERR_DUPLICATE_RESPONSE,
                        "A response already exists for this instrument, session, and participant")

    rec = {
        "instrument_id": instrument_id,
        "session_id": session_id,
        "participant_id": participant["id"],
        "answers": [dict(a) for a in answers],
        "weighted_score": None,
        "score_pct": None,
        "passed": None,
        "status": "DRAFT",
        "submitted_at": None,
    }
    stamp_new(rec)
    db.responses[rec["id"]] = rec
    return success(public(rec, "response"), status=201)


@bp.route("/playtests/survey-responses", methods=["GET"])
def list_responses():
    require_roles("ResearchOpsAdmin", "Researcher", "Participant")
    from flask import request
    limit, offset = parse_pagination(request.args)
    items = list(db.responses.values())
    for param in ("instrument_id", "session_id", "participant_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if str(r.get(param)) == v]
    page, pagination = paginate_list(items, limit, offset)
    return success([public(r, "response") for r in page], status=200, pagination=pagination)


@bp.route("/playtests/survey-responses/<rid>", methods=["GET"])
def get_response(rid):
    require_roles("ResearchOpsAdmin", "Researcher", "Participant")
    r = _get_response(rid)
    return success(public(r, "response"), status=200)


@bp.route("/playtests/survey-responses/<rid>/submit", methods=["POST"])
def submit_response(rid):
    user_id, _role = require_roles("Participant")
    r = _get_response(rid)
    if user_id != r["participant_id"]:
        raise_error(ERR_FORBIDDEN, "Only the owning participant may submit")
    if r["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "Response must be DRAFT to submit")
    instrument = db.instruments.get(r["instrument_id"])
    if instrument is None:
        raise_error(ERR_NOT_FOUND, "Survey instrument not found")
    if instrument["status"] != "PUBLISHED":
        raise_error(ERR_INVALID_STATE, "Instrument must be PUBLISHED at submit time")

    # Referential gate: ATTENDED booking for (session, participant)
    attended = any(
        b for b in db.bookings.values()
        if b["session_id"] == r["session_id"]
        and b["participant_id"] == r["participant_id"]
        and b["status"] == "ATTENDED"
    )
    if not attended:
        raise_error(ERR_ATTENDANCE_REQUIRED, "An ATTENDED booking is required to submit")

    # Every answered question_key must exist in the instrument
    q_keys = {q["question_key"] for q in (instrument.get("questions") or [])}
    for a in (r.get("answers") or []):
        if a.get("question_key") not in q_keys:
            raise_error(ERR_UNKNOWN_QUESTION, "Answer references an unknown question_key")

    weighted_score, score_pct, passed = survey_weighted_score(r, instrument)
    r["weighted_score"] = weighted_score
    r["score_pct"] = score_pct
    r["passed"] = passed
    r["submitted_at"] = db.clock.now_iso()
    r["status"] = "SUBMITTED"
    touch(r)
    return success(public(r, "response"), status=200)
