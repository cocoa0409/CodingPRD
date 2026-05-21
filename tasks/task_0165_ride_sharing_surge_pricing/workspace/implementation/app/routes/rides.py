"""Ride endpoints."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..auth import current_user, require_roles
from ..envelope import paginate, parse_pagination, success_array, success_object
from ..errors import (
    err_invalid_input,
    err_invalid_state,
    err_no_drivers_available,
    err_not_owner,
    err_reference_not_found,
)
from ..serializers import serialize_ride
from ..services.fares import final_fare_for, quoted_fare_for
from ..services.queue import driver_in_any_queue, remove_from_queue
from ..services.selection import select_driver
from ..services.surge import recompute_surge
from ..store import store
from ..util import new_uuid
from ._helpers import (
    filter_by_status,
    get_driver_or_404,
    get_grid_by_code,
    get_json,
    get_rider_or_404,
    get_ride_or_404,
    require_number,
    require_string,
)

bp = Blueprint("rides", __name__)


@bp.route("/rides", methods=["POST"])
@require_roles(["Rider"])
def create_ride():
    body = get_json()
    user_id, _role = current_user()

    pickup_code = require_string(body, "pickup_grid_code")
    dropoff_code = require_string(body, "dropoff_grid_code")
    distance_km = require_number(body, "distance_km", min_value=0.0, strict_min=True)

    s = store()
    # Body FK existence: pickup/dropoff grids. (Rider identity comes from X-User-ID per §2.1.)
    pickup_grid = get_grid_by_code(pickup_code)
    if pickup_grid is None:
        raise err_reference_not_found("pickup_grid_code does not reference an existing grid")
    dropoff_grid = get_grid_by_code(dropoff_code)
    if dropoff_grid is None:
        raise err_reference_not_found("dropoff_grid_code does not reference an existing grid")

    now = s.now()
    rid = new_uuid()
    ride = {
        "id": rid,
        "rider_id": user_id,
        "driver_id": None,
        "pickup_grid_code": pickup_code,
        "dropoff_grid_code": dropoff_code,
        "distance_km": distance_km,
        "status": "REQUESTED",
        "base_fare_cents": 0,
        "pickup_multiplier_snapshot": None,
        "rush_hour_bonus_snapshot": None,
        "quoted_fare_cents": 0,
        "final_fare_cents": None,
        "driver_earnings_cents": None,
        "requested_at": now,
        "completed_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }

    # Compute quoted fare BEFORE incrementing demand (uses pre-this-ride multiplier).
    quoted_fare_for(ride, pickup_grid)

    s.insert("rides", ride)
    # Open-demand bump + surge recompute on pickup grid
    pickup_grid["open_demand_count"] += 1
    recompute_surge(pickup_grid, bump_version=True)

    return jsonify(success_object(serialize_ride(ride))), 201


@bp.route("/rides/<ride_id>", methods=["GET"])
@require_roles(["Rider", "Driver", "PlatformAdmin", "DisputeOps"])
def get_ride(ride_id):
    r = get_ride_or_404(ride_id)
    user_id, role = current_user()
    if role == "Rider" and r["rider_id"] != user_id:
        raise err_not_owner()
    return jsonify(success_object(serialize_ride(r))), 200


@bp.route("/rides", methods=["GET"])
@require_roles(["PlatformAdmin", "DisputeOps"])
def list_rides():
    limit, offset = parse_pagination()
    status = request.args.get("status")
    rider_id = request.args.get("rider_id")
    driver_id = request.args.get("driver_id")
    items = sorted(store().list_collection("rides"), key=lambda x: x["created_at"])
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if rider_id is not None:
        items = [r for r in items if r["rider_id"] == rider_id]
    if driver_id is not None:
        items = [r for r in items if r["driver_id"] == driver_id]
    total = len(items)
    page = paginate(items, limit, offset)
    return jsonify(success_array(
        [serialize_ride(r) for r in page], limit=limit, offset=offset, total_count=total
    )), 200


@bp.route("/rides/<ride_id>/assign", methods=["POST"])
@require_roles(["PlatformAdmin"])
def assign_ride(ride_id):
    ride = get_ride_or_404(ride_id)
    body = get_json()
    allow_neighbor = body.get("allow_neighbor_grid", False)
    if not isinstance(allow_neighbor, bool):
        raise err_invalid_input("allow_neighbor_grid must be boolean if provided")

    if ride["status"] != "REQUESTED":
        raise err_invalid_state()

    s = store()
    pickup_grid = get_grid_by_code(ride["pickup_grid_code"])
    if pickup_grid is None:
        raise err_reference_not_found("Pickup grid no longer exists")

    selected, from_airport_queue = select_driver(pickup_grid, allow_neighbor)
    if selected is None:
        raise err_no_drivers_available()

    now = s.now()

    # Determine prior status to handle the supply count correctly.
    prior_status = selected["status"]
    selected_prior_grid_code = selected.get("current_grid_code")

    ride["driver_id"] = selected["id"]
    ride["status"] = "ASSIGNED"
    selected["status"] = "EN_ROUTE_PICKUP"
    selected["current_grid_code"] = ride["pickup_grid_code"]

    # Pickup-grid counts: open demand -= 1 (always), active_driver_count -= 1 ONLY if the driver
    # was an AVAILABLE driver in the pickup grid (airport-queue drivers aren't counted as supply).
    pickup_grid["open_demand_count"] -= 1
    if prior_status == "AVAILABLE" and selected_prior_grid_code == pickup_grid["code"]:
        pickup_grid["active_driver_count"] -= 1
    elif prior_status == "AVAILABLE" and selected_prior_grid_code != pickup_grid["code"]:
        # Neighbor-grid pickup: that other grid loses an available driver.
        other_grid = get_grid_by_code(selected_prior_grid_code) if selected_prior_grid_code else None
        if other_grid is not None:
            other_grid["active_driver_count"] -= 1
            recompute_surge(other_grid, bump_version=True)
    # If prior_status == IN_AIRPORT_QUEUE, queued drivers weren't in supply, no change.

    # Remove driver from airport queue (if any).
    if from_airport_queue:
        row = driver_in_any_queue(selected["id"])
        if row is not None:
            remove_from_queue(row["id"])

    selected["updated_at"] = now
    selected["version"] += 1
    ride["updated_at"] = now
    ride["version"] += 1

    recompute_surge(pickup_grid, bump_version=True)
    return jsonify(success_object(serialize_ride(ride))), 200


@bp.route("/rides/<ride_id>/start", methods=["POST"])
@require_roles(["Driver"])
def start_ride(ride_id):
    ride = get_ride_or_404(ride_id)
    user_id, _role = current_user()
    # Ownership check: driver must equal Ride.driver_id.
    if ride["driver_id"] != user_id:
        raise err_not_owner()
    if ride["status"] != "ASSIGNED":
        raise err_invalid_state()

    s = store()
    driver = s.drivers.get(user_id)
    if driver is None:
        raise err_not_owner()

    ride["status"] = "ON_TRIP"
    driver["status"] = "ON_TRIP"
    now = s.now()
    ride["updated_at"] = now
    ride["version"] += 1
    driver["updated_at"] = now
    driver["version"] += 1
    return jsonify(success_object(serialize_ride(ride))), 200


@bp.route("/rides/<ride_id>/complete", methods=["POST"])
@require_roles(["Driver"])
def complete_ride(ride_id):
    ride = get_ride_or_404(ride_id)
    user_id, _role = current_user()
    if ride["driver_id"] != user_id:
        raise err_not_owner()
    if ride["status"] != "ON_TRIP":
        raise err_invalid_state()

    s = store()
    driver = s.drivers.get(user_id)
    if driver is None:
        raise err_not_owner()

    pickup_grid = get_grid_by_code(ride["pickup_grid_code"])
    dropoff_grid = get_grid_by_code(ride["dropoff_grid_code"])
    if pickup_grid is None:
        raise err_reference_not_found("Pickup grid disappeared")
    if dropoff_grid is None:
        raise err_reference_not_found("Dropoff grid disappeared")

    now = s.now()
    ride["completed_at"] = now
    ride["status"] = "COMPLETED"

    # Chronological fare calculation
    final_fare_for(ride, pickup_grid)
    driver["total_earnings_cents"] += ride["driver_earnings_cents"]

    # Driver returns to AVAILABLE at dropoff_grid
    driver["status"] = "AVAILABLE"
    driver["current_grid_code"] = ride["dropoff_grid_code"]
    dropoff_grid["active_driver_count"] += 1

    # Quest progress
    if driver.get("quest_id"):
        q = s.quest_bonuses.get(driver["quest_id"])
        if q is not None and q["status"] == "ACTIVE":
            # The completion is within the active window (since now() falls within [ws, we))
            if q["window_start"] <= now < q["window_end"]:
                driver["quest_completed_rides"] += 1

    driver["updated_at"] = now
    driver["version"] += 1
    ride["updated_at"] = now
    ride["version"] += 1

    recompute_surge(dropoff_grid, bump_version=True)
    return jsonify(success_object(serialize_ride(ride))), 200


@bp.route("/rides/<ride_id>/cancel", methods=["POST"])
@require_roles(["Rider"])
def cancel_ride(ride_id):
    ride = get_ride_or_404(ride_id)
    user_id, _role = current_user()
    if ride["rider_id"] != user_id:
        raise err_not_owner()
    if ride["status"] not in ("REQUESTED", "ASSIGNED"):
        raise err_invalid_state()

    s = store()
    now = s.now()
    pickup_grid = get_grid_by_code(ride["pickup_grid_code"])

    if ride["status"] == "REQUESTED":
        ride["status"] = "CANCELED"
        if pickup_grid is not None:
            pickup_grid["open_demand_count"] -= 1
            recompute_surge(pickup_grid, bump_version=True)
    else:  # ASSIGNED
        driver = s.drivers.get(ride["driver_id"])
        ride["status"] = "CANCELED"
        if driver is not None:
            # Driver reverts to AVAILABLE; current_grid_code unchanged (last grid they were en-route from).
            driver["status"] = "AVAILABLE"
            driver_grid = get_grid_by_code(driver["current_grid_code"]) if driver["current_grid_code"] else None
            if driver_grid is not None:
                driver_grid["active_driver_count"] += 1
                recompute_surge(driver_grid, bump_version=True)
            driver["updated_at"] = now
            driver["version"] += 1

    ride["updated_at"] = now
    ride["version"] += 1
    return jsonify(success_object(serialize_ride(ride))), 200
