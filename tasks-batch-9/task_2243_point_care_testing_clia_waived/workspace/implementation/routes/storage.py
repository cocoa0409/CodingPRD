"""Storage units, probe readings and excursion resolution (PRD 3.5)."""

from flask import Blueprint

import clock
import db
import errors
import response
import serializers
import valid
from middleware import route
from services import calc, derive

bp = Blueprint("storage", __name__)

ALL_ROLES = ("ProgramAdmin", "LabDirector", "QualityCoordinator", "Surveyor",
             "Operator")


@route(bp, "/storage-units", ["POST"], ["ProgramAdmin"])
def create_storage_unit(user_id, role):
    payload = valid.body()
    site = valid.resolve_body("sites", payload, "site_id")
    name = valid.req_str(payload, "name")
    min_temp = valid.req_num(payload, "min_temp_c")
    max_temp = valid.req_num(payload, "max_temp_c")
    if calc.dec(max_temp) <= calc.dec(min_temp):
        raise errors.invalid_request(
            "max_temp_c must be strictly greater than min_temp_c.")

    row = db.insert("storage_units", {
        "site_id": site["id"],
        "name": name,
        "min_temp_c": min_temp,
        "max_temp_c": max_temp,
        "excursion_state": "IN_RANGE",
        "excursion_opened_at": None,
        "last_reading_c": None,
        "quarantined_lot_count": 0,
    })
    return response.object_response(serializers.dump("storage_units", row), 201)


@route(bp, "/storage-units/<unit_id>", ["GET"], ALL_ROLES)
def read_storage_unit(user_id, role, unit_id):
    row = valid.resolve("storage_units", unit_id)
    return response.object_response(serializers.dump("storage_units", row))


@route(bp, "/storage-units", ["GET"], ALL_ROLES)
def list_storage_units(user_id, role):
    limit, offset = valid.pagination()
    site_id = valid.arg("site_id")
    items = [u for u in db.rows("storage_units")
             if site_id is None or u["site_id"] == site_id]
    return response.list_response(
        serializers.dump_many("storage_units", valid.page(items, limit, offset)),
        limit, offset, len(items))


@route(bp, "/storage-units/<unit_id>/temperature-readings", ["POST"],
       ["Operator", "QualityCoordinator", "ProgramAdmin"])
def record_reading(user_id, role, unit_id):
    unit = valid.resolve("storage_units", unit_id)
    payload = valid.body()
    reading_c = valid.req_num(payload, "reading_c")
    recorded_at = valid.req_datetime(payload, "recorded_at")
    recorded_by = valid.req_str(payload, "recorded_by_user_id")

    disposition = calc.temperature_disposition(
        reading_c, unit["min_temp_c"], unit["max_temp_c"])
    opens = disposition == "OUT_OF_RANGE" and unit["excursion_state"] == "IN_RANGE"

    row = db.insert("temp_readings", {
        "storage_unit_id": unit["id"],
        "reading_c": reading_c,
        "recorded_at": clock.iso(recorded_at),
        "recorded_by_user_id": recorded_by,
        "disposition": disposition,
        "triggered_excursion": opens,
    }, common=False)

    snap = db.snapshot(unit)
    unit["last_reading_c"] = _latest_reading(unit["id"])
    if opens:
        unit["excursion_state"] = "EXCURSION_OPEN"
        unit["excursion_opened_at"] = clock.now_iso()
    db.touch_if_changed(unit, snap)

    if opens:
        derive.cascade_temperature_excursion(unit)

    return response.object_response(serializers.dump("temp_readings", row), 201)


def _latest_reading(unit_id):
    readings = [r for r in db.data["temp_readings"].values()
                if r["storage_unit_id"] == unit_id]
    if not readings:
        return None
    readings.sort(key=lambda r: (r["recorded_at"], r["_seq"]))
    return readings[-1]["reading_c"]


@route(bp, "/storage-units/<unit_id>/temperature-readings", ["GET"], ALL_ROLES)
def list_readings(user_id, role, unit_id):
    unit = valid.resolve("storage_units", unit_id)
    limit, offset = valid.pagination()
    items = [r for r in db.rows("temp_readings")
             if r["storage_unit_id"] == unit["id"]]
    return response.list_response(
        serializers.dump_many("temp_readings", valid.page(items, limit, offset)),
        limit, offset, len(items))


@route(bp, "/storage-units/<unit_id>/excursion-resolution", ["POST"],
       ["QualityCoordinator", "LabDirector"])
def resolve_excursion(user_id, role, unit_id):
    unit = valid.resolve("storage_units", unit_id)
    payload = valid.body()
    valid.req_str(payload, "assessment_note")
    disposition = valid.req_enum(payload, "lot_disposition", ("RELEASE", "DISCARD"))
    # Rank 50.
    if unit["excursion_state"] != "EXCURSION_OPEN":
        raise errors.invalid_state("The storage unit has no open excursion.")

    quarantined = [lot for lot in db.rows("lots")
                   if lot["storage_unit_id"] == unit["id"]
                   and lot["verification_status"] == "QUARANTINED"]
    if disposition == "RELEASE":
        if any(lot["verified_at"] is None for lot in quarantined):
            raise errors.invalid_state(
                "A never-verified quarantined lot cannot be released.")

    for lot in quarantined:
        snap = db.snapshot(lot)
        if disposition == "RELEASE":
            lot["verification_status"] = "VERIFIED"
            lot["quarantine_reason"] = None
        else:
            lot["verification_status"] = "DISCARDED"
        db.touch_if_changed(lot, snap)

    snap = db.snapshot(unit)
    unit["excursion_state"] = "IN_RANGE"
    unit["excursion_opened_at"] = None
    unit["quarantined_lot_count"] = 0
    db.touch_if_changed(unit, snap)

    derive.recompute_site_by_id(unit["site_id"])
    return response.object_response(serializers.dump("storage_units", unit))
