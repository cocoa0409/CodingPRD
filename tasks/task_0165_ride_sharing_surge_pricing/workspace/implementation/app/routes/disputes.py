"""Dispute endpoints."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..auth import current_user, require_roles
from ..envelope import paginate, parse_pagination, success_array, success_object
from ..errors import (
    err_dispute_already_exists,
    err_invalid_state,
    err_not_owner,
    err_refund_exceeds_fare,
    err_refund_exceeds_request,
    err_reference_not_found,
)
from ..serializers import serialize_dispute
from ..services.fares import clawback_for_refund
from ..store import store
from ..util import new_uuid
from ._helpers import (
    REASON_CODES,
    get_dispute_or_404,
    get_json,
    get_ride_or_404,
    optional_int,
    require_int,
    require_string,
)

bp = Blueprint("disputes", __name__)


def _existing_open_or_approved_dispute_for(ride_id: str):
    for d in store().list_collection("disputes"):
        if d["ride_id"] == ride_id and d["status"] in ("OPEN", "APPROVED"):
            return d
    return None


@bp.route("/disputes", methods=["POST"])
@require_roles(["Rider"])
def create_dispute():
    body = get_json()
    user_id, _role = current_user()

    ride_id = require_string(body, "ride_id")
    reason_code = require_string(body, "reason_code")
    if reason_code not in REASON_CODES:
        from ..errors import err_invalid_input
        raise err_invalid_input(f"reason_code must be one of {sorted(REASON_CODES)}")
    requested_refund_cents = require_int(body, "requested_refund_cents")

    s = store()
    ride = s.rides.get(ride_id)
    if ride is None:
        raise err_reference_not_found("ride_id does not reference an existing ride")

    # Rider-side ownership (priority 6) before state checks.
    if ride["rider_id"] != user_id:
        raise err_not_owner()

    # Priority 8 (PRD §2.9): combined uniqueness + ride-status check.
    # If an OPEN/APPROVED dispute already exists for this ride, the
    # uniqueness condition is what fails — yielding
    # ERR_DISPUTE_ALREADY_EXISTS. This must be checked BEFORE the bare
    # state precondition, since a duplicate dispute also leaves the ride
    # in DISPUTED state, and PRD's ordering example explicitly resolves
    # this as ERR_DISPUTE_ALREADY_EXISTS.
    if _existing_open_or_approved_dispute_for(ride_id) is not None:
        raise err_dispute_already_exists()

    # State precondition (priority 7): Ride.status must be COMPLETED.
    if ride["status"] != "COMPLETED":
        raise err_invalid_state()

    # Fiscal validation: 0 < requested_refund_cents <= ride.final_fare_cents.
    if requested_refund_cents <= 0:
        raise err_refund_exceeds_fare("requested_refund_cents must be > 0")
    if ride.get("final_fare_cents") is None or requested_refund_cents > ride["final_fare_cents"]:
        raise err_refund_exceeds_fare()

    now = s.now()
    did = new_uuid()
    dispute = {
        "id": did,
        "ride_id": ride_id,
        "rider_id": ride["rider_id"],
        "reason_code": reason_code,
        "requested_refund_cents": requested_refund_cents,
        "approved_refund_cents": None,
        "status": "OPEN",
        "resolved_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    s.insert("disputes", dispute)
    # Side effect: ride status moves to DISPUTED.
    ride["status"] = "DISPUTED"
    ride["updated_at"] = now
    ride["version"] += 1
    return jsonify(success_object(serialize_dispute(dispute))), 201


@bp.route("/disputes/<dispute_id>", methods=["GET"])
@require_roles(["Rider", "DisputeOps", "PlatformAdmin"])
def get_dispute(dispute_id):
    d = get_dispute_or_404(dispute_id)
    user_id, role = current_user()
    if role == "Rider" and d["rider_id"] != user_id:
        raise err_not_owner()
    return jsonify(success_object(serialize_dispute(d))), 200


@bp.route("/disputes", methods=["GET"])
@require_roles(["DisputeOps", "PlatformAdmin"])
def list_disputes():
    limit, offset = parse_pagination()
    status = request.args.get("status")
    rider_id = request.args.get("rider_id")
    items = sorted(store().list_collection("disputes"), key=lambda x: x["created_at"])
    if status is not None:
        items = [d for d in items if d["status"] == status]
    if rider_id is not None:
        items = [d for d in items if d["rider_id"] == rider_id]
    total = len(items)
    page = paginate(items, limit, offset)
    return jsonify(success_array(
        [serialize_dispute(d) for d in page], limit=limit, offset=offset, total_count=total
    )), 200


@bp.route("/disputes/<dispute_id>/approve", methods=["POST"])
@require_roles(["DisputeOps"])
def approve_dispute(dispute_id):
    dispute = get_dispute_or_404(dispute_id)
    body = get_json()

    s = store()
    ride = s.rides.get(dispute["ride_id"])
    if ride is None:
        raise err_reference_not_found("Ride not found for dispute")

    # State preconditions
    if dispute["status"] != "OPEN" or ride["status"] != "DISPUTED":
        raise err_invalid_state()

    approved_amount = optional_int(body, "approved_refund_cents", min_value=0)
    if approved_amount is None:
        approved_amount = dispute["requested_refund_cents"]
    else:
        if approved_amount > dispute["requested_refund_cents"]:
            raise err_refund_exceeds_request()

    # Final guard: cap at ride.final_fare_cents.
    if ride.get("final_fare_cents") is not None and approved_amount > ride["final_fare_cents"]:
        approved_amount = ride["final_fare_cents"]

    now = s.now()
    dispute["approved_refund_cents"] = approved_amount
    dispute["status"] = "APPROVED"
    dispute["resolved_at"] = now
    dispute["updated_at"] = now
    dispute["version"] += 1

    # Wallet credit
    rider = s.riders.get(dispute["rider_id"])
    if rider is not None:
        rider["wallet_balance_cents"] += approved_amount
        rider["updated_at"] = now
        rider["version"] += 1

    # Compensating clawback on driver earnings
    driver = s.drivers.get(ride["driver_id"]) if ride.get("driver_id") else None
    if driver is not None:
        clawback = clawback_for_refund(approved_amount)
        driver["total_earnings_cents"] = max(0, driver["total_earnings_cents"] - clawback)
        driver["updated_at"] = now
        driver["version"] += 1

    ride["status"] = "REFUNDED"
    ride["updated_at"] = now
    ride["version"] += 1

    return jsonify(success_object(serialize_dispute(dispute))), 200


@bp.route("/disputes/<dispute_id>/reject", methods=["POST"])
@require_roles(["DisputeOps"])
def reject_dispute(dispute_id):
    dispute = get_dispute_or_404(dispute_id)

    s = store()
    ride = s.rides.get(dispute["ride_id"])
    if ride is None:
        raise err_reference_not_found("Ride not found for dispute")
    if dispute["status"] != "OPEN" or ride["status"] != "DISPUTED":
        raise err_invalid_state()

    now = s.now()
    dispute["status"] = "REJECTED"
    dispute["resolved_at"] = now
    dispute["updated_at"] = now
    dispute["version"] += 1

    ride["status"] = "COMPLETED"
    ride["updated_at"] = now
    ride["version"] += 1
    return jsonify(success_object(serialize_dispute(dispute))), 200
