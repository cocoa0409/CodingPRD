"""/_clock/advance — Simulated clock test-driving endpoint.

Triggers:
- PA APPROVED -> EXPIRED when clock_now() >= effective_end
- Member.ytd_* reset and benefit_year_start advance when crossing year boundary
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import Blueprint

from ..auth import require_roles
from ..envelope import success
from ..errors import APIError, ERR_VALIDATION
from ..store import STORE
from ..validation import get_json_body, require_field, as_int

bp = Blueprint("clock", __name__)


def _parse_ts(ts_str: str) -> datetime:
    # Accept the format produced by Store.fmt_ts: YYYY-MM-DDTHH:MM:SS.sssZ
    if ts_str.endswith("Z"):
        ts_str = ts_str[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _run_auto_transitions() -> None:
    """Evaluate auto-transitions after a clock change."""
    now = STORE.clock.now()

    # Auto-expire PAs whose effective_end has been reached.
    for pa in STORE.prior_authorizations.values():
        if pa["status"] == "APPROVED" and pa.get("effective_end"):
            eff_end = _parse_ts(pa["effective_end"])
            if now >= eff_end:
                pa["status"] = "EXPIRED"
                STORE.bump(pa)

    # Rollover benefit year for any member whose benefit_year_start + 1y <= now.
    for member in STORE.members.values():
        bys = _parse_ts(member["benefit_year_start"])
        # Repeatedly advance benefit_year_start in 365-day chunks while now has crossed it.
        # PRD §2.11: "benefit_year_start plus one year is at or earlier than the new clock time"
        # We interpret "one year" as 365 days for consistency with deterministic day arithmetic.
        rolled = False
        while now >= bys + timedelta(days=365):
            bys = bys + timedelta(days=365)
            rolled = True
        if rolled:
            member["benefit_year_start"] = STORE.fmt_ts(bys)
            member["ytd_deductible_paid_cents"] = 0
            member["ytd_oop_paid_cents"] = 0
            STORE.bump(member)


@bp.post("/_clock/advance")
@require_roles("PBMAdmin")
def advance_clock():
    body = get_json_body()
    seconds_val = require_field(body, "seconds")
    seconds = as_int(seconds_val, "seconds")
    if seconds < 0:
        raise APIError(ERR_VALIDATION, "seconds must be >= 0", 422)
    with STORE.lock:
        STORE.clock.advance(seconds)
        _run_auto_transitions()
        return success({"clock_now": STORE.now_ts()})
