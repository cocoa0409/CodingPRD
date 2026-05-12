"""State-transition helpers and side-effect chains."""
from __future__ import annotations

from db import db, new_id
from services.audit import write_audit
from services.calculations import (
    compute_priority_score,
    MAX_ROLLBACKS,
    DEADLOCK_PENALTY,
)
from services.pathfinding import shortest_path_via, shortest_path_simple


def bump(obj: dict, fleet: dict):
    """Increment version and refresh updated_at."""
    obj["version"] = obj.get("version", 1) + 1
    obj["updated_at"] = fleet["clock_now"]


def trajectory_count_for(robot_id: str) -> int:
    return sum(1 for r in db.trajectory_records.values() if r["robot_id"] == robot_id)


def queue_length_for(station_id: str) -> int:
    """Number of robots whose operational_state == WAITING_CHARGER for this station."""
    return sum(
        1 for r in db.robots.values()
        if r.get("charging_station_id") == station_id and r["operational_state"] == "WAITING_CHARGER"
    )


# -----------------------------------------------------------------------------
# Charging-session helpers
# -----------------------------------------------------------------------------

def cancel_charging_session(session: dict, fleet: dict, actor_role: str):
    """Cancel a session (operator or system-driven). Side effects per the scaffold."""
    prev_status = session["status"]
    if session["status"] in {"COMPLETED", "CANCELLED"}:
        return  # idempotent no-op
    station = db.charging_stations.get(session["charging_station_id"])
    robot = db.robots.get(session["robot_id"])

    if prev_status == "CHARGING":
        # Free the station and run queue advance
        if station:
            station["status"] = "AVAILABLE"
            station["occupying_robot_id"] = None
            bump(station, fleet)
        if robot:
            # Only flip to IDLE if not already faulted (caller may pre-set OUT_OF_SERVICE)
            if robot["operational_state"] == "CHARGING":
                robot["operational_state"] = "IDLE"
            robot["charging_station_id"] = None
            bump(robot, fleet)
    elif prev_status == "QUEUED":
        if robot:
            if robot["operational_state"] == "WAITING_CHARGER":
                robot["operational_state"] = "IDLE"
            robot["charging_station_id"] = None
            bump(robot, fleet)

    session["status"] = "CANCELLED"
    bump(session, fleet)

    # Queue advance if this was the active session
    if prev_status == "CHARGING" and station:
        advance_station_queue(station, fleet)


def advance_station_queue(station: dict, fleet: dict):
    """If the station's WAITING_CHARGER queue is non-empty, promote one robot.

    Selection rule: lowest battery_pct (tie-break Robot.code asc), BUT FORCED_LOW
    queued sessions outrank OPPORTUNITY/MANUAL regardless of battery.
    """
    if station["status"] != "AVAILABLE":
        return
    queued_sessions = [
        s for s in db.charging_sessions.values()
        if s["charging_station_id"] == station["id"] and s["status"] == "QUEUED"
    ]
    if not queued_sessions:
        return

    def rank(session):
        robot = db.robots.get(session["robot_id"])
        if not robot:
            return (99, 999, "")
        # FORCED_LOW first (0), then OPPORTUNITY/MANUAL (1)
        trig_rank = 0 if session["trigger"] == "FORCED_LOW" else 1
        return (trig_rank, robot["battery_pct"], robot["code"])

    queued_sessions.sort(key=rank)
    winner = queued_sessions[0]
    robot = db.robots.get(winner["robot_id"])
    if not robot:
        return
    # Promote
    winner["status"] = "CHARGING"
    winner["started_at"] = fleet["clock_now"]
    winner["start_battery_pct"] = robot["battery_pct"]
    bump(winner, fleet)
    station["status"] = "OCCUPIED"
    station["occupying_robot_id"] = robot["id"]
    bump(station, fleet)
    robot["operational_state"] = "CHARGING"
    robot["charging_station_id"] = station["id"]
    bump(robot, fleet)


# -----------------------------------------------------------------------------
# Slot reservation helpers
# -----------------------------------------------------------------------------

def release_robot_held_reservations(robot_id: str, fleet: dict, only_future: bool = True):
    now = fleet["clock_now"]
    for slot in db.slot_reservations.values():
        if slot["robot_id"] != robot_id:
            continue
        if slot["status"] != "HELD":
            continue
        if only_future and slot["scheduled_at"] < now:
            continue
        slot["status"] = "RELEASED"


def release_task_held_reservations(task_id: str, fleet: dict, only_future: bool = True):
    now = fleet["clock_now"]
    for slot in db.slot_reservations.values():
        if slot.get("task_id") != task_id:
            continue
        if slot["status"] != "HELD":
            continue
        if only_future and slot["scheduled_at"] < now:
            continue
        slot["status"] = "RELEASED"


# -----------------------------------------------------------------------------
# Fault chain
# -----------------------------------------------------------------------------

def open_fault_incident(robot: dict, kind: str, fleet: dict, actor_role: str) -> dict:
    """Open a FaultIncident and run the cascading side-effect chain.

    Returns the new incident.
    """
    incident_id = new_id()
    now = fleet["clock_now"]
    prev_op_state = robot["operational_state"]

    # 1. Determine isolation zone (Manhattan distance ≤ 1 of robot position)
    pos_node = db.map_nodes.get(robot["position_node_id"])
    isolation_ids: list[str] = []
    if pos_node:
        px, py = pos_node["x"], pos_node["y"]
        fleet_id = robot["fleet_id"]
        for n in db.map_nodes.values():
            if n["fleet_id"] != fleet_id:
                continue
            if abs(n["x"] - px) + abs(n["y"] - py) <= 1:
                isolation_ids.append(n["id"])

    # 2. Roll back the in-progress task (if any)
    rolled_back_task_id = None
    reassigned_task_id = None
    if robot.get("current_task_id"):
        task = db.tasks.get(robot["current_task_id"])
        if task and task["status"] in {"ASSIGNED", "EXECUTING"}:
            rolled_back_task_id = task["id"]
            prev_task_state = task["status"]
            task["status"] = "ROLLED_BACK"
            task["assigned_robot_id"] = None
            task["planned_path_node_ids"] = []
            task["started_at"] = None
            task["assigned_at"] = None
            task["rollback_count"] = task.get("rollback_count", 0) + 1
            bump(task, fleet)
            write_audit(fleet, "TASK_STATUS", "Task", task["id"],
                        prev_task_state, "ROLLED_BACK", "system")
            # Immediately requeue if under ceiling, else cancel.
            if task["rollback_count"] <= MAX_ROLLBACKS:
                task["status"] = "QUEUED"
                task["queued_at"] = fleet["clock_now"]
                task["priority_score"] = compute_priority_score(task, fleet)
                bump(task, fleet)
                write_audit(fleet, "TASK_STATUS", "Task", task["id"],
                            "ROLLED_BACK", "QUEUED", "system")
                reassigned_task_id = task["id"]
            else:
                task["status"] = "CANCELLED"
                bump(task, fleet)
                write_audit(fleet, "TASK_STATUS", "Task", task["id"],
                            "ROLLED_BACK", "CANCELLED", "system")

    # 3. Release held slot reservations for this robot
    release_robot_held_reservations(robot["id"], fleet, only_future=False)

    # 4. If charging, cancel the session
    if prev_op_state == "CHARGING":
        active = [s for s in db.charging_sessions.values()
                  if s["robot_id"] == robot["id"] and s["status"] == "CHARGING"]
        for s in active:
            cancel_charging_session(s, fleet, "system")
    elif prev_op_state == "WAITING_CHARGER":
        queued = [s for s in db.charging_sessions.values()
                  if s["robot_id"] == robot["id"] and s["status"] == "QUEUED"]
        for s in queued:
            cancel_charging_session(s, fleet, "system")

    # 5. Flip robot state
    robot["fault_state"] = "FAULTED"
    robot["operational_state"] = "OUT_OF_SERVICE"
    robot["current_task_id"] = None
    bump(robot, fleet)

    # 6. Mark isolation nodes as BLOCKED with reason=OBSTACLE
    for nid in isolation_ids:
        n = db.map_nodes.get(nid)
        if n and n["status"] == "OPEN":
            n["status"] = "BLOCKED"
            n["blocked_reason"] = "OBSTACLE"
            bump(n, fleet)

    # 7. Persist the incident
    incident = {
        "id": incident_id,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "fleet_id": robot["fleet_id"],
        "robot_id": robot["id"],
        "kind": kind,
        "status": "OPEN",
        "isolation_node_ids": isolation_ids,
        "rolled_back_task_id": rolled_back_task_id,
        "reassigned_task_id": reassigned_task_id,
        "detected_at": now,
        "takeover_started_at": None,
        "resolved_at": None,
    }
    db.fault_incidents[incident_id] = incident
    write_audit(fleet, "FAULT", "Robot", robot["id"], prev_op_state, "OUT_OF_SERVICE", actor_role)
    write_audit(fleet, "FAULT", "FaultIncident", incident_id, None, "OPEN", actor_role)

    # 8. Reroute executing robots whose path goes through any blocked iso node
    for nid in isolation_ids:
        reroute_around_blocked(nid, fleet)

    return incident


def reroute_around_blocked(blocked_node_id: str, fleet: dict):
    """When a node becomes BLOCKED, reroute any EXECUTING robot whose planned
    path still includes that node ahead of its current position."""
    for robot in db.robots.values():
        if robot["fleet_id"] != fleet["id"]:
            continue
        if robot["operational_state"] != "EXECUTING":
            continue
        task_id = robot.get("current_task_id")
        if not task_id:
            continue
        task = db.tasks.get(task_id)
        if not task or task["status"] != "EXECUTING":
            continue
        path = task.get("planned_path_node_ids") or []
        # Find robot position in path
        if blocked_node_id not in path:
            continue
        try:
            pos_idx = path.index(robot["position_node_id"])
        except ValueError:
            pos_idx = -1
        try:
            block_idx = path.index(blocked_node_id)
        except ValueError:
            continue
        if pos_idx >= 0 and block_idx <= pos_idx:
            continue  # blocked node is behind us
        # Recompute
        pickup = task["pickup_node_id"]
        dropoff = task["dropoff_node_id"]
        # If robot already past pickup, just route to dropoff
        # We treat the via point as pickup if it lies ahead, otherwise just dropoff.
        cost, new_path = shortest_path_via(fleet["id"], robot["position_node_id"], pickup, dropoff)
        if cost is None:
            # No alternative: robot parks in WAITING_RIGHT_OF_WAY, task stays EXECUTING
            from db import db as _db
            _db.robot_wait_transition_at[robot["id"]] = fleet["clock_now"]
            robot["operational_state"] = "WAITING_RIGHT_OF_WAY"
            bump(robot, fleet)
        else:
            task["planned_path_node_ids"] = new_path
            bump(task, fleet)
            # Release future-scheduled HELD reservations of this robot
            release_robot_held_reservations(robot["id"], fleet, only_future=True)


# -----------------------------------------------------------------------------
# Parent task aggregation
# -----------------------------------------------------------------------------

def aggregate_parent_tasks(fleet: dict):
    """For every parent task with non-empty direct-child set, update parent.status
    according to the aggregation rules. Idempotent; safe to call repeatedly."""
    parents = []
    for t in db.tasks.values():
        if t["fleet_id"] != fleet["id"]:
            continue
        if t.get("parent_task_id"):
            continue
        children = [c for c in db.tasks.values() if c.get("parent_task_id") == t["id"]]
        if not children:
            continue
        parents.append((t, children))
    # Process in chronological order: by clock_now (same for all in this pass), child id asc
    parents.sort(key=lambda p: p[0]["id"])
    for parent, children in parents:
        if parent["status"] in {"COMPLETED", "CANCELLED", "EXPIRED", "MERGED"}:
            continue
        statuses = [c["status"] for c in children]
        if all(s == "COMPLETED" for s in statuses):
            prev = parent["status"]
            parent["status"] = "COMPLETED"
            parent["completed_at"] = fleet["clock_now"]
            bump(parent, fleet)
            write_audit(fleet, "TASK_STATUS", "Task", parent["id"], prev, "COMPLETED", "system")
        elif all(s in {"CANCELLED", "EXPIRED", "MERGED", "COMPLETED"} for s in statuses) and any(s == "CANCELLED" for s in statuses):
            prev = parent["status"]
            parent["status"] = "CANCELLED"
            bump(parent, fleet)
            write_audit(fleet, "TASK_STATUS", "Task", parent["id"], prev, "CANCELLED", "system")
        elif all(s in {"EXPIRED", "MERGED", "COMPLETED"} for s in statuses) and any(s == "EXPIRED" for s in statuses):
            prev = parent["status"]
            parent["status"] = "EXPIRED"
            bump(parent, fleet)
            write_audit(fleet, "TASK_STATUS", "Task", parent["id"], prev, "EXPIRED", "system")
        # else: stays QUEUED


def project_parent_status(parent: dict) -> str:
    """Compute provisional parent status as if every non-terminal child completed."""
    children = [c for c in db.tasks.values() if c.get("parent_task_id") == parent["id"]]
    if not children:
        return parent["status"]
    projected = []
    for c in children:
        if c["status"] in {"CANCELLED", "EXPIRED", "MERGED", "COMPLETED"}:
            projected.append(c["status"])
        else:
            projected.append("COMPLETED")
    if all(s == "COMPLETED" for s in projected):
        return "COMPLETED"
    if all(s in {"CANCELLED", "EXPIRED", "MERGED", "COMPLETED"} for s in projected) and any(s == "CANCELLED" for s in projected):
        return "CANCELLED"
    if all(s in {"EXPIRED", "MERGED", "COMPLETED"} for s in projected) and any(s == "EXPIRED" for s in projected):
        return "EXPIRED"
    return parent["status"]


# -----------------------------------------------------------------------------
# Robot selection (dispatcher)
# -----------------------------------------------------------------------------

def select_robot_for_task(task: dict, fleet: dict):
    """Return (robot, total_cost, path) or (None, None, None) if no candidate."""
    fleet_id = fleet["id"]
    candidates = []
    for r in db.robots.values():
        if r["fleet_id"] != fleet_id:
            continue
        if r["fault_state"] != "OK":
            continue
        if r["connectivity"] != "ONLINE":
            continue
        if r["operational_state"] != "IDLE":
            continue
        if r.get("current_task_id"):
            continue
        if r["battery_pct"] <= fleet["charging_low_threshold_pct"]:
            continue
        cost, path = shortest_path_via(fleet_id, r["position_node_id"],
                                       task["pickup_node_id"], task["dropoff_node_id"])
        if cost is None or not path:
            continue
        candidates.append((cost, r["battery_pct"], r["code"], r, path))
    if not candidates:
        return None, None, None
    # Sort: cost asc, battery desc, code asc
    candidates.sort(key=lambda t: (t[0], -t[1], t[2]))
    cost, _bat, _code, robot, path = candidates[0]
    return robot, cost, path
