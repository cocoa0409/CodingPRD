"""Candidate identification, survey revision, outreach, RF qualification."""

from flask import Blueprint

import calc
import services
from db import db, get_dt, new_record, now, serialize
from errors import ApiError
from response import created, ok
from routes.common import fetch, listing
from validation import (ALL_ROLES, INTEGER, NUMBER, ROLE_AGENT,
                        ROLE_CONSTRUCTION, ROLE_RF, STRING, actor_id,
                        authenticate, f, validate_body)

bp = Blueprint("candidates", __name__)

SITE_TYPES = ["TOWER", "ROOFTOP", "RAW_LAND"]
EVENT_TYPES = ["OUTREACH_SENT", "LANDLORD_REPLY", "LANDLORD_DECLINED"]


@bp.post("/candidates")
def create_candidate():
    authenticate([ROLE_AGENT])
    body = validate_body([
        f("search_ring_id", STRING),
        f("landlord_id", STRING),
        f("jurisdiction_id", STRING),
        f("owning_agent_user_id", STRING),
        f("site_type", STRING, enum=SITE_TYPES),
        f("lat", NUMBER),
        f("lon", NUMBER),
        f("distance_from_center_m", INTEGER, ge=0),
        f("agl_m", INTEGER, ge=0),
        f("months_to_availability", INTEGER, ge=0),
        f("measured_rsrp_dbm", NUMBER),
        f("offered_capacity_gbps", NUMBER, ge=0),
    ])

    ring = db.search_rings.get(body["search_ring_id"])
    if ring is None:
        raise ApiError("ERR_SEARCH_RING_NOT_FOUND", 404)
    landlord = db.landlords.get(body["landlord_id"])
    if landlord is None:
        raise ApiError("ERR_LANDLORD_NOT_FOUND", 404)
    jurisdiction = db.jurisdictions.get(body["jurisdiction_id"])
    if jurisdiction is None:
        raise ApiError("ERR_JURISDICTION_NOT_FOUND", 404)

    if (landlord["market_code"] != ring["market_code"]
            or jurisdiction["market_code"] != ring["market_code"]):
        raise ApiError("ERR_MARKET_MISMATCH", 409)

    candidate = new_record({
        "search_ring_id": ring["id"],
        "landlord_id": landlord["id"],
        "jurisdiction_id": jurisdiction["id"],
        "owning_agent_user_id": body["owning_agent_user_id"],
        "site_type": body["site_type"],
        "lat": body["lat"],
        "lon": body["lon"],
        "distance_from_center_m": body["distance_from_center_m"],
        "agl_m": body["agl_m"],
        "months_to_availability": body["months_to_availability"],
        "measured_rsrp_dbm": body["measured_rsrp_dbm"],
        "offered_capacity_gbps": body["offered_capacity_gbps"],
        "rf_qualification_score": None,
        "acquisition_status": "PROSPECTING",
        "feasibility_status": "UNSCREENED",
        "outreach_event_count": 0,
        "environmental_cleared": False,
        "permit_issued": False,
    })
    db.candidates[candidate["id"]] = candidate
    services.refresh_ring_rollups(ring)
    return created(serialize(candidate))


@bp.get("/candidates")
def list_candidates():
    authenticate(ALL_ROLES)
    return listing("candidates", ["search_ring_id", "landlord_id", "jurisdiction_id",
                                  "acquisition_status", "feasibility_status"])


@bp.get("/candidates/<candidate_id>")
def read_candidate(candidate_id):
    authenticate(ALL_ROLES)
    return ok(serialize(fetch("candidates", candidate_id)))


def _require_owner(candidate):
    if actor_id() != candidate["owning_agent_user_id"]:
        raise ApiError("ERR_NOT_CANDIDATE_OWNER", 403)


@bp.patch("/candidates/<candidate_id>")
def update_candidate(candidate_id):
    authenticate([ROLE_AGENT])
    body = validate_body([
        f("distance_from_center_m", INTEGER, required=False, ge=0),
        f("agl_m", INTEGER, required=False, ge=0),
        f("months_to_availability", INTEGER, required=False, ge=0),
        f("measured_rsrp_dbm", NUMBER, required=False),
        f("offered_capacity_gbps", NUMBER, required=False, ge=0),
    ])
    candidate = fetch("candidates", candidate_id)
    _require_owner(candidate)
    if candidate["feasibility_status"] != "UNSCREENED":
        raise ApiError("ERR_INVALID_CANDIDATE_STATE", 409)
    services.apply(candidate, body)
    return ok(serialize(candidate))


@bp.post("/candidates/<candidate_id>/outreach-events")
def record_outreach(candidate_id):
    authenticate([ROLE_AGENT])
    body = validate_body([
        f("event_type", STRING, enum=EVENT_TYPES),
        f("note", STRING, required=False),
    ])
    candidate = fetch("candidates", candidate_id)
    _require_owner(candidate)

    landlord = db.landlords.get(candidate["landlord_id"])
    if landlord is not None and landlord["outreach_optout"]:
        raise ApiError("ERR_LANDLORD_OPTED_OUT", 409)

    event = body["event_type"]
    status = candidate["acquisition_status"]
    count = candidate["outreach_event_count"] + 1

    if event == "OUTREACH_SENT":
        if status != "PROSPECTING":
            raise ApiError("ERR_INVALID_CANDIDATE_STATE", 409)
        services.apply(candidate, {"acquisition_status": "OUTREACH_SENT",
                                   "outreach_event_count": count})
    elif event == "LANDLORD_REPLY":
        if status != "OUTREACH_SENT":
            raise ApiError("ERR_INVALID_CANDIDATE_STATE", 409)
        services.apply(candidate, {"acquisition_status": "LANDLORD_ENGAGED",
                                   "outreach_event_count": count})
    else:  # LANDLORD_DECLINED
        if status not in ("OUTREACH_SENT", "LANDLORD_ENGAGED"):
            raise ApiError("ERR_INVALID_CANDIDATE_STATE", 409)
        services.relinquish_candidate(candidate, {"outreach_event_count": count})

    return ok(serialize(candidate))


@bp.post("/candidates/<candidate_id>/rf-qualify")
def rf_qualify(candidate_id):
    authenticate([ROLE_RF])
    validate_body([])
    candidate = fetch("candidates", candidate_id)

    ring = db.search_rings.get(candidate["search_ring_id"])
    if ring is None or ring["status"] != "OPEN":
        raise ApiError("ERR_RING_NOT_OPEN", 409)
    if candidate["feasibility_status"] != "UNSCREENED":
        raise ApiError("ERR_INVALID_CANDIDATE_STATE", 409)

    score = calc.rf_qualification_score(candidate, ring)
    if score >= calc.RF_QUALIFY_MIN_SCORE:
        services.apply(candidate, {"rf_qualification_score": score,
                                   "feasibility_status": "RF_QUALIFIED"})
    else:
        services.disqualify_candidate(candidate, {"rf_qualification_score": score})
    return ok(serialize(candidate))


@bp.post("/candidates/<candidate_id>/mark-build-ready")
def mark_build_ready(candidate_id):
    authenticate([ROLE_CONSTRUCTION])
    validate_body([])
    candidate = fetch("candidates", candidate_id)

    if (candidate["feasibility_status"] not in ("STRUCTURALLY_CLEARED", "ENTITLED")
            or candidate["acquisition_status"] != "LEASE_EXECUTED"):
        raise ApiError("ERR_INVALID_CANDIDATE_STATE", 409)
    if not candidate["environmental_cleared"]:
        raise ApiError("ERR_ENVIRONMENTAL_NOT_CLEARED", 409)

    issued = [p for p in services.permits_of_candidate(candidate["id"])
              if p["status"] == "ISSUED"]
    if not candidate["permit_issued"] or not issued:
        raise ApiError("ERR_PERMIT_NOT_ISSUED", 409)

    clock = now()
    live = []
    for permit in issued:
        expiry = get_dt(permit, "expiry_date")
        if expiry is not None and clock > expiry:
            continue
        live.append(permit)
    if not live:
        # the permits are relied upon here, so their lazy expiry fires now
        for permit in issued:
            services.refresh_permit(permit)
        raise ApiError("ERR_PERMIT_EXPIRED", 409)

    services.apply(candidate, {"feasibility_status": "BUILD_READY"})
    return ok(serialize(candidate))
