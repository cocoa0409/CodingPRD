"""Session endpoints (hold/release/complete/cancel/mark-no-show/excuse)."""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_UNAUTHORIZED,
    ERR_TEMPORAL_INVALID,
)
from middleware import require_roles
from response import success_object, success_list
from services import domain
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    optional_string,
    paginate,
    parse_pagination,
    require_bool,
    sort_by_created_at,
)

bp = Blueprint("sessions", __name__)


def _get_session_or_404(session_id: str) -> dict:
    s = db.sessions.get(session_id)
    if s is None:
        raise_err(ERR_NOT_FOUND, "Session id does not exist")
    return s


@bp.route("/ucc/sessions/<session_id>", methods=["GET"])
@require_roles("FrontDesk", "Counselor", "ClinicalDirector")
def get_session(session_id: str, _user_id: str, _role: str):
    s = _get_session_or_404(session_id)
    return success_object(serialize(s))


@bp.route("/ucc/sessions", methods=["GET"])
@require_roles("FrontDesk", "Counselor", "ClinicalDirector")
def list_sessions(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.sessions.values()))
    items = apply_filters(items, ["episode_id", "counselor_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/ucc/sessions/<session_id>/hold", methods=["POST"])
@require_roles("FrontDesk")
def hold_session(session_id: str, _user_id: str, _role: str):
    s = _get_session_or_404(session_id)
    if s.get("status") != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "Session is not SCHEDULED")
    s["status"] = "HELD"
    db.touch(s)
    return success_object(serialize(s))


@bp.route("/ucc/sessions/<session_id>/release-hold", methods=["POST"])
@require_roles("FrontDesk")
def release_hold(session_id: str, _user_id: str, _role: str):
    s = _get_session_or_404(session_id)
    if s.get("status") != "HELD":
        raise_err(ERR_INVALID_STATE, "Session is not HELD")
    s["status"] = "SCHEDULED"
    db.touch(s)
    return success_object(serialize(s))


def _complete_session(s: dict) -> dict:
    episode = db.episodes.get(s["episode_id"])
    if episode is None:
        raise_err(ERR_NOT_FOUND, "Linked episode does not exist")
    student = db.students.get(episode["student_id"])
    if student is None:
        raise_err(ERR_NOT_FOUND, "Linked student does not exist")
    # Billing
    billed = domain.session_billing_amount(
        student.get("funding_model", "STUDENT_FEE"),
        "COMPLETED",
        int(s.get("duration_minutes", 0)),
    )
    s["status"] = "COMPLETED"
    s["billed_amount_cents"] = billed
    db.touch(s)
    # Consumption ledger recount + possible exhaustion cascade.
    domain.recompute_episode_after_consumption_change(episode)
    return s


@bp.route("/ucc/sessions/<session_id>/complete", methods=["POST"])
@require_roles("Counselor", "ClinicalDirector")
def complete_session(session_id: str, _user_id: str, _role: str):
    s = _get_session_or_404(session_id)
    # Ownership (p2.5): Counselor must own session; CD bypasses.
    if _role == "Counselor" and s.get("counselor_id") != _user_id:
        raise_err(ERR_UNAUTHORIZED, "Counselor may only complete own sessions")
    if s.get("status") not in ("SCHEDULED", "HELD"):
        raise_err(ERR_INVALID_STATE, "Session is not in SCHEDULED or HELD")
    # Temporal: logical clock >= starts_at
    start = db.parse_iso(s["starts_at"])
    if db.clock() < start:
        raise_err(ERR_TEMPORAL_INVALID, "Cannot complete before starts_at")
    return success_object(serialize(_complete_session(s)))


@bp.route("/ucc/sessions/<session_id>/cancel", methods=["POST"])
@require_roles("FrontDesk")
def cancel_session(session_id: str, _user_id: str, _role: str):
    s = _get_session_or_404(session_id)
    body = get_json_body()
    cancellation_reason = optional_string(body, "cancellation_reason")
    if s.get("status") != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "Session is not SCHEDULED")

    episode = db.episodes.get(s["episode_id"])
    if episode is None:
        raise_err(ERR_NOT_FOUND, "Linked episode does not exist")
    student = db.students.get(episode["student_id"])
    if student is None:
        raise_err(ERR_NOT_FOUND, "Linked student does not exist")

    # Policy window classification. Use the published policy for the episode's
    # term; if none, no late window (cancellation is timely).
    policy = domain.published_policy_for_term(episode.get("academic_term"))
    window_hours = int(policy.get("late_cancel_window_hours", 0)) if policy else 0

    start = db.parse_iso(s["starts_at"])
    now = db.clock()
    hours_until = (start - now).total_seconds() / 3600.0

    if hours_until >= window_hours:
        s["status"] = "CANCELLED_TIMELY"
        s["cancellation_reason"] = cancellation_reason
        db.touch(s)
    else:
        s["status"] = "CANCELLED_LATE"
        s["cancellation_reason"] = cancellation_reason
        s["billed_amount_cents"] = domain.session_billing_amount(
            student.get("funding_model", "STUDENT_FEE"),
            "CANCELLED_LATE",
            int(s.get("duration_minutes", 0)),
        )
        db.touch(s)
    return success_object(serialize(s))


@bp.route("/ucc/sessions/<session_id>/mark-no-show", methods=["POST"])
@require_roles("Counselor", "ClinicalDirector")
def mark_no_show(session_id: str, _user_id: str, _role: str):
    s = _get_session_or_404(session_id)
    # Ownership (p2.5)
    if _role == "Counselor" and s.get("counselor_id") != _user_id:
        raise_err(ERR_UNAUTHORIZED, "Counselor may only mark no-show on own sessions")
    body = get_json_body()
    chargeable = require_bool(body, "chargeable")
    if s.get("status") != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "Session is not SCHEDULED")
    start = db.parse_iso(s["starts_at"])
    if not (db.clock() > start):
        raise_err(ERR_TEMPORAL_INVALID, "Logical clock must be past starts_at")

    episode = db.episodes.get(s["episode_id"])
    if episode is None:
        raise_err(ERR_NOT_FOUND, "Linked episode does not exist")
    student = db.students.get(episode["student_id"])
    if student is None:
        raise_err(ERR_NOT_FOUND, "Linked student does not exist")

    if chargeable:
        s["status"] = "NO_SHOW_CHARGED"
        s["billed_amount_cents"] = domain.session_billing_amount(
            student.get("funding_model", "STUDENT_FEE"),
            "NO_SHOW_CHARGED",
            int(s.get("duration_minutes", 0)),
        )
        db.touch(s)
        # Consumption recount + possible exhaustion cascade.
        domain.recompute_episode_after_consumption_change(episode)
        # Strike increment + posture recompute (with possible SUSPENDED cascade).
        domain.recompute_strikes_and_posture(student)
    else:
        s["status"] = "NO_SHOW_EXCUSED"
        s["billed_amount_cents"] = 0
        db.touch(s)
    return success_object(serialize(s))


@bp.route("/ucc/sessions/<session_id>/excuse", methods=["POST"])
@require_roles("ClinicalDirector")
def excuse_session(session_id: str, _user_id: str, _role: str):
    s = _get_session_or_404(session_id)
    if s.get("status") != "NO_SHOW_CHARGED":
        raise_err(ERR_INVALID_STATE, "Session is not NO_SHOW_CHARGED")
    episode = db.episodes.get(s["episode_id"])
    if episode is None:
        raise_err(ERR_NOT_FOUND, "Linked episode does not exist")
    student = db.students.get(episode["student_id"])
    if student is None:
        raise_err(ERR_NOT_FOUND, "Linked student does not exist")

    s["status"] = "NO_SHOW_EXCUSED"
    s["billed_amount_cents"] = 0
    db.touch(s)

    # Compensation: consumption recount (drops by 1).
    domain.recompute_episode_after_consumption_change(episode)
    # Strike decrement + posture recompute.
    domain.recompute_strikes_and_posture(student)
    return success_object(serialize(s))
