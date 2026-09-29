"""Meter deployment, health monitoring and the fault/repair cascades."""
from flask import Blueprint

from auth import ALL_ROLES, FIELD_TECHNICIAN, roles
from calculations import FAULT_CODES, METER_TYPES
from common import must
from errors import ApiError
from response import apply_filters, created, listing, ok
from services import fault_cascade, repair_cascade
from store import db
from util import get_body, require_fields, want_enum, want_pattern, want_str

bp = Blueprint("meters", __name__)


@bp.post("/meters")
@roles(FIELD_TECHNICIAN)
def ship_meter():
    body = get_body()
    household = None
    if body.get("household_id") is not None:
        household = must("households", body["household_id"])
    require_fields(body, ["household_id", "meter_type", "serial_no"])
    meter_type = want_enum(body, "meter_type", METER_TYPES)
    serial_no = want_pattern(body, "serial_no", r"^MT-\d{6}$", max_len=9)
    if household["status"] not in ("RECRUITED", "INSTALL_SCHEDULED"):
        raise ApiError("ERR_HOUSEHOLD_NOT_ACCEPTING_METERS",
                       "this household takes no new devices")
    for meter in db.all("meters"):
        if meter["serial_no"] == serial_no:
            raise ApiError("ERR_METER_SERIAL_DUPLICATE",
                           "this serial_no already exists")
    for meter in db.where("meters", household_id=household["id"]):
        if (meter["meter_type"] == meter_type
                and meter["install_status"] in ("SHIPPED", "INSTALLED")):
            raise ApiError("ERR_METER_TYPE_ALREADY_PRESENT",
                           "the household already holds this meter_type")
    market = db.get("markets", household["market_id"])
    if market is not None and market["recruitment_posture"] == "FROZEN":
        raise ApiError("ERR_MARKET_FROZEN", "the market is frozen")
    meter = db.insert("meters", {
        "household_id": household["id"],
        "meter_type": meter_type,
        "serial_no": serial_no,
        "install_status": "SHIPPED",
        "health_status": "HEALTHY",
        "installed_at": None,
        "fault_count": 0,
        "last_fault_code": None,
        "missing_minutes_last_scan": 0,
    })
    if household["status"] == "RECRUITED":
        household["status"] = "INSTALL_SCHEDULED"
        db.touch(household)
    return created(meter)


@bp.post("/meters/<meter_id>/install-confirmations")
@roles(FIELD_TECHNICIAN)
def confirm_install(meter_id):
    meter = must("meters", meter_id)
    if meter["install_status"] != "SHIPPED":
        raise ApiError("ERR_METER_NOT_SHIPPED", "only a SHIPPED meter installs")
    meter["install_status"] = "INSTALLED"
    meter["installed_at"] = db.now_iso()
    db.touch(meter)
    household = db.get("households", meter["household_id"])
    if (meter["meter_type"] == "TV_TUNER" and household is not None
            and household["status"] == "INSTALL_SCHEDULED"):
        household["status"] = "ENUM_PENDING"
        db.touch(household)
    return ok(meter)


@bp.post("/meters/<meter_id>/fault-reports")
@roles(FIELD_TECHNICIAN)
def report_fault(meter_id):
    meter = must("meters", meter_id)
    body = get_body()
    require_fields(body, ["fault_code"])
    fault_code = want_enum(body, "fault_code", FAULT_CODES)
    if meter["health_status"] not in ("HEALTHY", "SUSPECT"):
        raise ApiError("ERR_METER_ALREADY_FAULTED",
                       "this device is already faulted")
    if meter["install_status"] != "INSTALLED":
        raise ApiError("ERR_METER_NOT_INSTALLED",
                       "only an INSTALLED device reports a fault")
    meter["health_status"] = "FAULTED"
    meter["fault_count"] = meter["fault_count"] + 1
    meter["last_fault_code"] = fault_code
    db.touch(meter)
    fault_cascade(meter)
    return ok(meter)


@bp.post("/meters/<meter_id>/repairs")
@roles(FIELD_TECHNICIAN)
def repair_meter(meter_id):
    meter = must("meters", meter_id)
    body = get_body()
    require_fields(body, ["repair_note"])
    want_str(body, "repair_note", min_len=1, max_len=400)
    if (meter["health_status"] not in ("FAULTED", "SUSPECT")
            or meter["install_status"] == "REMOVED"):
        raise ApiError("ERR_METER_NOT_FAULTED", "this device has nothing to repair")
    meter["health_status"] = "HEALTHY"
    meter["last_fault_code"] = None
    meter["missing_minutes_last_scan"] = 0
    db.touch(meter)
    repair_cascade(meter)
    return ok(meter)


@bp.post("/meters/<meter_id>/removals")
@roles(FIELD_TECHNICIAN)
def remove_meter(meter_id):
    meter = must("meters", meter_id)
    body = get_body()
    require_fields(body, ["removal_note"])
    want_str(body, "removal_note", min_len=1, max_len=400)
    if meter["install_status"] != "INSTALLED":
        raise ApiError("ERR_METER_NOT_INSTALLED",
                       "only an INSTALLED device is removed")
    household = db.get("households", meter["household_id"])
    if household is None or household["status"] not in (
            "INSTALL_SCHEDULED", "ENUM_PENDING", "NONCOMPLIANT_HOLD",
            "FAULT_HOLD"):
        raise ApiError("ERR_HOUSEHOLD_IN_TAB",
                       "take the household out of tab before pulling equipment")
    meter["install_status"] = "REMOVED"
    db.touch(meter)
    return ok(meter)


@bp.get("/meters/<meter_id>")
@roles(*ALL_ROLES)
def read_meter(meter_id):
    return ok(must("meters", meter_id))


@bp.get("/meters")
@roles(*ALL_ROLES)
def list_meters():
    rows = apply_filters(db.all("meters"), {
        "household_id": ("household_id", "str"),
        "install_status": ("install_status", "str"),
        "health_status": ("health_status", "str"),
        "meter_type": ("meter_type", "str"),
    })
    return listing("meters", rows)
