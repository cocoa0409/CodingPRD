"""Pool endpoints: create, get, list, OCC-guarded rate PATCH, close/reopen
transitions, and settlement.

Closing may push the season OPEN -> HARVEST_CLOSED (locking quotas); reopening
under HARVEST_CLOSED reverts the season to OPEN (clearing locks); settling
computes the final rate and creates PatronageDistribution rows.
"""
from decimal import Decimal

from flask import Blueprint

from db import store, new_common, touch
from errors import ApiError
from middleware import authenticate, require_roles, ANY_ROLE
from response import ok, created, paginate
from services import coupling, settlement
from validation import (get_body, req_string, req_number, req_int, req_enum,
                        require_nonnegative, require_range)

bp = Blueprint("pools", __name__)

POOL_CODES = {"MAIN", "OVER_QUOTA"}
POOL_STATUSES = {"OPEN", "CLOSED", "SETTLED"}
OPEN_DELIVERY_STATUSES = {"RECEIVED", "GRADED", "DISPUTED"}


def get_pool_or_404(pool_id):
    pool = store.pools.get(pool_id)
    if pool is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Pool not found")
    return pool


@bp.post("/coop/pools")
def create_pool():
    body = get_body()
    season_id = req_string(body, "season_id")
    code = req_enum(body, "code", POOL_CODES)
    rate = require_nonnegative(req_number(body, "provisional_advance_rate_per_barrel"),
                               "provisional_advance_rate_per_barrel")
    retain = require_range(req_number(body, "retain_pct"), "retain_pct",
                           Decimal("0"), Decimal("1"))

    _, role = authenticate()
    require_roles(role, {"PoolManager"})

    season = store.seasons.get(season_id)
    if season is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Season not found")

    for p in store.pools.values():
        if p["season_id"] == season_id and p["code"] == code:
            raise ApiError("ERR_DUPLICATE_POOL_CODE", 409,
                           "A pool with the same code already exists for the season")

    if season["status"] not in ("SETUP", "OPEN"):
        raise ApiError("ERR_SEASON_NOT_OPEN", 409,
                       "Season must be SETUP or OPEN for pool creation")

    pool = new_common({
        "season_id": season_id,
        "code": code,
        "provisional_advance_rate_per_barrel": rate,
        "retain_pct": retain,
        "status": "OPEN",
        "accepted_net_barrels": Decimal("0"),
        "weighted_barrels_total": Decimal("0"),
        "advances_outstanding": Decimal("0"),
        "realized_revenue": None,
        "operating_costs": None,
        "final_rate_per_weighted_barrel": None,
        "coop_equity_residual": None,
    })
    store.pools[pool["id"]] = pool
    return created(pool)


@bp.get("/coop/pools/<pool_id>")
def get_pool(pool_id):
    _, role = authenticate()
    require_roles(role, ANY_ROLE)
    return ok(get_pool_or_404(pool_id))


@bp.get("/coop/pools")
def list_pools():
    _, role = authenticate()
    require_roles(role, ANY_ROLE)
    rows = list(store.pools.values())
    rows = paginate.filter(rows, "season_id")
    rows = paginate.filter(rows, "code")
    rows = paginate.filter(rows, "status")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.patch("/coop/pools/<pool_id>")
def patch_pool(pool_id):
    body = get_body()
    rate = require_nonnegative(req_number(body, "provisional_advance_rate_per_barrel"),
                               "provisional_advance_rate_per_barrel")
    expected_version = req_int(body, "expected_pool_version")

    _, role = authenticate()
    require_roles(role, {"PoolManager"})

    pool = get_pool_or_404(pool_id)

    # OCC (band 5) precedes the pool-state fiscal check (band 10).
    if expected_version != pool["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_pool_version does not match the pool's current version")
    if pool["status"] != "OPEN":
        raise ApiError("ERR_POOL_NOT_OPEN", 409, "Pool is not OPEN")

    # Rate changes never retroactively alter recorded delivery advances.
    pool["provisional_advance_rate_per_barrel"] = rate
    touch(pool)
    return ok(pool)


@bp.post("/coop/pools/<pool_id>/transition")
def transition_pool(pool_id):
    body = get_body()
    to = req_enum(body, "to", POOL_STATUSES)

    _, role = authenticate()
    require_roles(role, {"PoolManager"})

    pool = get_pool_or_404(pool_id)
    season = store.seasons.get(pool["season_id"])

    if pool["status"] == "OPEN" and to == "CLOSED":
        for d in store.deliveries.values():
            if d["season_id"] == pool["season_id"] and d["status"] in OPEN_DELIVERY_STATUSES:
                raise ApiError("ERR_POOL_HAS_OPEN_DELIVERIES", 409,
                               "Season has deliveries still in RECEIVED/GRADED/DISPUTED")
        pool["status"] = "CLOSED"
        touch(pool)
        if season is not None:
            coupling.maybe_close_season(season)
    elif pool["status"] == "CLOSED" and to == "OPEN":
        if season is not None and season["status"] == "SETTLED":
            raise ApiError("ERR_SEASON_NOT_OPEN", 409,
                           "Season is SETTLED; pools cannot be reopened")
        pool["status"] = "OPEN"
        touch(pool)
        if season is not None:
            coupling.maybe_reopen_season(season)
    else:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Pool transition %s -> %s is not defined" % (pool["status"], to))

    return ok(pool)


@bp.post("/coop/pools/<pool_id>/settle")
def settle_pool(pool_id):
    body = get_body()
    revenue = req_number(body, "realized_revenue")
    costs = req_number(body, "operating_costs")
    expected_version = req_int(body, "expected_pool_version")

    _, role = authenticate()
    require_roles(role, {"PoolManager"})

    pool = get_pool_or_404(pool_id)

    # Band 5: optimistic concurrency.
    if expected_version != pool["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_pool_version does not match the pool's current version")
    # Band 6: state legality.
    if pool["status"] != "CLOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Pool is not CLOSED")
    # Band 9: referenced-entity state compatibility.
    season = store.seasons.get(pool["season_id"])
    if season is None or season["status"] != "HARVEST_CLOSED":
        raise ApiError("ERR_SEASON_NOT_OPEN", 409,
                       "Season must be HARVEST_CLOSED for settlement")
    # Band 10: settlement money sanity.
    if costs < 0 or revenue < costs:
        raise ApiError("ERR_SETTLEMENT_INPUT_INVALID", 422,
                       "Require operating_costs >= 0 and realized_revenue >= operating_costs")
    if pool["weighted_barrels_total"] == 0 and (revenue != 0 or costs != 0):
        raise ApiError("ERR_SETTLEMENT_INPUT_INVALID", 422,
                       "A pool with zero weighted barrels requires zero revenue and zero costs")

    settlement.settle_pool(pool, revenue, costs)
    return ok(pool)
