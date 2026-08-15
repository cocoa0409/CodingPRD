"""POST /_clock/set_current_utc — advance the logical clock and run the system sweep."""

from datetime import date, datetime, time, timezone

from flask import Blueprint

import clock
import db
import errors as E
from errors import ApiError
from middleware import require_auth, require_role
from response import success
from services.helpers import (
    compute_msl_exposure_hours,
    get_json_body,
    parse_iso_datetime,
    quarantine_cascade,
)

bp = Blueprint("clock", __name__)


def _sweep_registrations(now: datetime):
    today = now.date()
    for reg in db.design_registrations.values():
        if reg["status"] in ("SUBMITTED", "APPROVED"):
            if reg["_valid_to"] < today:
                reg["status"] = "EXPIRED"
                reg["updated_at"] = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:23] + "Z"
                reg["version"] += 1


def _sweep_msl(now: datetime):
    # Snapshot candidate lots first so cascades during iteration are stable.
    for lot in list(db.inventory_lots.values()):
        if lot["status"] != "AVAILABLE":
            continue
        part = db.parts.get(lot["part_id"])
        if part is None:
            continue
        exposure = compute_msl_exposure_hours(lot)
        if exposure >= part["floor_life_hours"]:
            quarantine_cascade(lot)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    user_id, role = require_auth()
    require_role(user_id, role, {"DistributorAdmin"})
    body = get_json_body()
    raw = body.get("to_iso8601")
    dt = parse_iso_datetime(raw)
    if dt is None:
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "to_iso8601 must be an ISO 8601 datetime.")
    clock.set_now(dt)
    _sweep_registrations(dt)
    _sweep_msl(dt)
    now_str = clock.now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:23] + "Z"
    return success({"now": now_str}, status=200)
