"""Meter capture, exception handling, voiding and the period sweep (PRD 3.4)."""
from flask import Blueprint

import calc
import cascade
import derive
import serialize
import validation as v
from auth import require
from envelope import created, ok, ok_list
from errors import fail
from resolve import get_device, get_period, get_read
from store import db, new_row, touch
from util import overlaps

bp = Blueprint("meters", __name__)

VOID_REASONS = ("WRONG_DEVICE", "DUPLICATE_CAPTURE", "CUSTOMER_DISPUTE")
METERABLE_STATES = ("ACTIVE", "SERVICE_HOLD")
BLOCKING_READ_STATES = ("PENDING_VALIDATION", "ACCEPTED")


def _intake(user_id, source):
    body = v.body()
    device_id = v.id_field(body, "device_id")
    period_id = v.id_field(body, "billing_period_id")
    mono_meter = v.int_field(body, "mono_meter", minimum=0)
    color_meter = v.int_field(body, "color_meter", minimum=0)
    toner_level = v.int_field(body, "toner_level_pct", minimum=0, maximum=100)
    coverage_start = v.dt_field(body, "coverage_start")
    coverage_end = v.dt_field(body, "coverage_end")

    device = get_device(device_id)
    period = get_period(period_id)

    contract = derive.device_contract(device)
    if contract is None or contract["status"] != "ACTIVE":
        fail("ERR_CONTRACT_NOT_ACTIVE", "The governing contract is not ACTIVE.")
    if period["status"] == "CLOSED":
        fail("ERR_PERIOD_ALREADY_CLOSED", "The billing period is already CLOSED.")
    if (device["contract_id"] != period["contract_id"]
            or not (period["period_start"] <= coverage_end < period["period_end"])):
        fail("ERR_READ_OUTSIDE_PERIOD",
             "coverage_end must fall inside the period's half-open window.")
    if device["lifecycle_state"] not in METERABLE_STATES:
        fail("ERR_DEVICE_NOT_METERABLE",
             "A device in %s is not meterable." % device["lifecycle_state"])
    if coverage_start >= coverage_end:
        fail("ERR_READ_INTERVAL_OVERLAP",
             "coverage_start must be strictly earlier than coverage_end.")
    for other in derive.device_reads(device["id"]):
        if other["status"] not in BLOCKING_READ_STATES:
            continue
        if overlaps(coverage_start, coverage_end,
                    other["coverage_start"], other["coverage_end"]):
            fail("ERR_READ_INTERVAL_OVERLAP",
                 "The coverage interval intersects an existing reading of this device.")

    row = new_row()
    row.update({
        "device_id": device["id"],
        "billing_period_id": period["id"],
        "source": source,
        "status": "PENDING_VALIDATION",
        "mono_meter": mono_meter,
        "color_meter": color_meter,
        "toner_level_pct": toner_level,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "mono_delta": 0,
        "color_delta": 0,
        "exception_reason": "NONE",
        "read_at": db.clock,
        "submitted_by_user_id": user_id,
        "resolved_by_user_id": None,
        "resolution_note": None,
        "voided_reason": "NONE",
    })
    db.meter_reads[row["id"]] = row

    status, reason, mono_delta, color_delta = calc.validate_read(row, device)
    if status == "ACCEPTED":
        cascade.accept_read(row, device, mono_delta, color_delta)
    else:
        cascade.reject_read(row, reason)
    return created(serialize.meter_read(row))


@bp.post("/_agent/meter-reads")
def agent_meter_read():
    user_id, _role = require("FleetOpsController")
    return _intake(user_id, "AUTOMATED")


@bp.post("/meter-reads")
def manual_meter_read():
    user_id, _role = require("FieldTechnician")
    return _intake(user_id, "MANUAL")


@bp.get("/meter-reads/<read_id>")
def read_meter_read(read_id):
    require("FleetOpsController", "BillingAnalyst", "FieldTechnician", "AccountManager")
    read = get_read(read_id)
    return ok(serialize.meter_read(read))


@bp.get("/meter-reads")
def list_meter_reads():
    require("FleetOpsController", "BillingAnalyst", "FieldTechnician", "AccountManager")
    rows = db.sorted_rows("meter_reads")
    for field in ("device_id", "billing_period_id", "status", "source"):
        value = v.query_filter(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    data, meta = v.paginate(rows, serialize.meter_read)
    return ok_list(data, meta)


@bp.post("/meter-reads/<read_id>/resolve-exception")
def resolve_exception(read_id):
    user_id, _role = require("FleetOpsController")
    read = get_read(read_id)
    body = v.body()
    mono_meter = v.int_field(body, "corrected_mono_meter", minimum=0)
    color_meter = v.int_field(body, "corrected_color_meter", minimum=0)
    toner_level = v.int_field(body, "corrected_toner_level_pct", minimum=0, maximum=100)
    note = v.string_field(body, "resolution_note", non_empty=False)

    if read["status"] != "EXCEPTION":
        fail("ERR_READ_INVALID_STATE",
             "A reading in %s cannot be resolved." % read["status"])
    period = db.periods.get(read["billing_period_id"])
    if period is not None and period["status"] == "CLOSED":
        fail("ERR_PERIOD_ALREADY_CLOSED", "The billing period is already CLOSED.")
    if user_id == read["submitted_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The resolver must differ from the reading's submitter.")

    device = db.devices.get(read["device_id"])
    read["mono_meter"] = mono_meter
    read["color_meter"] = color_meter
    read["toner_level_pct"] = toner_level
    read["resolution_note"] = note
    read["resolved_by_user_id"] = user_id
    read["status"] = "PENDING_VALIDATION"
    read["exception_reason"] = "NONE"
    touch(read)

    status, reason, mono_delta, color_delta = calc.validate_read(read, device)
    if status == "ACCEPTED":
        cascade.accept_read(read, device, mono_delta, color_delta)
    else:
        cascade.reject_read(read, reason)
    return ok(serialize.meter_read(read))


@bp.post("/meter-reads/<read_id>/void")
def void_meter_read(read_id):
    require("FleetOpsController")
    read = get_read(read_id)
    body = v.body()
    voided_reason = v.enum_field(body, "voided_reason", VOID_REASONS)

    if read["status"] != "ACCEPTED":
        fail("ERR_READ_INVALID_STATE",
             "A reading in %s cannot be voided." % read["status"])
    period = db.periods.get(read["billing_period_id"])
    if period is not None and period["status"] == "CLOSED":
        fail("ERR_PERIOD_ALREADY_CLOSED", "The billing period is already CLOSED.")
    newest = derive.newest_accepted_read(read["device_id"])
    if newest is None or newest["id"] != read["id"]:
        fail("ERR_READ_NOT_NEWEST",
             "Only the newest ACCEPTED reading of the device may be voided.")

    device = db.devices.get(read["device_id"])
    cascade.void_read(read, device, voided_reason)
    return ok(serialize.meter_read(read))


@bp.post("/billing-periods/<period_id>/meter-sweep")
def meter_sweep(period_id):
    user_id, _role = require("FleetOpsController")
    period = get_period(period_id)
    v.body()
    if period["status"] not in ("OPEN", "SWEPT"):
        fail("ERR_PERIOD_INVALID_STATE",
             "A period in %s cannot be swept." % period["status"])
    contract = db.contracts.get(period["contract_id"])
    if contract is None or contract["status"] != "ACTIVE":
        fail("ERR_CONTRACT_NOT_ACTIVE", "The governing contract is not ACTIVE.")

    for device in derive.contract_devices(contract["id"]):
        if device["lifecycle_state"] not in METERABLE_STATES:
            continue
        reads = derive.device_reads(device["id"])
        covered = False
        already_swept = False
        for read in reads:
            in_window = (period["period_start"] <= read["coverage_end"]
                         < period["period_end"])
            if read["status"] == "ACCEPTED" and in_window:
                covered = True
            if (read["billing_period_id"] == period["id"]
                    and read["source"] == "SWEEP_ESTIMATE"
                    and read["status"] == "EXCEPTION"):
                already_swept = True
        if covered or already_swept:
            continue
        row = new_row()
        row.update({
            "device_id": device["id"],
            "billing_period_id": period["id"],
            "source": "SWEEP_ESTIMATE",
            "status": "EXCEPTION",
            "mono_meter": device["last_accepted_mono_meter"],
            "color_meter": device["last_accepted_color_meter"],
            "toner_level_pct": device["toner_level_pct"],
            "coverage_start": period["period_start"],
            "coverage_end": db.clock,
            "mono_delta": 0,
            "color_delta": 0,
            "exception_reason": "DEVICE_OFFLINE",
            "read_at": db.clock,
            "submitted_by_user_id": user_id,
            "resolved_by_user_id": None,
            "resolution_note": None,
            "voided_reason": "NONE",
        })
        db.meter_reads[row["id"]] = row

    period["status"] = "SWEPT"
    period["sweep_run_count"] += 1
    touch(period)
    return ok(serialize.period(period))
