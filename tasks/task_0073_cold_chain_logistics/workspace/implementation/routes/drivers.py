"""Driver routes."""

from flask import Blueprint, request

from clock import clock
from db import db, new_id
from errors import err
from middleware import require_roles
from response import object_response
from serializers import driver as ser_driver
from validators import require_dict, require_int, require_str


bp = Blueprint("drivers", __name__)


@bp.post("/drivers")
@require_roles("CARRIER")
def create_driver():
    body = require_dict(request.get_json(silent=True) or {})
    license_no = require_str(body.get("license_no"), field="license_no", min_len=1, max_len=32)
    name = require_str(body.get("name"), field="name", min_len=1, max_len=120)
    max_daily_minutes = body.get("max_daily_minutes")
    if max_daily_minutes is None:
        max_daily_minutes = 660
    else:
        max_daily_minutes = require_int(
            max_daily_minutes, field="max_daily_minutes", min_val=1, max_val=1440
        )
    if license_no in db.license_no_index:
        err("ERR_VALIDATION", "license_no already exists.")
    now_iso = clock.now_iso()
    row = {
        "id": new_id(),
        "license_no": license_no,
        "name": name,
        "max_daily_minutes": max_daily_minutes,
        "status": "OFF_DUTY",
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    db.drivers.put(row)
    db.license_no_index[license_no] = row["id"]
    return object_response(ser_driver(row), status_code=201)


@bp.get("/drivers/<driver_id>")
@require_roles("CARRIER", "DISPATCHER", "COMPLIANCE_OFFICER")
def get_driver(driver_id):
    row = db.drivers.get(driver_id)
    if row is None:
        err("ERR_NOT_FOUND", "Driver not found.")
    return object_response(ser_driver(row))
