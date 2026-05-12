"""Virtual clock advancement and time-driven side effects."""
from __future__ import annotations

import math
from datetime import timedelta

from db import db, to_unix
from services.audit import write_audit
from services.calculations import (
    compute_priority_score,
    MAX_ROLLBACKS,
    HEARTBEAT_TIMEOUT_SECONDS,
    DEADLOCK_PENALTY,
)
from services.transitions import (
    advance_station_queue,
    aggregate_parent_tasks,
    bump,
    cancel_charging_session,
    open_fault_incident,
    release_robot_held_reservations,
)
from services.pathfinding import shortest_path_via


def advance_clock(fleet: dict, delta_seconds: int):
    """Advance Fleet.clock_now by delta_seconds and run all time-driven side effects."""
    advance_start = fleet["clock_now"]
    new_now = advance_start + timedelta(seconds=delta_seconds)

    # ------------------------------------------------------------------
    # 1) Snapshot charging robots BEFORE we move the clock so we can compute
    #    completion times correctly.
    # ------------------------------------------------------------------
    charging_snapshot = []
    for r in db.robots.values():
        if r["fleet_id"] != fleet["id"]:
            continue
        if r["operational_state"] == "CHARGING":
            charging_snapshot.append({
                "robot_id": r["id"],
                "start_battery": r["battery_pct"],
                "station_id": r.get("charging_station_id"),
            })

    # ------------------------------------------------------------------
    # 2) Move the clock
    # ------------------------------------------------------------------
    fleet["clock_now"] = new_now
    bump(fleet, fleet)

    # ------------------------------------------------------------------
    # 3) Charge progression for snapshot
    # ------------------------------------------------------------------
    for snap in charging_snapshot:
        robot = db.robots.get(snap["robot_id"])
        station = db.charging_stations.get(snap["station_id"]) if snap["station_id"] else None
        if not robot or not station:
            continue
        rate = station["charge_rate_pct_per_second"]
        gained = delta_seconds * rate
        new_battery = min(100, snap["start_battery"] + gained)
        robot["battery_pct"] = new_battery
        bump(robot, fleet)
        # Locate the active charging session for this robot
        session = None
        for s in db.charging_sessions.values():
            if s["robot_id"] == robot["id"] and s["status"] == "CHARGING" and s["charging_station_id"] == station["id"]:
                session = s
                break
        if session and new_battery >= fleet["charging_full_pct"]:
            # Linear back-solve for the wall-clock completion instant.
            needed = math.ceil((fleet["charging_full_pct"] - snap["start_battery"]) / rate)
            completed_at = advance_start + timedelta(seconds=needed)
            session["status"] = "COMPLETED"
            session["end_battery_pct"] = new_battery
            session["completed_at"] = completed_at
            bump(session, fleet)
            # Free station, return robot to IDLE
            station["status"] = "AVAILABLE"
            station["occupying_robot_id"] = None
            bump(station, fleet)
            robot["operational_state"] = "IDLE"
            robot["charging_station_id"] = None
            bump(robot, fleet)
            # Queue advance
            advance_station_queue(station, fleet)

    # ------------------------------------------------------------------
    # 4) Task expiry sweep
    # ------------------------------------------------------------------
    expiry_seconds = fleet["task_expiry_seconds"]
    for t in list(db.tasks.values()):
        if t["fleet_id"] != fleet["id"]:
            continue
        if t["status"] != "QUEUED":
            continue
        if t.get("queued_at") is None:
            continue
        age = to_unix(fleet["clock_now"]) - to_unix(t["queued_at"])
        if age >= expiry_seconds:
            prev = t["status"]
            t["status"] = "EXPIRED"
            bump(t, fleet)
            write_audit(fleet, "TASK_STATUS", "Task", t["id"], prev, "EXPIRED", "system")

    # ------------------------------------------------------------------
    # 5) Heartbeat timeout → comm-loss fault chain
    # ------------------------------------------------------------------
    for r in list(db.robots.values()):
        if r["fleet_id"] != fleet["id"]:
            continue
        if r["connectivity"] != "ONLINE":
            continue
        if r["fault_state"] == "FAULTED":
            continue
        last_hb = r.get("last_heartbeat_at")
        if last_hb is None:
            continue
        if to_unix(fleet["clock_now"]) - to_unix(last_hb) >= HEARTBEAT_TIMEOUT_SECONDS:
            r["connectivity"] = "OFFLINE"
            bump(r, fleet)
            open_fault_incident(r, "COMM_LOSS", fleet, "system")

    # ------------------------------------------------------------------
    # 6) Deadlock recovery
    # ------------------------------------------------------------------
    deadlock_recovery(fleet)

    # ------------------------------------------------------------------
    # 7) Re-compute priority_score for QUEUED tasks; parent aggregation
    # ------------------------------------------------------------------
    for t in db.tasks.values():
        if t["fleet_id"] != fleet["id"]:
            continue
        if t["status"] == "QUEUED" and t.get("queued_at"):
            t["priority_score"] = compute_priority_score(t, fleet)

    aggregate_parent_tasks(fleet)


def deadlock_recovery(fleet: dict):
    """Among robots in WAITING_RIGHT_OF_WAY beyond the deadlock_wait_seconds window,
    detect cycles in next-node graphs and reroute the lowest-standby_priority robot
    in each cycle. We use a simple approach: find any cycle among waiting robots
    where each is blocked on a node occupied by another waiting robot in the cycle.
    """
    fleet_id = fleet["id"]
    wait_threshold = fleet["deadlock_wait_seconds"]
    now_unix = to_unix(fleet["clock_now"])
    waiting = []
    for r in db.robots.values():
        if r["fleet_id"] != fleet_id:
            continue
        if r["operational_state"] != "WAITING_RIGHT_OF_WAY":
            continue
        last_t = db.robot_wait_transition_at.get(r["id"])
        if last_t is None:
            continue
        elapsed = now_unix - to_unix(last_t)
        if elapsed < wait_threshold:
            continue
        waiting.append(r)
    if len(waiting) < 2:
        return

    # Build "next desired node" map for each waiting robot from its planned_path.
    next_node_of: dict[str, str | None] = {}
    occupied_by: dict[str, str] = {}
    for r in waiting:
        task_id = r.get("current_task_id")
        if not task_id:
            next_node_of[r["id"]] = None
            continue
        task = db.tasks.get(task_id)
        if not task:
            next_node_of[r["id"]] = None
            continue
        path = task.get("planned_path_node_ids") or []
        try:
            idx = path.index(r["position_node_id"])
        except ValueError:
            idx = -1
        nxt = path[idx + 1] if idx >= 0 and idx + 1 < len(path) else None
        next_node_of[r["id"]] = nxt
        occupied_by[r["position_node_id"]] = r["id"]

    # Find a cycle in waiting set: robot A's next-node is occupied by robot B and so on.
    waiting_ids = {r["id"] for r in waiting}
    cycle_members: list[str] = []
    for start in waiting:
        visited_order = []
        cur_id = start["id"]
        seen = {}
        while cur_id is not None and cur_id not in seen:
            seen[cur_id] = len(visited_order)
            visited_order.append(cur_id)
            nxt_node = next_node_of.get(cur_id)
            if nxt_node is None:
                cur_id = None
                break
            owner = occupied_by.get(nxt_node)
            if owner is None or owner not in waiting_ids:
                cur_id = None
                break
            cur_id = owner
        if cur_id is not None and cur_id in seen:
            idx = seen[cur_id]
            cycle_members = visited_order[idx:]
            break

    if not cycle_members:
        return

    # Choose the robot with the lowest standby_priority (tie by code asc) in the cycle.
    cycle_robots = [db.robots[rid] for rid in cycle_members]
    cycle_robots.sort(key=lambda r: (r["standby_priority"], r["code"]))
    chosen = cycle_robots[0]
    # Contested node = chosen robot's next desired node
    contested = next_node_of[chosen["id"]]
    task = db.tasks.get(chosen.get("current_task_id"))
    if not task or task["status"] != "EXECUTING" or contested is None:
        return
    penalty = {contested: DEADLOCK_PENALTY}
    cost, new_path = shortest_path_via(fleet_id, chosen["position_node_id"],
                                       task["pickup_node_id"], task["dropoff_node_id"],
                                       penalty_nodes=penalty)
    if cost is None:
        return  # leave deadlock alone
    # Release future HELD reservations for this robot
    release_robot_held_reservations(chosen["id"], fleet, only_future=True)
    task["planned_path_node_ids"] = new_path
    bump(task, fleet)
    prev_state = chosen["operational_state"]
    chosen["operational_state"] = "EXECUTING"
    bump(chosen, fleet)
    # Clear waiting-since timestamp for this robot
    db.robot_wait_transition_at.pop(chosen["id"], None)
    write_audit(fleet, "TASK_STATUS", "Robot", chosen["id"], prev_state, "EXECUTING", "system")
