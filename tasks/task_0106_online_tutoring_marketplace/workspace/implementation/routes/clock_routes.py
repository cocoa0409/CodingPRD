"""Test-driving clock endpoints + sweeps."""

from datetime import timedelta

from flask import Blueprint, request

from clock import clock, parse_iso
from config import (
    DISPUTE_AUTO_ESCALATE_DAYS,
    NON_TERMINAL_DISPUTE_STATES,
    SETTLEMENT_HOLD_HOURS,
)
from db import db, touch
from errors import APIError
from middleware import require_auth
from response import success_response
from services.sessions import settle_session
from services.validators import require_body, require_string
from services.verification import expire_due_credentials

clock_bp = Blueprint("clock", __name__)


def _sweep_in_progress():
    now = clock.now()
    for s in list(db.sessions.values()):
        if s["status"] != "CONFIRMED":
            continue
        start_at = parse_iso(s["start_at"])
        end_at = parse_iso(s["end_at"])
        if start_at <= now < end_at:
            s["status"] = "IN_PROGRESS"
            touch(s)


def _sweep_settle_completed():
    now = clock.now()
    for s in sorted(list(db.sessions.values()), key=lambda r: r["id"]):
        if s["status"] != "COMPLETED":
            continue
        end_at = parse_iso(s["end_at"])
        elapsed_hours = (now - end_at).total_seconds() / 3600.0
        if elapsed_hours < SETTLEMENT_HOLD_HOURS:
            continue
        # No active dispute attached
        has_active = any(
            d["session_id"] == s["id"] and d["status"] in NON_TERMINAL_DISPUTE_STATES
            for d in db.disputes.values()
        )
        if has_active:
            continue
        settle_session(s)


def _sweep_dispute_escalation():
    now = clock.now()
    threshold = timedelta(days=DISPUTE_AUTO_ESCALATE_DAYS)
    for d in list(db.disputes.values()):
        if d["status"] not in ("OPEN", "TUTOR_RESPONDED"):
            continue
        created = parse_iso(d["created_at"])
        if (now - created) >= threshold:
            d["status"] = "ARBITRATION"
            touch(d)


def run_clock_sweeps():
    # Order: credential expiry first (may cancel future sessions), then in-progress,
    # then settle completed (only those without active disputes), then auto-escalate.
    expire_due_credentials()
    _sweep_in_progress()
    _sweep_settle_completed()
    _sweep_dispute_escalation()


@clock_bp.route("/_clock/advance", methods=["POST"])
@require_auth({"PlatformAdmin"})
def clock_advance():
    body = request.get_json(silent=True) or {}
    require_body(body)
    target = require_string(body, "to_iso8601")
    parse_iso(target)  # validate format
    clock.advance_to(target)
    run_clock_sweeps()
    return success_response({"now": clock.now_iso()}, status=200)


@clock_bp.route("/_clock", methods=["GET"])
@require_auth({"PlatformAdmin", "Tutor", "Student", "Parent", "CredentialVerifier", "PlatformArbiter"})
def clock_read():
    return success_response({"now": clock.now_iso()}, status=200)
