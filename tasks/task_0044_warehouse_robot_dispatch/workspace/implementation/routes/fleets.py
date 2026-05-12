"""Fleet, dispatch, advance_clock, metrics endpoints."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from flask import Blueprint, request, g

from db import db, new_id, to_unix, EPOCH
from errors import raise_error
from middleware import require_roles
from response import success, list_response
from services.audit import write_audit
from services.calculations import (
    compute_priority_score,
    has_non_terminal_descendants,
    round_half_up,
)
from services.clock import advance_clock
from services.lookup import get_fleet_or_404
from services.pagination import parse_pagination, paginate
from services.serialize import fleet_to_dict, task_to_dict
from services.transitions import (
    bump,
    select_robot_for_task,
)

fleets_bp = Blueprint("fleets", __name__)


@fleets_bp.route("/fleets", methods=["POST"])
def create_fleet():
    require_roles(["FleetAdmin"])
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    if not isinstance(name, str) or not name:
        raise_error("ERR_BAD_REQUEST", "name is required and must be a string")

    def int_opt(key, default, min_val=None, max_val=None):
        val = body.get(key, default)
        if not isinstance(val, int) or isinstance(val, bool):
            raise_error("ERR_BAD_REQUEST", f"{key} must be an integer")
        if min_val is not None and val < min_val:
            raise_error("ERR_BAD_REQUEST", f"{key} must be >= {min_val}")
        if max_val is not None and val > max_val:
            raise_error("ERR_BAD_REQUEST", f"{key} must be <= {max_val}")
        return val

    low = int_opt("charging_low_threshold_pct", 20, 0, 100)
    opp = int_opt("charging_opportunity_pct", 60, 0, 100)
    full = int_opt("charging_full_pct", 95, 0, 100)
    if not (opp > low):
        raise_error("ERR_BAD_REQUEST", "charging_opportunity_pct must be > charging_low_threshold_pct")
    if not (full > opp):
        raise_error("ERR_BAD_REQUEST", "charging_full_pct must be > charging_opportunity_pct")
    slot_seconds = int_opt("slot_seconds", 10, 1)
    expiry = int_opt("task_expiry_seconds", 600, 1)
    deadlock = int_opt("deadlock_wait_seconds", 30, 1)

    fid = new_id()
    now = EPOCH  # 1970-01-01T00:00:00.000Z initial virtual clock
    fleet = {
        "id": fid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "name": name,
        "clock_now": EPOCH,
        "charging_low_threshold_pct": low,
        "charging_opportunity_pct": opp,
        "charging_full_pct": full,
        "slot_seconds": slot_seconds,
        "task_expiry_seconds": expiry,
        "deadlock_wait_seconds": deadlock,
    }
    db.fleets[fid] = fleet
    return success(fleet_to_dict(fleet), status=201)


@fleets_bp.route("/fleets/<fleet_id>", methods=["GET"])
def get_fleet(fleet_id):
    require_roles(["Operator", "FleetAdmin", "WMS"])
    fleet = get_fleet_or_404(fleet_id)
    return success(fleet_to_dict(fleet))


@fleets_bp.route("/fleets/<fleet_id>:advance_clock", methods=["POST"])
def advance_clock_endpoint(fleet_id):
    require_roles(["Operator", "FleetAdmin"])
    fleet = get_fleet_or_404(fleet_id)
    body = request.get_json(silent=True) or {}
    delta = body.get("delta_seconds")
    if not isinstance(delta, int) or isinstance(delta, bool):
        raise_error("ERR_BAD_REQUEST", "delta_seconds must be an integer")
    if delta < 1:
        raise_error("ERR_CLOCK_BACKWARDS", "delta_seconds must be at least 1")
    # OCC
    if "version" in body and body["version"] != fleet["version"]:
        raise_error("ERR_INVALID_STATE", "Version mismatch")
    advance_clock(fleet, delta)
    return success(fleet_to_dict(fleet))


@fleets_bp.route("/fleets/<fleet_id>/dispatch", methods=["POST"])
def dispatch(fleet_id):
    require_roles(["Operator", "FleetAdmin"])
    fleet = get_fleet_or_404(fleet_id)
    # Expiry sweep first
    expiry = fleet["task_expiry_seconds"]
    for t in list(db.tasks.values()):
        if t["fleet_id"] != fleet_id or t["status"] != "QUEUED":
            continue
        if t.get("queued_at") is None:
            continue
        age = to_unix(fleet["clock_now"]) - to_unix(t["queued_at"])
        if age >= expiry:
            prev = t["status"]
            t["status"] = "EXPIRED"
            bump(t, fleet)
            write_audit(fleet, "TASK_STATUS", "Task", t["id"], prev, "EXPIRED", "system")

    # Re-compute priority scores
    for t in db.tasks.values():
        if t["fleet_id"] != fleet_id or t["status"] != "QUEUED":
            continue
        t["priority_score"] = compute_priority_score(t, fleet)

    # Collect dispatchable queued tasks (exclude parents with non-terminal descendants and children of split)
    candidates = []
    for t in db.tasks.values():
        if t["fleet_id"] != fleet_id or t["status"] != "QUEUED":
            continue
        # Exclude parents with non-terminal descendants (per scaffold dispatch filter)
        if has_non_terminal_descendants(t):
            continue
        candidates.append(t)
    # Sort by priority_score asc, then id asc
    candidates.sort(key=lambda t: (t["priority_score"], t["id"]))

    assigned: list[dict] = []
    for task in candidates:
        robot, cost, path = select_robot_for_task(task, fleet)
        if robot is None:
            continue
        # Commit assignment
        task["status"] = "ASSIGNED"
        task["assigned_robot_id"] = robot["id"]
        task["assigned_at"] = fleet["clock_now"]
        task["planned_path_node_ids"] = path
        bump(task, fleet)
        robot["current_task_id"] = task["id"]
        bump(robot, fleet)
        write_audit(fleet, "TASK_STATUS", "Task", task["id"], "QUEUED", "ASSIGNED", g.user_role)
        assigned.append(task)
    return list_response([task_to_dict(t) for t in assigned], total=len(assigned), limit=len(assigned) or 10, offset=0)


@fleets_bp.route("/fleets/<fleet_id>/metrics", methods=["GET"])
def metrics(fleet_id):
    require_roles(["Operator", "FleetAdmin", "WMS"])
    fleet = get_fleet_or_404(fleet_id)
    args = request.args
    try:
        window_seconds = int(args.get("window_seconds", 3600))
    except (ValueError, TypeError):
        raise_error("ERR_BAD_REQUEST", "window_seconds must be an integer")
    if window_seconds < 1:
        raise_error("ERR_BAD_REQUEST", "window_seconds must be >= 1")
    boundary = args.get("window_boundary", "closed")
    if boundary not in {"closed", "open"}:
        raise_error("ERR_BAD_REQUEST", "window_boundary must be 'closed' or 'open'")
    cutoff_unix = to_unix(fleet["clock_now"]) - window_seconds

    def in_window(ts):
        if ts is None:
            return False
        u = to_unix(ts)
        return (u >= cutoff_unix) if boundary == "closed" else (u > cutoff_unix)

    fleet_tasks = [t for t in db.tasks.values() if t["fleet_id"] == fleet_id]
    fleet_robots = [r for r in db.robots.values() if r["fleet_id"] == fleet_id]

    # |S|: completed in window
    S = [t for t in fleet_tasks if t["status"] == "COMPLETED" and in_window(t.get("completed_at"))]
    # |T|: queued in window across all statuses
    T = [t for t in fleet_tasks if in_window(t.get("queued_at"))]
    task_completion_rate = round_half_up(len(S) / max(1, len(T)), 4)

    # Average task duration
    durations = []
    for t in S:
        if t.get("started_at") and t.get("completed_at"):
            durations.append(to_unix(t["completed_at"]) - to_unix(t["started_at"]))
    avg_dur = round_half_up(sum(durations) / max(1, len(durations)), 2)

    # Per-robot utilization: reconstruct from audit events: track time spent in EXECUTING.
    per_robot_util = []
    for r in fleet_robots:
        executing_seconds = _reconstruct_executing_seconds(r["id"], cutoff_unix,
                                                            to_unix(fleet["clock_now"]), boundary)
        per_robot_util.append(round_half_up(executing_seconds / window_seconds, 4))
    if per_robot_util:
        fleet_util = round_half_up(sum(per_robot_util) / len(per_robot_util), 4)
    else:
        fleet_util = 0.0

    # Fault rate
    fault_count = sum(1 for fi in db.fault_incidents.values()
                      if fi["fleet_id"] == fleet_id and in_window(fi.get("detected_at")))
    fault_rate = round_half_up(fault_count / max(1, len(fleet_robots)), 4)

    # Charging-time ratio
    charging_seconds_total = 0
    executing_seconds_total = 0
    for r in fleet_robots:
        charging_seconds_total += _reconstruct_charging_seconds(r["id"], cutoff_unix,
                                                                 to_unix(fleet["clock_now"]), boundary)
        executing_seconds_total += _reconstruct_executing_seconds(r["id"], cutoff_unix,
                                                                   to_unix(fleet["clock_now"]), boundary)
    denom = charging_seconds_total + executing_seconds_total
    charging_time_ratio = round_half_up(charging_seconds_total / max(1, denom), 4)

    # Bottleneck zones
    node_counts = []
    for n in db.map_nodes.values():
        if n["fleet_id"] != fleet_id:
            continue
        if n["kind"] not in {"INTERSECTION", "LIFT_POINT"}:
            continue
        cnt = 0
        for slot in db.slot_reservations.values():
            if slot["node_id"] != n["id"]:
                continue
            if slot["status"] not in {"HELD", "CONSUMED"}:
                continue
            if in_window(slot.get("scheduled_at")):
                cnt += 1
        node_counts.append((n["code"], n["id"], cnt))
    node_counts.sort(key=lambda x: (-x[2], x[0]))
    bottleneck_zones = [
        {"node_id": nid, "code": code, "reservation_count": cnt}
        for code, nid, cnt in node_counts[:5]
    ]

    return success({
        "task_completion_rate": task_completion_rate,
        "average_task_duration_seconds": avg_dur,
        "fleet_robot_utilization": fleet_util,
        "fault_rate": fault_rate,
        "charging_time_ratio": charging_time_ratio,
        "bottleneck_zones": bottleneck_zones,
    })


def _reconstruct_executing_seconds(robot_id: str, cutoff_unix: int, now_unix: int, boundary: str) -> int:
    """Reconstruct seconds spent in EXECUTING within [cutoff, now] from audit events."""
    return _reconstruct_state_seconds(robot_id, "EXECUTING", cutoff_unix, now_unix, boundary)


def _reconstruct_charging_seconds(robot_id: str, cutoff_unix: int, now_unix: int, boundary: str) -> int:
    return _reconstruct_state_seconds(robot_id, "CHARGING", cutoff_unix, now_unix, boundary)


def _reconstruct_state_seconds(robot_id: str, target_state: str,
                                cutoff_unix: int, now_unix: int, boundary: str) -> int:
    """Walk audit events for this robot and tally seconds spent in target_state."""
    events = [ev for ev in db.audit_events.values()
              if ev.get("subject_kind") == "Robot" and ev.get("subject_id") == robot_id]
    events.sort(key=lambda e: to_unix(e["occurred_at"]))
    # If no events, we can't reconstruct — current state applies for now.
    total = 0
    current_state = None
    current_start = None
    for ev in events:
        t = to_unix(ev["occurred_at"])
        if current_state == target_state and current_start is not None:
            # Tally interval [current_start, t] intersected with [cutoff, now]
            total += _interval_intersect(current_start, t, cutoff_unix, now_unix, boundary)
        current_state = ev.get("to_state")
        current_start = t
    # Final open interval [current_start, now] if currently in target state
    if current_state == target_state and current_start is not None:
        total += _interval_intersect(current_start, now_unix, cutoff_unix, now_unix, boundary)
    # If we have no audit history but the robot is currently in target state:
    robot = db.robots.get(robot_id)
    if robot and not events and robot.get("operational_state") == target_state:
        total += max(0, now_unix - max(cutoff_unix, 0))
    return max(0, total)


def _interval_intersect(start: int, end: int, cutoff: int, now: int, boundary: str) -> int:
    lo = max(start, cutoff)
    hi = min(end, now)
    if hi <= lo:
        return 0
    return hi - lo
