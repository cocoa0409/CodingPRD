"""Refund dispute routes."""

from datetime import timedelta

from flask import Blueprint, g, request

from clock import clock, parse_iso
from config import (
    DISPUTE_MAX_ROUNDS,
    DISPUTE_REASON_CODES,
    DISPUTE_WINDOW_DAYS,
    NON_TERMINAL_DISPUTE_STATES,
    SETTLEMENT_HOLD_HOURS,
)
from db import db, init_common_fields, touch
from errors import APIError
from middleware import require_auth
from response import success_response
from services.sessions import (
    refund_session_from_dispute,
    settle_session_from_dispute_deny,
)
from services.validators import (
    optional_int,
    require_body,
    require_enum,
    require_field,
    require_int,
    require_string,
)

dispute_bp = Blueprint("dispute", __name__)


def _resolve_active_link(parent_id, student_id):
    for link in db.parent_child_links.values():
        if (
            link["parent_id"] == parent_id
            and link["student_id"] == student_id
            and link["link_status"] == "ACTIVE"
        ):
            return link
    return None


def _dispute_accessible_by(dispute, session, user_id, user_role):
    if user_role == "PlatformAdmin":
        return True
    if user_role == "PlatformArbiter":
        return True
    if user_role == "Tutor" and user_id == session["tutor_id"]:
        return True
    if user_role == "Student" and user_id == session["student_id"]:
        return True
    if user_role == "Parent":
        student = db.students.get(session["student_id"])
        if student is None or student["account_type"] != "MINOR":
            return False
        return _resolve_active_link(user_id, session["student_id"]) is not None
    return False


def _ensure_opener(dispute, session):
    """Caller is allowed to act as 'opener' (student or linked parent)."""
    if g.user_role == "Student":
        if g.user_id != session["student_id"]:
            raise APIError("ERR_NOT_AUTHORIZED_FOR_RESOURCE")
        student = db.students[session["student_id"]]
        if student["account_type"] == "MINOR":
            raise APIError("ERR_MINOR_REQUIRES_PARENT")
    elif g.user_role == "Parent":
        student = db.students.get(session["student_id"])
        if student is None or student["account_type"] != "MINOR":
            raise APIError("ERR_MINOR_REQUIRES_PARENT")
        link = _resolve_active_link(g.user_id, session["student_id"])
        if link is None:
            raise APIError("ERR_MINOR_REQUIRES_PARENT")
    else:
        raise APIError("ERR_FORBIDDEN")


@dispute_bp.route("/disputes", methods=["POST"])
@require_auth({"Student", "Parent"})
def open_dispute():
    body = request.get_json(silent=True) or {}
    require_body(body)
    session_id = require_string(body, "session_id")
    reason_code = require_enum(body, "reason_code", DISPUTE_REASON_CODES)
    requested_amount = require_int(body, "requested_amount_cents")

    session = db.sessions.get(session_id)
    if session is None:
        raise APIError("ERR_NOT_FOUND")

    _ensure_opener(None, session)

    # Uniqueness — no non-terminal dispute for this session. PRD §3.7:
    # "At most one non-terminal dispute may exist per session at any
    # time; a second attempt is rejected with ERR_DISPUTE_ALREADY_OPEN."
    # This must be checked before the state gate because a DISPUTED
    # session is, by construction, the result of a prior open dispute;
    # surfacing ERR_DISPUTE_WINDOW_CLOSED there would mask the more
    # specific uniqueness error PRD names.
    for d in db.disputes.values():
        if d["session_id"] == session_id and d["status"] in NON_TERMINAL_DISPUTE_STATES:
            raise APIError("ERR_DISPUTE_ALREADY_OPEN")

    # Window + state
    if session["status"] not in ("COMPLETED", "SETTLED"):
        raise APIError("ERR_DISPUTE_WINDOW_CLOSED")
    end_at = parse_iso(session["end_at"])
    if (clock.now() - end_at) > timedelta(days=DISPUTE_WINDOW_DAYS):
        raise APIError("ERR_DISPUTE_WINDOW_CLOSED")

    # Amount range
    if requested_amount <= 0 or requested_amount > session["charged_amount_cents"]:
        raise APIError("ERR_AMOUNT_OUT_OF_RANGE")

    opened_by_role = g.user_role  # 'Student' or 'Parent'
    dispute = init_common_fields({
        "session_id": session_id,
        "opened_by_role": opened_by_role,
        "opened_by_user_id": g.user_id,
        "reason_code": reason_code,
        "requested_amount_cents": requested_amount,
        "status": "OPEN",
        "round_count": 0,
        "arbitrated_by": None,
        "resolved_refund_cents": None,
        "counter_amount_cents": None,
    })
    db.disputes[dispute["id"]] = dispute

    # Cascade: COMPLETED -> DISPUTED. SETTLED stays.
    if session["status"] == "COMPLETED":
        session["status"] = "DISPUTED"
        touch(session)

    return success_response(dispute, status=201)


def _get_dispute(dispute_id):
    dispute = db.disputes.get(dispute_id)
    if dispute is None:
        raise APIError("ERR_NOT_FOUND")
    session = db.sessions.get(dispute["session_id"])
    return dispute, session


@dispute_bp.route("/disputes/<dispute_id>", methods=["GET"])
@require_auth({"Student", "Parent", "Tutor", "PlatformArbiter", "PlatformAdmin"})
def get_dispute(dispute_id):
    dispute, session = _get_dispute(dispute_id)
    if not _dispute_accessible_by(dispute, session, g.user_id, g.user_role):
        raise APIError("ERR_NOT_AUTHORIZED_FOR_RESOURCE")
    return success_response(dispute, status=200)


@dispute_bp.route("/disputes/<dispute_id>/respond", methods=["POST"])
@require_auth({"Tutor"})
def respond_dispute(dispute_id):
    dispute, session = _get_dispute(dispute_id)
    if g.user_id != session["tutor_id"]:
        raise APIError("ERR_NOT_AUTHORIZED_FOR_RESOURCE")
    if dispute["status"] != "OPEN":
        raise APIError("ERR_INVALID_STATE")
    dispute["status"] = "TUTOR_RESPONDED"
    touch(dispute)
    return success_response(dispute, status=200)


@dispute_bp.route("/disputes/<dispute_id>/counter", methods=["POST"])
@require_auth({"Tutor"})
def counter_dispute(dispute_id):
    dispute, session = _get_dispute(dispute_id)
    if g.user_id != session["tutor_id"]:
        raise APIError("ERR_NOT_AUTHORIZED_FOR_RESOURCE")
    if dispute["status"] != "TUTOR_RESPONDED":
        raise APIError("ERR_INVALID_STATE")
    body = request.get_json(silent=True) or {}
    require_body(body)
    counter_amount = require_int(body, "counter_amount_cents")
    if counter_amount < 0 or counter_amount > dispute["requested_amount_cents"]:
        raise APIError("ERR_AMOUNT_OUT_OF_RANGE")
    if dispute["round_count"] >= DISPUTE_MAX_ROUNDS:
        raise APIError("ERR_INVALID_STATE")
    dispute["counter_amount_cents"] = counter_amount
    dispute["round_count"] += 1
    dispute["status"] = "COUNTER_PROPOSED"
    touch(dispute)
    return success_response(dispute, status=200)


@dispute_bp.route("/disputes/<dispute_id>/accept", methods=["POST"])
@require_auth({"Student", "Parent"})
def accept_counter(dispute_id):
    dispute, session = _get_dispute(dispute_id)
    _ensure_opener(dispute, session)
    if dispute["status"] != "COUNTER_PROPOSED":
        raise APIError("ERR_INVALID_STATE")
    counter = dispute.get("counter_amount_cents")
    if counter is None:
        counter = 0
    # Bound (defensive — should already be bounded at counter time)
    if counter < 0 or counter > dispute["requested_amount_cents"]:
        raise APIError("ERR_AMOUNT_OUT_OF_RANGE")
    dispute["resolved_refund_cents"] = counter
    dispute["status"] = "RESOLVED_REFUND"
    touch(dispute)
    # Cascade session DISPUTED -> REFUNDED
    if session["status"] == "DISPUTED":
        refund_session_from_dispute(session, dispute)
    return success_response(dispute, status=200)


@dispute_bp.route("/disputes/<dispute_id>/reopen", methods=["POST"])
@require_auth({"Student", "Parent"})
def reopen_dispute(dispute_id):
    dispute, session = _get_dispute(dispute_id)
    _ensure_opener(dispute, session)
    if dispute["status"] != "COUNTER_PROPOSED":
        raise APIError("ERR_INVALID_STATE")
    if dispute["round_count"] >= DISPUTE_MAX_ROUNDS:
        raise APIError("ERR_INVALID_STATE")
    dispute["status"] = "OPEN"
    touch(dispute)
    return success_response(dispute, status=200)


@dispute_bp.route("/disputes/<dispute_id>/escalate", methods=["POST"])
@require_auth({"Student", "Parent", "PlatformAdmin"})
def escalate_dispute(dispute_id):
    dispute, session = _get_dispute(dispute_id)
    if g.user_role in ("Student", "Parent"):
        _ensure_opener(dispute, session)
    if dispute["status"] not in ("OPEN", "TUTOR_RESPONDED"):
        raise APIError("ERR_INVALID_STATE")
    # Allowed iff round_count >= 3 OR age >= 14 days
    age = clock.now() - parse_iso(dispute["created_at"])
    if dispute["round_count"] < DISPUTE_MAX_ROUNDS and age < timedelta(days=14):
        raise APIError("ERR_ESCALATION_NOT_ALLOWED")
    dispute["status"] = "ARBITRATION"
    touch(dispute)
    return success_response(dispute, status=200)


@dispute_bp.route("/disputes/<dispute_id>/arbitrate", methods=["POST"])
@require_auth({"PlatformArbiter"})
def arbitrate_dispute(dispute_id):
    dispute, session = _get_dispute(dispute_id)
    if dispute["status"] != "ARBITRATION":
        raise APIError("ERR_INVALID_STATE")

    # Segregation: arbiter cannot be tutor/student/linked parent
    if g.user_id == session["tutor_id"]:
        raise APIError("ERR_SEGREGATION_VIOLATION")
    if g.user_id == session["student_id"]:
        raise APIError("ERR_SEGREGATION_VIOLATION")
    student = db.students.get(session["student_id"])
    if student and student["account_type"] == "MINOR" and student.get("parent_id") == g.user_id:
        raise APIError("ERR_SEGREGATION_VIOLATION")

    body = request.get_json(silent=True) or {}
    require_body(body)
    decision = require_enum(body, "decision", {"REFUND", "DENY"})
    refund_amount = optional_int(body, "refund_amount_cents")

    dispute["arbitrated_by"] = g.user_id
    if decision == "REFUND":
        if refund_amount is None:
            # If unspecified, use the full requested amount
            refund_amount = dispute["requested_amount_cents"]
        if refund_amount < 0:
            refund_amount = 0
        if refund_amount > dispute["requested_amount_cents"]:
            refund_amount = dispute["requested_amount_cents"]
        dispute["resolved_refund_cents"] = refund_amount
        dispute["status"] = "RESOLVED_REFUND"
        touch(dispute)
        if session["status"] == "DISPUTED":
            refund_session_from_dispute(session, dispute)
    else:  # DENY
        dispute["resolved_refund_cents"] = 0
        dispute["status"] = "RESOLVED_DENY"
        touch(dispute)
        if session["status"] == "DISPUTED":
            settle_session_from_dispute_deny(session)

    return success_response(dispute, status=200)


@dispute_bp.route("/disputes/<dispute_id>/withdraw", methods=["POST"])
@require_auth({"Student", "Parent"})
def withdraw_dispute(dispute_id):
    dispute, session = _get_dispute(dispute_id)
    _ensure_opener(dispute, session)
    if dispute["status"] not in ("OPEN", "COUNTER_PROPOSED"):
        raise APIError("ERR_INVALID_STATE")
    dispute["status"] = "WITHDRAWN"
    touch(dispute)
    # Cascade session
    if session["status"] == "DISPUTED":
        end_at = parse_iso(session["end_at"])
        elapsed_hours = (clock.now() - end_at).total_seconds() / 3600.0
        if elapsed_hours >= SETTLEMENT_HOLD_HOURS:
            settle_session_from_dispute_deny(session)
        else:
            session["status"] = "COMPLETED"
            touch(session)
    return success_response(dispute, status=200)
