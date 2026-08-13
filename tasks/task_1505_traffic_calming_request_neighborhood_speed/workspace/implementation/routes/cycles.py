"""Funding cycles: creation, ranking publication waterfall, close (PRD §3.4)."""
from flask import Blueprint

from auth import require_roles, ALL_ROLES
from calc import allocation_for
from envelope import object_response, list_response
from errors import (
    ApiError, ERR_DUPLICATE_CYCLE_YEAR, ERR_CYCLE_INVALID_STATE,
    ERR_NO_ELIGIBLE_REQUESTS, ERR_STALE_VERSION,
)
from helpers import get_cycle, paginated
from store import store, touch
from validate import parse_body, Struct, pagination

bp = Blueprint("cycles", __name__)


@bp.post("/api/funding-cycles")
@require_roles("CityAdmin")
def create_cycle():
    data, perr = parse_body()
    s = Struct(data, perr)
    year = s.get_int("cycle_year")
    total = s.get_int("budget_total_cents", min=1)
    s.raise_if_errors()
    for c in store.cycles.values():
        if c["cycle_year"] == year:
            raise ApiError(409, ERR_DUPLICATE_CYCLE_YEAR,
                           "A funding cycle with this cycle_year already exists")
    cycle = {
        "id": store.new_id(),
        "cycle_year": year,
        "budget_total_cents": total,
        "budget_committed_cents": 0,
        "budget_available_cents": total,
        "status": "OPEN",
        "published_at": None,
        "created_at": store.now,
        "updated_at": store.now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.cycles[cycle["id"]] = cycle
    return object_response(cycle, 201)


@bp.get("/api/funding-cycles/<cycleId>")
@require_roles(*ALL_ROLES)
def get_one(cycleId):
    return object_response(get_cycle(cycleId))


@bp.get("/api/funding-cycles/<cycleId>/ranking")
@require_roles(*ALL_ROLES)
def ranking(cycleId):
    """Computed read: requests considered in the latest publication — the
    FUNDED and WAITLISTED rows — sorted by citywide_rank ascending (PRD §3.4)."""
    cycle = get_cycle(cycleId)
    considered = [r for r in store.requests.values()
                  if (r["status"] == "FUNDED" and r["funding_cycle_id"] == cycle["id"])
                  or (r["status"] == "WAITLISTED" and r["_ranked_cycle_id"] == cycle["id"])]
    considered.sort(key=lambda r: (r["citywide_rank"], r["_seq"]))
    limit, offset = pagination()
    return list_response(considered, limit, offset)


@bp.post("/api/funding-cycles/<cycleId>/publish-ranking")
@require_roles("CityAdmin")
def publish_ranking(cycleId):
    cycle = get_cycle(cycleId)
    data, perr = parse_body()
    s = Struct(data, perr)
    expected = s.get_int("expected_funding_cycle_version")
    # Tier 4: OCC on the cycle version (PRD §2.7)
    if expected is not None and expected != cycle["version"]:
        raise ApiError(412, ERR_STALE_VERSION,
                       "expected_funding_cycle_version does not match the cycle's current version")
    # Tier 5: cycle state
    if cycle["status"] not in ("OPEN", "RANKING_PUBLISHED"):
        raise ApiError(409, ERR_CYCLE_INVALID_STATE,
                       "Rankings can only be published on an OPEN or RANKING_PUBLISHED cycle")
    # Tier 8: structural (the OCC field is a non-optional input, PRD §2.7)
    s.raise_if_errors()
    # Tier 9: the pool must be non-empty. Re-publication returns this cycle's
    # WAITLISTED requests to the pool; previously FUNDED requests keep their
    # allocation and are excluded from re-ranking (PRD §3.4).
    pool = [r for r in store.requests.values() if r["status"] == "RANKING_ELIGIBLE"]
    if cycle["status"] == "RANKING_PUBLISHED":
        pool += [r for r in store.requests.values()
                 if r["status"] == "WAITLISTED" and r["_ranked_cycle_id"] == cycle["id"]]
    if not pool:
        raise ApiError(409, ERR_NO_ELIGIBLE_REQUESTS,
                       "publish-ranking requires a non-empty eligible pool")
    # Rank: certified_score DESC, crash_count_3yr DESC, created_at ASC (PRD §3.4)
    def rank_key(r):
        seg = store.segments[r["street_segment_id"]]
        return (-r["certified_score"], -seg["crash_count_3yr"], r["created_at"], r["_seq"])
    pool.sort(key=rank_key)
    for i, r in enumerate(pool):
        r["citywide_rank"] = i + 1
        r["_ranked_cycle_id"] = cycle["id"]
    # Strict-stop waterfall; exact fit funds (inclusive >= boundary)
    stopped = False
    for r in pool:
        if not stopped:
            allocated = allocation_for(r["requested_budget_cents"])
            if cycle["budget_available_cents"] >= allocated:
                r["status"] = "FUNDED"
                r["funding_cycle_id"] = cycle["id"]
                r["allocated_cents"] = allocated
                cycle["budget_committed_cents"] += allocated
                cycle["budget_available_cents"] = (
                    cycle["budget_total_cents"] - cycle["budget_committed_cents"])
            else:
                stopped = True
        if stopped:
            r["status"] = "WAITLISTED"
            r["allocated_cents"] = 0
            r["funding_cycle_id"] = None
        touch(r)
    cycle["published_at"] = store.now
    # Publication moves the cycle OPEN -> RANKING_PUBLISHED (and a
    # re-publication keeps it there); only RANKING_PUBLISHED can close (PRD §3.4)
    cycle["status"] = "RANKING_PUBLISHED"
    cycle["version"] += 1  # exactly one increment per publication (PRD §3.4)
    cycle["updated_at"] = store.now
    return object_response(cycle)


@bp.post("/api/funding-cycles/<cycleId>/close")
@require_roles("CityAdmin")
def close_cycle(cycleId):
    cycle = get_cycle(cycleId)
    if cycle["status"] != "RANKING_PUBLISHED":
        raise ApiError(409, ERR_CYCLE_INVALID_STATE,
                       "Only a RANKING_PUBLISHED cycle can be closed")
    # Every request the cycle left WAITLISTED cycles back to RANKING_ELIGIBLE
    for r in store.requests.values():
        if r["status"] == "WAITLISTED" and r["_ranked_cycle_id"] == cycle["id"]:
            r["status"] = "RANKING_ELIGIBLE"
            r["citywide_rank"] = None
            r["_ranked_cycle_id"] = None
            touch(r)
    cycle["status"] = "CLOSED"
    touch(cycle)
    return object_response(cycle)
