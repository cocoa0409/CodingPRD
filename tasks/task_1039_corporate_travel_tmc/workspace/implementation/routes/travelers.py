"""Traveler endpoints, including suspend/reactivate and the suspension cascade."""

from flask import Blueprint, request

import store
from store import touch
from common import get_or_404, single, list_result, filter_by, as_str
from auth import authenticate
from validate import get_body, req_str, req_enum
from errors import bad_request, invalid_state, not_found

bp = Blueprint("travelers", __name__)

GRADES = {"STANDARD", "MANAGER", "EXECUTIVE", "VIP"}
READERS = {"TravelManager", "Traveler", "Approver", "FinanceOfficer"}


@bp.post("/tmc/travelers")
def create_traveler():
    authenticate({"TravelManager"})
    body = get_body()
    # Existence (priority 3): policy_id FK must resolve.
    policy_id = body.get("policy_id")
    if isinstance(policy_id, str) and policy_id != "":
        if policy_id not in store.policies:
            raise not_found("Policy not found")
    rec = {
        "full_name": req_str(body, "full_name"),
        "email": req_str(body, "email"),
        "grade": req_enum(body, "grade", GRADES),
        "policy_id": req_str(body, "policy_id"),
        "home_iata": req_str(body, "home_iata"),
        "status": "ACTIVE",
    }
    if rec["policy_id"] not in store.policies:
        raise not_found("Policy not found")
    # email unique among ACTIVE travelers (PRD §3.1)
    for t in store.travelers.values():
        if t["status"] == "ACTIVE" and t["email"] == rec["email"]:
            raise bad_request("Email already in use by an active traveler")
    store.stamp_new(rec)
    store.travelers[rec["id"]] = rec
    return single(rec, 201)


@bp.get("/tmc/travelers/<tid>")
def get_traveler(tid):
    authenticate(READERS)
    return single(get_or_404(store.travelers, tid))


@bp.get("/tmc/travelers")
def list_travelers():
    authenticate(READERS)
    recs = filter_by(store.travelers.values(), request.args,
                     {"policy_id": as_str, "status": as_str})
    return list_result(recs)


@bp.post("/tmc/travelers/<tid>/suspend")
def suspend_traveler(tid):
    authenticate({"TravelManager"})
    traveler = get_or_404(store.travelers, tid)
    if traveler["status"] != "ACTIVE":
        raise invalid_state("Traveler is not ACTIVE")
    traveler["status"] = "SUSPENDED"
    touch(traveler)
    # CASCADE: cancel every DRAFT / PENDING_MANAGER / PENDING_EXEC trip of this traveler
    for trip in store.trips.values():
        if trip["traveler_id"] == tid and trip["status"] in ("DRAFT", "PENDING_MANAGER", "PENDING_EXEC"):
            trip["status"] = "CANCELLED"
            touch(trip)
    return single(traveler)


@bp.post("/tmc/travelers/<tid>/reactivate")
def reactivate_traveler(tid):
    authenticate({"TravelManager"})
    traveler = get_or_404(store.travelers, tid)
    if traveler["status"] != "SUSPENDED":
        raise invalid_state("Traveler is not SUSPENDED")
    traveler["status"] = "ACTIVE"
    touch(traveler)
    return single(traveler)
