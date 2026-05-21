"""System clock + sweep routes."""
from __future__ import annotations

from flask import Blueprint

from core.auth import require_roles
from core.envelope import get_json_body, success_response
from core.serializers import clock_view
from services.clock_service import advance_clock, get_clock_snapshot
from services.purchase_service import run_sweep


bp = Blueprint("system", __name__)


@bp.route("/_clock", methods=["GET"])
@require_roles("PlanAdministrator", "PayrollAgent", "Participant", "TaxAuthority")
def get_clock():
    return success_response(clock_view(get_clock_snapshot()))


@bp.route("/_clock/advance", methods=["POST"])
@require_roles("PlanAdministrator")
def post_advance():
    payload = get_json_body()
    clock = advance_clock(payload)
    return success_response(clock_view(clock))


@bp.route("/_sweep/run", methods=["POST"])
@require_roles("PlanAdministrator")
def post_sweep():
    result = run_sweep()
    return success_response(result)
