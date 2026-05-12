"""Test-only system endpoints: clock advance + sweep."""
from datetime import datetime, timezone

from flask import Blueprint, g

import db
from clock import set_now, parse_iso, now
from errors import err
from middleware import require_auth
from response import success
from services.scholarship_lifecycle import (
    transition_scholarship, can_advance_to_open, can_advance_to_reviewing,
    can_advance_to_finalized,
)
from services.validation import get_body


bp = Blueprint("system", __name__)


@bp.route("/_test/reset", methods=["POST"])
def test_reset():
    """Test-only hook to wipe all in-memory state. Not part of PRD §4."""
    db.reset_all()
    # Reset logical clock to real now so subsequent tests start fresh.
    set_now(datetime.now(tz=timezone.utc))
    return success({}, 200)


@bp.route("/_clock/advance", methods=["POST"])
@require_auth(roles={"SchoolAdmin"})
def clock_advance():
    body = get_body()
    to = body.get("to")
    if to is None:
        raise err("ERR_BAD_REQUEST", "to is required")
    try:
        dt = parse_iso(to)
    except ValueError as e:
        raise err("ERR_BAD_REQUEST", f"invalid to: {e}")
    set_now(dt)
    return success({}, 200)


@bp.route("/_sweep/run", methods=["POST"])
@require_auth(roles={"SchoolAdmin"})
def run_sweep():
    """Run pending auto-transitions for every scholarship whose window has elapsed.

    Per the PRD this transitions:
      * DRAFT → OPEN when now() >= application_window_start (preconditions still apply)
      * OPEN → REVIEWING when now() >= application_window_end
      * ANNOUNCED → FINALIZED when now() >= announcement_window_end (and no PENDING objection)
    Runs in fixed-point fashion: keep sweeping until no further transitions happen.
    """
    actor_role = g.user_role
    actor_id = g.user_id

    progress = True
    iters = 0
    while progress and iters < 10:
        progress = False
        iters += 1
        for s in list(db.scholarships.values()):
            target = _maybe_target(s)
            if target is None:
                continue
            try:
                transition_scholarship(s, target, actor_role=actor_role, actor_id=actor_id)
                progress = True
            except Exception:
                # Skip silently — sweep is best-effort.
                pass
    return success({}, 200)


def _maybe_target(s):
    status = s["status"]
    n = now()
    if status == "DRAFT":
        try:
            if n >= parse_iso(s["application_window_start"]):
                return "OPEN"
        except Exception:
            return None
    elif status == "OPEN":
        try:
            if n >= parse_iso(s["application_window_end"]):
                return "REVIEWING"
        except Exception:
            return None
    elif status == "ANNOUNCED":
        try:
            if n >= parse_iso(s["announcement_window_end"]):
                return "FINALIZED"
        except Exception:
            return None
    return None
