"""Marina root routes — create, get, clock advance, ops sweep."""
from __future__ import annotations

from flask import Blueprint

from ..auth import require_auth
from ..clock import iso_format, parse_iso
from ..common import bump, get_json_body, positive_int, require_fields, stamp_new
from ..errors import ApiError
from ..marina_helpers import get_marina
from ..ops_run import run_ops
from ..response import respond
from ..serializers import marina_view
from ..store import store


bp = Blueprint("marinas", __name__, url_prefix="/marinas")


EPOCH_INSTANT = "1970-01-01T00:00:00.000Z"


@bp.post("")
@require_auth("DockMaster", "BillingClerk")
def create_marina():
    body = get_json_body()
    require_fields(body, "name", "base_daily_rate_cents", "liveaboard_quota")
    base_rate = positive_int(body["base_daily_rate_cents"], "base_daily_rate_cents", allow_zero=True)
    quota = positive_int(body["liveaboard_quota"], "liveaboard_quota", allow_zero=True)
    timezone_str = body.get("timezone") or "America/New_York"
    marina = {
        "name": body["name"],
        "timezone": timezone_str,
        "current_date": EPOCH_INSTANT,
        "ops_run_index": 0,
        "base_daily_rate_cents": base_rate,
        "liveaboard_quota": quota,
        "liveaboard_active_count": 0,
    }
    stamp_new(marina)
    with store.lock:
        store.marinas[marina["id"]] = marina
    return respond(marina_view(marina), 201)


@bp.get("/<marina_id>")
@require_auth("DockMaster", "BillingClerk", "Boater")
def fetch_marina(marina_id: str):
    with store.lock:
        marina = get_marina(marina_id)
        return respond(marina_view(marina), 200)


@bp.post("/<marina_id>/_clock/advance")
@require_auth("DockMaster")
def advance_clock(marina_id: str):
    body = get_json_body()
    require_fields(body, "to")
    try:
        to_dt = parse_iso(body["to"])
    except ValueError as exc:
        raise ApiError("ERR_BAD_REQUEST", f"to: {exc}")
    with store.lock:
        marina = get_marina(marina_id)
        marina["current_date"] = iso_format(to_dt)
        bump(marina)
        return respond(marina_view(marina), 200)


@bp.post("/<marina_id>/_ops/run")
@require_auth("DockMaster")
def ops_run(marina_id: str):
    with store.lock:
        marina = get_marina(marina_id)
        run_ops(marina)
        return respond(marina_view(marina), 200)
