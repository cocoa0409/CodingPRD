"""The logical clock and the synchronous expiry sweep (PRD 2.6)."""

from flask import Blueprint

from db import fmt_dt_sec, store
from helpers import get_body, req_dt, require_roles
from response import success
from services import run_expiry_sweep

bp = Blueprint("clock", __name__)

ALL_ROLES = (
    "FleetAdmin",
    "CrewingManager",
    "CredentialingOfficer",
    "PortCaptain",
    "UnionDispatcher",
    "Mariner",
)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("FleetAdmin")
def set_clock():
    body = get_body()
    target = req_dt(body, "to_iso8601")
    store.clock = target
    run_expiry_sweep()
    return success({"current_utc": fmt_dt_sec(store.clock)})


@bp.route("/_clock/current", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_clock():
    return success({"current_utc": fmt_dt_sec(store.clock)})
