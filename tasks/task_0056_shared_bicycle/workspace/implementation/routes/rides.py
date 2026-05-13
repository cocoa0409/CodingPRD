"""Ride endpoints (PRD §3.4, §3.5, §3.10)."""
from __future__ import annotations

from flask import Blueprint, g

from constants import (
    DISPUTE_WINDOW_MINUTES,
    MIN_UNLOCK_BALANCE_CENTS,
)
from db import (
    LOCK,
    bikes,
    new_id,
    regions,
    rides,
    riders,
    work_orders,
)
from errors import (
    ERR_ADJUSTMENT_EXCEEDS_FARE,
    ERR_BIKE_IN_FORBIDDEN_ZONE,
    ERR_BIKE_NOT_AVAILABLE,
    ERR_BIKE_OFF_SHELF,
    ERR_DISPUTE_WINDOW_CLOSED,
    ERR_END_IN_FORBIDDEN_ZONE,
    ERR_FORBIDDEN_ROLE,
    ERR_INSUFFICIENT_BALANCE,
    ERR_INSUFFICIENT_BALANCE_AT_SETTLEMENT,
    ERR_NOT_FOUND,
    ERR_REFERENCE_NOT_FOUND,
    ERR_RIDER_HAS_ACTIVE_RIDE,
    ERR_RIDER_SUSPENDED,
    ERR_RIDE_NOT_ACTIVE,
    ERR_RIDE_NOT_DISPUTED,
    ERR_RIDE_NOT_SETTLED,
    ERR_VALIDATION,
    raise_err,
)
from middleware import require_role, require_rider_owner
from response import success_object
from services.audit import write_audit
from services.geofence_lookup import is_in_forbidden
from services.regions import recompute_region_counts
from services.settlement import settle_ride
from services.validators import (
    bump_version,
    ensure_enum,
    ensure_non_negative_int,
    ensure_number,
    get_json_body,
)
from time_utils import now_iso


bp = Blueprint("rides", __name__)


FAULT_CATEGORIES = {"FLAT_TIRE", "BRAKE", "LOCK_FAILURE", "BATTERY_SWAP", "CHARGING", "OTHER"}


def serialize_ride(r: dict) -> dict:
    return dict(r)


@bp.post("/rides")
def create_ride():
    require_role("Rider")
    body = get_json_body()
    rider_id = body.get("rider_id")
    bike_id = body.get("bike_id")
    if not isinstance(rider_id, str) or not rider_id:
        raise_err(ERR_VALIDATION, "rider_id is required")
    if not isinstance(bike_id, str) or not bike_id:
        raise_err(ERR_VALIDATION, "bike_id is required")
    # Ownership check first — a rider can only act on their own.
    require_rider_owner(rider_id)

    with LOCK:
        rider = riders.get(rider_id)
        if rider is None:
            raise_err(ERR_REFERENCE_NOT_FOUND, "rider_id not found")
        bike = bikes.get(bike_id)
        if bike is None:
            raise_err(ERR_REFERENCE_NOT_FOUND, "bike_id not found")

        # State validations (scaffold-order)
        if bike["shelf_state"] != "ON_SHELF":
            raise_err(ERR_BIKE_OFF_SHELF, "Bike is not ON_SHELF")
        if bike["status"] != "AVAILABLE":
            raise_err(ERR_BIKE_NOT_AVAILABLE, "Bike is not AVAILABLE")
        # Forbidden-zone check at unlock.
        region_id = bike["region_id"]
        bike_lat = bike.get("last_lat")
        bike_lng = bike.get("last_lng")
        if bike_lat is not None and bike_lng is not None and region_id:
            if is_in_forbidden(region_id, float(bike_lat), float(bike_lng)):
                raise_err(ERR_BIKE_IN_FORBIDDEN_ZONE, "Bike is in a forbidden zone")
        # Rider suspension
        if rider.get("status") != "ACTIVE":
            raise_err(ERR_RIDER_SUSPENDED, "Rider is not ACTIVE")
        # No other active ride for this rider.
        for r in rides.values():
            if r.get("rider_id") == rider_id and r.get("status") == "ACTIVE":
                raise_err(ERR_RIDER_HAS_ACTIVE_RIDE, "Rider already has an active ride")
        # Payment capacity.
        region = regions.get(region_id)
        clock_now = int(region.get("clock_minutes", 0)) if region else 0
        pass_active = rider.get("monthly_pass_expires_minute", 0) > clock_now
        if not pass_active and rider.get("wallet_balance_cents", 0) < MIN_UNLOCK_BALANCE_CENTS:
            raise_err(ERR_INSUFFICIENT_BALANCE, "Wallet balance below minimum unlock")

        # Commit: create the ride and flip bike.
        ride_id = new_id()
        ts = now_iso()
        ride = {
            "id": ride_id,
            "rider_id": rider_id,
            "bike_id": bike_id,
            "region_id": region_id,
            "status": "ACTIVE",
            "start_minute": clock_now,
            "end_minute": None,
            "end_lat": None,
            "end_lng": None,
            "end_fence_kind": None,
            "applied_free_minutes": 0,
            "pass_covered_minutes": 0,
            "chargeable_minutes": 0,
            "base_fare_cents": 0,
            "penalty_cents": 0,
            "reward_cents": 0,
            "final_fare_cents": 0,
            "settlement_variant": None,
            "payment_event_id": None,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        rides[ride_id] = ride
        bike["status"] = "IN_USE"
        bike["lock_state"] = "UNLOCKED"
        bike["current_ride_id"] = ride_id
        bump_version(bike)
        recompute_region_counts(region_id)
        write_audit(
            event_kind="OPS_ACTION",
            action="RIDE_UNLOCK",
            subject_type="Ride",
            subject_id=ride_id,
            before={},
            after={"rider_id": rider_id, "bike_id": bike_id, "region_id": region_id},
            region_id=region_id,
        )
    return success_object(serialize_ride(ride), status=201)


@bp.get("/rides/<ride_id>")
def get_ride(ride_id):
    require_role("Rider", "Admin")
    ride = rides.get(ride_id)
    if ride is None:
        raise_err(ERR_NOT_FOUND, "Ride not found")
    require_rider_owner(ride["rider_id"])
    return success_object(serialize_ride(ride))


@bp.post("/rides/<ride_id>/end")
def end_ride(ride_id):
    require_role("Rider")
    ride = rides.get(ride_id)
    if ride is None:
        raise_err(ERR_NOT_FOUND, "Ride not found")
    require_rider_owner(ride["rider_id"])
    body = get_json_body()
    if "end_lat" not in body or "end_lng" not in body:
        raise_err(ERR_VALIDATION, "end_lat and end_lng are required")
    end_lat = ensure_number(body["end_lat"], "end_lat")
    end_lng = ensure_number(body["end_lng"], "end_lng")

    with LOCK:
        # Re-fetch to avoid TOCTOU.
        ride = rides[ride_id]
        if ride["status"] != "ACTIVE":
            raise_err(ERR_RIDE_NOT_ACTIVE, "Ride is not ACTIVE")
        bike = bikes[ride["bike_id"]]
        region_id = ride["region_id"]
        if is_in_forbidden(region_id, end_lat, end_lng):
            raise_err(ERR_END_IN_FORBIDDEN_ZONE, "End location is in a FORBIDDEN zone")
        rider = riders[ride["rider_id"]]
        region = regions.get(region_id)
        end_minute = int(region.get("clock_minutes", 0)) if region else 0

        # Compute settlement on a snapshot copy first.
        preview_ride = dict(ride)
        settle_ride(
            ride=preview_ride,
            rider=rider,
            bike=bike,
            end_minute=end_minute,
            end_lat=end_lat,
            end_lng=end_lng,
            fault_waiver=False,
        )
        # Wallet balance check: wallet - final_fare must be >= 0 (before adding reward).
        if rider["wallet_balance_cents"] - preview_ride["final_fare_cents"] < 0:
            raise_err(
                ERR_INSUFFICIENT_BALANCE_AT_SETTLEMENT,
                "Wallet would go negative after settlement",
            )

        # Commit settlement onto the real ride.
        ride.update({k: preview_ride[k] for k in (
            "start_minute", "end_minute", "end_lat", "end_lng",
            "end_fence_kind", "applied_free_minutes", "pass_covered_minutes",
            "chargeable_minutes", "base_fare_cents", "penalty_cents",
            "reward_cents", "final_fare_cents", "settlement_variant",
        )})
        ride["payment_event_id"] = new_id()
        ride["status"] = "SETTLED"
        bump_version(ride)

        rider["free_minutes_remaining"] -= ride["applied_free_minutes"]
        rider["wallet_balance_cents"] -= ride["final_fare_cents"]
        rider["wallet_balance_cents"] += ride["reward_cents"]
        bump_version(rider)

        bike["status"] = "AVAILABLE"
        bike["lock_state"] = "LOCKED"
        bike["current_ride_id"] = None
        bike["last_motion_minute"] = end_minute
        bike["last_lat"] = end_lat
        bike["last_lng"] = end_lng
        bump_version(bike)

        recompute_region_counts(region_id)

        write_audit(
            event_kind="EXTERNAL_SYNC",
            action="PAYMENT_SYNC",
            subject_type="Ride",
            subject_id=ride_id,
            before={},
            after={
                "payment_event_id": ride["payment_event_id"],
                "final_fare_cents": ride["final_fare_cents"],
                "reward_cents": ride["reward_cents"],
            },
            region_id=region_id,
        )
    return success_object(serialize_ride(ride))


@bp.post("/rides/<ride_id>/fault-report")
def ride_fault_report(ride_id):
    require_role("Rider")
    ride = rides.get(ride_id)
    if ride is None:
        raise_err(ERR_NOT_FOUND, "Ride not found")
    require_rider_owner(ride["rider_id"])
    body = get_json_body()
    if "end_lat" not in body or "end_lng" not in body or "category" not in body:
        raise_err(ERR_VALIDATION, "end_lat, end_lng, and category are required")
    end_lat = ensure_number(body["end_lat"], "end_lat")
    end_lng = ensure_number(body["end_lng"], "end_lng")
    category = ensure_enum(body["category"], "category", FAULT_CATEGORIES)

    with LOCK:
        ride = rides[ride_id]
        if ride["status"] != "ACTIVE":
            raise_err(ERR_RIDE_NOT_ACTIVE, "Ride is not ACTIVE")
        bike = bikes[ride["bike_id"]]
        rider = riders[ride["rider_id"]]
        region_id = ride["region_id"]
        region = regions.get(region_id)
        end_minute = int(region.get("clock_minutes", 0)) if region else 0

        preview_ride = dict(ride)
        settle_ride(
            ride=preview_ride,
            rider=rider,
            bike=bike,
            end_minute=end_minute,
            end_lat=end_lat,
            end_lng=end_lng,
            fault_waiver=True,
        )
        if rider["wallet_balance_cents"] - preview_ride["final_fare_cents"] < 0:
            raise_err(
                ERR_INSUFFICIENT_BALANCE_AT_SETTLEMENT,
                "Wallet would go negative after settlement",
            )

        ride.update({k: preview_ride[k] for k in (
            "start_minute", "end_minute", "end_lat", "end_lng",
            "end_fence_kind", "applied_free_minutes", "pass_covered_minutes",
            "chargeable_minutes", "base_fare_cents", "penalty_cents",
            "reward_cents", "final_fare_cents", "settlement_variant",
        )})
        ride["payment_event_id"] = new_id()
        ride["status"] = "SETTLED"
        bump_version(ride)

        rider["free_minutes_remaining"] -= ride["applied_free_minutes"]
        rider["wallet_balance_cents"] -= ride["final_fare_cents"]
        rider["wallet_balance_cents"] += ride["reward_cents"]
        bump_version(rider)

        bike["status"] = "FAULT"
        bike["lock_state"] = "LOCKED"
        bike["current_ride_id"] = None
        bike["last_motion_minute"] = end_minute
        bike["last_lat"] = end_lat
        bike["last_lng"] = end_lng
        if category not in bike["fault_categories"]:
            bike["fault_categories"].append(category)
        bump_version(bike)

        wo_id = new_id()
        ts = now_iso()
        wo = {
            "id": wo_id,
            "bike_id": bike["id"],
            "region_id": region_id,
            "cause": "USER_REPORT",
            "category": category,
            "status": "OPEN",
            "assigned_operator_id": None,
            "sla_minutes": 1440,
            "opened_minute": end_minute,
            "resolved_minute": None,
            "resolution_note": None,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        work_orders[wo_id] = wo

        # Bike was IN_USE → FAULT; available_count not affected.
        recompute_region_counts(region_id)

        write_audit(
            event_kind="EXTERNAL_SYNC",
            action="PAYMENT_SYNC",
            subject_type="Ride",
            subject_id=ride_id,
            before={},
            after={
                "payment_event_id": ride["payment_event_id"],
                "final_fare_cents": ride["final_fare_cents"],
                "reward_cents": ride["reward_cents"],
            },
            region_id=region_id,
        )
    return success_object(serialize_ride(ride))


@bp.post("/rides/<ride_id>/dispute")
def dispute_ride(ride_id):
    require_role("Rider")
    ride = rides.get(ride_id)
    if ride is None:
        raise_err(ERR_NOT_FOUND, "Ride not found")
    require_rider_owner(ride["rider_id"])
    body = get_json_body()
    reason = body.get("reason")
    if not isinstance(reason, str) or not reason:
        raise_err(ERR_VALIDATION, "reason is required")

    with LOCK:
        ride = rides[ride_id]
        if ride["status"] != "SETTLED":
            raise_err(ERR_RIDE_NOT_SETTLED, "Ride is not SETTLED")
        region = regions.get(ride["region_id"])
        clock_now = int(region.get("clock_minutes", 0)) if region else 0
        if clock_now - int(ride["end_minute"]) > DISPUTE_WINDOW_MINUTES:
            raise_err(ERR_DISPUTE_WINDOW_CLOSED, "Dispute window has closed")
        before = {"status": "SETTLED"}
        ride["status"] = "DISPUTED"
        bump_version(ride)
        write_audit(
            event_kind="BILLING_ADJUSTMENT",
            action="RIDE_DISPUTE_OPEN",
            subject_type="Ride",
            subject_id=ride_id,
            before=before,
            after={"status": "DISPUTED", "reason": reason},
            region_id=ride["region_id"],
        )
    return success_object(serialize_ride(ride))


@bp.post("/rides/<ride_id>/adjust")
def adjust_ride(ride_id):
    require_role("Admin")
    ride = rides.get(ride_id)
    if ride is None:
        raise_err(ERR_NOT_FOUND, "Ride not found")
    body = get_json_body()
    if "new_final_fare_cents" not in body:
        raise_err(ERR_VALIDATION, "new_final_fare_cents is required")
    new_fare = body["new_final_fare_cents"]
    if not isinstance(new_fare, int) or isinstance(new_fare, bool) or new_fare < 0:
        raise_err(ERR_VALIDATION, "new_final_fare_cents must be a non-negative integer")

    with LOCK:
        ride = rides[ride_id]
        if ride["status"] != "DISPUTED":
            raise_err(ERR_RIDE_NOT_DISPUTED, "Ride is not DISPUTED")
        old_fare = int(ride["final_fare_cents"])
        if new_fare > old_fare:
            raise_err(ERR_ADJUSTMENT_EXCEEDS_FARE, "new_final_fare_cents exceeds original")
        diff = old_fare - new_fare
        rider = riders[ride["rider_id"]]
        rider["wallet_balance_cents"] += diff
        bump_version(rider)
        ride["final_fare_cents"] = new_fare
        ride["status"] = "SETTLED"
        bump_version(ride)
        write_audit(
            event_kind="BILLING_ADJUSTMENT",
            action="RIDE_FARE_ADJUST",
            subject_type="Ride",
            subject_id=ride_id,
            before={"final_fare_cents": old_fare},
            after={"final_fare_cents": new_fare},
            region_id=ride["region_id"],
        )
        write_audit(
            event_kind="EXTERNAL_SYNC",
            action="PAYMENT_SYNC",
            subject_type="Ride",
            subject_id=ride_id,
            before={},
            after={"refund_cents": diff, "new_final_fare_cents": new_fare},
            region_id=ride["region_id"],
        )
    return success_object(serialize_ride(ride))


@bp.post("/rides/<ride_id>/void")
def void_ride(ride_id):
    require_role("Admin")
    ride = rides.get(ride_id)
    if ride is None:
        raise_err(ERR_NOT_FOUND, "Ride not found")
    with LOCK:
        ride = rides[ride_id]
        if ride["status"] != "ACTIVE":
            raise_err(ERR_RIDE_NOT_ACTIVE, "Ride is not ACTIVE")
        ride["status"] = "VOIDED"
        ride["final_fare_cents"] = 0
        bump_version(ride)
        bike = bikes[ride["bike_id"]]
        bike["status"] = "AVAILABLE"
        bike["lock_state"] = "LOCKED"
        bike["current_ride_id"] = None
        bump_version(bike)
        recompute_region_counts(ride["region_id"])
    return success_object(serialize_ride(ride))
