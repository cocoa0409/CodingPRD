"""Emergency protective placements and facility bed capacity (PRD 3.4)."""
from datetime import timedelta

from flask import Blueprint, request

from store import store
from errors import ApiError
from envelope import success
from helpers import (authenticate, authorize, get_body, require_str, optional_bool,
                     resolve, resolve_body_id, parse_dt, base_fields, touch,
                     paginate, sort_key, serialize)
from recompute import recompute_client_placement

bp = Blueprint("placements", __name__)

EMERGENCY_CAP_HOURS = 72


def _overlaps(a_start, a_end, b_start, b_end):
    # half-open [start, end): overlap iff a_start < b_end and b_start < a_end
    return a_start < b_end and b_start < a_end


def _release_bed(facility):
    facility["occupied_beds"] -= 1
    facility["available_beds"] += 1
    touch(facility)


@bp.post("/placements")
def create_placement():
    uid, role = authenticate()
    authorize(role, {"Caseworker"})
    body = get_body()
    resolve_body_id(body, "case_id", "case")
    resolve_body_id(body, "facility_id", "facility")
    case_id = require_str(body, "case_id")
    facility_id = require_str(body, "facility_id")
    start_raw = require_str(body, "start_at")
    end_raw = require_str(body, "end_at")
    court_authorized = optional_bool(body, "court_authorized", False)
    case = resolve("case", case_id)
    facility = resolve("facility", facility_id)

    start_at = parse_dt(start_raw, "start_at")
    end_at = parse_dt(end_raw, "end_at")
    if not (end_at > start_at):
        raise ApiError("ERR_INVALID_DATE_RANGE", "end_at must be strictly after start_at", 422)

    client = store.clients[case["client_id"]]
    if not (client["capacity_status"] == "IMPAIRED" or client["risk_level"] == "HIGH"):
        raise ApiError("ERR_CLIENT_NOT_ELIGIBLE_FOR_PLACEMENT",
                       "Client is not eligible for emergency placement", 422)

    overlapping = 0
    for p in store.placements.values():
        if p["facility_id"] == facility_id and p["status"] == "ACTIVE":
            if _overlaps(start_at, end_at, p["start_at"], p["end_at"]):
                overlapping += 1
    if overlapping >= facility["total_beds"]:
        raise ApiError("ERR_NO_BED_AVAILABLE", "No bed available for the requested window", 409)

    if court_authorized:
        expires_at = end_at
    else:
        expires_at = start_at + timedelta(hours=EMERGENCY_CAP_HOURS)

    placement = base_fields()
    placement.update({
        "case_id": case_id,
        "client_id": case["client_id"],
        "facility_id": facility_id,
        "start_at": start_at,
        "end_at": end_at,
        "court_authorized": court_authorized,
        "status": "ACTIVE",
        "expires_at": expires_at,
        "discharged_at": None,
    })
    store.placements[placement["id"]] = placement

    facility["occupied_beds"] += 1
    facility["available_beds"] -= 1
    touch(facility)
    recompute_client_placement(client)
    touch(client)
    return success(serialize(placement, "placement")), 201


@bp.get("/placements/<pid>")
def get_placement(pid):
    uid, role = authenticate()
    authorize(role, {"Caseworker", "Supervisor"})
    placement = resolve("placement", pid)
    return success(serialize(placement, "placement")), 200


@bp.get("/placements")
def list_placements():
    uid, role = authenticate()
    authorize(role, {"Caseworker", "Supervisor"})
    items = list(store.placements.values())
    for key in ("case_id", "facility_id", "client_id"):
        val = request.args.get(key)
        if val is not None:
            items = [p for p in items if p[key] == val]
    items.sort(key=sort_key)
    page, pag = paginate(items)
    return success([serialize(p, "placement") for p in page], "array", pag), 200


@bp.post("/placements/<pid>/discharge")
def discharge(pid):
    uid, role = authenticate()
    authorize(role, {"Caseworker"})
    placement = resolve("placement", pid)
    if placement["status"] != "ACTIVE":
        raise ApiError("ERR_PLACEMENT_INVALID_STATE", "Placement is not ACTIVE", 409)
    placement["status"] = "DISCHARGED"
    placement["discharged_at"] = store.clock
    touch(placement)
    _release_bed(store.facilities[placement["facility_id"]])
    client = store.clients[placement["client_id"]]
    recompute_client_placement(client)
    touch(client)
    return success(serialize(placement, "placement")), 200


@bp.post("/placements/<pid>/review")
def review(pid):
    uid, role = authenticate()
    authorize(role, {"Supervisor"})
    placement = resolve("placement", pid)
    if placement["status"] != "ACTIVE":
        raise ApiError("ERR_PLACEMENT_INVALID_STATE", "Placement is not ACTIVE", 409)
    if (not placement["court_authorized"]) and store.clock >= placement["expires_at"]:
        placement["status"] = "EXPIRED"
        placement["discharged_at"] = store.clock
        touch(placement)
        _release_bed(store.facilities[placement["facility_id"]])
        client = store.clients[placement["client_id"]]
        recompute_client_placement(client)
        touch(client)
    return success(serialize(placement, "placement")), 200
