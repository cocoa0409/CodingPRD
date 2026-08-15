"""Breach case endpoints: report, open-investigation, substantiate, dismiss, sanction."""

import db
from middleware import require_roles
from response import success, parse_pagination, paginate_list
from routes import make_blueprint
from util import (
    get_payload, require_string, require_enum, optional_string,
    stamp_new, touch,
)
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_FORBIDDEN,
    ERR_INVALID_REQUEST, ERR_REPORTER_CANNOT_ADJUDICATE,
)
from services.serializers import public
from services.cascade import suspend_participant_cascade, ban_participant_cascade

bp = make_blueprint("breaches")

SEVERITY_WEIGHT = {"MINOR": 10, "MAJOR": 25, "CRITICAL": 40}


def _get_case(cid):
    c = db.breach_cases.get(cid)
    if c is None:
        raise_error(ERR_NOT_FOUND, "Breach case not found")
    return c


@bp.route("/playtests/breach-cases", methods=["POST"])
def create_case():
    user_id, role = require_roles("Moderator", "Researcher")
    body = get_payload()
    participant_id = require_string(body, "participant_id")
    study_id = require_string(body, "study_id")
    evidence_summary = require_string(body, "evidence_summary")
    severity = require_enum(body, "severity", ("MINOR", "MAJOR", "CRITICAL"))

    if participant_id not in db.participants:
        raise_error(ERR_NOT_FOUND, "Participant not found")
    if study_id not in db.studies:
        raise_error(ERR_NOT_FOUND, "Study not found")

    rec = {
        "participant_id": participant_id,
        "study_id": study_id,
        "evidence_summary": evidence_summary,
        "severity": severity,
        "reported_by_user_id": user_id,
        "reported_by_role": role,
        "adjudicated_by_user_id": None,
        "sanction_type": None,
        "sanction_note": None,
        "status": "REPORTED",
    }
    stamp_new(rec)
    db.breach_cases[rec["id"]] = rec
    return success(public(rec, "breach_case"), status=201)


@bp.route("/playtests/breach-cases", methods=["GET"])
def list_cases():
    require_roles("ResearchOpsAdmin", "LegalCounsel", "Researcher")
    from flask import request
    limit, offset = parse_pagination(request.args)
    items = list(db.breach_cases.values())
    for param in ("participant_id", "study_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if str(c.get(param)) == v]
    page, pagination = paginate_list(items, limit, offset)
    return success([public(c, "breach_case") for c in page], status=200, pagination=pagination)


@bp.route("/playtests/breach-cases/<cid>", methods=["GET"])
def get_case(cid):
    require_roles("ResearchOpsAdmin", "LegalCounsel", "Researcher")
    c = _get_case(cid)
    return success(public(c, "breach_case"), status=200)


@bp.route("/playtests/breach-cases/<cid>/open-investigation", methods=["POST"])
def open_investigation(cid):
    user_id, _role = require_roles("LegalCounsel")
    c = _get_case(cid)
    if c["status"] != "REPORTED":
        raise_error(ERR_INVALID_STATE, "Case must be REPORTED to open an investigation")
    if user_id == c["reported_by_user_id"]:
        raise_error(ERR_REPORTER_CANNOT_ADJUDICATE,
                    "The reporter cannot adjudicate their own report")
    c["status"] = "UNDER_INVESTIGATION"
    c["adjudicated_by_user_id"] = user_id
    touch(c)
    return success(public(c, "breach_case"), status=200)


@bp.route("/playtests/breach-cases/<cid>/substantiate", methods=["POST"])
def substantiate(cid):
    user_id, _role = require_roles("LegalCounsel")
    c = _get_case(cid)
    if c["status"] != "UNDER_INVESTIGATION":
        raise_error(ERR_INVALID_STATE, "Case must be UNDER_INVESTIGATION to substantiate")
    if user_id != c.get("adjudicated_by_user_id"):
        raise_error(ERR_FORBIDDEN, "Only the adjudicating counsel may substantiate")

    participant = db.participants.get(c["participant_id"])
    if participant is None:
        raise_error(ERR_NOT_FOUND, "Participant not found")

    weight = SEVERITY_WEIGHT[c["severity"]]
    participant["risk_score"] = min(100, participant.get("risk_score", 0) + weight)
    touch(participant)

    c["status"] = "SUBSTANTIATED"
    touch(c)

    # Cascade: if the participant is ACTIVE they become SUSPENDED with the full
    # suspension cascade (bookings cancelled + waitlist promotion; ISSUED keys revoked).
    if participant["status"] == "ACTIVE":
        suspend_participant_cascade(participant)
    return success(public(c, "breach_case"), status=200)


@bp.route("/playtests/breach-cases/<cid>/dismiss", methods=["POST"])
def dismiss(cid):
    user_id, _role = require_roles("LegalCounsel")
    c = _get_case(cid)
    if c["status"] != "UNDER_INVESTIGATION":
        raise_error(ERR_INVALID_STATE, "Case must be UNDER_INVESTIGATION to dismiss")
    if user_id != c.get("adjudicated_by_user_id"):
        raise_error(ERR_FORBIDDEN, "Only the adjudicating counsel may dismiss")
    c["status"] = "DISMISSED"
    touch(c)
    return success(public(c, "breach_case"), status=200)


@bp.route("/playtests/breach-cases/<cid>/sanction", methods=["POST"])
def sanction(cid):
    user_id, _role = require_roles("LegalCounsel")
    c = _get_case(cid)
    if c["status"] != "SUBSTANTIATED":
        raise_error(ERR_INVALID_STATE, "Case must be SUBSTANTIATED to sanction")
    if user_id != c.get("adjudicated_by_user_id"):
        raise_error(ERR_FORBIDDEN, "Only the adjudicating counsel may sanction")
    body = get_payload()
    sanction_type = require_enum(body, "sanction_type", ("WARNING", "BAN"))
    sanction_note = optional_string(body, "sanction_note")

    c["sanction_type"] = sanction_type
    c["sanction_note"] = sanction_note
    c["status"] = "SANCTIONED"
    touch(c)

    if sanction_type == "BAN":
        participant = db.participants.get(c["participant_id"])
        if participant is not None and participant["status"] in ("ACTIVE", "SUSPENDED"):
            ban_participant_cascade(participant)
    # WARNING: participant status unchanged (remains SUSPENDED)
    return success(public(c, "breach_case"), status=200)
