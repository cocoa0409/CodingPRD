"""Tank commissioning, temperature surveillance and the alarm-response lifecycle."""
from flask import Blueprint

import calc
import services as svc
from errors import fail
from middleware import endpoint, get_body, v_enum, v_int, v_num, v_str, v_ts
from response import object_response
from store import base_row, db, iso, now, pdt, public, touch

bp = Blueprint("tanks", __name__)


@bp.route("/cbb/storage-tanks", methods=["POST"])
@endpoint("FacilitiesEngineer", "PlatformAdmin")
def commission_tank(user_id, role):
    body = get_body()
    tank_code = v_str(body, "tank_code", min_len=1, max_len=20)
    tank_class = v_enum(body, "tank_class", ("STANDARD", "PREMIUM"))
    capacity = v_int(body, "capacity_slots", ge=1)
    start = v_ts(body, "maintenance_window_start", required=False)
    end = v_ts(body, "maintenance_window_end", required=False)
    if start is not None and end is not None and end <= start:
        fail("ERR_VALIDATION_FAILED",
             "maintenance_window_end must be later than maintenance_window_start.")
    for tank in db.tanks.values():
        if tank["tank_code"] == tank_code:
            fail("ERR_VALIDATION_FAILED", "tank_code must be unique.")

    row = base_row()
    row.update({
        "tank_code": tank_code,
        "tank_class": tank_class,
        "capacity_slots": capacity,
        "maintenance_window_start": iso(start) if start is not None else None,
        "maintenance_window_end": iso(end) if end is not None else None,
        "occupied_slots": 0,
        "status": "ONLINE",
        "last_temperature_c": None,
        "last_reading_at": None,
        "cumulative_excursion_minutes_30d": 0,
    })
    db.tanks[row["id"]] = row
    return object_response(public(row), 201)


@bp.route("/cbb/storage-tanks/<tid>/temperature-readings", methods=["POST"])
@endpoint("FacilitiesEngineer", "PlatformAdmin")
def post_reading(user_id, role, tid):
    body = get_body()
    reading_c = v_num(body, "reading_c")
    reading_at = v_ts(body, "reading_at")
    tank = svc.get_tank(tid)

    tank["last_temperature_c"] = calc.num(reading_c)
    tank["last_reading_at"] = iso(reading_at)
    touch(tank)

    if reading_c > calc.ALARM_THRESHOLD_C:
        live = svc.live_excursion(tid)
        if live is not None:
            # Only one excursion may be live per tank; the peak still tracks.
            if calc.D(live["peak_temperature_c"]) < reading_c:
                live["peak_temperature_c"] = calc.num(reading_c)
                touch(live)
        else:
            if tank["status"] in ("ONLINE", "MAINTENANCE"):
                tank["status"] = "ALARM"
                touch(tank)
            row = base_row()
            row.update({
                "tank_id": tid,
                "detected_at": iso(reading_at),
                "peak_temperature_c": calc.num(reading_c),
                "acknowledged_at": None,
                "acknowledged_by_user_id": None,
                "resolved_at": None,
                "duration_minutes": None,
                "disposition": None,
                "status": "OPEN",
            })
            db.excursions[row["id"]] = row
            svc.cascade_quarantine(tank)
    return object_response(public(tank))


@bp.route("/cbb/temperature-excursions/<xid>/acknowledge", methods=["POST"])
@endpoint("FacilitiesEngineer", "PlatformAdmin")
def acknowledge_excursion(user_id, role, xid):
    body = get_body()
    v_str(body, "acknowledgement_note", required=False, min_len=0, max_len=500)
    excursion = svc.get_excursion(xid)

    if excursion["status"] not in ("OPEN", "ESCALATED"):
        fail("ERR_INVALID_EXCURSION_STATE")

    excursion["status"] = "ACKNOWLEDGED"
    excursion["acknowledged_at"] = iso(now())
    excursion["acknowledged_by_user_id"] = user_id
    touch(excursion)
    return object_response(public(excursion))


@bp.route("/cbb/temperature-excursions/<xid>/resolve", methods=["POST"])
@endpoint("MedicalDirector", "FacilitiesEngineer", "PlatformAdmin")
def resolve_excursion(user_id, role, xid):
    body = get_body()
    disposition = v_enum(body, "disposition", ("NO_IMPACT", "REQUALIFY", "TOTAL_LOSS"))
    peak = v_num(body, "peak_temperature_c")
    excursion = svc.get_excursion(xid)

    if excursion["status"] not in ("ACKNOWLEDGED", "ESCALATED"):
        fail("ERR_INVALID_EXCURSION_STATE")

    resolved = now()
    excursion["disposition"] = disposition
    excursion["peak_temperature_c"] = calc.num(peak)
    excursion["resolved_at"] = iso(resolved)
    excursion["duration_minutes"] = calc.duration_minutes(
        pdt(excursion["detected_at"]), resolved)
    excursion["status"] = "CLOSED_LOSS" if disposition == "TOTAL_LOSS" else "RESOLVED"
    touch(excursion)

    tank = db.tanks.get(excursion["tank_id"])
    if tank is not None:
        if disposition == "TOTAL_LOSS":
            if tank["status"] == "ALARM":
                tank["status"] = "OFFLINE"
                touch(tank)
            svc.cascade_excursion_total_loss(tank)
        else:
            if tank["status"] == "ALARM":
                tank["status"] = "ONLINE"
                touch(tank)
            svc.cascade_excursion_benign(tank)
        svc.recompute_excursion_minutes(tank)
    return object_response(public(excursion))
