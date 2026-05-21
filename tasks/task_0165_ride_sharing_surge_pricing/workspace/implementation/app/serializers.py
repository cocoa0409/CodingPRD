"""Serializers — convert internal entity dicts to JSON-safe responses."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict

from .util import format_iso8601


def _ts(dt) -> str | None:
    if dt is None:
        return None
    return format_iso8601(dt)


def _num(d: Decimal | float | int | None):
    if d is None:
        return None
    if isinstance(d, Decimal):
        # serialize as float (2dp expected)
        return float(d)
    return d


def serialize_grid(g: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": g["id"],
        "code": g["code"],
        "name": g["name"],
        "is_airport": g["is_airport"],
        "rush_hour_eligible": g["rush_hour_eligible"],
        "active_driver_count": g["active_driver_count"],
        "open_demand_count": g["open_demand_count"],
        "current_multiplier": _num(g["current_multiplier"]),
        "last_surge_recomputed_at": _ts(g.get("last_surge_recomputed_at")),
        "created_at": _ts(g["created_at"]),
        "updated_at": _ts(g["updated_at"]),
        "version": g["version"],
    }


def serialize_driver(d: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": d["id"],
        "name": d["name"],
        "status": d["status"],
        "current_grid_code": d["current_grid_code"],
        "quest_id": d["quest_id"],
        "quest_completed_rides": d["quest_completed_rides"],
        "total_earnings_cents": d["total_earnings_cents"],
        "created_at": _ts(d["created_at"]),
        "updated_at": _ts(d["updated_at"]),
        "version": d["version"],
    }


def serialize_rider(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": r["id"],
        "name": r["name"],
        "wallet_balance_cents": r["wallet_balance_cents"],
        "created_at": _ts(r["created_at"]),
        "updated_at": _ts(r["updated_at"]),
        "version": r["version"],
    }


def serialize_rush_hour_window(w: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": w["id"],
        "label": w["label"],
        "day_of_week": w["day_of_week"],
        "start_minute": w["start_minute"],
        "end_minute": w["end_minute"],
        "additive_bonus": _num(w["additive_bonus"]),
        "is_active": w["is_active"],
        "created_at": _ts(w["created_at"]),
        "updated_at": _ts(w["updated_at"]),
        "version": w["version"],
    }


def serialize_quest_bonus(q: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": q["id"],
        "name": q["name"],
        "target_ride_count": q["target_ride_count"],
        "bonus_amount_cents": q["bonus_amount_cents"],
        "window_start": _ts(q["window_start"]),
        "window_end": _ts(q["window_end"]),
        "status": q["status"],
        "created_at": _ts(q["created_at"]),
        "updated_at": _ts(q["updated_at"]),
        "version": q["version"],
    }


def serialize_airport_queue(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "grid_code": row["grid_code"],
        "driver_id": row["driver_id"],
        "position": row["position"],
        "joined_at": _ts(row["joined_at"]),
        "created_at": _ts(row["created_at"]),
    }


def serialize_ride(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": r["id"],
        "rider_id": r["rider_id"],
        "driver_id": r["driver_id"],
        "pickup_grid_code": r["pickup_grid_code"],
        "dropoff_grid_code": r["dropoff_grid_code"],
        "distance_km": r["distance_km"],
        "status": r["status"],
        "base_fare_cents": r["base_fare_cents"],
        "pickup_multiplier_snapshot": _num(r["pickup_multiplier_snapshot"]),
        "rush_hour_bonus_snapshot": _num(r["rush_hour_bonus_snapshot"]),
        "quoted_fare_cents": r["quoted_fare_cents"],
        "final_fare_cents": r["final_fare_cents"],
        "driver_earnings_cents": r["driver_earnings_cents"],
        "requested_at": _ts(r["requested_at"]),
        "completed_at": _ts(r["completed_at"]),
        "created_at": _ts(r["created_at"]),
        "updated_at": _ts(r["updated_at"]),
        "version": r["version"],
    }


def serialize_dispute(d: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": d["id"],
        "ride_id": d["ride_id"],
        "rider_id": d["rider_id"],
        "reason_code": d["reason_code"],
        "requested_refund_cents": d["requested_refund_cents"],
        "approved_refund_cents": d["approved_refund_cents"],
        "status": d["status"],
        "resolved_at": _ts(d["resolved_at"]),
        "created_at": _ts(d["created_at"]),
        "updated_at": _ts(d["updated_at"]),
        "version": d["version"],
    }


def serialize_heatmap_snapshot(s: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": s["id"],
        "grid_code": s["grid_code"],
        "multiplier": _num(s["multiplier"]),
        "active_driver_count": s["active_driver_count"],
        "open_demand_count": s["open_demand_count"],
        "snapshot_at": _ts(s["snapshot_at"]),
        "created_at": _ts(s["created_at"]),
    }
