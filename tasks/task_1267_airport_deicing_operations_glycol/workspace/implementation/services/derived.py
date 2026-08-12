"""Derived-state recomputation: tank reserved/available/status, station
posture, active_supply_alert, collected pool (PRD §2.7)."""
from decimal import Decimal

import db


REQUEST_RESERVED_STATUSES = {"QUEUED", "ASSIGNED", "IN_PROGRESS", "DEFERRED"}
REWORK_RESERVED_STATUSES = {"PLANNED", "SPRAYING", "AWAITING_INSPECTION"}


def recompute_tank(tank):
    """Recompute reserved_liters, available_liters, status for one tank."""
    reserved = Decimal("0")
    for req in db.deice_requests.values():
        if (
            req.get("assigned_tank_id") == tank["id"]
            and req["status"] in REQUEST_RESERVED_STATUSES
        ):
            reserved += Decimal(str(req["estimated_liters"]))
    for op in db.deice_operations.values():
        if (
            op.get("tank_id") == tank["id"]
            and op.get("parent_operation_id") is not None
            and op["status"] in REWORK_RESERVED_STATUSES
        ):
            reserved += Decimal(str(op["estimated_liters"]))
    tank["reserved_liters"] = float(reserved)
    available = Decimal(str(tank["on_hand_liters"])) - reserved
    tank["available_liters"] = float(available)
    if Decimal(str(tank["on_hand_liters"])) == 0:
        tank["status"] = "EMPTY"
    elif available < Decimal(str(tank["reorder_threshold_liters"])):
        tank["status"] = "REORDER_PENDING"
    else:
        tank["status"] = "OK"


def recompute_station(station):
    """Recompute posture, active_supply_alert, collected_pool_liters."""
    station_id = station["id"]
    # Posture: permits first, fluid second.
    permits = [p for p in db.discharge_permits.values() if p["station_id"] == station_id]
    if permits and not any(p["status"] == "ACTIVE" for p in permits):
        station["posture"] = "PERMIT_SUSPENDED"
    else:
        total_available = Decimal("0")
        for tank in db.fluid_tanks.values():
            if tank["station_id"] == station_id:
                total_available += Decimal(str(tank["available_liters"]))
        if total_available < Decimal(str(station["fluid_ops_minimum_liters"])):
            station["posture"] = "FLUID_CONSTRAINED"
        else:
            station["posture"] = "NORMAL"
    # Supply alert: any tank REORDER_PENDING or EMPTY.
    alert = False
    for tank in db.fluid_tanks.values():
        if tank["station_id"] == station_id and tank["status"] in (
            "REORDER_PENDING",
            "EMPTY",
        ):
            alert = True
            break
    station["active_supply_alert"] = alert
    # Collected pool: CLEARED/REWORK_REQUIRED collected minus shipments.
    pool = Decimal("0")
    for op in db.deice_operations.values():
        if op["station_id"] == station_id and op["status"] in (
            "CLEARED",
            "REWORK_REQUIRED",
        ):
            pool += Decimal(str(op.get("collected_liters") or 0))
    for contract in db.recycling_contracts.values():
        if contract["station_id"] == station_id:
            pool -= Decimal(str(contract.get("delivered_liters") or 0))
    station["collected_pool_liters"] = float(pool)


def recompute_tank_and_station(tank):
    recompute_tank(tank)
    station = db.stations.get(tank["station_id"])
    if station is not None:
        recompute_station(station)


def recompute_station_all(station_id):
    """Recompute every tank of a station, then the station itself."""
    station = db.stations.get(station_id)
    if station is None:
        return
    for tank in db.fluid_tanks.values():
        if tank["station_id"] == station_id:
            recompute_tank(tank)
    recompute_station(station)


def active_weather_event(station_id):
    """The single governing ACTIVE event at a station: latest started_at,
    tie-break earliest created_at. Returns None when none is ACTIVE."""
    candidates = [
        e
        for e in db.weather_events.values()
        if e["station_id"] == station_id and e["status"] == "ACTIVE"
    ]
    if not candidates:
        return None
    # Latest started_at wins; tie-break earliest created_at. Sort created_at
    # ascending first, then started_at descending (stable two-pass sort).
    candidates.sort(key=lambda e: e["_created_dt"])
    candidates.sort(key=lambda e: e["_started_dt"], reverse=True)
    return candidates[0]
