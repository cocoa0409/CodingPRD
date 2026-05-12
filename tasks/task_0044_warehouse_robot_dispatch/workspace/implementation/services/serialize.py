"""Resource serialization — produces the JSON form for each entity."""
from __future__ import annotations

from db import fmt_iso


def _common(obj: dict) -> dict:
    """Common quartet: id, created_at, updated_at, version."""
    return {
        "id": obj["id"],
        "created_at": fmt_iso(obj["created_at"]),
        "updated_at": fmt_iso(obj["updated_at"]),
        "version": obj["version"],
    }


def fleet_to_dict(fleet: dict) -> dict:
    return {
        **_common(fleet),
        "name": fleet["name"],
        "clock_now": fmt_iso(fleet["clock_now"]),
        "charging_low_threshold_pct": fleet["charging_low_threshold_pct"],
        "charging_opportunity_pct": fleet["charging_opportunity_pct"],
        "charging_full_pct": fleet["charging_full_pct"],
        "slot_seconds": fleet["slot_seconds"],
        "task_expiry_seconds": fleet["task_expiry_seconds"],
        "deadlock_wait_seconds": fleet["deadlock_wait_seconds"],
    }


def map_node_to_dict(node: dict) -> dict:
    return {
        **_common(node),
        "fleet_id": node["fleet_id"],
        "code": node["code"],
        "kind": node["kind"],
        "x": node["x"],
        "y": node["y"],
        "capacity": node["capacity"],
        "status": node["status"],
        "blocked_reason": node.get("blocked_reason"),
    }


def map_edge_to_dict(edge: dict) -> dict:
    # Append-only ledger: only id and created_at
    return {
        "id": edge["id"],
        "created_at": fmt_iso(edge["created_at"]),
        "fleet_id": edge["fleet_id"],
        "from_node_id": edge["from_node_id"],
        "to_node_id": edge["to_node_id"],
        "cost": edge["cost"],
        "directional": edge["directional"],
    }


def charging_station_to_dict(station: dict, queue_length: int) -> dict:
    return {
        **_common(station),
        "fleet_id": station["fleet_id"],
        "node_id": station["node_id"],
        "status": station["status"],
        "occupying_robot_id": station.get("occupying_robot_id"),
        "queue_length": queue_length,
        "charge_rate_pct_per_second": station["charge_rate_pct_per_second"],
    }


def robot_to_dict(robot: dict, trajectory_count: int) -> dict:
    return {
        **_common(robot),
        "fleet_id": robot["fleet_id"],
        "code": robot["code"],
        "connectivity": robot["connectivity"],
        "operational_state": robot["operational_state"],
        "fault_state": robot["fault_state"],
        "battery_pct": robot["battery_pct"],
        "position_node_id": robot["position_node_id"],
        "current_task_id": robot.get("current_task_id"),
        "charging_station_id": robot.get("charging_station_id"),
        "last_heartbeat_at": fmt_iso(robot["last_heartbeat_at"]) if robot.get("last_heartbeat_at") else None,
        "standby_priority": robot["standby_priority"],
        "trajectory_archived_count": trajectory_count,
    }


def task_to_dict(task: dict) -> dict:
    return {
        **_common(task),
        "fleet_id": task["fleet_id"],
        "source": task["source"],
        "priority_class": task["priority_class"],
        "priority_score": task["priority_score"],
        "payload_units": task["payload_units"],
        "max_units_per_robot": task["max_units_per_robot"],
        "pickup_node_id": task["pickup_node_id"],
        "dropoff_node_id": task["dropoff_node_id"],
        "status": task["status"],
        "assigned_robot_id": task.get("assigned_robot_id"),
        "parent_task_id": task.get("parent_task_id"),
        "merged_into_task_id": task.get("merged_into_task_id"),
        "queued_at": fmt_iso(task["queued_at"]) if task.get("queued_at") else None,
        "assigned_at": fmt_iso(task["assigned_at"]) if task.get("assigned_at") else None,
        "started_at": fmt_iso(task["started_at"]) if task.get("started_at") else None,
        "completed_at": fmt_iso(task["completed_at"]) if task.get("completed_at") else None,
        "planned_path_node_ids": list(task.get("planned_path_node_ids") or []),
        "rollback_count": task.get("rollback_count", 0),
    }


def slot_reservation_to_dict(slot: dict) -> dict:
    return {
        "id": slot["id"],
        "created_at": fmt_iso(slot["created_at"]),
        "fleet_id": slot["fleet_id"],
        "node_id": slot["node_id"],
        "robot_id": slot["robot_id"],
        "task_id": slot.get("task_id"),
        "slot_index": slot["slot_index"],
        "scheduled_at": fmt_iso(slot["scheduled_at"]),
        "status": slot["status"],
    }


def charging_session_to_dict(session: dict) -> dict:
    return {
        **_common(session),
        "fleet_id": session["fleet_id"],
        "robot_id": session["robot_id"],
        "charging_station_id": session["charging_station_id"],
        "trigger": session["trigger"],
        "status": session["status"],
        "start_battery_pct": session.get("start_battery_pct"),
        "end_battery_pct": session.get("end_battery_pct"),
        "started_at": fmt_iso(session["started_at"]) if session.get("started_at") else None,
        "completed_at": fmt_iso(session["completed_at"]) if session.get("completed_at") else None,
    }


def fault_incident_to_dict(incident: dict) -> dict:
    return {
        **_common(incident),
        "fleet_id": incident["fleet_id"],
        "robot_id": incident["robot_id"],
        "kind": incident["kind"],
        "status": incident["status"],
        "isolation_node_ids": list(incident.get("isolation_node_ids") or []),
        "rolled_back_task_id": incident.get("rolled_back_task_id"),
        "reassigned_task_id": incident.get("reassigned_task_id"),
        "detected_at": fmt_iso(incident["detected_at"]) if incident.get("detected_at") else None,
        "takeover_started_at": fmt_iso(incident["takeover_started_at"]) if incident.get("takeover_started_at") else None,
        "resolved_at": fmt_iso(incident["resolved_at"]) if incident.get("resolved_at") else None,
    }


def trajectory_record_to_dict(rec: dict) -> dict:
    return {
        "id": rec["id"],
        "created_at": fmt_iso(rec["created_at"]),
        "robot_id": rec["robot_id"],
        "from_node_id": rec["from_node_id"],
        "to_node_id": rec["to_node_id"],
        "occurred_at": fmt_iso(rec["occurred_at"]),
    }


def audit_event_to_dict(ev: dict) -> dict:
    return {
        "id": ev["id"],
        "created_at": fmt_iso(ev["created_at"]),
        "fleet_id": ev["fleet_id"],
        "event_kind": ev["event_kind"],
        "subject_kind": ev["subject_kind"],
        "subject_id": ev["subject_id"],
        "from_state": ev.get("from_state"),
        "to_state": ev["to_state"],
        "actor_role": ev["actor_role"],
        "occurred_at": fmt_iso(ev["occurred_at"]),
    }
