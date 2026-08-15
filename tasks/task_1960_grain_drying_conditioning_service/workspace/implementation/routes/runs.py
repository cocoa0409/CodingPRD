"""Dryer runs: scheduling, start, completion, abort, cancel (PRD §3.5)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from db import (
    current_date,
    iso_z,
    logical_now,
    parse_datetime,
    public,
    sort_by_creation,
    stamp_new,
    store,
    touch,
)
from errors import raise_err
from middleware import get_ctx, require_roles
from response import success
from routes.helpers import check_grower_on_run, get_lot, get_run, get_ticket, get_unit, scope_by_lot_for_grower
from services.calculations import (
    DRYER_INTAKE_LIMIT_PCT,
    energy_passthrough_charge,
    final_weight_reconciliation,
    find_schedule,
    storage_baseline_bushels,
)
from validation import get_body, opt_bool, paginate, req_datetime, req_int, req_num

bp = Blueprint("runs", __name__)

READ_ROLES = {"ElevatorManager", "Grower", "DryerOperator"}
RUN_TERMINAL = {"COMPLETED", "ABORTED", "CANCELLED"}


def _overlaps(unit_id, cooldown_minutes, new_start, new_end, exclude_id=None):
    """Half-open [start, end) windows; cooldown counts as occupied time
    around each run. Non-cancelled runs only."""
    buffer = timedelta(minutes=cooldown_minutes)
    for r in store.runs.values():
        if r["unit_id"] != unit_id or r["status"] == "CANCELLED" or r["id"] == exclude_id:
            continue
        other_start = parse_datetime(r["scheduled_start"]) - buffer
        other_end = parse_datetime(r["scheduled_end"]) + buffer
        if new_start < other_end and other_start < new_end:
            return True
    return False


@bp.post("/dryer-runs")
def create_run():
    ctx = get_ctx()
    require_roles(ctx, {"DryerOperator"})
    body = get_body()
    # priority 4: body FK existence (unit_id, lot_id, queue_ticket_id — input order)
    unit = None
    lot = None
    if body.get("unit_id") is not None:
        unit = get_unit(body["unit_id"])
    if body.get("lot_id") is not None:
        lot = get_lot(body["lot_id"])
    if body.get("queue_ticket_id") is not None:
        get_ticket(body["queue_ticket_id"])
    # priority 5: shape
    if not isinstance(body.get("unit_id"), str) or not body["unit_id"]:
        raise_err("ERR_INVALID_REQUEST", "Field unit_id is required")
    if not isinstance(body.get("lot_id"), str) or not body["lot_id"]:
        raise_err("ERR_INVALID_REQUEST", "Field lot_id is required")
    if not isinstance(body.get("queue_ticket_id"), str) or not body["queue_ticket_id"]:
        raise_err("ERR_INVALID_REQUEST", "Field queue_ticket_id is required")
    start_s = req_datetime(body, "scheduled_start")
    end_s = req_datetime(body, "scheduled_end")
    start_dt, end_dt = parse_datetime(start_s), parse_datetime(end_s)
    if end_dt <= start_dt:
        raise_err("ERR_INVALID_REQUEST", "scheduled_end must be after scheduled_start")
    # priority 9: dryer safety against the lot's certified intake
    if lot["intake_moisture_pct"] is not None and Decimal(str(lot["intake_moisture_pct"])) > DRYER_INTAKE_LIMIT_PCT:
        raise_err("ERR_MOISTURE_EXCEEDS_DRYER_LIMIT", "intake_moisture_pct exceeds the 26.0 dryer safety limit")
    # priority 10: window overlap including cooldown buffer
    if _overlaps(unit["id"], unit["cooldown_minutes"], start_dt, end_dt):
        raise_err("ERR_RUN_OVERLAP", "Run window collides with another non-cancelled run on the unit within the cooldown buffer")
    rec = stamp_new(
        {
            "unit_id": unit["id"],
            "lot_id": lot["id"],
            "queue_ticket_id": body["queue_ticket_id"],
            "scheduled_start": iso_z(start_dt),
            "scheduled_end": iso_z(end_dt),
            "actual_start": None,
            "actual_end": None,
            "operator_user_id": None,
            "meter_start_therms": None,
            "meter_end_therms": None,
            "energy_estimated": False,
            "scale_out_weight_lbs": None,
            "discharge_moisture_pct": None,
            "fuel_therms": None,
            "energy_charge_cents": None,
            "status": "SCHEDULED",
        }
    )
    store.runs[rec["id"]] = rec
    return success(public(rec), code=201)


@bp.get("/dryer-runs")
def list_runs():
    ctx = get_ctx()
    require_roles(ctx, READ_ROLES)
    records = scope_by_lot_for_grower(ctx, list(store.runs.values()), "lot_id")
    for field in ("lot_id", "unit_id", "queue_ticket_id", "status"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r.get(field) == val]
    records = sort_by_creation(records)
    page, meta = paginate(records, request.args)
    return success([public(r) for r in page], response_type="array", pagination=meta)


@bp.get("/dryer-runs/<rid>")
def get_one_run(rid):
    ctx = get_ctx()
    require_roles(ctx, READ_ROLES)
    rec = get_run(rid)
    check_grower_on_run(ctx, rec)
    return success(public(rec))


@bp.post("/dryer-runs/<rid>/start")
def start_run(rid):
    ctx = get_ctx()
    require_roles(ctx, {"DryerOperator"})
    rec = get_run(rid)
    body = get_body()
    # priority 5: shape
    meter_start = req_num(body, "meter_start_therms")
    # priority 6: state
    if rec["status"] in RUN_TERMINAL:
        raise_err("ERR_ALREADY_TERMINAL", "Dryer run is in a terminal state")
    if rec["status"] != "SCHEDULED":
        raise_err("ERR_INVALID_STATE", "Only a SCHEDULED run may be started")
    lot = store.lots.get(rec["lot_id"])
    if lot is None or lot["status"] != "QUEUED":
        raise_err("ERR_INVALID_STATE", "Lot must be QUEUED to start a run")
    ticket = store.tickets.get(rec["queue_ticket_id"])
    if (
        ticket is None
        or ticket["status"] != "CONFIRMED"
        or ticket["window_date"] != parse_datetime(rec["scheduled_start"]).date().isoformat()
    ):
        raise_err("ERR_INVALID_STATE", "Backing ticket must be CONFIRMED with window_date equal to the scheduled start date")
    for other in store.runs.values():
        if other["unit_id"] == rec["unit_id"] and other["status"] == "IN_PROGRESS":
            raise_err("ERR_INVALID_STATE", "Another run is IN_PROGRESS on the same unit")
    # side effects
    rec["meter_start_therms"] = meter_start
    rec["actual_start"] = iso_z(logical_now())
    rec["_actual_start_dt"] = logical_now()
    rec["operator_user_id"] = ctx["user_id"]
    rec["status"] = "IN_PROGRESS"
    touch(rec)
    ticket["status"] = "CONSUMED"
    touch(ticket)
    lot["status"] = "DRYING"
    touch(lot)
    return success(public(rec))


@bp.post("/dryer-runs/<rid>/complete")
def complete_run(rid):
    ctx = get_ctx()
    require_roles(ctx, {"DryerOperator"})
    rec = get_run(rid)
    body = get_body()
    # priority 5: shape
    scale_out = req_int(body, "scale_out_weight_lbs", minimum=1)
    discharge = req_num(body, "discharge_moisture_pct", minimum=0.0)
    estimated = opt_bool(body, "energy_estimated", default=False)
    meter_end = None
    if not estimated:
        meter_end = req_num(body, "meter_end_therms")
    elif body.get("meter_end_therms") is not None:
        meter_end = req_num(body, "meter_end_therms")
    # priority 6: state
    if rec["status"] in RUN_TERMINAL:
        raise_err("ERR_ALREADY_TERMINAL", "Dryer run is in a terminal state")
    if rec["status"] != "IN_PROGRESS":
        raise_err("ERR_INVALID_STATE", "Only an IN_PROGRESS run may be completed")
    # priority 10: meter sanity for the metered variant
    if not estimated and not (Decimal(str(meter_end)) > Decimal(str(rec["meter_start_therms"]))):
        raise_err("ERR_METER_READING_INVALID", "meter_end_therms must be strictly greater than meter_start_therms")
    lot = store.lots.get(rec["lot_id"])
    # energy pass-through (schedule covering the completion date; none -> zero charge)
    actual_end = logical_now()
    rec["actual_end"] = iso_z(actual_end)
    rec["meter_end_therms"] = meter_end
    rec["energy_estimated"] = estimated
    rec["scale_out_weight_lbs"] = scale_out
    rec["discharge_moisture_pct"] = discharge
    schedule = find_schedule(lot["commodity"], current_date()) if lot is not None else None
    if schedule is not None:
        fuel, charge = energy_passthrough_charge(rec, lot, schedule, actual_end)
        rec["fuel_therms"] = fuel
        rec["energy_charge_cents"] = charge
    else:
        if estimated:
            rec["fuel_therms"] = 0.0
        else:
            rec["fuel_therms"] = float(Decimal(str(meter_end)) - Decimal(str(rec["meter_start_therms"])))
        rec["energy_charge_cents"] = 0
    rec["status"] = "COMPLETED"
    touch(rec)
    # final weight reconciliation on the lot
    final_dry, final_shrink, variance = final_weight_reconciliation(lot, scale_out)
    lot["final_dry_weight_lbs"] = final_dry
    lot["final_shrink_pct"] = final_shrink
    lot["shrink_variance_lbs"] = variance
    lot["current_moisture_pct"] = discharge
    # storage cascade: exactly one RESERVED agreement -> activate, lot -> STORED
    reserved = [
        a for a in store.agreements.values()
        if a["lot_id"] == lot["id"] and a["status"] == "RESERVED"
    ]
    if reserved:
        agreement = reserved[0]
        agreement["baseline_bushels"] = storage_baseline_bushels(lot)
        agreement["start_date"] = current_date().isoformat()
        agreement["accrued_days"] = 0
        agreement["accrued_storage_cents"] = 0
        agreement["status"] = "ACTIVE"
        touch(agreement)
        lot["status"] = "STORED"
    else:
        lot["status"] = "DRIED"
    touch(lot)
    return success(public(rec))


@bp.post("/dryer-runs/<rid>/abort")
def abort_run(rid):
    ctx = get_ctx()
    require_roles(ctx, {"DryerOperator"})
    rec = get_run(rid)
    if rec["status"] in RUN_TERMINAL:
        raise_err("ERR_ALREADY_TERMINAL", "Dryer run is in a terminal state")
    if rec["status"] != "IN_PROGRESS":
        raise_err("ERR_INVALID_STATE", "Only an IN_PROGRESS run may be aborted")
    rec["status"] = "ABORTED"
    touch(rec)
    # compensation pair: ticket CONSUMED -> CONFIRMED, lot DRYING -> QUEUED
    ticket = store.tickets.get(rec["queue_ticket_id"])
    if ticket is not None and ticket["status"] == "CONSUMED":
        ticket["status"] = "CONFIRMED"
        touch(ticket)
    lot = store.lots.get(rec["lot_id"])
    if lot is not None and lot["status"] == "DRYING":
        lot["status"] = "QUEUED"
        touch(lot)
    return success(public(rec))


@bp.post("/dryer-runs/<rid>/cancel")
def cancel_run(rid):
    ctx = get_ctx()
    require_roles(ctx, {"DryerOperator"})
    rec = get_run(rid)
    if rec["status"] in RUN_TERMINAL:
        raise_err("ERR_ALREADY_TERMINAL", "Dryer run is in a terminal state")
    if rec["status"] != "SCHEDULED":
        raise_err("ERR_INVALID_STATE", "Only a SCHEDULED run may be cancelled")
    rec["status"] = "CANCELLED"
    touch(rec)
    return success(public(rec))
