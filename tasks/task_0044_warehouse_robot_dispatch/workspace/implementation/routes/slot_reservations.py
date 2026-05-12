"""Slot reservation endpoints."""
from __future__ import annotations

from datetime import datetime

from flask import Blueprint, request

from db import db, new_id, parse_iso, to_unix
from errors import raise_error
from middleware import require_roles
from response import success, list_response
from services.lookup import get_fleet_or_404, get_robot_or_404, get_map_node_or_404
from services.pagination import parse_pagination, paginate
from services.serialize import slot_reservation_to_dict

slots_bp = Blueprint("slots", __name__)


@slots_bp.route("/fleets/<fleet_id>/slot_reservations", methods=["POST"])
def create_slot(fleet_id):
    require_roles(["Operator"])
    fleet = get_fleet_or_404(fleet_id)
    body = request.get_json(silent=True) or {}
    node_id = body.get("node_id")
    robot_id = body.get("robot_id")
    scheduled_at = body.get("scheduled_at")
    if not isinstance(node_id, str) or not node_id:
        raise_error("ERR_BAD_REQUEST", "node_id required")
    if not isinstance(robot_id, str) or not robot_id:
        raise_error("ERR_BAD_REQUEST", "robot_id required")
    if not isinstance(scheduled_at, str) or not scheduled_at:
        raise_error("ERR_BAD_REQUEST", "scheduled_at required")
    node = get_map_node_or_404(fleet_id, node_id)
    robot = get_robot_or_404(fleet_id, robot_id)
    try:
        sched_dt = parse_iso(scheduled_at)
    except Exception:
        raise_error("ERR_BAD_REQUEST", "scheduled_at must be ISO 8601")
    sched_unix = to_unix(sched_dt)
    slot_seconds = fleet["slot_seconds"]
    if sched_unix % slot_seconds != 0:
        raise_error("ERR_SLOT_TIME_INVALID", "scheduled_at must be aligned to slot_seconds")
    if sched_dt < fleet["clock_now"]:
        raise_error("ERR_SLOT_TIME_INVALID", "scheduled_at must be at or after current clock")
    slot_index = sched_unix // slot_seconds
    # Uniqueness on (fleet_id, node_id, slot_index, status=HELD)
    for s in db.slot_reservations.values():
        if (s["fleet_id"] == fleet_id
                and s["node_id"] == node_id
                and s["slot_index"] == slot_index
                and s["status"] == "HELD"):
            raise_error("ERR_SLOT_ALREADY_RESERVED",
                        f"Slot {slot_index} at {node_id} already held")
    sid = new_id()
    now = fleet["clock_now"]
    # Try to attach a task_id (robot's current task)
    task_id = robot.get("current_task_id")
    slot = {
        "id": sid,
        "created_at": now,
        "fleet_id": fleet_id,
        "node_id": node_id,
        "robot_id": robot_id,
        "task_id": task_id,
        "slot_index": slot_index,
        "scheduled_at": sched_dt,
        "status": "HELD",
    }
    db.slot_reservations[sid] = slot
    return success(slot_reservation_to_dict(slot), status=201)


@slots_bp.route("/fleets/<fleet_id>/slot_reservations", methods=["GET"])
def list_slots(fleet_id):
    require_roles(["Operator", "FleetAdmin"])
    get_fleet_or_404(fleet_id)
    limit, offset = parse_pagination()
    args = request.args
    node_id_f = args.get("node_id")
    robot_id_f = args.get("robot_id")
    status_f = args.get("status")
    sched_min = args.get("scheduled_at_min")
    sched_max = args.get("scheduled_at_max")
    items = [s for s in db.slot_reservations.values() if s["fleet_id"] == fleet_id]
    if node_id_f:
        items = [s for s in items if s["node_id"] == node_id_f]
    if robot_id_f:
        items = [s for s in items if s["robot_id"] == robot_id_f]
    if status_f:
        items = [s for s in items if s["status"] == status_f]
    if sched_min:
        try:
            cutoff = parse_iso(sched_min)
            items = [s for s in items if s["scheduled_at"] >= cutoff]
        except Exception:
            raise_error("ERR_BAD_REQUEST", "scheduled_at_min must be ISO 8601")
    if sched_max:
        try:
            cap = parse_iso(sched_max)
            items = [s for s in items if s["scheduled_at"] <= cap]
        except Exception:
            raise_error("ERR_BAD_REQUEST", "scheduled_at_max must be ISO 8601")
    items.sort(key=lambda s: s["created_at"])
    page, total = paginate(items, limit, offset)
    return list_response(
        [slot_reservation_to_dict(s) for s in page],
        total=total, limit=limit, offset=offset,
    )
