"""Task endpoints: create, read, list, assign, start, complete, cancel, split, merge."""
from __future__ import annotations

import math
from flask import Blueprint, request, g

from db import db, new_id
from errors import raise_error
from middleware import require_roles
from response import success, list_response
from services.audit import write_audit
from services.calculations import (
    compute_priority_score,
    has_non_terminal_descendants_for_cancel,
    MAX_ROLLBACKS,
)
from services.lookup import get_fleet_or_404, get_task_or_404, get_robot_or_404, get_map_node_or_404
from services.pagination import parse_pagination, paginate
from services.pathfinding import shortest_path_via
from services.serialize import task_to_dict
from services.transitions import (
    aggregate_parent_tasks,
    bump,
    project_parent_status,
    release_task_held_reservations,
)

tasks_bp = Blueprint("tasks", __name__)

SOURCES = {"INBOUND", "OUTBOUND", "REPLENISHMENT", "RELOCATION"}
PRIORITY_CLASSES = {"CRITICAL", "HIGH", "NORMAL", "LOW"}


@tasks_bp.route("/fleets/<fleet_id>/tasks", methods=["POST"])
def create_task(fleet_id):
    require_roles(["Operator", "WMS"])
    fleet = get_fleet_or_404(fleet_id)
    body = request.get_json(silent=True) or {}
    source = body.get("source")
    pickup = body.get("pickup_node_id")
    dropoff = body.get("dropoff_node_id")
    priority_class = body.get("priority_class", "NORMAL")
    payload_units = body.get("payload_units", 1)
    max_units = body.get("max_units_per_robot", 10)
    if source not in SOURCES:
        raise_error("ERR_BAD_REQUEST", "source invalid")
    if priority_class not in PRIORITY_CLASSES:
        raise_error("ERR_BAD_REQUEST", "priority_class invalid")
    if not isinstance(pickup, str) or not pickup:
        raise_error("ERR_BAD_REQUEST", "pickup_node_id required")
    if not isinstance(dropoff, str) or not dropoff:
        raise_error("ERR_BAD_REQUEST", "dropoff_node_id required")
    get_map_node_or_404(fleet_id, pickup)
    get_map_node_or_404(fleet_id, dropoff)
    if not isinstance(payload_units, int) or isinstance(payload_units, bool) or payload_units < 1:
        raise_error("ERR_BAD_REQUEST", "payload_units must be a positive integer")
    if not isinstance(max_units, int) or isinstance(max_units, bool) or max_units < 1:
        raise_error("ERR_BAD_REQUEST", "max_units_per_robot must be a positive integer")
    tid = new_id()
    now = fleet["clock_now"]
    task = {
        "id": tid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "fleet_id": fleet_id,
        "source": source,
        "priority_class": priority_class,
        "priority_score": 0,
        "payload_units": payload_units,
        "max_units_per_robot": max_units,
        "pickup_node_id": pickup,
        "dropoff_node_id": dropoff,
        "status": "QUEUED",
        "assigned_robot_id": None,
        "parent_task_id": None,
        "merged_into_task_id": None,
        "queued_at": now,
        "assigned_at": None,
        "started_at": None,
        "completed_at": None,
        "planned_path_node_ids": [],
        "rollback_count": 0,
    }
    task["priority_score"] = compute_priority_score(task, fleet)
    db.tasks[tid] = task
    write_audit(fleet, "TASK_STATUS", "Task", tid, None, "QUEUED", g.user_role)
    return success(task_to_dict(task), status=201)


@tasks_bp.route("/fleets/<fleet_id>/tasks/<task_id>", methods=["GET"])
def get_task(fleet_id, task_id):
    require_roles(["Operator", "FleetAdmin", "WMS"])
    get_fleet_or_404(fleet_id)
    task = get_task_or_404(fleet_id, task_id)
    view = request.args.get("view")
    if view == "projected":
        # If task is a parent, compute provisional status. Else return persisted.
        # Determine if task is a parent (has direct children).
        has_children = any(
            t.get("parent_task_id") == task_id for t in db.tasks.values()
        )
        if has_children:
            projected_status = project_parent_status(task)
            # Return a copy with projected status (no mutation)
            view_task = dict(task)
            view_task["status"] = projected_status
            return success(task_to_dict(view_task))
    return success(task_to_dict(task))


@tasks_bp.route("/fleets/<fleet_id>/tasks", methods=["GET"])
def list_tasks(fleet_id):
    require_roles(["Operator", "FleetAdmin", "WMS"])
    get_fleet_or_404(fleet_id)
    limit, offset = parse_pagination()
    status_f = request.args.get("status")
    source_f = request.args.get("source")
    priority_f = request.args.get("priority_class")
    items = [t for t in db.tasks.values() if t["fleet_id"] == fleet_id]
    if status_f:
        items = [t for t in items if t["status"] == status_f]
    if source_f:
        items = [t for t in items if t["source"] == source_f]
    if priority_f:
        items = [t for t in items if t["priority_class"] == priority_f]
    items.sort(key=lambda t: t["created_at"])
    page, total = paginate(items, limit, offset)
    return list_response(
        [task_to_dict(t) for t in page],
        total=total, limit=limit, offset=offset,
    )


@tasks_bp.route("/fleets/<fleet_id>/tasks/<task_id>:assign", methods=["POST"])
def assign_task(fleet_id, task_id):
    require_roles(["Operator"])
    fleet = get_fleet_or_404(fleet_id)
    task = get_task_or_404(fleet_id, task_id)
    body = request.get_json(silent=True) or {}
    robot_id = body.get("robot_id")
    if not isinstance(robot_id, str) or not robot_id:
        raise_error("ERR_BAD_REQUEST", "robot_id required")
    robot = get_robot_or_404(fleet_id, robot_id)

    if task["status"] != "QUEUED":
        raise_error("ERR_TASK_ALREADY_ASSIGNED", "Task is no longer QUEUED")
    # OCC
    if "version" in body and body["version"] != task["version"]:
        raise_error("ERR_INVALID_STATE", "Version mismatch")
    if robot["fault_state"] == "FAULTED":
        raise_error("ERR_ROBOT_FAULTED", "Robot is faulted")
    if robot["connectivity"] != "ONLINE":
        raise_error("ERR_ROBOT_OFFLINE", "Robot is offline")
    if robot.get("current_task_id"):
        raise_error("ERR_ROBOT_BUSY", "Robot already has a task")
    if robot["battery_pct"] <= fleet["charging_low_threshold_pct"]:
        raise_error("ERR_BATTERY_LOW", "Robot battery too low")
    # Isolation check: if pickup or dropoff is inside an active isolation zone
    pickup_node = db.map_nodes.get(task["pickup_node_id"])
    dropoff_node = db.map_nodes.get(task["dropoff_node_id"])
    isolated_node_ids: set[str] = set()
    for fi in db.fault_incidents.values():
        if fi["fleet_id"] == fleet_id and fi["status"] in {"OPEN", "TAKEOVER"}:
            for nid in fi.get("isolation_node_ids") or []:
                isolated_node_ids.add(nid)
    if pickup_node and pickup_node["id"] in isolated_node_ids:
        raise_error("ERR_ISOLATION_VIOLATION", "pickup is inside an isolation zone")
    if dropoff_node and dropoff_node["id"] in isolated_node_ids:
        raise_error("ERR_ISOLATION_VIOLATION", "dropoff is inside an isolation zone")

    cost, path = shortest_path_via(fleet_id, robot["position_node_id"],
                                   task["pickup_node_id"], task["dropoff_node_id"])
    if cost is None or not path:
        raise_error("ERR_NO_PATH", "No feasible path from robot through pickup to dropoff")

    task["status"] = "ASSIGNED"
    task["assigned_robot_id"] = robot_id
    task["assigned_at"] = fleet["clock_now"]
    task["planned_path_node_ids"] = path
    bump(task, fleet)
    robot["current_task_id"] = task_id
    bump(robot, fleet)
    write_audit(fleet, "TASK_STATUS", "Task", task_id, "QUEUED", "ASSIGNED", g.user_role)
    return success(task_to_dict(task))


@tasks_bp.route("/fleets/<fleet_id>/tasks/<task_id>:start", methods=["POST"])
def start_task(fleet_id, task_id):
    require_roles(["Operator"])
    fleet = get_fleet_or_404(fleet_id)
    task = get_task_or_404(fleet_id, task_id)
    body = request.get_json(silent=True) or {}
    if task["status"] == "CANCELLED" and task.get("rollback_count", 0) > MAX_ROLLBACKS:
        raise_error("ERR_ROLLBACK_LIMIT_REACHED", "Task exceeded rollback limit and was auto-cancelled")
    if task["status"] != "ASSIGNED":
        raise_error("ERR_INVALID_STATE", "Task must be ASSIGNED")
    if "version" in body and body["version"] != task["version"]:
        raise_error("ERR_INVALID_STATE", "Version mismatch")
    robot = db.robots.get(task.get("assigned_robot_id"))
    if not robot:
        raise_error("ERR_INVALID_STATE", "Assigned robot missing")
    if robot["fault_state"] == "FAULTED":
        raise_error("ERR_ROBOT_FAULTED", "Robot is faulted")
    if robot["connectivity"] != "ONLINE":
        raise_error("ERR_ROBOT_OFFLINE", "Robot is offline")
    task["status"] = "EXECUTING"
    task["started_at"] = fleet["clock_now"]
    bump(task, fleet)
    prev = robot["operational_state"]
    robot["operational_state"] = "EXECUTING"
    bump(robot, fleet)
    write_audit(fleet, "TASK_STATUS", "Task", task_id, "ASSIGNED", "EXECUTING", g.user_role)
    write_audit(fleet, "TASK_STATUS", "Robot", robot["id"], prev, "EXECUTING", g.user_role)
    return success(task_to_dict(task))


@tasks_bp.route("/fleets/<fleet_id>/tasks/<task_id>:complete", methods=["POST"])
def complete_task(fleet_id, task_id):
    require_roles(["Operator"])
    fleet = get_fleet_or_404(fleet_id)
    task = get_task_or_404(fleet_id, task_id)
    body = request.get_json(silent=True) or {}
    if task["status"] != "EXECUTING":
        raise_error("ERR_INVALID_STATE", "Task must be EXECUTING")
    if "version" in body and body["version"] != task["version"]:
        raise_error("ERR_INVALID_STATE", "Version mismatch")
    robot = db.robots.get(task.get("assigned_robot_id"))
    if not robot:
        raise_error("ERR_INVALID_STATE", "Assigned robot missing")
    if robot["position_node_id"] != task["dropoff_node_id"]:
        raise_error("ERR_INVALID_STATE", "Robot is not at the dropoff node")
    task["status"] = "COMPLETED"
    task["completed_at"] = fleet["clock_now"]
    bump(task, fleet)
    prev = robot["operational_state"]
    robot["operational_state"] = "IDLE"
    robot["current_task_id"] = None
    bump(robot, fleet)
    write_audit(fleet, "TASK_STATUS", "Task", task_id, "EXECUTING", "COMPLETED", g.user_role)
    write_audit(fleet, "TASK_STATUS", "Robot", robot["id"], prev, "IDLE", g.user_role)
    # Release HELD reservations belonging to this robot with scheduled_at >= clock_now
    from services.transitions import release_robot_held_reservations
    release_robot_held_reservations(robot["id"], fleet, only_future=True)
    # Parent aggregation
    aggregate_parent_tasks(fleet)
    return success(task_to_dict(task))


@tasks_bp.route("/fleets/<fleet_id>/tasks/<task_id>:cancel", methods=["POST"])
def cancel_task(fleet_id, task_id):
    require_roles(["Operator"])
    fleet = get_fleet_or_404(fleet_id)
    task = get_task_or_404(fleet_id, task_id)
    body = request.get_json(silent=True) or {}
    if task["status"] not in {"QUEUED", "ASSIGNED", "EXECUTING"}:
        raise_error("ERR_INVALID_STATE", "Task cannot be cancelled from this state")
    if "version" in body and body["version"] != task["version"]:
        raise_error("ERR_INVALID_STATE", "Version mismatch")
    # Check robot fault — cancelling a robot's task while it's faulted is an
    # "operate-on-faulted-robot" action.
    if task.get("assigned_robot_id"):
        robot = db.robots.get(task["assigned_robot_id"])
        if robot and robot["fault_state"] == "FAULTED":
            raise_error("ERR_ROBOT_FAULTED", "Robot is faulted; use takeover/resolve")
    # Dependency check
    if has_non_terminal_descendants_for_cancel(task):
        raise_error("ERR_HAS_DEPENDENCIES", "Task has non-terminal descendants")
    prev = task["status"]
    task["status"] = "CANCELLED"
    bump(task, fleet)
    if task.get("assigned_robot_id"):
        robot = db.robots.get(task["assigned_robot_id"])
        if robot:
            prev_op = robot["operational_state"]
            robot["operational_state"] = "IDLE"
            robot["current_task_id"] = None
            bump(robot, fleet)
            write_audit(fleet, "TASK_STATUS", "Robot", robot["id"], prev_op, "IDLE", g.user_role)
    release_task_held_reservations(task_id, fleet, only_future=True)
    write_audit(fleet, "TASK_STATUS", "Task", task_id, prev, "CANCELLED", g.user_role)
    aggregate_parent_tasks(fleet)
    return success(task_to_dict(task))


@tasks_bp.route("/fleets/<fleet_id>/tasks/<task_id>:split", methods=["POST"])
def split_task(fleet_id, task_id):
    require_roles(["Operator"])
    fleet = get_fleet_or_404(fleet_id)
    task = get_task_or_404(fleet_id, task_id)
    body = request.get_json(silent=True) or {}
    if "version" in body and body["version"] != task["version"]:
        raise_error("ERR_INVALID_STATE", "Version mismatch")
    if task["status"] != "QUEUED":
        raise_error("ERR_SPLIT_NOT_APPLICABLE", "Task must be QUEUED")
    if task.get("parent_task_id"):
        raise_error("ERR_SPLIT_NOT_APPLICABLE", "Cannot split a child task")
    if task["payload_units"] <= task["max_units_per_robot"]:
        raise_error("ERR_SPLIT_NOT_APPLICABLE", "payload_units does not exceed max_units_per_robot")
    n = math.ceil(task["payload_units"] / task["max_units_per_robot"])
    per_child = task["payload_units"] // n
    remainder = task["payload_units"] - per_child * n
    children = []
    now = fleet["clock_now"]
    for i in range(n):
        units = per_child + (remainder if i == n - 1 else 0)
        cid = new_id()
        child = {
            "id": cid,
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "fleet_id": fleet_id,
            "source": task["source"],
            "priority_class": task["priority_class"],
            "priority_score": 0,
            "payload_units": units,
            "max_units_per_robot": task["max_units_per_robot"],
            "pickup_node_id": task["pickup_node_id"],
            "dropoff_node_id": task["dropoff_node_id"],
            "status": "QUEUED",
            "assigned_robot_id": None,
            "parent_task_id": task_id,
            "merged_into_task_id": None,
            "queued_at": now,
            "assigned_at": None,
            "started_at": None,
            "completed_at": None,
            "planned_path_node_ids": [],
            "rollback_count": 0,
        }
        child["priority_score"] = compute_priority_score(child, fleet)
        db.tasks[cid] = child
        write_audit(fleet, "TASK_STATUS", "Task", cid, None, "QUEUED", g.user_role)
        children.append(child)
    bump(task, fleet)
    return list_response(
        [task_to_dict(c) for c in children],
        total=len(children), limit=len(children) or 10, offset=0,
    )


@tasks_bp.route("/fleets/<fleet_id>/tasks:merge", methods=["POST"])
def merge_tasks(fleet_id):
    require_roles(["Operator"])
    fleet = get_fleet_or_404(fleet_id)
    body = request.get_json(silent=True) or {}
    a_id = body.get("task_id_a")
    b_id = body.get("task_id_b")
    if not isinstance(a_id, str) or not isinstance(b_id, str):
        raise_error("ERR_BAD_REQUEST", "task_id_a and task_id_b required")
    if a_id == b_id:
        raise_error("ERR_MERGE_INCOMPATIBLE", "Cannot merge a task with itself")
    a = get_task_or_404(fleet_id, a_id)
    b = get_task_or_404(fleet_id, b_id)
    if a["status"] != "QUEUED" or b["status"] != "QUEUED":
        raise_error("ERR_INVALID_STATE", "Both tasks must be QUEUED")
    if a.get("parent_task_id") or b.get("parent_task_id"):
        raise_error("ERR_MERGE_INCOMPATIBLE", "Cannot merge child tasks")
    if a["source"] != b["source"]:
        raise_error("ERR_MERGE_INCOMPATIBLE", "Source mismatch")
    if a["priority_class"] != b["priority_class"]:
        raise_error("ERR_MERGE_INCOMPATIBLE", "Priority class mismatch")
    if a["pickup_node_id"] != b["pickup_node_id"]:
        raise_error("ERR_MERGE_INCOMPATIBLE", "Pickup mismatch")
    if a["dropoff_node_id"] != b["dropoff_node_id"]:
        raise_error("ERR_MERGE_INCOMPATIBLE", "Dropoff mismatch")
    # Survivor: lexicographically smaller id
    if a_id < b_id:
        survivor, loser = a, b
    else:
        survivor, loser = b, a
    combined = survivor["payload_units"] + loser["payload_units"]
    if combined > survivor["max_units_per_robot"]:
        raise_error("ERR_MERGE_INCOMPATIBLE", "Combined payload exceeds max_units_per_robot")
    survivor["payload_units"] = combined
    bump(survivor, fleet)
    loser["status"] = "MERGED"
    loser["merged_into_task_id"] = survivor["id"]
    bump(loser, fleet)
    write_audit(fleet, "TASK_STATUS", "Task", loser["id"], "QUEUED", "MERGED", g.user_role)
    return success(task_to_dict(survivor))
