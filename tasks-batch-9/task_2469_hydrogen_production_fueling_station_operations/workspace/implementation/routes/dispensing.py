"""Dispensing sessions: reservation, fill protocol, cascade, settlement and voids."""
from decimal import Decimal as D

from flask import Blueprint

import derive
import serializers as ser
from auth import actor, require_station_owner
from constants import (
    BILLING_STATUSES,
    FILL_PROTOCOLS,
    FILL_STATUSES,
    PRESSURE_CLASSES,
    VEHICLE_CLASSES,
    VOID_REASONS,
)
from envelope import created, listing, ok
from errors import raise_error
from helpers import (
    append_ledger,
    get_session,
    get_station,
    require_not_frozen,
    require_not_restricted_h70,
    require_responders,
)
from store import base_row, db, touch
from validate import (
    f_enum,
    f_int,
    f_num,
    f_str,
    json_body,
    pagination,
    paginate,
    q_enum,
)

bp = Blueprint("dispensing", __name__)


@bp.get("/dispense-sessions/<session_id>")
def read_session(session_id):
    actor("PlatformAdmin", "StationOperator", "ComplianceAdmin", "ProgramAuditor")
    return ok(ser.dispense_session(get_session(session_id)))


@bp.get("/stations/<station_id>/dispense-sessions")
def list_sessions(station_id):
    actor("PlatformAdmin", "StationOperator", "ComplianceAdmin", "ProgramAuditor")
    station = get_station(station_id)
    limit, offset = pagination()
    fill_status = q_enum("fill_status", FILL_STATUSES)
    billing_status = q_enum("billing_status", BILLING_STATUSES)
    rows = derive.sessions_of(station["id"])
    if fill_status is not None:
        rows = [r for r in rows if r["fill_status"] == fill_status]
    if billing_status is not None:
        rows = [r for r in rows if r["billing_status"] == billing_status]
    page = paginate(rows, limit, offset)
    return listing([ser.dispense_session(r) for r in page], limit, offset, len(rows))


@bp.post("/dispense-sessions")
def open_session():
    user_id, role = actor("StationOperator")
    body = json_body()
    raw_station = body.get("station_id")
    if isinstance(raw_station, str) and raw_station.strip():
        require_station_owner(role, user_id, raw_station)

    station_id = f_str(body, "station_id")
    vehicle_class = f_enum(body, "vehicle_class", VEHICLE_CLASSES)
    target_pressure_class = f_enum(body, "target_pressure_class", PRESSURE_CLASSES)
    fill_protocol = f_enum(body, "fill_protocol", FILL_PROTOCOLS)
    planned_kg = f_num(body, "planned_kg", 3, gt=D(0))
    ambient_temp_c = f_num(body, "ambient_temp_c", 1, ge=D("-40"), le=D("55"))
    expected_station_version = f_int(body, "expected_station_version")

    station = get_station(station_id)

    if expected_station_version != station["version"]:
        raise_error("ERR_STALE_STATION_VERSION")

    require_not_frozen(station)
    require_not_restricted_h70(station, target_pressure_class)
    require_responders(station)

    in_flight = sum(1 for s in derive.sessions_of(station["id"])
                    if s["fill_status"] in ("PRECOOLING", "FUELING"))
    if in_flight >= station["nozzle_count"]:
        raise_error("ERR_NO_NOZZLE_AVAILABLE")

    if target_pressure_class == "H70" and station["max_pressure_class"] == "H35":
        raise_error("ERR_PRESSURE_CLASS_UNSUPPORTED")

    if planned_kg > derive.available_kg(station["id"]):
        raise_error("ERR_INSUFFICIENT_AVAILABLE_INVENTORY")

    row = base_row()
    row.update({
        "station_id": station["id"],
        "vehicle_class": vehicle_class,
        "target_pressure_class": target_pressure_class,
        "fill_protocol": fill_protocol,
        "planned_kg": planned_kg,
        "ambient_temp_c": ambient_temp_c,
        "required_precool_c": derive.required_precool_c(
            ambient_temp_c, target_pressure_class, fill_protocol),
        "precool_temp_achieved_c": None,
        "metered_kg": None,
        "avg_dispense_pressure_bar": None,
        "final_pressure_bar": None,
        "density_correction_factor": None,
        "corrected_kg": None,
        "metering_error_pct": None,
        "metering_within_tolerance": None,
        "direct_cascade_kg": None,
        "compressor_makeup_kg": None,
        "cascade_plan": [],
        "fill_status": "PRECOOLING",
        "billing_status": "PENDING",
        "abort_reason": None,
        "void_reason": None,
        "started_at": db.clock,
    })
    db.dispense_sessions[row["id"]] = row
    touch(station)
    return created(ser.dispense_session(row))


@bp.post("/dispense-sessions/<session_id>/fuel")
def start_fuelling(session_id):
    user_id, role = actor("StationOperator")
    session = get_session(session_id)
    require_station_owner(role, user_id, session["station_id"])

    body = json_body()
    achieved = f_num(body, "precool_temp_achieved_c", 1, ge=D("-40"), le=D("25"))

    if session["fill_status"] != "PRECOOLING":
        raise_error("ERR_INVALID_STATE_TRANSITION")

    station = db.stations[session["station_id"]]
    require_not_frozen(station)
    require_not_restricted_h70(station, session["target_pressure_class"])

    if achieved > session["required_precool_c"]:
        raise_error("ERR_FILL_PROTOCOL_VIOLATION")

    session["precool_temp_achieved_c"] = achieved
    session["fill_status"] = "FUELING"
    touch(session)
    return ok(ser.dispense_session(session))


@bp.post("/dispense-sessions/<session_id>/complete")
def complete_fill(session_id):
    user_id, role = actor("StationOperator")
    session = get_session(session_id)
    require_station_owner(role, user_id, session["station_id"])

    body = json_body()
    metered_kg = f_num(body, "metered_kg", 3, gt=D(0))
    avg_pressure = f_num(body, "avg_dispense_pressure_bar", 2, gt=D(0))
    final_pressure = f_num(body, "final_pressure_bar", 2, gt=D(0))

    if session["fill_status"] != "FUELING":
        raise_error("ERR_INVALID_STATE_TRANSITION")

    station = db.stations[session["station_id"]]
    require_not_frozen(station)

    if metered_kg > session["planned_kg"]:
        raise_error("ERR_METERED_EXCEEDS_PLANNED")

    plan, direct_kg, makeup_kg, pressures = derive.cascade_allocation(station, session)
    factor, corrected_kg, error_pct, within = derive.meter_correction(
        metered_kg, session["ambient_temp_c"], avg_pressure)

    for vessel_id, pressure in pressures.items():
        vessel = db.pressure_vessels[vessel_id]
        if vessel["current_pressure_bar"] != pressure:
            vessel["current_pressure_bar"] = pressure
            touch(vessel)

    session["metered_kg"] = metered_kg
    session["avg_dispense_pressure_bar"] = avg_pressure
    session["final_pressure_bar"] = final_pressure
    session["density_correction_factor"] = factor
    session["corrected_kg"] = corrected_kg
    session["metering_error_pct"] = error_pct
    session["metering_within_tolerance"] = within
    session["cascade_plan"] = plan
    session["direct_cascade_kg"] = direct_kg
    session["compressor_makeup_kg"] = makeup_kg
    session["fill_status"] = "COMPLETED"
    touch(session)

    append_ledger(station["id"], "DISPENSE_DRAW", -metered_kg, "DISPENSE_SESSION",
                  session["id"])
    touch(station)
    return ok(ser.dispense_session(session))


@bp.post("/dispense-sessions/<session_id>/abort")
def abort_session(session_id):
    user_id, role = actor("StationOperator")
    session = get_session(session_id)
    require_station_owner(role, user_id, session["station_id"])

    if session["fill_status"] not in ("PRECOOLING", "FUELING"):
        raise_error("ERR_INVALID_STATE_TRANSITION")

    session["fill_status"] = "ABORTED"
    session["abort_reason"] = "OPERATOR_ABORT"
    if session["billing_status"] == "PENDING":
        session["billing_status"] = "VOIDED"
    touch(session)
    touch(db.stations[session["station_id"]])
    return ok(ser.dispense_session(session))


@bp.post("/dispense-sessions/<session_id>/meter-settlement")
def settle_meter(session_id):
    actor("StationOperator", "ComplianceAdmin")
    session = get_session(session_id)

    if session["billing_status"] != "PENDING" or session["fill_status"] != "COMPLETED":
        raise_error("ERR_INVALID_STATE_TRANSITION")

    station = db.stations[session["station_id"]]
    session["billing_status"] = "METERED"
    touch(session)
    append_ledger(station["id"], "METER_CORRECTION",
                  session["metered_kg"] - session["corrected_kg"],
                  "DISPENSE_SESSION", session["id"])
    touch(station)
    return ok(ser.dispense_session(session))


@bp.post("/dispense-sessions/<session_id>/void-meter")
def void_meter(session_id):
    actor("ComplianceAdmin")
    session = get_session(session_id)
    body = json_body()
    void_reason = f_enum(body, "void_reason", VOID_REASONS)

    if session["billing_status"] != "METERED":
        raise_error("ERR_INVALID_STATE_TRANSITION")

    session_date = session["started_at"].date()
    for claim in derive.claims_of(session["station_id"]):
        if claim["status"] not in ("CERTIFIED", "CREDITS_ISSUED"):
            continue
        if claim["period_start"] <= session_date <= claim["period_end"]:
            raise_error("ERR_INVALID_STATE_TRANSITION")

    station = db.stations[session["station_id"]]
    session["billing_status"] = "VOIDED"
    session["void_reason"] = void_reason
    touch(session)
    append_ledger(station["id"], "METER_VOID_REVERSAL",
                  session["corrected_kg"] - session["metered_kg"],
                  "DISPENSE_SESSION", session["id"])
    touch(station)
    return ok(ser.dispense_session(session))
