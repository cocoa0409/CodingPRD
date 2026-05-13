"""Test-harness administrative endpoints (clock / dunning / archive)."""
from flask import Blueprint, request

from clock import clock, iso, parse_iso

from db import store, now_iso
from middleware import require_roles
from response import success
from services.dunning import run_dunning_sweep, process_clock_side_effects


bp = Blueprint("admin", __name__)


@bp.route("/_clock/advance", methods=["POST"])
@require_roles("PlatformAdmin")
def clock_advance():
    body = request.get_json(silent=True) or {}
    seconds = body.get("seconds", 0)
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        s = 0.0
    new_now = clock.advance(s)
    process_clock_side_effects()
    return success({"now": iso(new_now)}, status=200)


@bp.route("/_dunning/run", methods=["POST"])
@require_roles("PlatformAdmin")
def dunning_run():
    result = run_dunning_sweep()
    return success(result, status=200)


@bp.route("/_archive/run", methods=["POST"])
@require_roles("PlatformAdmin")
def archive_run():
    body = request.get_json(silent=True) or {}
    cutoff_iso = body.get("cutoff_iso")
    if not cutoff_iso:
        return success({"archived_count": 0}, status=200)
    cutoff = parse_iso(cutoff_iso)
    n = 0
    for rec in store.usage_records.values():
        if rec.get("archived"):
            continue
        ets = parse_iso(rec["event_timestamp"])
        if ets < cutoff:
            rec["archived"] = True
            n += 1
    return success({"archived_count": n}, status=200)
