"""Test-only / system routes: clock + sweep."""
from __future__ import annotations

from flask import Blueprint, request

from auth import require_roles
from constants import ROLE_PLATFORM_ADMIN
from response import ok_empty
from services.sweep import run_sweep, run_year_rollover
from store import store
from utils import get_body, parse_iso, require_str

bp = Blueprint("system", __name__)


@bp.post("/_clock/advance")
@require_roles(ROLE_PLATFORM_ADMIN)
def post_clock_advance():
    body = get_body(request)
    to_timestamp = require_str(body, "to_timestamp")
    dt = parse_iso(to_timestamp)
    with store.lock:
        store.set_clock(dt)
    return ok_empty()


@bp.post("/_sweep/run")
@require_roles(ROLE_PLATFORM_ADMIN)
def post_sweep_run():
    with store.lock:
        run_sweep()
    return ok_empty()


@bp.post("/_sweep/year-rollover")
@require_roles(ROLE_PLATFORM_ADMIN)
def post_year_rollover():
    with store.lock:
        run_year_rollover()
    return ok_empty()
