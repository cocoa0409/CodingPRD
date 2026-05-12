"""System endpoints: logical clock + health."""
from flask import Blueprint, request

from db import lock
from errors import err
from middleware import require_auth
from response import success
from services.validation import require_dict, required_str
from services.sweep import run_time_sweep
from clock import parse_iso, set_now, now, now_iso

bp = Blueprint("system", __name__)


@bp.route("/_health", methods=["GET"])
def health():
    return success({"status": "ok"})


@bp.route("/_clock", methods=["GET"])
@require_auth(roles=["PlatformAdmin", "RevenueAnalyst", "RevenueManager",
                     "ReservationsAgent", "FrontDeskClerk", "HousekeepingStaff", "Guest"])
def get_clock():
    return success({"now": now_iso()})


@bp.route("/_clock/advance", methods=["POST"])
@require_auth(roles=["PlatformAdmin"])
def advance_clock():
    body = require_dict(request.get_json(silent=True))
    raw = required_str(body, "new_now")
    try:
        new_now = parse_iso(raw)
    except ValueError as e:
        raise err("ERR_INVALID_INPUT", str(e))
    with lock():
        set_now(new_now)
        transitions = []
        # Run sweep until quiescent (one pass should be enough; do up to 3 to be safe)
        for _ in range(3):
            before = len(transitions)
            run_time_sweep(transitions)
            if len(transitions) == before:
                break
    return success({"now": now_iso(), "transitions_triggered": transitions})
