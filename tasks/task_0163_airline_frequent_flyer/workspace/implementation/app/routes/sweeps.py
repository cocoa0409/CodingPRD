"""Sweep endpoints under /_sweep."""

from __future__ import annotations

from flask import Blueprint, request

from .. import errors as E
from ..auth import require_roles
from ..envelope import ok_object
from ..services.common import get_json_body, require_fields
from ..services import sweeps


sweeps_bp = Blueprint("sweeps", __name__)


@sweeps_bp.post("/_sweep/expire-points")
@require_roles("ProgramAdmin")
def expire_points():
    n = sweeps.sweep_expire_points()
    return ok_object({"expired_count": n})


@sweeps_bp.post("/_sweep/expire-bookings")
@require_roles("ProgramAdmin")
def expire_bookings():
    n = sweeps.sweep_expire_bookings()
    return ok_object({"expired_count": n})


@sweeps_bp.post("/_sweep/expire-certificates")
@require_roles("ProgramAdmin")
def expire_certificates():
    n = sweeps.sweep_expire_certificates()
    return ok_object({"expired_count": n})


@sweeps_bp.post("/_sweep/expire-status-matches")
@require_roles("ProgramAdmin")
def expire_status_matches():
    n = sweeps.sweep_expire_status_matches()
    return ok_object({"expired_count": n})


@sweeps_bp.post("/_sweep/promote-upgrades")
@require_roles("ProgramAdmin")
def promote_upgrades():
    body = get_json_body()
    flight_id = body.get("flight_id")
    if flight_id is not None and not isinstance(flight_id, str):
        raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "flight_id must be a string.")
    n = sweeps.sweep_promote_upgrades(flight_id)
    return ok_object({"promoted_count": n})


@sweeps_bp.post("/_sweep/annual-rollover")
@require_roles("ProgramAdmin")
def annual_rollover():
    body = get_json_body()
    require_fields(body, "target_year")
    target_year = body["target_year"]
    if not isinstance(target_year, int) or isinstance(target_year, bool):
        raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "target_year must be an integer.")
    n = sweeps.sweep_annual_rollover(target_year)
    return ok_object({"rolled_count": n})
