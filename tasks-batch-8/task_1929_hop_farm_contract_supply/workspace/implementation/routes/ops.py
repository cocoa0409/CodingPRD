"""Ops endpoints: crop-year rollover (PRD §3.9) and the logical clock (§2.5)."""

from flask import Blueprint

from db import store, fmt_ts
from middleware import require_roles, ALL_ROLES, ROLE_FARM_MANAGER
from response import success_object
from util import get_body, check_unknown_fields, req_datetime
from services.core import crop_year_rollover

bp = Blueprint("ops", __name__)


@bp.route("/api/ops/crop-year-rollover", methods=["POST"])
def rollover():
    require_roles([ROLE_FARM_MANAGER])
    check_unknown_fields(get_body(), set())
    carried_over_lot_ids, completed_contract_ids = crop_year_rollover()
    return success_object({
        "carried_over_lot_ids": carried_over_lot_ids,
        "completed_contract_ids": completed_contract_ids,
    })


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    """Test-driving capability; the one endpoint mounted outside /api."""
    require_roles(ALL_ROLES)
    body = get_body()
    check_unknown_fields(body, {"to_iso8601"})
    dt = req_datetime(body, "to_iso8601")
    store.clock.set(dt)
    return success_object({"current_utc": fmt_ts(store.clock.now())})
