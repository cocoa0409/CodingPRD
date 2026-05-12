"""Map node, map edge, and events:emit endpoints."""
from __future__ import annotations

from flask import Blueprint, request, g

from db import db, new_id
from errors import raise_error
from middleware import require_roles
from response import success
from services.audit import write_audit
from services.lookup import get_fleet_or_404, get_map_node_or_404
from services.serialize import map_node_to_dict, map_edge_to_dict, audit_event_to_dict, task_to_dict
from services.transitions import bump, reroute_around_blocked
from services.calculations import compute_priority_score

map_bp = Blueprint("map", __name__)

NODE_KINDS = {"LANE", "INTERSECTION", "LIFT_POINT", "CHARGER", "PARK", "SHELF"}


@map_bp.route("/fleets/<fleet_id>/map_nodes", methods=["POST"])
def create_map_node(fleet_id):
    require_roles(["FleetAdmin"])
    fleet = get_fleet_or_404(fleet_id)
    body = request.get_json(silent=True) or {}
    code = body.get("code")
    kind = body.get("kind")
    x = body.get("x")
    y = body.get("y")
    capacity = body.get("capacity", 1)
    if not isinstance(code, str) or not code:
        raise_error("ERR_BAD_REQUEST", "code is required")
    if kind not in NODE_KINDS:
        raise_error("ERR_BAD_REQUEST", f"kind must be one of {NODE_KINDS}")
    if not isinstance(x, int) or isinstance(x, bool):
        raise_error("ERR_BAD_REQUEST", "x must be an integer")
    if not isinstance(y, int) or isinstance(y, bool):
        raise_error("ERR_BAD_REQUEST", "y must be an integer")
    if not isinstance(capacity, int) or isinstance(capacity, bool) or capacity < 1:
        raise_error("ERR_BAD_REQUEST", "capacity must be a positive integer")
    if kind in {"INTERSECTION", "LIFT_POINT", "CHARGER"} and capacity != 1:
        raise_error("ERR_BAD_REQUEST", f"{kind} nodes must have capacity=1")
    # Unique code per fleet
    for n in db.map_nodes.values():
        if n["fleet_id"] == fleet_id and n["code"] == code:
            raise_error("ERR_BAD_REQUEST", f"MapNode code {code} already exists in fleet")
    nid = new_id()
    now = fleet["clock_now"]
    node = {
        "id": nid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "fleet_id": fleet_id,
        "code": code,
        "kind": kind,
        "x": x,
        "y": y,
        "capacity": capacity,
        "status": "OPEN",
        "blocked_reason": None,
    }
    db.map_nodes[nid] = node
    return success(map_node_to_dict(node), status=201)


@map_bp.route("/fleets/<fleet_id>/map_edges", methods=["POST"])
def create_map_edge(fleet_id):
    require_roles(["FleetAdmin"])
    fleet = get_fleet_or_404(fleet_id)
    body = request.get_json(silent=True) or {}
    from_id = body.get("from_node_id")
    to_id = body.get("to_node_id")
    cost = body.get("cost", 1)
    directional = body.get("directional", False)
    if not isinstance(from_id, str) or not from_id:
        raise_error("ERR_BAD_REQUEST", "from_node_id is required")
    if not isinstance(to_id, str) or not to_id:
        raise_error("ERR_BAD_REQUEST", "to_node_id is required")
    if not isinstance(cost, int) or isinstance(cost, bool) or cost < 1:
        raise_error("ERR_BAD_REQUEST", "cost must be a positive integer")
    if not isinstance(directional, bool):
        raise_error("ERR_BAD_REQUEST", "directional must be a boolean")
    # Nodes must exist
    get_map_node_or_404(fleet_id, from_id)
    get_map_node_or_404(fleet_id, to_id)
    eid = new_id()
    now = fleet["clock_now"]
    edge = {
        "id": eid,
        "created_at": now,
        "fleet_id": fleet_id,
        "from_node_id": from_id,
        "to_node_id": to_id,
        "cost": cost,
        "directional": directional,
    }
    db.map_edges[eid] = edge
    # If non-directional, materialize the reverse
    if not directional:
        rid = new_id()
        rev = {
            "id": rid,
            "created_at": now,
            "fleet_id": fleet_id,
            "from_node_id": to_id,
            "to_node_id": from_id,
            "cost": cost,
            "directional": False,
        }
        db.map_edges[rid] = rev
    return success(map_edge_to_dict(edge), status=201)


@map_bp.route("/fleets/<fleet_id>/events:emit", methods=["POST"])
def emit_event(fleet_id):
    require_roles(["WMS", "FleetAdmin"])
    fleet = get_fleet_or_404(fleet_id)
    body = request.get_json(silent=True) or {}
    event_kind = body.get("event_kind")
    if event_kind not in {"TASK_STATUS", "FAULT", "WMS_SYNC", "EQUIPMENT_LOCK", "EQUIPMENT_UNLOCK"}:
        raise_error("ERR_BAD_REQUEST", "event_kind invalid")
    node_ids = body.get("node_ids") or []
    payload = body.get("wms_task_payload")

    if event_kind == "EQUIPMENT_LOCK":
        for nid in node_ids:
            node = db.map_nodes.get(nid)
            if not node or node["fleet_id"] != fleet_id:
                raise_error("ERR_NOT_FOUND", f"MapNode {nid} not found")
        for nid in node_ids:
            node = db.map_nodes[nid]
            if node["status"] == "OPEN":
                node["status"] = "BLOCKED"
                node["blocked_reason"] = "EQUIPMENT_LOCKED"
                bump(node, fleet)
                write_audit(fleet, "EQUIPMENT_LOCK", "MapNode", nid, "OPEN", "BLOCKED", g.user_role)
                reroute_around_blocked(nid, fleet)
        ev = write_audit(fleet, "EQUIPMENT_LOCK", "MapNode",
                         node_ids[0] if node_ids else fleet_id,
                         None, "BLOCKED", g.user_role)
        return success(audit_event_to_dict(ev))
    elif event_kind == "EQUIPMENT_UNLOCK":
        for nid in node_ids:
            node = db.map_nodes.get(nid)
            if not node or node["fleet_id"] != fleet_id:
                raise_error("ERR_NOT_FOUND", f"MapNode {nid} not found")
        for nid in node_ids:
            node = db.map_nodes[nid]
            if node["status"] == "BLOCKED":
                node["status"] = "OPEN"
                node["blocked_reason"] = None
                bump(node, fleet)
                write_audit(fleet, "EQUIPMENT_UNLOCK", "MapNode", nid, "BLOCKED", "OPEN", g.user_role)
        ev = write_audit(fleet, "EQUIPMENT_UNLOCK", "MapNode",
                         node_ids[0] if node_ids else fleet_id,
                         None, "OPEN", g.user_role)
        return success(audit_event_to_dict(ev))
    elif event_kind == "WMS_SYNC":
        if not isinstance(payload, dict):
            # PRD §3.10: wms_task_payload is OPTIONAL. With a payload it is
            # equivalent to creating a task; without one, just record the
            # external event with actor_role WMS.
            ev = write_audit(
                fleet, "WMS_SYNC", "Task",
                body.get("subject_id") or fleet_id,
                None, None, g.user_role,
            )
            return success(audit_event_to_dict(ev))
        # Equivalent to POST /tasks but actor_role = WMS
        source = payload.get("source")
        pickup = payload.get("pickup_node_id")
        dropoff = payload.get("dropoff_node_id")
        priority_class = payload.get("priority_class", "NORMAL")
        payload_units = payload.get("payload_units", 1)
        max_units = payload.get("max_units_per_robot", 10)
        if source not in {"INBOUND", "OUTBOUND", "REPLENISHMENT", "RELOCATION"}:
            raise_error("ERR_BAD_REQUEST", "source invalid")
        if priority_class not in {"CRITICAL", "HIGH", "NORMAL", "LOW"}:
            raise_error("ERR_BAD_REQUEST", "priority_class invalid")
        if not isinstance(pickup, str) or not pickup:
            raise_error("ERR_BAD_REQUEST", "pickup_node_id required")
        if not isinstance(dropoff, str) or not dropoff:
            raise_error("ERR_BAD_REQUEST", "dropoff_node_id required")
        # Verify nodes exist in fleet
        pn = db.map_nodes.get(pickup)
        dn = db.map_nodes.get(dropoff)
        if not pn or pn["fleet_id"] != fleet_id:
            raise_error("ERR_NOT_FOUND", "pickup_node_id not found in fleet")
        if not dn or dn["fleet_id"] != fleet_id:
            raise_error("ERR_NOT_FOUND", "dropoff_node_id not found in fleet")
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
        write_audit(fleet, "WMS_SYNC", "Task", tid, None, "QUEUED", "WMS")
        return success(task_to_dict(task), status=201)
    elif event_kind == "TASK_STATUS":
        ev = write_audit(fleet, "TASK_STATUS", "Task", body.get("subject_id") or fleet_id, None, "EVENT", g.user_role)
        return success(audit_event_to_dict(ev))
    elif event_kind == "FAULT":
        ev = write_audit(fleet, "FAULT", "Robot", body.get("subject_id") or fleet_id, None, "EVENT", g.user_role)
        return success(audit_event_to_dict(ev))
