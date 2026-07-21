"""TripRequest endpoints: create, submit, approve, reject, cancel."""

from flask import Blueprint, request

import store
import logic
from store import touch
from common import get_or_404, single, list_result, filter_by, as_str
from auth import authenticate
from validate import get_body, req_str, req_int, req_dt, opt_str
from errors import (ApiError, not_found, invalid_state,
                    ERR_SELF_APPROVAL, ERR_TRAVELER_SUSPENDED,
                    ERR_APPROVAL_RANK_TOO_LOW)

bp = Blueprint("trips", __name__)

READERS = {"TravelManager", "Traveler", "Approver", "FinanceOfficer"}
APPROVER_GRADES = {"MANAGER", "EXECUTIVE", "VIP"}


@bp.post("/tmc/trip-requests")
def create_trip():
    authenticate({"Traveler"})
    body = get_body()
    traveler_id = body.get("traveler_id")
    if isinstance(traveler_id, str) and traveler_id != "" and traveler_id not in store.travelers:
        raise not_found("Traveler not found")
    rec = {
        "traveler_id": req_str(body, "traveler_id"),
        "origin": req_str(body, "origin"),
        "destination": req_str(body, "destination"),
        "depart_date": req_dt(body, "depart_date"),
        "return_date": req_dt(body, "return_date"),
        "purpose": req_str(body, "purpose"),
        "market_estimate_cents": req_int(body, "market_estimate_cents", min_value=0),
        "estimated_cost_cents": 0,
        "actual_cost_cents": 0,
        "approval_level_required": "NONE",
        "status": "DRAFT",
    }
    if rec["traveler_id"] not in store.travelers:
        raise not_found("Traveler not found")
    store.stamp_new(rec)
    store.trips[rec["id"]] = rec
    return single(rec, 201)


@bp.get("/tmc/trip-requests/<tid>")
def get_trip(tid):
    authenticate(READERS)
    return single(get_or_404(store.trips, tid))


@bp.get("/tmc/trip-requests")
def list_trips():
    authenticate(READERS)
    recs = filter_by(store.trips.values(), request.args,
                     {"traveler_id": as_str, "status": as_str})
    return list_result(recs)


@bp.post("/tmc/trip-requests/<tid>/submit")
def submit_trip(tid):
    authenticate({"Traveler"})
    trip = get_or_404(store.trips, tid)
    if trip["status"] != "DRAFT":
        raise invalid_state("Trip is not in DRAFT")
    traveler = store.travelers.get(trip["traveler_id"])
    if not traveler or traveler["status"] != "ACTIVE":
        raise ApiError(ERR_TRAVELER_SUSPENDED, 409, "Owning traveler is not ACTIVE")
    policy = logic.policy_for_traveler(traveler)
    estimate, level = logic.compute_estimate_and_level(trip, policy)
    trip["estimated_cost_cents"] = estimate
    trip["approval_level_required"] = level
    trip["status"] = "APPROVED" if level == "NONE" else "PENDING_MANAGER"
    touch(trip)
    return single(trip)


@bp.post("/tmc/trip-requests/<tid>/approve")
def approve_trip(tid):
    user_id, _ = authenticate({"Approver"})
    trip = get_or_404(store.trips, tid)
    if trip["status"] not in ("PENDING_MANAGER", "PENDING_EXEC"):
        raise invalid_state("Trip is not pending approval")
    if user_id == trip["traveler_id"]:
        raise ApiError(ERR_SELF_APPROVAL, 403, "Approver may not approve their own trip")
    approver = store.travelers.get(user_id)
    grade = approver["grade"] if approver else None
    if trip["status"] == "PENDING_MANAGER":
        if grade not in APPROVER_GRADES:
            raise ApiError(ERR_APPROVAL_RANK_TOO_LOW, 409, "Approver grade insufficient")
        if trip["approval_level_required"] == "MANAGER":
            trip["status"] = "APPROVED"
        else:  # EXEC
            trip["status"] = "PENDING_EXEC"
    else:  # PENDING_EXEC
        if grade != "EXECUTIVE":
            raise ApiError(ERR_APPROVAL_RANK_TOO_LOW, 409, "Executive grade required")
        trip["status"] = "APPROVED"
    touch(trip)
    return single(trip)


@bp.post("/tmc/trip-requests/<tid>/reject")
def reject_trip(tid):
    user_id, _ = authenticate({"Approver"})
    trip = get_or_404(store.trips, tid)
    if trip["status"] not in ("PENDING_MANAGER", "PENDING_EXEC"):
        raise invalid_state("Trip is not pending approval")
    if user_id == trip["traveler_id"]:
        raise ApiError(ERR_SELF_APPROVAL, 403, "Approver may not reject their own trip")
    body = get_body()
    opt_str(body, "reason")
    trip["status"] = "DRAFT"
    touch(trip)
    return single(trip)


@bp.post("/tmc/trip-requests/<tid>/cancel")
def cancel_trip(tid):
    authenticate({"Traveler", "TravelManager"})
    trip = get_or_404(store.trips, tid)
    if trip["status"] not in ("APPROVED", "BOOKED"):
        raise invalid_state("Only APPROVED or BOOKED trips may be cancelled")
    was_booked = trip["status"] == "BOOKED"
    trip["status"] = "CANCELLED"
    touch(trip)
    if was_booked:
        # CASCADE: terminate every non-terminal (TICKETED) booking of this trip.
        for booking in list(store.bookings.values()):
            if booking["trip_request_id"] == tid and booking["status"] == "TICKETED":
                logic.terminate_booking(booking)
        logic.recompute_actual_cost(trip)
    return single(trip)
