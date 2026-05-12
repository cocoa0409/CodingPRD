"""Lookup helpers that raise ERR_NOT_FOUND if a path-segment ID is missing."""
from __future__ import annotations

from db import db
from errors import raise_error


def get_fleet_or_404(fleet_id: str) -> dict:
    fleet = db.fleets.get(fleet_id)
    if not fleet:
        raise_error("ERR_NOT_FOUND", f"Fleet {fleet_id} not found")
    return fleet


def get_robot_or_404(fleet_id: str, robot_id: str) -> dict:
    robot = db.robots.get(robot_id)
    if not robot or robot["fleet_id"] != fleet_id:
        raise_error("ERR_NOT_FOUND", f"Robot {robot_id} not found")
    return robot


def get_task_or_404(fleet_id: str, task_id: str) -> dict:
    task = db.tasks.get(task_id)
    if not task or task["fleet_id"] != fleet_id:
        raise_error("ERR_NOT_FOUND", f"Task {task_id} not found")
    return task


def get_station_or_404(fleet_id: str, station_id: str) -> dict:
    station = db.charging_stations.get(station_id)
    if not station or station["fleet_id"] != fleet_id:
        raise_error("ERR_NOT_FOUND", f"ChargingStation {station_id} not found")
    return station


def get_incident_or_404(fleet_id: str, incident_id: str) -> dict:
    incident = db.fault_incidents.get(incident_id)
    if not incident or incident["fleet_id"] != fleet_id:
        raise_error("ERR_NOT_FOUND", f"FaultIncident {incident_id} not found")
    return incident


def get_session_or_404(fleet_id: str, session_id: str) -> dict:
    session = db.charging_sessions.get(session_id)
    if not session or session["fleet_id"] != fleet_id:
        raise_error("ERR_NOT_FOUND", f"ChargingSession {session_id} not found")
    return session


def get_map_node_or_404(fleet_id: str, node_id: str) -> dict:
    node = db.map_nodes.get(node_id)
    if not node or node["fleet_id"] != fleet_id:
        raise_error("ERR_NOT_FOUND", f"MapNode {node_id} not found")
    return node
