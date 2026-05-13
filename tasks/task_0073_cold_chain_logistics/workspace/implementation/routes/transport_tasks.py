"""TransportTask routes including state transitions and stop operations."""

import math
from datetime import timedelta

from flask import Blueprint, request

from clock import clock, parse_iso8601
from db import db, new_id
from errors import err
from middleware import require_roles, auth_context
from response import object_response, array_response
from serializers import (
    task as ser_task,
    task_stop as ser_stop,
    handover as ser_handover,
)
from services import audit
from validators import (
    get_pagination,
    paginate,
    require_dict,
    require_int,
    require_str,
    require_enum,
    require_number,
    require_iso,
    require_list,
    require_bool,
)


bp = Blueprint("transport_tasks", __name__)

CARGO_TYPES = {"FOOD", "PHARMACEUTICAL", "BIOLOGICAL"}
TASK_TERMINAL = {"CLOSED", "ABORTED"}
TASK_ACTIVE = {"DISPATCHED", "IN_TRANSIT", "AT_STOP"}


def _bump(task: dict):
    task["updated_at"] = clock.now_iso()
    task["version"] = task.get("version", 0) + 1


def _bump_stop(stop: dict):
    stop["updated_at"] = clock.now_iso()
    stop["version"] = stop.get("version", 0) + 1


def _bump_vehicle(vehicle: dict):
    if vehicle is not None:
        vehicle["updated_at"] = clock.now_iso()
        vehicle["version"] = vehicle.get("version", 0) + 1


def _bump_driver(driver: dict):
    if driver is not None:
        driver["updated_at"] = clock.now_iso()
        driver["version"] = driver.get("version", 0) + 1


# ----------------------------- Create / list / fetch / patch ------------------

@bp.post("/transport-tasks")
@require_roles("SHIPPER", "DISPATCHER")
def create_task():
    body = require_dict(request.get_json(silent=True) or {})
    cargo_type = require_enum(body.get("cargo_type"), CARGO_TYPES, field="cargo_type")
    cargo_value_cents = require_int(
        body.get("cargo_value_cents"), field="cargo_value_cents", min_val=1
    )
    cargo_quantity = require_int(body.get("cargo_quantity"), field="cargo_quantity", min_val=1)

    temp_min = body.get("temp_min_celsius")
    temp_max = body.get("temp_max_celsius")
    require_number(temp_min, field="temp_min_celsius", gt=-80.0)
    require_number(temp_max, field="temp_max_celsius", lt=80.0)
    if not (temp_min < temp_max):
        err("ERR_VALIDATION", "temp_min_celsius must be < temp_max_celsius.")

    shipper_id = require_str(body.get("shipper_id"), field="shipper_id", min_len=1)
    consignee_id = require_str(body.get("consignee_id"), field="consignee_id", min_len=1)
    carrier_id = require_str(body.get("carrier_id"), field="carrier_id", min_len=1)

    planned_start_at_str = body.get("planned_start_at")
    planned_end_at_str = body.get("planned_end_at")
    require_iso(planned_start_at_str, field="planned_start_at")
    require_iso(planned_end_at_str, field="planned_end_at")
    planned_start_at = parse_iso8601(planned_start_at_str)
    planned_end_at = parse_iso8601(planned_end_at_str)
    if planned_start_at < clock.now() - timedelta(seconds=1):
        # planned_start_at must be >= current clock at moment of creation
        # Allow up to 1 second tolerance for clock-tick races
        err("ERR_VALIDATION", "planned_start_at must be >= current clock.")
    if not (planned_end_at > planned_start_at):
        err("ERR_VALIDATION", "planned_end_at must be > planned_start_at.")

    polling = body.get("polling_interval_seconds")
    if polling is None:
        polling = 60
    else:
        polling = require_int(
            polling, field="polling_interval_seconds", min_val=10, max_val=3600
        )

    stops_input = require_list(body.get("stops"), field="stops", min_len=1)

    # Body-FK validation: vehicle_id / driver_id (optional at creation)
    vehicle_id = body.get("vehicle_id")
    driver_id = body.get("driver_id")
    if vehicle_id is not None and not db.vehicles.exists(vehicle_id):
        err("ERR_REFERENCE_NOT_FOUND", "vehicle_id does not exist.")
    if driver_id is not None and not db.drivers.exists(driver_id):
        err("ERR_REFERENCE_NOT_FOUND", "driver_id does not exist.")

    # Validate stops (sequence/labels/arrival monotonicity)
    seen_seqs = set()
    last_arrival = None
    parsed_stops = []
    for idx, s in enumerate(stops_input):
        if not isinstance(s, dict):
            err("ERR_VALIDATION", f"stops[{idx}] must be an object.")
        seq = require_int(s.get("sequence"), field=f"stops[{idx}].sequence", min_val=1)
        if seq in seen_seqs:
            err("ERR_VALIDATION", f"stops[{idx}].sequence duplicate.")
        seen_seqs.add(seq)
        label = require_str(
            s.get("location_label"), field=f"stops[{idx}].location_label", min_len=1, max_len=200
        )
        arrival_str = s.get("planned_arrival_at")
        require_iso(arrival_str, field=f"stops[{idx}].planned_arrival_at")
        arrival = parse_iso8601(arrival_str)
        handover_required = s.get("handover_required")
        if handover_required is None:
            handover_required = True
        else:
            handover_required = require_bool(
                handover_required, field=f"stops[{idx}].handover_required"
            )
        parsed_stops.append(
            {
                "sequence": seq,
                "location_label": label,
                "planned_arrival_at": arrival_str,
                "planned_arrival_at_dt": arrival,
                "handover_required": handover_required,
            }
        )

    parsed_stops.sort(key=lambda s: s["sequence"])
    for i in range(1, len(parsed_stops)):
        if not (parsed_stops[i]["planned_arrival_at_dt"] > parsed_stops[i - 1]["planned_arrival_at_dt"]):
            err(
                "ERR_VALIDATION",
                f"stops[{i}].planned_arrival_at must be > preceding stop's planned_arrival_at.",
            )

    now_iso = clock.now_iso()
    task_row = {
        "id": new_id(),
        "cargo_type": cargo_type,
        "cargo_value_cents": cargo_value_cents,
        "cargo_quantity": cargo_quantity,
        "temp_min_celsius": float(temp_min),
        "temp_max_celsius": float(temp_max),
        "shipper_id": shipper_id,
        "consignee_id": consignee_id,
        "carrier_id": carrier_id,
        "vehicle_id": vehicle_id,
        "driver_id": driver_id,
        "planned_start_at": planned_start_at_str,
        "planned_end_at": planned_end_at_str,
        "polling_interval_seconds": polling,
        "status": "PLANNED",
        "closed_at": None,
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    db.tasks.put(task_row)

    for s in parsed_stops:
        stop_row = {
            "id": new_id(),
            "task_id": task_row["id"],
            "sequence": s["sequence"],
            "location_label": s["location_label"],
            "planned_arrival_at": s["planned_arrival_at"],
            "actual_arrival_at": None,
            "status": "PENDING",
            "handover_required": s["handover_required"],
            "created_at": now_iso,
            "updated_at": now_iso,
            "version": 1,
        }
        db.stops.put(stop_row)

    return object_response(ser_task(task_row), status_code=201)


@bp.get("/transport-tasks/<task_id>")
@require_roles(
    "SHIPPER", "CARRIER", "DRIVER", "CONSIGNEE", "DISPATCHER",
    "COMPLIANCE_OFFICER", "INSURANCE_ADJUSTER",
)
def get_task(task_id):
    task = db.tasks.get(task_id)
    if task is None:
        err("ERR_NOT_FOUND", "TransportTask not found.")
    return object_response(ser_task(task))


@bp.patch("/transport-tasks/<task_id>")
@require_roles("DISPATCHER")
def patch_task(task_id):
    task = db.tasks.get(task_id)
    if task is None:
        err("ERR_NOT_FOUND", "TransportTask not found.")
    body = require_dict(request.get_json(silent=True) or {})

    # body-FK existence
    if "vehicle_id" in body and body["vehicle_id"] is not None:
        if not db.vehicles.exists(body["vehicle_id"]):
            err("ERR_REFERENCE_NOT_FOUND", "vehicle_id does not exist.")
    if "driver_id" in body and body["driver_id"] is not None:
        if not db.drivers.exists(body["driver_id"]):
            err("ERR_REFERENCE_NOT_FOUND", "driver_id does not exist.")

    # state eligibility: vehicle_id/driver_id only mutable in PLANNED
    if "vehicle_id" in body or "driver_id" in body:
        if task["status"] != "PLANNED":
            err("ERR_INVALID_STATE", "vehicle_id/driver_id only mutable in PLANNED.")

    # OCC check
    if "version" in body:
        if body["version"] != task["version"]:
            err("ERR_VERSION_CONFLICT", "version mismatch.")

    # field validation
    if "polling_interval_seconds" in body and body["polling_interval_seconds"] is not None:
        require_int(
            body["polling_interval_seconds"],
            field="polling_interval_seconds",
            min_val=10,
            max_val=3600,
        )

    # Apply
    if "vehicle_id" in body:
        task["vehicle_id"] = body["vehicle_id"]
    if "driver_id" in body:
        task["driver_id"] = body["driver_id"]
    if "polling_interval_seconds" in body and body["polling_interval_seconds"] is not None:
        task["polling_interval_seconds"] = body["polling_interval_seconds"]

    _bump(task)
    return object_response(ser_task(task))


@bp.get("/transport-tasks")
@require_roles("SHIPPER", "CARRIER", "DISPATCHER", "COMPLIANCE_OFFICER")
def list_tasks():
    limit, offset = get_pagination(request.args)
    rows = db.tasks.all()

    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    cargo_type = request.args.get("cargo_type")
    if cargo_type:
        rows = [r for r in rows if r["cargo_type"] == cargo_type]
    after = request.args.get("planned_start_after")
    if after:
        after_dt = parse_iso8601(after)
        if after_dt is None:
            err("ERR_VALIDATION", "planned_start_after must be ISO 8601.")
        rows = [r for r in rows if parse_iso8601(r["planned_start_at"]) >= after_dt]
    before = request.args.get("planned_start_before")
    if before:
        before_dt = parse_iso8601(before)
        if before_dt is None:
            err("ERR_VALIDATION", "planned_start_before must be ISO 8601.")
        rows = [r for r in rows if parse_iso8601(r["planned_start_at"]) < before_dt]

    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return array_response(
        [ser_task(r) for r in page], limit=limit, offset=offset, total_count=total
    )


# ----------------------------- Dispatch ---------------------------------------

def _intervals_overlap_half_open(a_start, a_end, b_start, b_end) -> bool:
    """Half-open [start, end). Adjacency (a.end == b.start) is NOT overlap."""
    return a_start < b_end and b_start < a_end


def _ceil_minutes(seconds: float) -> int:
    return math.ceil(seconds / 60)


def _overlap_minutes(task_start, task_end, win_start, win_end) -> int:
    start = max(task_start, win_start)
    end = min(task_end, win_end)
    if end <= start:
        return 0
    return _ceil_minutes((end - start).total_seconds())


def _check_vehicle_overlap(task, vehicle):
    new_start = parse_iso8601(task["planned_start_at"])
    new_end = parse_iso8601(task["planned_end_at"])
    for t in db.tasks.all():
        if t["id"] == task["id"]:
            continue
        if t.get("vehicle_id") != vehicle["id"]:
            continue
        if t["status"] not in TASK_ACTIVE:
            continue
        ex_start = parse_iso8601(t["planned_start_at"])
        ex_end = parse_iso8601(t["planned_end_at"])
        if _intervals_overlap_half_open(new_start, new_end, ex_start, ex_end):
            err("ERR_VEHICLE_OVERLAP", "Vehicle has an overlapping active task.")


def _check_driver_hours(task, driver):
    new_start = parse_iso8601(task["planned_start_at"])
    new_end = parse_iso8601(task["planned_end_at"])
    max_minutes = driver["max_daily_minutes"]

    # Collect all driver-assigned active tasks (excluding the candidate)
    existing = []
    for t in db.tasks.all():
        if t["id"] == task["id"]:
            continue
        if t.get("driver_id") != driver["id"]:
            continue
        if t["status"] not in TASK_ACTIVE:
            continue
        existing.append(
            (parse_iso8601(t["planned_start_at"]), parse_iso8601(t["planned_end_at"]))
        )

    # Anchor windows: candidate's planned_start_at, planned_end_at, and each
    # boundary from existing tasks. Each candidate window is [t - 86400, t].
    anchors = {new_start, new_end}
    for s, e in existing:
        anchors.add(s)
        anchors.add(e)

    for anchor in anchors:
        win_start = anchor - timedelta(seconds=86400)
        win_end = anchor
        # Driver accumulated minutes from existing tasks in this window
        total = 0
        for s, e in existing:
            total += _overlap_minutes(s, e, win_start, win_end)
        # Plus overlap of new task with the window
        total += _overlap_minutes(new_start, new_end, win_start, win_end)
        if total > max_minutes:
            err(
                "ERR_DRIVER_HOURS_EXCEEDED",
                "Driver rolling 24h minutes would exceed max_daily_minutes.",
            )


@bp.post("/transport-tasks/<task_id>/dispatch")
@require_roles("DISPATCHER")
def dispatch(task_id):
    with db.global_lock:
        task = db.tasks.get(task_id)
        if task is None:
            err("ERR_NOT_FOUND", "TransportTask not found.")
        if task["status"] != "PLANNED":
            err("ERR_INVALID_STATE", "Task must be PLANNED to dispatch.")

        vehicle = db.vehicles.get(task.get("vehicle_id"))
        if vehicle is None:
            err("ERR_INVALID_STATE", "Task vehicle_id is not assigned.")

        driver = db.drivers.get(task.get("driver_id"))
        if driver is None:
            err("ERR_INVALID_STATE", "Task driver_id is not assigned.")

        stops = db.stops_for_task(task["id"])
        if len(stops) < 2:
            err("ERR_INVALID_STATE", "Task must have at least 2 stops.")

        # PRD §3.3 + §2.6: when the vehicle is already IN_USE (or driver ON_DUTY)
        # due to a prior dispatch, the rejection must surface via the
        # overlap / hours checks rather than as a bare ERR_INVALID_STATE.
        # PRD §2.6: "When two dispatch requests race for the same Vehicle,
        #  ... the second is rejected with ERR_VEHICLE_OVERLAP; the second
        #  caller, on re-read, sees the vehicle already IN_USE."
        # The overlap and hours checks below are what enforce the
        # AVAILABLE/OFF_DUTY rule under multi-task scheduling.
        _check_vehicle_overlap(task, vehicle)
        _check_driver_hours(task, driver)

        # Mutate
        task["status"] = "DISPATCHED"
        vehicle["status"] = "IN_USE"
        driver["status"] = "ON_DUTY"
        _bump(task)
        _bump_vehicle(vehicle)
        _bump_driver(driver)
    return object_response(ser_task(task))


# ----------------------------- Depart / arrive / depart-stop ------------------

@bp.post("/transport-tasks/<task_id>/depart")
@require_roles("DRIVER")
def depart(task_id):
    task = db.tasks.get(task_id)
    if task is None:
        err("ERR_NOT_FOUND", "TransportTask not found.")
    if task["status"] != "DISPATCHED":
        err("ERR_INVALID_STATE", "Task must be DISPATCHED to depart.")
    planned_start = parse_iso8601(task["planned_start_at"])
    if clock.now() < planned_start - timedelta(seconds=3600):
        err(
            "ERR_INVALID_STATE",
            "Cannot depart earlier than 1 hour before planned_start_at.",
        )
    # Side effect: first stop PENDING -> ARRIVED
    stops = db.stops_for_task(task_id)
    if stops and stops[0]["status"] == "PENDING":
        stop = stops[0]
        stop["status"] = "ARRIVED"
        stop["actual_arrival_at"] = clock.now_iso()
        _bump_stop(stop)
    task["status"] = "IN_TRANSIT"
    _bump(task)
    return object_response(ser_task(task))


@bp.post("/transport-tasks/<task_id>/stops/<stop_id>/arrive")
@require_roles("DRIVER")
def arrive(task_id, stop_id):
    task = db.tasks.get(task_id)
    if task is None:
        err("ERR_NOT_FOUND", "TransportTask not found.")
    stop = db.stops.get(stop_id)
    if stop is None or stop["task_id"] != task_id:
        err("ERR_NOT_FOUND", "TaskStop not found.")
    if task["status"] != "IN_TRANSIT":
        err("ERR_INVALID_STATE", "Task must be IN_TRANSIT to arrive.")
    if stop["status"] != "PENDING":
        err("ERR_INVALID_STATE", "Stop must be PENDING to arrive.")
    # Must be lowest-sequence PENDING stop
    stops = db.stops_for_task(task_id)
    pending = [s for s in stops if s["status"] == "PENDING"]
    if pending and pending[0]["id"] != stop_id:
        err("ERR_INVALID_STATE", "Stop is not the lowest-sequence PENDING stop.")

    stop["status"] = "ARRIVED"
    stop["actual_arrival_at"] = clock.now_iso()
    _bump_stop(stop)
    task["status"] = "AT_STOP"
    _bump(task)
    return object_response(ser_stop(stop))


@bp.post("/transport-tasks/<task_id>/stops/<stop_id>/depart")
@require_roles("DRIVER")
def depart_stop(task_id, stop_id):
    task = db.tasks.get(task_id)
    if task is None:
        err("ERR_NOT_FOUND", "TransportTask not found.")
    stop = db.stops.get(stop_id)
    if stop is None or stop["task_id"] != task_id:
        err("ERR_NOT_FOUND", "TaskStop not found.")
    if task["status"] != "AT_STOP":
        err("ERR_INVALID_STATE", "Task must be AT_STOP to depart-stop.")
    # Stop must be HANDED_OVER, or (handover_required=false AND ARRIVED)
    is_handed = stop["status"] == "HANDED_OVER"
    is_no_handover_arrived = stop["status"] == "ARRIVED" and not stop.get("handover_required", True)
    if not (is_handed or is_no_handover_arrived):
        err("ERR_INVALID_STATE", "Stop not eligible for depart.")
    # At least one PENDING stop remaining
    stops = db.stops_for_task(task_id)
    pending = [s for s in stops if s["status"] == "PENDING"]
    if not pending:
        err("ERR_INVALID_STATE", "No further pending stops.")

    task["status"] = "IN_TRANSIT"
    _bump(task)
    return object_response(ser_stop(stop))


# ----------------------------- Handover ---------------------------------------

@bp.post("/transport-tasks/<task_id>/stops/<stop_id>/handovers")
@require_roles("DRIVER")
def create_handover(task_id, stop_id):
    with db.global_lock:
        task = db.tasks.get(task_id)
        if task is None:
            err("ERR_NOT_FOUND", "TransportTask not found.")
        stop = db.stops.get(stop_id)
        if stop is None or stop["task_id"] != task_id:
            err("ERR_NOT_FOUND", "TaskStop not found.")
        # PRD §3.4: "The stop advances from `ARRIVED` to `HANDED_OVER`."
        # The handover gate is on the stop, not the parent task. After
        # /depart, stop 1 is ARRIVED (per side effect) but task is IN_TRANSIT.
        # PRD §3.4 (uniqueness): "Because HandoverRecord is unique per stop,
        # a second handover attempt against the same stop ... is rejected
        # with ERR_HANDOVER_ALREADY_EXISTS." Check uniqueness before state
        # so a duplicate (where stop is HANDED_OVER) surfaces the correct id.
        if db.handovers_for_stop(stop_id):
            err("ERR_HANDOVER_ALREADY_EXISTS", "A HandoverRecord already exists for this stop.")
        if stop["status"] != "ARRIVED":
            err("ERR_INVALID_STATE", "Stop must be ARRIVED to record handover.")

        body = require_dict(request.get_json(silent=True) or {})
        from_party_id = require_str(body.get("from_party_id"), field="from_party_id", min_len=1)
        to_party_id = require_str(body.get("to_party_id"), field="to_party_id", min_len=1)
        temp = body.get("temperature_at_handover_celsius")
        require_number(
            temp,
            field="temperature_at_handover_celsius",
            min_val=-80.0,
            max_val=80.0,
        )
        quantity = require_int(
            body.get("quantity_attested"),
            field="quantity_attested",
            min_val=0,
            max_val=task["cargo_quantity"],
        )
        photo = require_str(
            body.get("photo_evidence_ref"),
            field="photo_evidence_ref",
            min_len=1,
            max_len=255,
        )

        # Body-FK check: parties must reference an existing principal.
        # The PRD says: "Must reference an existing Shipper, Carrier, Driver, or Consignee principal."
        # Since principals are opaque, we accept any id present on the task's parties,
        # or on the Driver entity. (Shipper/Carrier/Consignee don't have persisted rows.)
        def _principal_ok(pid: str) -> bool:
            if pid in (task.get("shipper_id"), task.get("carrier_id"),
                       task.get("consignee_id")):
                return True
            if db.drivers.exists(pid):
                return True
            return False

        if not _principal_ok(from_party_id):
            err("ERR_REFERENCE_NOT_FOUND", "from_party_id is not a known principal.")
        if not _principal_ok(to_party_id):
            err("ERR_REFERENCE_NOT_FOUND", "to_party_id is not a known principal.")

        now_iso = clock.now_iso()
        handover_row = {
            "id": new_id(),
            "stop_id": stop_id,
            "task_id": task_id,
            "from_party_id": from_party_id,
            "to_party_id": to_party_id,
            "temperature_at_handover_celsius": float(temp),
            "quantity_attested": quantity,
            "photo_evidence_ref": photo,
            "handed_over_at": now_iso,
            "created_at": now_iso,
        }
        db.handovers.put(handover_row)
        stop["status"] = "HANDED_OVER"
        _bump_stop(stop)

        # Cascade: if final-sequence stop AND all other stops in {HANDED_OVER, SKIPPED}
        stops = db.stops_for_task(task_id)
        final = stops[-1] if stops else None
        if final is not None and final["id"] == stop_id:
            if all(s["status"] in {"HANDED_OVER", "SKIPPED"} for s in stops):
                task["status"] = "DELIVERED"
                _bump(task)
                # Side effects: driver OFF_DUTY, vehicle AVAILABLE
                drv = db.drivers.get(task.get("driver_id"))
                if drv is not None:
                    drv["status"] = "OFF_DUTY"
                    _bump_driver(drv)
                veh = db.vehicles.get(task.get("vehicle_id"))
                if veh is not None:
                    veh["status"] = "AVAILABLE"
                    _bump_vehicle(veh)

    return object_response(ser_handover(handover_row), status_code=201)


# ----------------------------- Skip / Close / Abort ---------------------------

@bp.post("/transport-tasks/<task_id>/stops/<stop_id>/skip")
@require_roles("DISPATCHER")
def skip_stop(task_id, stop_id):
    task = db.tasks.get(task_id)
    if task is None:
        err("ERR_NOT_FOUND", "TransportTask not found.")
    stop = db.stops.get(stop_id)
    if stop is None or stop["task_id"] != task_id:
        err("ERR_NOT_FOUND", "TaskStop not found.")
    if stop["status"] != "PENDING":
        err("ERR_INVALID_STATE", "Stop must be PENDING to skip.")
    if stop.get("handover_required", True):
        err("ERR_INVALID_STATE", "Cannot skip a stop with handover_required=true.")
    stop["status"] = "SKIPPED"
    _bump_stop(stop)
    return object_response(ser_stop(stop))


@bp.post("/transport-tasks/<task_id>/close")
@require_roles("CARRIER")
def close_task(task_id):
    task = db.tasks.get(task_id)
    if task is None:
        err("ERR_NOT_FOUND", "TransportTask not found.")
    if task["status"] != "DELIVERED":
        err("ERR_INVALID_STATE", "Task must be DELIVERED to close.")
    # Any alert OPEN/ACKNOWLEDGED/IN_RESPONSE/ESCALATED blocks
    blocking = {"OPEN", "ACKNOWLEDGED", "IN_RESPONSE", "ESCALATED"}
    for a in db.alerts_for_task(task_id):
        if a["status"] in blocking:
            err("ERR_INVALID_STATE", "Cannot close: an alert is still active.")
    task["status"] = "CLOSED"
    task["closed_at"] = clock.now_iso()
    _bump(task)
    # Cascade RESOLVED alerts to CLOSED
    for a in db.alerts_for_task(task_id):
        if a["status"] == "RESOLVED":
            a["status"] = "CLOSED"
            a["updated_at"] = clock.now_iso()
            a["version"] = a.get("version", 0) + 1
            audit.log("ALERT", a["id"], "CLOSED", "SYSTEM", "system")
    return object_response(ser_task(task))


@bp.post("/transport-tasks/<task_id>/abort")
@require_roles("DISPATCHER")
def abort_task(task_id):
    task = db.tasks.get(task_id)
    if task is None:
        err("ERR_NOT_FOUND", "TransportTask not found.")
    if task["status"] not in {"PLANNED", "DISPATCHED", "IN_TRANSIT"}:
        err("ERR_INVALID_STATE", "Task cannot be aborted from this state.")
    body = require_dict(request.get_json(silent=True) or {})
    reason = body.get("reason")
    require_str(reason, field="reason", min_len=1, max_len=500)
    prior = task["status"]
    task["status"] = "ABORTED"
    _bump(task)
    if prior in {"DISPATCHED", "IN_TRANSIT"}:
        veh = db.vehicles.get(task.get("vehicle_id"))
        if veh is not None:
            veh["status"] = "AVAILABLE"
            _bump_vehicle(veh)
        drv = db.drivers.get(task.get("driver_id"))
        if drv is not None:
            drv["status"] = "OFF_DUTY"
            _bump_driver(drv)
    return object_response(ser_task(task))
