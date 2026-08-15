"""Logical clock control (PRD 2.7) — the only endpoint outside /eqip."""
from flask import Blueprint

from db import STORE
from errors import ApiError
from helpers import as_dt, body, req_field
from middleware import require_roles
from response import ok
from services.sweep import run_sweep
from util import fmt_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("ProgramAdmin")
def set_current_utc(_uid, _role):
    data = body()
    target = as_dt(req_field(data, "to_iso8601"), "to_iso8601")
    if target < STORE.clock:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "the logical clock may only move forward",
        )
    STORE.clock = target
    run_sweep()
    return ok({"current_utc": fmt_dt(STORE.clock)})
