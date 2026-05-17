"""Clock control endpoints — test-driving the logical clock."""
from __future__ import annotations

from flask import Blueprint

from ..auth import (
    ROLE_AUDITOR,
    ROLE_COMPLIANCE,
    ROLE_CUSTODIAN,
    ROLE_PARTICIPANT,
    require_roles,
)
from ..clock import clock, current_date, current_year, date_iso
from ..helpers import assert_integer, require_json_object
from ..responses import ok
from ..services.ledger import run_forfeit_sweep, run_year_roll
from ..store import store

bp = Blueprint("clock", __name__)


def _clock_state(extra: dict | None = None) -> dict:
    body = {
        "current_date": current_date().isoformat(),
        "clock_year": current_year(),
    }
    if extra:
        body.update(extra)
    return body


@bp.post("/_clock/advance")
@require_roles(ROLE_AUDITOR, ROLE_CUSTODIAN, ROLE_COMPLIANCE)
def advance(**_kw):
    body = require_json_object()
    days = assert_integer(body.get("days"), "days", minimum=0)
    with store().lock:
        clock.advance_days(days)  # type: ignore[arg-type]
        forfeited = run_forfeit_sweep()
        return ok(_clock_state({"forfeited_claim_ids": forfeited}))


@bp.post("/_clock/advance-year")
@require_roles(ROLE_AUDITOR, ROLE_CUSTODIAN, ROLE_COMPLIANCE)
def advance_year(**_kw):
    require_json_object()  # ignored body
    with store().lock:
        summary = run_year_roll()
        return ok(_clock_state(summary))


@bp.get("/_clock")
@require_roles(ROLE_AUDITOR, ROLE_CUSTODIAN, ROLE_COMPLIANCE, ROLE_PARTICIPANT)
def read_clock(**_kw):
    return ok(_clock_state())
