"""Estate configuration: funding agreements, stations, vessels, certifications, clock."""
from decimal import Decimal as D

from flask import Blueprint

import derive
import serializers as ser
from auth import actor
from constants import (
    BANK_TIERS,
    CERT_TYPES,
    INSPECTION_OUTCOMES,
    INSPECTION_STATUSES,
    LEDGER_REASONS,
    POSTURES,
    PRESSURE_CLASSES,
    UPTIME_METHODS,
)
from envelope import created, listing, ok
from errors import raise_error
from helpers import (
    append_ledger,
    get_agreement,
    get_station,
    get_vessel,
    require_not_frozen,
)
from store import base_row, db, sort_created, touch
from validate import (
    bad,
    f_bool,
    f_date,
    f_dt,
    f_enum,
    f_int,
    f_num,
    f_str,
    json_body,
    pagination,
    paginate,
    q_enum,
    q_str,
)

bp = Blueprint("config", __name__)


# =========================================================================
# FundingAgreement
# =========================================================================
@bp.get("/funding-agreements/<agreement_id>")
def read_agreement(agreement_id):
    actor("PlatformAdmin", "ComplianceAdmin", "ProgramAuditor")
    return ok(ser.funding_agreement(get_agreement(agreement_id)))


@bp.get("/funding-agreements")
def list_agreements():
    actor("PlatformAdmin", "ComplianceAdmin", "ProgramAuditor")
    limit, offset = pagination()
    funder_name = q_str("funder_name")
    method = q_enum("uptime_method", UPTIME_METHODS)
    rows = sort_created(list(db.funding_agreements.values()))
    if funder_name is not None:
        rows = [r for r in rows if r["funder_name"] == funder_name]
    if method is not None:
        rows = [r for r in rows if r["uptime_method"] == method]
    page = paginate(rows, limit, offset)
    return listing([ser.funding_agreement(r) for r in page], limit, offset, len(rows))


@bp.post("/funding-agreements")
def create_agreement():
    actor("PlatformAdmin")
    body = json_body()
    agreement_code = f_str(body, "agreement_code")
    funder_name = f_str(body, "funder_name")
    min_uptime_pct = f_num(body, "min_uptime_pct", 3, ge=D(0), le=D(100))
    penalty_per_point_cents = f_int(body, "penalty_per_point_cents", ge=0)
    initial_holdback_cents = f_int(body, "initial_holdback_cents", ge=0)
    uptime_method = f_enum(body, "uptime_method", UPTIME_METHODS)

    if any(r["agreement_code"] == agreement_code for r in db.funding_agreements.values()):
        raise_error("ERR_CODE_TAKEN")

    row = base_row()
    row.update({
        "agreement_code": agreement_code,
        "funder_name": funder_name,
        "min_uptime_pct": min_uptime_pct,
        "penalty_per_point_cents": penalty_per_point_cents,
        "initial_holdback_cents": initial_holdback_cents,
        "uptime_method": uptime_method,
    })
    db.funding_agreements[row["id"]] = row
    return created(ser.funding_agreement(row))


# =========================================================================
# Station
# =========================================================================
@bp.get("/stations/<station_id>")
def read_station(station_id):
    actor("PlatformAdmin", "StationOperator", "ComplianceAdmin", "SafetyOfficer",
          "LogisticsDispatcher", "ProgramAuditor")
    return ok(ser.station(get_station(station_id)))


@bp.get("/stations")
def list_stations():
    actor("PlatformAdmin", "ComplianceAdmin", "ProgramAuditor", "LogisticsDispatcher")
    limit, offset = pagination()
    agreement_id = q_str("funding_agreement_id")
    posture = q_enum("safety_posture", POSTURES)
    rows = sort_created(list(db.stations.values()))
    if agreement_id is not None:
        rows = [r for r in rows if r["funding_agreement_id"] == agreement_id]
    if posture is not None:
        rows = [r for r in rows if derive.safety_posture(r) == posture]
    page = paginate(rows, limit, offset)
    return listing([ser.station(r) for r in page], limit, offset, len(rows))


@bp.post("/stations")
def create_station():
    actor("PlatformAdmin")
    body = json_body()
    funding_agreement_id = f_str(body, "funding_agreement_id")
    code = f_str(body, "code")
    name = f_str(body, "name")
    nozzle_count = f_int(body, "nozzle_count", ge=1)
    offload_bay_count = f_int(body, "offload_bay_count", ge=1)
    storage_capacity_kg = f_num(body, "storage_capacity_kg", 3, gt=D(0))
    reserve_floor_kg = f_num(body, "reserve_floor_kg", 3, ge=D(0))
    max_pressure_class = f_enum(body, "max_pressure_class", PRESSURE_CLASSES)
    setback_compliant = f_bool(body, "setback_compliant", required=False, default=True)

    get_agreement(funding_agreement_id)

    if any(r["code"] == code for r in db.stations.values()):
        raise_error("ERR_STATION_CODE_TAKEN")

    row = base_row()
    row.update({
        "funding_agreement_id": funding_agreement_id,
        "code": code,
        "name": name,
        "nozzle_count": nozzle_count,
        "offload_bay_count": offload_bay_count,
        "storage_capacity_kg": storage_capacity_kg,
        "reserve_floor_kg": reserve_floor_kg,
        "max_pressure_class": max_pressure_class,
        "setback_compliant": setback_compliant,
        "ventilation_status": "NORMAL",
        "leak_detection_status": "NORMAL",
        "compressor_status": "ONLINE",
    })
    db.stations[row["id"]] = row
    return created(ser.station(row))


# =========================================================================
# PressureVessel
# =========================================================================
@bp.get("/stations/<station_id>/pressure-vessels")
def list_vessels(station_id):
    actor("PlatformAdmin", "StationOperator", "SafetyOfficer", "LogisticsDispatcher")
    station = get_station(station_id)
    limit, offset = pagination()
    bank_tier = q_enum("bank_tier", BANK_TIERS)
    status = q_enum("inspection_status", INSPECTION_STATUSES)
    rows = derive.vessels_of(station["id"])
    if bank_tier is not None:
        rows = [r for r in rows if r["bank_tier"] == bank_tier]
    if status is not None:
        rows = [r for r in rows if derive.vessel_status(r) == status]
    page = paginate(rows, limit, offset)
    return listing([ser.pressure_vessel(r) for r in page], limit, offset, len(rows))


@bp.get("/pressure-vessels/<vessel_id>")
def read_vessel(vessel_id):
    actor("PlatformAdmin", "StationOperator", "SafetyOfficer", "LogisticsDispatcher")
    return ok(ser.pressure_vessel(get_vessel(vessel_id)))


@bp.post("/stations/<station_id>/pressure-vessels")
def commission_vessel(station_id):
    actor("PlatformAdmin", "SafetyOfficer")
    station = get_station(station_id)
    body = json_body()
    bank_tier = f_enum(body, "bank_tier", BANK_TIERS)
    water_volume_l = f_num(body, "water_volume_l", 3, gt=D(0))
    mawp_bar = f_num(body, "mawp_bar", 2, gt=D(0))
    min_residual_bar = f_num(body, "min_residual_bar", 2, ge=D(0))
    initial_pressure_bar = f_num(body, "initial_pressure_bar", 2)
    next_inspection_due_date = f_date(body, "next_inspection_due_date")

    if min_residual_bar >= mawp_bar:
        bad("Field 'min_residual_bar' must be strictly less than 'mawp_bar'.")
    if initial_pressure_bar < min_residual_bar:
        bad("Field 'initial_pressure_bar' must be at least 'min_residual_bar'.")
    if initial_pressure_bar > mawp_bar:
        bad("Field 'initial_pressure_bar' must not exceed 'mawp_bar'.")

    row = base_row()
    row.update({
        "station_id": station["id"],
        "bank_tier": bank_tier,
        "water_volume_l": water_volume_l,
        "mawp_bar": mawp_bar,
        "min_residual_bar": min_residual_bar,
        "initial_pressure_bar": initial_pressure_bar,
        "current_pressure_bar": initial_pressure_bar,
        "last_inspection_date": None,
        "next_inspection_due_date": next_inspection_due_date,
        "inspection_count": 0,
        "condemned": False,
    })
    db.pressure_vessels[row["id"]] = row

    append_ledger(station["id"], "OPENING_BALANCE", derive.vessel_stored_mass(row),
                  "PRESSURE_VESSEL", None)
    touch(station)
    return created(ser.pressure_vessel(row))


@bp.post("/pressure-vessels/<vessel_id>/inspections")
def record_inspection(vessel_id):
    actor("SafetyOfficer")
    vessel = get_vessel(vessel_id)
    body = json_body()
    outcome = f_enum(body, "outcome", INSPECTION_OUTCOMES)
    next_due_date = f_date(body, "next_due_date", required=False, default=None)
    if outcome == "PASS" and next_due_date is None:
        bad("Field 'next_due_date' is required when 'outcome' is PASS.")

    if derive.vessel_status(vessel) not in ("DUE", "OVERDUE"):
        raise_error("ERR_INVALID_STATE_TRANSITION")

    station = db.stations[vessel["station_id"]]
    require_not_frozen(station)

    if outcome == "PASS":
        vessel["last_inspection_date"] = db.clock.date()
        vessel["next_inspection_due_date"] = next_due_date
        vessel["inspection_count"] = vessel["inspection_count"] + 1
    else:
        vented = derive.vessel_stored_mass(vessel)
        vessel["condemned"] = True
        vessel["current_pressure_bar"] = D("0.00")
        append_ledger(station["id"], "INSPECTION_VENT", -vented, "PRESSURE_VESSEL",
                      vessel["id"])
    touch(vessel)
    touch(station)
    return ok(ser.pressure_vessel(vessel))


# =========================================================================
# ResponderCertification
# =========================================================================
@bp.get("/stations/<station_id>/responder-certifications")
def list_certs(station_id):
    actor("PlatformAdmin", "SafetyOfficer", "StationOperator")
    station = get_station(station_id)
    limit, offset = pagination()
    cert_type = q_enum("cert_type", CERT_TYPES)
    rows = derive.certs_of(station["id"])
    if cert_type is not None:
        rows = [r for r in rows if r["cert_type"] == cert_type]
    page = paginate(rows, limit, offset)
    return listing([ser.responder_cert(r) for r in page], limit, offset, len(rows))


@bp.post("/stations/<station_id>/responder-certifications")
def create_cert(station_id):
    actor("SafetyOfficer", "PlatformAdmin")
    station = get_station(station_id)
    body = json_body()
    responder_ref = f_str(body, "responder_ref")
    cert_type = f_enum(body, "cert_type", CERT_TYPES)
    valid_from = f_date(body, "valid_from")
    expires_on = f_date(body, "expires_on")
    if expires_on < valid_from:
        bad("Field 'expires_on' must not be earlier than 'valid_from'.")

    row = base_row()
    row.update({
        "station_id": station["id"],
        "responder_ref": responder_ref,
        "cert_type": cert_type,
        "valid_from": valid_from,
        "expires_on": expires_on,
    })
    db.responder_certs[row["id"]] = row
    return created(ser.responder_cert(row))


# =========================================================================
# Inventory ledger
# =========================================================================
@bp.get("/stations/<station_id>/inventory-ledger")
def list_ledger(station_id):
    actor("PlatformAdmin", "StationOperator", "ComplianceAdmin", "ProgramAuditor")
    station = get_station(station_id)
    limit, offset = pagination()
    reason = q_enum("reason", LEDGER_REASONS)
    rows = ser.ledger_page(station["id"], reason)
    page = paginate(rows, limit, offset)
    return listing([ser.ledger_entry(entry, value) for entry, value in page],
                   limit, offset, len(rows))


# =========================================================================
# Logical clock
# =========================================================================
@bp.post("/_clock/set_current_utc")
def set_clock():
    actor("PlatformAdmin")
    body = json_body()
    target, raw = f_dt(body, "to_iso8601")

    before = {s["id"]: derive.safety_posture(s) for s in db.stations.values()}
    db.clock = target

    vessels_recomputed = sum(1 for v in db.pressure_vessels.values()
                             if not v["condemned"])
    for station in sort_created(list(db.stations.values())):
        if derive.safety_posture(station) != before[station["id"]]:
            touch(station)

    return ok({
        "current_utc": raw,
        "vessels_recomputed": vessels_recomputed,
        "stations_recomputed": len(db.stations),
    })
