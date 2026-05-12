"""Test-driving + external event ingress routes (clock advance, sweep, events emit)."""

from flask import Blueprint, g, request

from db import LOCK
from middleware import require_roles
from response import success_object
from services.events import emit
from services.sweep import advance_clock, run_sweep


bp = Blueprint("system", __name__)


@bp.route("/_clock/advance", methods=["POST"])
@require_roles("OperationsAdmin")
def post_clock_advance():
    with LOCK:
        out = advance_clock(request.get_json(silent=True) or {})
        return success_object(out)


@bp.route("/_sweep/run", methods=["POST"])
@require_roles("OperationsAdmin")
def post_sweep_run():
    with LOCK:
        out = run_sweep()
        return success_object(out)


@bp.route("/events/emit", methods=["POST"])
@require_roles("OperationsAdmin")
def post_events_emit():
    with LOCK:
        out = emit(request.get_json(silent=True) or {}, g.role, g.user_id)
        return success_object(out)
