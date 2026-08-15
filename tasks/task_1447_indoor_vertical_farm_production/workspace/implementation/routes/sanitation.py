"""Routes: sanitation cycles."""

from datetime import timedelta

from flask import Blueprint

from db import store
from errors import raise_error
from middleware import require_roles, ALL_ROLES
from response import success, list_response
from util import get_body, get_body_optional, pagination_params, parse_dt, req_enum, req_int
from services.core import (
    stamp_new, touch, logical_now,
    get_cycle, get_loop, ser_cycle, loop_posture, recompute_loop_schedule,
    batches_on_loop, recompute_shipment_aggregates, batch_lines,
    SANITATION_BUFFER_HOURS, MIN_CYCLE_HOURS, MAX_CYCLE_HOURS,
    SANITATION_EARLY_START_MINUTES, SANITATION_RESULTS,
)

bp = Blueprint("sanitation", __name__)


def _q(name):
    from flask import request
    v = request.args.get(name)
    return v if v not in (None, "") else None


@bp.post("/sanitation-cycles")
def create_cycle():
    require_roles("SanitationLead")
    body = get_body({"water_loop_id", "scheduled_start_at", "scheduled_end_at", "parent_cycle_id"},
                    {"water_loop_id", "scheduled_start_at", "scheduled_end_at"})
    loop_id = body["water_loop_id"]
    if not isinstance(loop_id, str):
        raise_error("ERR_INVALID_REQUEST", "water_loop_id must be a string")
    loop = store.water_loops.get(loop_id)
    if loop is None:
        raise_error("ERR_NOT_FOUND", "WaterLoop not found")
    parent_id = body.get("parent_cycle_id")
    parent = None
    if parent_id is not None:
        if not isinstance(parent_id, str):
            raise_error("ERR_INVALID_REQUEST", "parent_cycle_id must be a string")
        parent = store.sanitation_cycles.get(parent_id)
        if parent is None:
            raise_error("ERR_NOT_FOUND", "Parent cycle not found")
    start = parse_dt(body["scheduled_start_at"], "scheduled_start_at")
    end = parse_dt(body["scheduled_end_at"], "scheduled_end_at")
    if end <= start:
        raise_error("ERR_CYCLE_DURATION_INVALID", "end must be after start")
    duration_hours = (end - start).total_seconds() / 3600.0
    if duration_hours < MIN_CYCLE_HOURS or duration_hours > MAX_CYCLE_HOURS:
        raise_error("ERR_CYCLE_DURATION_INVALID", "Cycle duration must be within [2h, 12h]")
    # closed-interval overlap + 4h buffer against SCHEDULED / IN_PROGRESS cycles on same loop
    buf = timedelta(hours=SANITATION_BUFFER_HOURS)
    for c in store.sanitation_cycles.values():
        if c["water_loop_id"] != loop["id"]:
            continue
        if c["cycle_status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        # buffered windows: closed-interval overlap, plus a 4-hour buffer that a
        # gap of exactly 4 hours satisfies (PRD §3.4: "respect a 4-hour buffer")
        if start < c["scheduled_end_at"] + buf and c["scheduled_start_at"] - buf < end:
            raise_error("ERR_SANITATION_OVERLAP", "Sanitation window overlap or buffer violation")
    cycle = stamp_new({
        "water_loop_id": loop["id"],
        "parent_cycle_id": parent["id"] if parent else None,
        "scheduled_start_at": start,
        "scheduled_end_at": end,
        "started_at": None,
        "completed_at": None,
        "result": None,
        "coliform_cfu": None,
        "result_recorded_by": None,
        "cycle_status": "SCHEDULED",
    })
    store.sanitation_cycles[cycle["id"]] = cycle
    return success(ser_cycle(cycle), status=201)


@bp.get("/sanitation-cycles")
def list_cycles():
    require_roles(*ALL_ROLES)
    limit, offset = pagination_params()
    items = list(store.sanitation_cycles.values())
    wl = _q("water_loop_id")
    st = _q("cycle_status")
    pc = _q("parent_cycle_id")
    if wl is not None:
        items = [c for c in items if c["water_loop_id"] == wl]
    if st is not None:
        items = [c for c in items if c["cycle_status"] == st]
    if pc is not None:
        items = [c for c in items if c.get("parent_cycle_id") == pc]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    return list_response(items, ser_cycle, limit, offset)


@bp.get("/sanitation-cycles/<cid>")
def get_cycle_route(cid):
    require_roles(*ALL_ROLES)
    return success(ser_cycle(get_cycle(cid)))


@bp.post("/sanitation-cycles/<cid>/start")
def start_cycle(cid):
    require_roles("SanitationLead")
    get_body_optional(set())
    cycle = get_cycle(cid)
    if cycle["cycle_status"] != "SCHEDULED":
        raise_error("ERR_INVALID_STATE_TRANSITION", "Cycle not SCHEDULED")
    loop = get_loop(cycle["water_loop_id"])
    if loop_posture(loop) not in ("IN_SERVICE", "SANITATION_DUE", "SANITATION_HOLD"):
        raise_error("ERR_WATER_LOOP_SANITATION_HOLD", "Loop posture does not permit start")
    # harvest-in-flight gate
    for b in batches_on_loop(loop["id"]):
        if b["production_status"] in ("HARVEST_READY", "HARVESTED"):
            raise_error("ERR_HARVEST_IN_FLIGHT", "Batch HARVEST_READY/HARVESTED on loop")
    now = logical_now()
    if now < cycle["scheduled_start_at"] - timedelta(minutes=SANITATION_EARLY_START_MINUTES):
        raise_error("ERR_CYCLE_NOT_DUE", "Cycle not due")
    cycle["started_at"] = now
    cycle["cycle_status"] = "IN_PROGRESS"
    touch(cycle)
    # side effects: OPERATING racks on loop -> SANITATION_HOLD
    for rack in store.racks.values():
        if rack["water_loop_id"] == loop["id"] and rack["rack_posture"] == "OPERATING":
            rack["rack_posture"] = "SANITATION_HOLD"
            touch(rack)
    touch(loop)
    return success(ser_cycle(cycle))


@bp.post("/sanitation-cycles/<cid>/record-result")
def record_result(cid):
    user_id, _ = require_roles("SanitationLead")
    body = get_body({"result", "coliform_cfu"}, {"result", "coliform_cfu"})
    result = req_enum(body["result"], "result", SANITATION_RESULTS)
    cfu = req_int(body["coliform_cfu"], "coliform_cfu")
    if cfu < 0:
        raise_error("ERR_INVALID_REQUEST", "coliform_cfu must be non-negative")
    cycle = get_cycle(cid)
    # segregation of duties on retests (priority 3)
    if cycle.get("parent_cycle_id"):
        parent = store.sanitation_cycles.get(cycle["parent_cycle_id"])
        if parent is not None and parent.get("result_recorded_by") is not None \
                and parent["result_recorded_by"] == user_id:
            raise_error("ERR_SEGREGATION_OF_DUTIES", "Retest must be recorded by a different user")
    if cycle["cycle_status"] != "IN_PROGRESS":
        raise_error("ERR_INVALID_STATE_TRANSITION", "Cycle not IN_PROGRESS")
    now = logical_now()
    cycle["result"] = result
    cycle["coliform_cfu"] = cfu
    cycle["result_recorded_by"] = user_id
    cycle["completed_at"] = now
    cycle["cycle_status"] = result
    touch(cycle)
    loop = get_loop(cycle["water_loop_id"])
    if result == "PASSED":
        # loop -> IN_SERVICE: recompute schedule; racks -> OPERATING; QUARANTINED batches -> PENDING
        recompute_loop_schedule(loop)
        touch(loop)
        for rack in store.racks.values():
            if rack["water_loop_id"] == loop["id"] and rack["rack_posture"] == "SANITATION_HOLD":
                rack["rack_posture"] = "OPERATING"
                touch(rack)
        for b in batches_on_loop(loop["id"]):
            if b["safety_status"] == "QUARANTINED":
                b["safety_status"] = "PENDING"
                touch(b)
        # shipments recompute has_safety_block
        affected = set()
        for b in batches_on_loop(loop["id"]):
            for l in batch_lines(b["id"]):
                affected.add(l["shipment_id"])
        for sid in affected:
            s = store.shipments.get(sid)
            if s is not None:
                recompute_shipment_aggregates(s)
                touch(s)
    else:  # FAILED
        touch(loop)
        # racks stay SANITATION_HOLD; batches -> QUARANTINED
        rack_ids = {r["id"] for r in store.racks.values() if r["water_loop_id"] == loop["id"]}
        for b in batches_on_loop(loop["id"]):
            if b["production_status"] in ("SEEDED", "GROWING", "AT_RISK", "HARVEST_READY", "HARVESTED", "PACKED"):
                if b["safety_status"] in ("PENDING", "RELEASED"):
                    b["safety_status"] = "QUARANTINED"
                    touch(b)
        affected = set()
        for b in batches_on_loop(loop["id"]):
            for l in batch_lines(b["id"]):
                if l["line_status"] in ("RESERVED", "PACKED", "SHORTED"):
                    affected.add(l["shipment_id"])
        for sid in affected:
            s = store.shipments.get(sid)
            if s is not None:
                recompute_shipment_aggregates(s)
                touch(s)
    return success(ser_cycle(cycle))


@bp.post("/sanitation-cycles/<cid>/cancel")
def cancel_cycle(cid):
    require_roles("SanitationLead")
    get_body_optional(set())
    cycle = get_cycle(cid)
    if cycle["cycle_status"] != "SCHEDULED":
        raise_error("ERR_INVALID_STATE_TRANSITION", "Cycle not SCHEDULED")
    cycle["cycle_status"] = "CANCELED"
    touch(cycle)
    return success(ser_cycle(cycle))
