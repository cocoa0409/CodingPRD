"""The logical clock and the SearchRing surface."""

from decimal import Decimal

from flask import Blueprint

import calc
import services
from db import db, new_record, serialize, sort_key
from errors import ApiError
from response import created, ok
from routes.common import fetch, listing
from validation import (ALL_ROLES, DATETIME, INTEGER, NUMBER, ROLE_DIRECTOR,
                        ROLE_RF, STRING, actor_id, authenticate, f,
                        validate_body)

bp = Blueprint("rings", __name__)

OBJECTIVE_TYPES = ["COVERAGE", "CAPACITY", "COVERAGE_AND_CAPACITY"]


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate([ROLE_DIRECTOR])
    body = validate_body([f("to_iso8601", DATETIME)])
    db.clock = body["to_iso8601"].dt
    return ok({})


# ---------------------------------------------------------------------------
# search rings
# ---------------------------------------------------------------------------

@bp.post("/search-rings")
def create_ring():
    authenticate([ROLE_RF])
    body = validate_body([
        f("name", STRING),
        f("market_code", STRING),
        f("center_lat", NUMBER),
        f("center_lon", NUMBER),
        f("radius_m", INTEGER, ge=100),
        f("required_agl_m", INTEGER, ge=10),
        f("objective_type", STRING, enum=OBJECTIVE_TYPES),
        f("target_rsrp_dbm", NUMBER),
        f("target_capacity_gbps", NUMBER, gt=0),
        f("market_benchmark_monthly_rent_usd", NUMBER, gt=0),
        f("capex_budget_usd", NUMBER, ge=0),
        f("priority_rank", INTEGER),
    ])
    ring = new_record({
        "name": body["name"],
        "market_code": body["market_code"],
        "center_lat": body["center_lat"],
        "center_lon": body["center_lon"],
        "radius_m": body["radius_m"],
        "required_agl_m": body["required_agl_m"],
        "objective_type": body["objective_type"],
        "target_rsrp_dbm": body["target_rsrp_dbm"],
        "target_capacity_gbps": body["target_capacity_gbps"],
        "market_benchmark_monthly_rent_usd": body["market_benchmark_monthly_rent_usd"],
        "capex_budget_usd": body["capex_budget_usd"],
        "priority_rank": body["priority_rank"],
        "status": "DRAFT",
        "selected_candidate_id": None,
        "candidate_count": 0,
        "committed_capex_usd": Decimal("0"),
        "reopen_count": 0,
    })
    db.search_rings[ring["id"]] = ring
    return created(serialize(ring))


@bp.get("/search-rings")
def list_rings():
    authenticate(ALL_ROLES)
    return listing("search_rings", ["market_code", "status", "selected_candidate_id"])


@bp.get("/search-rings/<ring_id>")
def read_ring(ring_id):
    authenticate(ALL_ROLES)
    return ok(serialize(fetch("search_rings", ring_id)))


@bp.post("/search-rings/<ring_id>/open")
def open_ring(ring_id):
    authenticate([ROLE_RF])
    validate_body([])
    ring = fetch("search_rings", ring_id)
    if ring["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_RING_STATE", 409)
    services.apply(ring, {"status": "OPEN"})
    return ok(serialize(ring))


def _selection_key(candidate):
    score = candidate["rf_qualification_score"]
    score = calc.dec(score) if score is not None else Decimal("0")
    lease = services.executed_lease_of_candidate(candidate)
    rent = None
    if lease is not None:
        rent = lease["committed_rent_final_usd"]
    rent = calc.dec(rent) if rent is not None else Decimal("0")
    return (-score, rent, sort_key(candidate))


@bp.post("/search-rings/<ring_id>/select-site")
def select_site(ring_id):
    authenticate([ROLE_DIRECTOR])
    body = validate_body([f("expected_search_ring_version", INTEGER)])
    ring = fetch("search_rings", ring_id)

    if body["expected_search_ring_version"] != ring["version"]:
        raise ApiError("ERR_STALE_RING_VERSION", 412)
    if ring["status"] != "OPEN":
        raise ApiError("ERR_RING_NOT_OPEN", 409)

    candidates = services.candidates_of_ring(ring["id"])
    for candidate in candidates:
        services.refresh_candidate_permits(candidate["id"])

    pool = [c for c in services.candidates_of_ring(ring["id"])
            if c["acquisition_status"] == "LEASE_EXECUTED"
            and c["feasibility_status"] == "BUILD_READY"]
    if not pool:
        raise ApiError("ERR_NO_ELIGIBLE_CANDIDATE", 409)

    pool.sort(key=_selection_key)
    winner = pool[0]
    services.apply(ring, {
        "selected_candidate_id": winner["id"],
        "status": "SITE_SELECTED",
        "committed_capex_usd": services.ring_committed_capex(ring["id"]),
    })
    return ok(serialize(ring))


@bp.post("/search-rings/<ring_id>/reopen")
def reopen_ring(ring_id):
    authenticate([ROLE_DIRECTOR])
    validate_body([f("reason", STRING)])
    ring = fetch("search_rings", ring_id)
    if ring["status"] != "SITE_SELECTED":
        raise ApiError("ERR_INVALID_RING_STATE", 409)
    services.apply(ring, {
        "selected_candidate_id": None,
        "status": "OPEN",
        "reopen_count": ring["reopen_count"] + 1,
        "committed_capex_usd": services.ring_committed_capex(ring["id"]),
    })
    return ok(serialize(ring))
