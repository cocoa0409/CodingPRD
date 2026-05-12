"""Charging station endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from db import db, new_id
from errors import raise_error
from middleware import require_roles
from response import success
from services.lookup import get_fleet_or_404, get_station_or_404, get_map_node_or_404
from services.serialize import charging_station_to_dict
from services.transitions import queue_length_for

charging_stations_bp = Blueprint("charging_stations", __name__)


@charging_stations_bp.route("/fleets/<fleet_id>/charging_stations", methods=["POST"])
def create_station(fleet_id):
    require_roles(["FleetAdmin"])
    fleet = get_fleet_or_404(fleet_id)
    body = request.get_json(silent=True) or {}
    node_id = body.get("node_id")
    rate = body.get("charge_rate_pct_per_second", 1)
    if not isinstance(node_id, str) or not node_id:
        raise_error("ERR_BAD_REQUEST", "node_id required")
    node = get_map_node_or_404(fleet_id, node_id)
    if node["kind"] != "CHARGER":
        raise_error("ERR_BAD_REQUEST", "node_id must reference a CHARGER node")
    if not isinstance(rate, int) or isinstance(rate, bool) or rate < 1:
        raise_error("ERR_BAD_REQUEST", "charge_rate_pct_per_second must be a positive integer")
    sid = new_id()
    now = fleet["clock_now"]
    station = {
        "id": sid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "fleet_id": fleet_id,
        "node_id": node_id,
        "status": "AVAILABLE",
        "occupying_robot_id": None,
        "charge_rate_pct_per_second": rate,
    }
    db.charging_stations[sid] = station
    return success(charging_station_to_dict(station, queue_length_for(sid)), status=201)


@charging_stations_bp.route("/fleets/<fleet_id>/charging_stations/<station_id>", methods=["GET"])
def get_station(fleet_id, station_id):
    require_roles(["Operator", "FleetAdmin", "WMS"])
    get_fleet_or_404(fleet_id)
    station = get_station_or_404(fleet_id, station_id)
    return success(charging_station_to_dict(station, queue_length_for(station_id)))
