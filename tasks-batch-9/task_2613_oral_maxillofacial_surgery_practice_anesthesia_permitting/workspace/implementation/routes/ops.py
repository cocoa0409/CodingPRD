"""Operational utilities: the logical clock and the compliance sweep."""
from flask import Blueprint

from db import clock_dt, clock_str, db, set_clock
from errors import ApiError
from middleware import authorize
from response import object_response
from routes.helpers import ALL_ROLES
from services.domain import referenced_row
from services.sweep import run_sweep
from timeutil import parse_date
from validation import read_body, v_id, v_instant

bp = Blueprint("ops", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authorize(*ALL_ROLES)
    body = read_body(required=("current_utc",))
    current_utc = v_instant(body, "current_utc")

    requested = parse_date(current_utc)
    if requested < clock_dt():
        raise ApiError("ERR_CLOCK_MONOTONIC_VIOLATION")

    previous = clock_str()
    set_clock(requested)
    return object_response({"current_utc": clock_str(), "previous_utc": previous})


@bp.post("/_ops/run-compliance-sweep")
def run_compliance_sweep():
    authorize("PracticeAdministrator")
    body = read_body(optional=("practice_id",))
    practice_id = v_id(body, "practice_id", default=None)
    if practice_id is not None:
        referenced_row(db.practices, practice_id)
    return object_response(run_sweep(practice_id))
