"""Clock control endpoints (PRD §3.16, SCAFFOLD §1.5 _clock)."""
from __future__ import annotations

from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import require_auth
from response import success
from services.clock_engine import sweep_time_gated
from services.common import get_json_body
from utils import iso_now, parse_iso_datetime


bp = Blueprint("clock", __name__)


@bp.post("/_clock/advance")
@require_auth(["CourtClerk"])
def advance_clock():
    body = get_json_body(request)
    raw = body.get("to_timestamp")
    if not raw:
        raise ApiError("ERR_BAD_REQUEST", 400, "to_timestamp is required.")
    parsed = parse_iso_datetime(raw)
    if parsed is None:
        raise ApiError("ERR_BAD_REQUEST", 400, "to_timestamp must be ISO 8601 UTC.")

    with store.lock:
        store.clock.set_to(parsed)
        sweep_time_gated()

    return success({
        "logical_clock": iso_now(store.logical_now()),
    }, 200)


@bp.get("/_clock")
@require_auth(["CourtClerk", "Executor", "Beneficiary", "Fiduciary"])
def read_clock():
    return success({
        "logical_clock": iso_now(store.logical_now()),
    }, 200)
