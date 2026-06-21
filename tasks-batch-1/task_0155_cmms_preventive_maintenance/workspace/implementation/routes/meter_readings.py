"""MeterReading routes (PRD §3.2, §3.3, §4).

Submitting a reading advances the asset meter (monotonic), bumps the asset
version, and auto-generates PREVENTIVE work orders for every active METER
schedule that becomes due.
"""
from flask import Blueprint

import db
import errors
import serialize
from middleware import authenticate, authorize, get_json_body
from helpers import require_number, require_dt, parse_pagination, paginate
from response import object_response, array_response
from services import calc, workflow

bp = Blueprint("meter_readings", __name__)


@bp.post("/assets/<aid>/meter-readings")
def create_meter_reading(aid):
    _, role = authenticate()
    authorize(role, ["Technician", "MaintenanceManager"])
    body = get_json_body()
    with db.LOCK:
        asset = db.assets.get(aid)
        if asset is None:
            raise errors.not_found()
        value = require_number(body, "value")
        reading_at = require_dt(body, "reading_at")

        # Monotonicity (priority 10): value >= current meter_reading AND
        # reading_at strictly after the latest existing reading's reading_at.
        if value < asset["meter_reading"]:
            raise errors.ApiError(errors.ERR_METER_NOT_MONOTONIC,
                                  "Meter value is below the asset's current meter_reading.", 422)
        existing = [r for r in db.meter_readings.values() if r["asset_id"] == aid]
        if existing:
            existing.sort(key=lambda r: (db.parse_stored_dt(r["reading_at"]), r["_seq"]))
            latest_at = db.parse_stored_dt(existing[-1]["reading_at"])
            if not (reading_at > latest_at):
                raise errors.ApiError(errors.ERR_METER_NOT_MONOTONIC,
                                      "reading_at must be strictly after the latest reading.", 422)

        rec = db.new_record(with_version=False)
        rec.update({
            "asset_id": aid,
            "value": value,
            "reading_at": db.iso(reading_at),
            "triggered_pm": False,
        })
        db.meter_readings[rec["id"]] = rec

        # Recompute asset.meter_reading and bump the asset version (PRD §3.2).
        calc.recompute_meter_reading(asset)
        db.touch(asset)

        # Auto-generate due METER PMs (PRD §3.3).
        triggered = False
        for sched in sorted(db.pm_schedules.values(), key=lambda s: s["_seq"]):
            if (sched["asset_id"] == aid
                    and sched["active"]
                    and sched["trigger_type"] == "METER"
                    and calc.is_due(sched, asset)):
                workflow.generate_due_for_schedule(sched, asset)
                triggered = True
        if triggered:
            rec["triggered_pm"] = True

        return object_response(serialize.meter_reading(rec), 201)


@bp.get("/assets/<aid>/meter-readings")
def list_meter_readings(aid):
    _, role = authenticate()
    authorize(role, ["MaintenanceManager", "Planner", "Technician"])
    limit, offset = parse_pagination()
    with db.LOCK:
        if aid not in db.assets:
            raise errors.not_found()
        items = sorted(
            (r for r in db.meter_readings.values() if r["asset_id"] == aid),
            key=lambda r: r["_seq"])
        total = len(items)
        page = paginate(items, limit, offset)
        return array_response([serialize.meter_reading(r) for r in page],
                              limit, offset, total)
