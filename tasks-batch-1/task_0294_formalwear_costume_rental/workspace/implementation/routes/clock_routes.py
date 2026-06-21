"""System clock endpoints (PRD §3.10)."""
from flask import Blueprint

import db
from clock import parse_iso, set_clock, current_dt
from errors import err, ERR_INVALID_REQUEST
from middleware import authenticate, require_role
from response import success
from services import helpers

bp = Blueprint("clock_routes", __name__)


def _parse_target(body):
    to_iso = body.get("to_iso8601")
    if to_iso is None:
        raise err(ERR_INVALID_REQUEST, "Missing required field: to_iso8601")
    try:
        return parse_iso(to_iso)
    except (ValueError, TypeError):
        raise err(ERR_INVALID_REQUEST, "to_iso8601 is not a valid timestamp")


@bp.route("/_clock/set", methods=["POST"])
def clock_set():
    _, role = authenticate()
    require_role(role, {"StoreManager"})
    body = helpers.get_json_body()
    target = _parse_target(body)
    # Pure setup: set the clock, fire no transitions.
    set_clock(target)
    return success({})


@bp.route("/_clock/advance", methods=["POST"])
def clock_advance():
    _, role = authenticate()
    require_role(role, {"StoreManager"})
    body = helpers.get_json_body()
    target = _parse_target(body)
    set_clock(target)
    _run_sweep()
    return success({})


def _run_sweep():
    """Overdue + cleaning-buffer sweep, processed created_at ASC across reservations."""
    now = current_dt()

    # First: PICKED_UP reservations past return_window_end -> OVERDUE (no settlement).
    ordered_res = sorted(
        db.reservations.values(),
        key=lambda r: (r["created_at"], db.seq_of(r)),
    )
    for r in ordered_res:
        if r["status"] == "PICKED_UP" and now > parse_iso(r["return_window_end_iso"]):
            r["status"] = "OVERDUE"
            db.touch(r)

    # Second: IN_CLEANING units past available_from_iso -> AVAILABLE.
    ordered_units = sorted(
        db.garment_units.values(),
        key=lambda u: (u["created_at"], db.seq_of(u)),
    )
    for u in ordered_units:
        if u["status"] != "IN_CLEANING":
            continue
        afi = u["available_from_iso"]
        if afi is not None and now >= parse_iso(afi):
            u["status"] = "AVAILABLE"
            db.touch(u)
