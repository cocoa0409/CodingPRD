"""Robot endpoints — register, read, list, heartbeat, step, dock/undock, queue, faults."""
from __future__ import annotations

from flask import Blueprint, request, g

from db import db, new_id
from errors import raise_error
from middleware import require_roles
from response import success, list_response
from services.audit import write_audit
from services.calculations import compute_priority_score
from services.lookup import (
    get_fleet_or_404,
    get_robot_or_404,
    get_map_node_or_404,
    get_station_or_404,
)
from services.pagination import parse_pagination, paginate
from services.serialize import (
    robot_to_dict,
    charging_session_to_dict,
    trajectory_record_to_dict,
    fault_incident_to_dict,
)
from services.transitions import (
    advance_station_queue,
    bump,
    cancel_charging_session,
    open_fault_incident,
    queue_length_for,
    release_robot_held_reservations,
    trajectory_count_for,
)

robots_bp = Blueprint("robots", __name__)


@robots_bp.route("/fleets/<fleet_id>/robots", methods=["POST"])
def register_robot(fleet_id):
    require_roles(["FleetAdmin"])
    fleet = get_fleet_or_404(fleet_id)
    body = request.get_json(silent=True) or {}
    code = body.get("code")
    pos = body.get("position_node_id")
    battery = body.get("battery_pct", 100)
    standby = body.get("standby_priority", 100)
    if not isinstance(code, str) or not code:
        raise_error("ERR_BAD_REQUEST", "code required")
    if not isinstance(pos, str) or not pos:
        raise_error("ERR_BAD_REQUEST", "position_node_id required")
    get_map_node_or_404(fleet_id, pos)
    if not isinstance(battery, int) or isinstance(battery, bool) or not (0 <= battery <= 100):
        raise_error("ERR_BAD_REQUEST", "battery_pct must be 0..100")
    if not isinstance(standby, int) or isinstance(standby, bool) or standby < 0:
        raise_error("ERR_BAD_REQUEST", "standby_priority must be >= 0")
    for r in db.robots.values():
        if r["fleet_id"] == fleet_id and r["code"] == code:
            raise_error("ERR_BAD_REQUEST", f"Robot code {code} already exists in fleet")
    rid = new_id()
    now = fleet["clock_now"]
    robot = {
        "id": rid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "fleet_id": fleet_id,
        "code": code,
        "connectivity": "ONLINE",
        "operational_state": "IDLE",
        "fault_state": "OK",
        "battery_pct": battery,
        "position_node_id": pos,
        "current_task_id": None,
        "charging_station_id": None,
        "last_heartbeat_at": now,
        "standby_priority": standby,
    }
    db.robots[rid] = robot
    return success(robot_to_dict(robot, trajectory_count_for(rid)), status=201)


@robots_bp.route("/fleets/<fleet_id>/robots/<robot_id>", methods=["GET"])
def get_robot(fleet_id, robot_id):
    require_roles(["Operator", "FleetAdmin", "WMS"])
    get_fleet_or_404(fleet_id)
    robot = get_robot_or_404(fleet_id, robot_id)
    return success(robot_to_dict(robot, trajectory_count_for(robot_id)))


@robots_bp.route("/fleets/<fleet_id>/robots", methods=["GET"])
def list_robots(fleet_id):
    require_roles(["Operator", "FleetAdmin", "WMS"])
    get_fleet_or_404(fleet_id)
    limit, offset = parse_pagination()
    op_state = request.args.get("operational_state")
    conn = request.args.get("connectivity")
    flt = request.args.get("fault_state")
    items = [r for r in db.robots.values() if r["fleet_id"] == fleet_id]
    if op_state:
        items = [r for r in items if r["operational_state"] == op_state]
    if conn:
        items = [r for r in items if r["connectivity"] == conn]
    if flt:
        items = [r for r in items if r["fault_state"] == flt]
    items.sort(key=lambda r: r["created_at"])
    page, total = paginate(items, limit, offset)
    return list_response(
        [robot_to_dict(r, trajectory_count_for(r["id"])) for r in page],
        total=total, limit=limit, offset=offset,
    )


@robots_bp.route("/fleets/<fleet_id>/robots/<robot_id>:heartbeat", methods=["POST"])
def heartbeat(fleet_id, robot_id):
    require_roles(["Operator"])
    fleet = get_fleet_or_404(fleet_id)
    robot = get_robot_or_404(fleet_id, robot_id)
    robot["last_heartbeat_at"] = fleet["clock_now"]
    if robot["connectivity"] == "OFFLINE":
        robot["connectivity"] = "ONLINE"
    bump(robot, fleet)
    return success(robot_to_dict(robot, trajectory_count_for(robot_id)))


@robots_bp.route("/fleets/<fleet_id>/robots/<robot_id>:step", methods=["POST"])
def step_robot(fleet_id, robot_id):
    require_roles(["Operator"])
    fleet = get_fleet_or_404(fleet_id)
    robot = get_robot_or_404(fleet_id, robot_id)
    if robot["fault_state"] == "FAULTED":
        raise_error("ERR_ROBOT_FAULTED", "Robot is faulted")
    if robot["connectivity"] != "ONLINE":
        raise_error("ERR_ROBOT_OFFLINE", "Robot is offline")
    if robot["operational_state"] not in {"EXECUTING", "WAITING_RIGHT_OF_WAY"}:
        raise_error("ERR_INVALID_STATE", "Robot must be EXECUTING or WAITING_RIGHT_OF_WAY to step")
    task_id = robot.get("current_task_id")
    if not task_id:
        raise_error("ERR_INVALID_STATE", "Robot has no current task")
    task = db.tasks.get(task_id)
    if not task:
        raise_error("ERR_INVALID_STATE", "Task missing")
    path = task.get("planned_path_node_ids") or []
    if not path:
        raise_error("ERR_INVALID_STATE", "Robot has no planned path")
    try:
        idx = path.index(robot["position_node_id"])
    except ValueError:
        raise_error("ERR_INVALID_STATE", "Robot position not on planned path")
    if idx + 1 >= len(path):
        raise_error("ERR_INVALID_STATE", "Robot already at end of planned path")
    next_node_id = path[idx + 1]
    next_node = db.map_nodes.get(next_node_id)
    if not next_node:
        raise_error("ERR_INVALID_STATE", "Next node missing")
    # Blocked node check
    if next_node["status"] == "BLOCKED":
        raise_error("ERR_OBSTACLE_BLOCKING", "Next node is blocked")
    # Compute occupancy of next node
    occupants = sum(1 for r in db.robots.values()
                    if r["fleet_id"] == fleet_id and r["position_node_id"] == next_node_id and r["id"] != robot_id)
    needs_slot = next_node["kind"] in {"INTERSECTION", "LIFT_POINT"}
    slot_index_for_now = (int((fleet["clock_now"] - db.fleets[fleet_id]["clock_now"]).total_seconds()) +
                          0)  # placeholder; we compute below
    # Compute current slot at INTERSECTION/LIFT_POINT
    from db import to_unix
    slot_seconds = fleet["slot_seconds"]
    current_slot_index = to_unix(fleet["clock_now"]) // slot_seconds

    if needs_slot:
        # Robot must hold a HELD reservation for (next_node_id, current_slot_index)
        held = [
            s for s in db.slot_reservations.values()
            if s["fleet_id"] == fleet_id and s["node_id"] == next_node_id and s["robot_id"] == robot_id
            and s["status"] == "HELD" and s["slot_index"] == current_slot_index
        ]
        if not held:
            raise_error("ERR_RIGHT_OF_WAY_MISSING", "No HELD slot reservation for this slot")
    # Capacity check
    if occupants >= next_node["capacity"]:
        prev = robot["operational_state"]
        robot["operational_state"] = "WAITING_RIGHT_OF_WAY"
        robot["last_heartbeat_at"] = fleet["clock_now"]
        bump(robot, fleet)
        db.robot_wait_transition_at[robot_id] = fleet["clock_now"]
        if prev != "WAITING_RIGHT_OF_WAY":
            write_audit(fleet, "TASK_STATUS", "Robot", robot_id, prev, "WAITING_RIGHT_OF_WAY", g.user_role)
        return success(robot_to_dict(robot, trajectory_count_for(robot_id)))
    # Move
    prev_pos = robot["position_node_id"]
    robot["position_node_id"] = next_node_id
    # Battery debit: traversed edge's cost
    edge_cost = 1
    for edge in db.map_edges.values():
        if edge["fleet_id"] == fleet_id and edge["from_node_id"] == prev_pos and edge["to_node_id"] == next_node_id:
            edge_cost = edge["cost"]
            break
    robot["battery_pct"] = max(0, robot["battery_pct"] - edge_cost)
    # Append trajectory record
    tr_id = new_id()
    tr = {
        "id": tr_id,
        "created_at": fleet["clock_now"],
        "robot_id": robot_id,
        "from_node_id": prev_pos,
        "to_node_id": next_node_id,
        "occurred_at": fleet["clock_now"],
    }
    db.trajectory_records[tr_id] = tr
    # If we were waiting and held a reservation, consume it
    if robot["operational_state"] == "WAITING_RIGHT_OF_WAY":
        prev_op = "WAITING_RIGHT_OF_WAY"
        robot["operational_state"] = "EXECUTING"
        db.robot_wait_transition_at.pop(robot_id, None)
        write_audit(fleet, "TASK_STATUS", "Robot", robot_id, prev_op, "EXECUTING", g.user_role)
    if needs_slot:
        held = [
            s for s in db.slot_reservations.values()
            if s["fleet_id"] == fleet_id and s["node_id"] == next_node_id and s["robot_id"] == robot_id
            and s["status"] == "HELD" and s["slot_index"] == current_slot_index
        ]
        if held:
            held[0]["status"] = "CONSUMED"
    bump(robot, fleet)
    return success(robot_to_dict(robot, trajectory_count_for(robot_id)))


@robots_bp.route("/fleets/<fleet_id>/robots/<robot_id>:dock", methods=["POST"])
def dock(fleet_id, robot_id):
    require_roles(["Operator"])
    fleet = get_fleet_or_404(fleet_id)
    robot = get_robot_or_404(fleet_id, robot_id)
    if robot["fault_state"] == "FAULTED":
        raise_error("ERR_ROBOT_FAULTED", "Robot is faulted")
    if robot["operational_state"] == "EXECUTING":
        raise_error("ERR_INVALID_STATE", "Cannot dock while EXECUTING; complete or cancel first")
    if robot["operational_state"] not in {"IDLE", "WAITING_RIGHT_OF_WAY"}:
        raise_error("ERR_INVALID_STATE", "Robot must be IDLE or WAITING_RIGHT_OF_WAY to dock")
    # Find station co-located on this node
    station = None
    for s in db.charging_stations.values():
        if s["fleet_id"] == fleet_id and s["node_id"] == robot["position_node_id"]:
            station = s
            break
    if not station:
        raise_error("ERR_CHARGER_UNAVAILABLE", "No charging station at robot position")
    if station["status"] != "AVAILABLE":
        raise_error("ERR_CHARGER_UNAVAILABLE", "Charging station not available")
    # Determine trigger
    low = fleet["charging_low_threshold_pct"]
    opp = fleet["charging_opportunity_pct"]
    bat = robot["battery_pct"]
    if bat <= low:
        trigger = "FORCED_LOW"
    elif robot["operational_state"] == "IDLE" and bat <= opp:
        trigger = "OPPORTUNITY"
    else:
        trigger = "MANUAL"
    # Create session
    sid = new_id()
    now = fleet["clock_now"]
    session = {
        "id": sid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "fleet_id": fleet_id,
        "robot_id": robot_id,
        "charging_station_id": station["id"],
        "trigger": trigger,
        "status": "CHARGING",
        "start_battery_pct": bat,
        "end_battery_pct": None,
        "started_at": now,
        "completed_at": None,
    }
    db.charging_sessions[sid] = session
    station["status"] = "OCCUPIED"
    station["occupying_robot_id"] = robot_id
    bump(station, fleet)
    prev = robot["operational_state"]
    robot["operational_state"] = "CHARGING"
    robot["charging_station_id"] = station["id"]
    bump(robot, fleet)
    if prev != "CHARGING":
        write_audit(fleet, "TASK_STATUS", "Robot", robot_id, prev, "CHARGING", g.user_role)
    return success(charging_session_to_dict(session))


@robots_bp.route("/fleets/<fleet_id>/robots/<robot_id>:undock", methods=["POST"])
def undock(fleet_id, robot_id):
    require_roles(["Operator"])
    fleet = get_fleet_or_404(fleet_id)
    robot = get_robot_or_404(fleet_id, robot_id)
    if robot["fault_state"] == "FAULTED":
        raise_error("ERR_ROBOT_FAULTED", "Robot is faulted")
    if robot["operational_state"] != "CHARGING":
        raise_error("ERR_INVALID_STATE", "Robot is not CHARGING")
    # Find active session
    session = None
    for s in db.charging_sessions.values():
        if s["robot_id"] == robot_id and s["status"] == "CHARGING":
            session = s
            break
    station_id = robot.get("charging_station_id")
    station = db.charging_stations.get(station_id) if station_id else None
    if session:
        session["status"] = "COMPLETED"
        session["end_battery_pct"] = robot["battery_pct"]
        session["completed_at"] = fleet["clock_now"]
        bump(session, fleet)
    if station:
        station["status"] = "AVAILABLE"
        station["occupying_robot_id"] = None
        bump(station, fleet)
    prev = robot["operational_state"]
    robot["operational_state"] = "IDLE"
    robot["charging_station_id"] = None
    bump(robot, fleet)
    write_audit(fleet, "TASK_STATUS", "Robot", robot_id, prev, "IDLE", g.user_role)
    if station:
        advance_station_queue(station, fleet)
    return success(robot_to_dict(robot, trajectory_count_for(robot_id)))


@robots_bp.route("/fleets/<fleet_id>/robots/<robot_id>:queue_charger", methods=["POST"])
def queue_charger(fleet_id, robot_id):
    require_roles(["Operator"])
    fleet = get_fleet_or_404(fleet_id)
    robot = get_robot_or_404(fleet_id, robot_id)
    if robot["fault_state"] == "FAULTED":
        raise_error("ERR_ROBOT_FAULTED", "Robot is faulted")
    if robot["operational_state"] not in {"IDLE", "EXECUTING", "WAITING_RIGHT_OF_WAY"}:
        raise_error("ERR_INVALID_STATE", "Cannot queue from this state")
    body = request.get_json(silent=True) or {}
    station_id = body.get("charging_station_id")
    if not isinstance(station_id, str) or not station_id:
        raise_error("ERR_BAD_REQUEST", "charging_station_id required")
    station = get_station_or_404(fleet_id, station_id)
    sid = new_id()
    now = fleet["clock_now"]
    session = {
        "id": sid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "fleet_id": fleet_id,
        "robot_id": robot_id,
        "charging_station_id": station_id,
        "trigger": "OPPORTUNITY" if robot["battery_pct"] > fleet["charging_low_threshold_pct"] else "FORCED_LOW",
        "status": "QUEUED",
        "start_battery_pct": robot["battery_pct"],
        "end_battery_pct": None,
        "started_at": None,
        "completed_at": None,
    }
    db.charging_sessions[sid] = session
    prev = robot["operational_state"]
    robot["operational_state"] = "WAITING_CHARGER"
    robot["charging_station_id"] = station_id
    bump(robot, fleet)
    write_audit(fleet, "TASK_STATUS", "Robot", robot_id, prev, "WAITING_CHARGER", g.user_role)
    return success(charging_session_to_dict(session))


@robots_bp.route("/fleets/<fleet_id>/robots/<robot_id>/faults", methods=["POST"])
def open_fault(fleet_id, robot_id):
    require_roles(["Operator", "FleetAdmin"])
    fleet = get_fleet_or_404(fleet_id)
    robot = get_robot_or_404(fleet_id, robot_id)
    body = request.get_json(silent=True) or {}
    kind = body.get("kind")
    if kind not in {"COMM_LOSS", "SENSOR_ANOMALY", "MECHANICAL_FAULT"}:
        raise_error("ERR_BAD_REQUEST", "kind invalid")
    incident = open_fault_incident(robot, kind, fleet, g.user_role)
    return success(fault_incident_to_dict(incident), status=201)


@robots_bp.route("/fleets/<fleet_id>/robots/<robot_id>/trajectory", methods=["GET"])
def list_trajectory(fleet_id, robot_id):
    require_roles(["Operator", "FleetAdmin", "WMS"])
    get_fleet_or_404(fleet_id)
    get_robot_or_404(fleet_id, robot_id)
    limit, offset = parse_pagination()
    items = [t for t in db.trajectory_records.values() if t["robot_id"] == robot_id]
    items.sort(key=lambda t: t["created_at"])
    page, total = paginate(items, limit, offset)
    return list_response(
        [trajectory_record_to_dict(t) for t in page],
        total=total, limit=limit, offset=offset,
    )
