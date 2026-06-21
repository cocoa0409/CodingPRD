"""Trip endpoints: unlock, pause, resume, end (cascade), cancel, reads.

POST /api/trips                 — Rider (unlock)
GET  /api/trips/{id}            — PlatformAdmin, Rider
GET  /api/trips                 — PlatformAdmin, Rider
GET  /api/trips/{id}/segments   — PlatformAdmin, Rider
POST /api/trips/{id}/pause      — Rider
POST /api/trips/{id}/resume     — Rider
POST /api/trips/{id}/end        — Rider
POST /api/trips/{id}/cancel     — Rider

Validation ordering follows PRD §2.8 / scaffold §1.4 priorities.
"""
from flask import Blueprint, request

import constants
import errors
from clock import now, now_iso
from db import db, stamp_new, touch
from middleware import authenticate, require_role, require_rider_owner
from response import success
from services import pricing
from services import zone as zone_svc
from services.mds import parse_iso
from services.trip import open_segment, close_open_segment
from services.vehicle import set_status
from services.wallet import create_txn
from util import (
    get_json_body, require_fields, require_string,
    public, parse_pagination, paginate,
)

bp = Blueprint("trips", __name__)


@bp.post("/api/trips")
def create_trip():
    role, user_id = authenticate()
    require_role(role, {"Rider"})

    body = get_json_body()
    require_fields(body, ["rider_id", "vehicle_id"])
    require_string(body["rider_id"], "rider_id")
    require_string(body["vehicle_id"], "vehicle_id")

    # Body FK references (priority 5) before ownership-on-body and business rules.
    rider = db.riders.get(body["rider_id"])
    if rider is None:
        raise errors.reference_not_found("rider_id does not reference a rider")
    vehicle = db.vehicles.get(body["vehicle_id"])
    if vehicle is None:
        raise errors.reference_not_found("vehicle_id does not reference a vehicle")

    # A Rider may only unlock for themselves (PRD §2.1).
    require_rider_owner(role, user_id, rider["id"])

    # Business-safety gates in priority order (PRD §2.8): NO_RIDE (7) before
    # battery (9) before vehicle-availability (10).
    if zone_svc.is_no_ride(vehicle["current_zone_id"]):
        raise errors.ApiError(
            errors.ERR_START_IN_NO_RIDE_ZONE, 422,
            "Cannot start a trip on a vehicle in a NO_RIDE zone",
        )
    if vehicle["battery_pct"] < constants.MIN_START_BATTERY_PCT:
        raise errors.ApiError(
            errors.ERR_BATTERY_TOO_LOW, 422,
            "Vehicle battery is below the minimum to start a trip",
        )
    if vehicle["status"] != "AVAILABLE":
        raise errors.ApiError(
            errors.ERR_VEHICLE_NOT_AVAILABLE, 409,
            "Vehicle is not available to unlock",
        )

    plan = db.plans[rider["plan_id"]]

    trip = {
        "rider_id": rider["id"],
        "vehicle_id": vehicle["id"],
        "start_zone_id": vehicle["current_zone_id"],
        "end_zone_id": None,
        "status": "ACTIVE",
        "started_at": now_iso(),
        "ended_at": None,
        "estimated_fare_cents": pricing.trip_provisional_fare(plan),
        "final_fare_cents": 0,
        "billable_minutes": 0,
    }
    stamp_new(trip)
    db.trips[trip["id"]] = trip

    # Vehicle AVAILABLE -> RESERVED -> IN_USE within the same call; trip created
    # directly ACTIVE (PRD §3.3). Open the first RIDE segment at the start zone.
    set_status(vehicle, "IN_USE")
    touch(vehicle)
    open_segment(trip, "RIDE", trip["start_zone_id"])

    return success(public(trip), status=201)


@bp.get("/api/trips/<trip_id>")
def get_trip(trip_id):
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin", "Rider"})
    trip = _require_trip(trip_id)
    require_rider_owner(role, user_id, trip["rider_id"])
    return success(public(trip))


@bp.get("/api/trips")
def list_trips():
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin", "Rider"})
    limit, offset = parse_pagination()

    rows = list(db.trips.values())
    # A Rider sees only their own trips; an explicit rider_id filter is honored
    # but for a Rider it is also constrained to their own id.
    if role == "Rider":
        rows = [r for r in rows if r["rider_id"] == user_id]

    rider_id = request.args.get("rider_id")
    if rider_id is not None:
        rows = [r for r in rows if r["rider_id"] == rider_id]
    vehicle_id = request.args.get("vehicle_id")
    if vehicle_id is not None:
        rows = [r for r in rows if r["vehicle_id"] == vehicle_id]
    start_zone_id = request.args.get("start_zone_id")
    if start_zone_id is not None:
        rows = [r for r in rows if r["start_zone_id"] == start_zone_id]
    end_zone_id = request.args.get("end_zone_id")
    if end_zone_id is not None:
        rows = [r for r in rows if r["end_zone_id"] == end_zone_id]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]

    page, pagination = paginate(rows, limit, offset)
    return success(page, is_array=True, pagination=pagination)


@bp.get("/api/trips/<trip_id>/segments")
def list_trip_segments(trip_id):
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin", "Rider"})
    trip = _require_trip(trip_id)
    require_rider_owner(role, user_id, trip["rider_id"])
    limit, offset = parse_pagination()

    rows = [s for s in db.trip_segments.values() if s["trip_id"] == trip["id"]]
    page, pagination = paginate(rows, limit, offset)
    return success(page, is_array=True, pagination=pagination)


@bp.post("/api/trips/<trip_id>/pause")
def pause_trip(trip_id):
    role, user_id = authenticate()
    require_role(role, {"Rider"})
    trip = _require_trip(trip_id)
    require_rider_owner(role, user_id, trip["rider_id"])
    if trip["status"] != "ACTIVE":
        raise errors.invalid_state("Trip is not ACTIVE")

    # Close the open RIDE segment; open a fresh PAUSE segment (PRD §3.4).
    close_open_segment(trip)
    vehicle = db.vehicles[trip["vehicle_id"]]
    open_segment(trip, "PAUSE", vehicle["current_zone_id"])
    trip["status"] = "PAUSED"
    touch(trip)
    return success(public(trip))


@bp.post("/api/trips/<trip_id>/resume")
def resume_trip(trip_id):
    role, user_id = authenticate()
    require_role(role, {"Rider"})
    trip = _require_trip(trip_id)
    require_rider_owner(role, user_id, trip["rider_id"])
    if trip["status"] != "PAUSED":
        raise errors.invalid_state("Trip is not PAUSED")

    # Close the open PAUSE segment; open a new RIDE segment at the vehicle's
    # current zone (PRD §3.4).
    close_open_segment(trip)
    vehicle = db.vehicles[trip["vehicle_id"]]
    open_segment(trip, "RIDE", vehicle["current_zone_id"])
    trip["status"] = "ACTIVE"
    touch(trip)
    return success(public(trip))


@bp.post("/api/trips/<trip_id>/end")
def end_trip(trip_id):
    role, user_id = authenticate()
    require_role(role, {"Rider"})
    trip = _require_trip(trip_id)
    require_rider_owner(role, user_id, trip["rider_id"])

    body = get_json_body()
    require_fields(body, ["end_zone_id"])
    require_string(body["end_zone_id"], "end_zone_id")
    end_zone = db.zones.get(body["end_zone_id"])
    if end_zone is None:
        # end_zone_id is supplied at end; a dangling reference is not-found.
        raise errors.reference_not_found("end_zone_id does not reference a zone")

    rider = db.riders[trip["rider_id"]]

    # State legality (priority 6): trip must be ACTIVE or PAUSED, and the rider
    # must be ACTIVE (cross-entity Trip<-Rider) — both -> ERR_INVALID_STATE.
    if trip["status"] not in ("ACTIVE", "PAUSED"):
        raise errors.invalid_state("Trip is not ACTIVE or PAUSED")
    if rider["status"] != "ACTIVE":
        raise errors.invalid_state("Rider is not ACTIVE")

    # Business-safety (priority 8): may not end in a NO_RIDE zone.
    if zone_svc.is_no_ride(end_zone["id"]):
        raise errors.ApiError(
            errors.ERR_END_IN_NO_RIDE_ZONE, 422,
            "Cannot end a trip in a NO_RIDE zone",
        )

    plan = db.plans[rider["plan_id"]]
    vehicle = db.vehicles[trip["vehicle_id"]]

    # Close the open segment (RIDE if ending from ACTIVE, PAUSE if from PAUSED).
    close_open_segment(trip)

    trip["ended_at"] = now_iso()
    trip["end_zone_id"] = end_zone["id"]
    trip["status"] = "COMPLETED"

    # billable_minutes then final_fare_cents (PRD §3.4, §3.5).
    trip["billable_minutes"] = pricing.trip_billable_minutes(trip)
    final_fare = pricing.trip_final_fare(trip, plan)
    trip["final_fare_cents"] = final_fare
    touch(trip)

    # CASCADE link1: TRIP_CHARGE wallet debit.
    create_txn(rider["id"], "TRIP_CHARGE", -final_fare, trip_id=trip["id"])
    rider["wallet_balance_cents"] -= final_fare
    touch(rider)

    # CASCADE link2/link3: NO_PARK -> raise Fine + FINE_CHARGE debit.
    if zone_svc.is_no_park(end_zone["id"]):
        amount = pricing.fine_amount(plan)
        fine = {
            "rider_id": rider["id"],
            "trip_id": trip["id"],
            "reason": "BAD_PARKING_NO_PARK",
            "amount_cents": amount,
            "settlement_status": "PENDING",
        }
        stamp_new(fine)
        db.fines[fine["id"]] = fine

        create_txn(rider["id"], "FINE_CHARGE", -amount, trip_id=trip["id"], fine_id=fine["id"])
        rider["wallet_balance_cents"] -= amount
        rider["outstanding_fine_cents"] += amount
        touch(rider)

    # Vehicle leaves use: relocate to end zone, then AVAILABLE or LOW_BATTERY.
    vehicle["current_zone_id"] = end_zone["id"]
    if vehicle["battery_pct"] >= constants.MIN_START_BATTERY_PCT:
        set_status(vehicle, "AVAILABLE")
    else:
        set_status(vehicle, "LOW_BATTERY")
        # Auto-create a SWAP RebalancingTask; this does NOT bump vehicle version.
        _auto_swap_task(vehicle)
    touch(vehicle)

    return success(public(trip))


@bp.post("/api/trips/<trip_id>/cancel")
def cancel_trip(trip_id):
    role, user_id = authenticate()
    require_role(role, {"Rider"})
    trip = _require_trip(trip_id)
    require_rider_owner(role, user_id, trip["rider_id"])

    # Cancel only while ACTIVE and within GRACE_SECONDS of start (PRD §3.5).
    if trip["status"] != "ACTIVE":
        raise errors.invalid_state("Trip is not ACTIVE")
    started = parse_iso(trip["started_at"])
    elapsed = (now() - started).total_seconds()
    if elapsed > constants.GRACE_SECONDS:
        raise errors.invalid_state("Cancellation grace window has elapsed")

    # Close all open segments; zero the fare; return vehicle without zone change.
    close_open_segment(trip)
    trip["final_fare_cents"] = 0
    trip["billable_minutes"] = 0
    trip["status"] = "CANCELLED"
    trip["ended_at"] = now_iso()
    touch(trip)

    vehicle = db.vehicles[trip["vehicle_id"]]
    set_status(vehicle, "AVAILABLE")
    touch(vehicle)

    return success(public(trip))


def _auto_swap_task(vehicle):
    """Auto-create the OPEN SWAP task for a depleted vehicle (PRD §3.5).

    Does NOT bump the vehicle's version (PRD §2.4 exception).
    """
    start = now()
    end = start.replace(microsecond=start.microsecond)  # keep precision
    from datetime import timedelta
    end = start + timedelta(seconds=constants.AUTO_SWAP_WINDOW_SECONDS)
    task = {
        "vehicle_id": vehicle["id"],
        "technician_id": None,
        "task_type": "SWAP",
        "target_zone_id": None,
        "window_start": now_iso(),
        "window_end": end.strftime("%Y-%m-%dT%H:%M:%S.") + f"{end.microsecond // 1000:03d}Z",
        "status": "OPEN",
    }
    stamp_new(task)
    db.rebalancing_tasks[task["id"]] = task
    return task


def _require_trip(trip_id):
    trip = db.trips.get(trip_id)
    if trip is None:
        raise errors.not_found("Trip not found")
    return trip
