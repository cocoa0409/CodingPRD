"""InvestmentPool and NavPeriod endpoints (PRD 3.1)."""
from flask import Blueprint, request

from db import db, common_create_fields, touch, LOCK
from errors import err
from middleware import get_identity, require_role, get_json_body, get_pagination, paginate
from response import object_response, array_response
from services import serialize
from services.lookup import (
    get_or_404, require_string, require_enum, require_int, filtered_sorted,
)

bp = Blueprint("pools", __name__)

RISK_TIERS = {"CONSERVATIVE", "BALANCED", "GROWTH"}
POOL_READ_ROLES = {"SponsorAdmin", "DonorAdvisor", "GrantOfficer"}


# ---------------- InvestmentPool ----------------
@bp.post("/daf/pools")
def create_pool():
    _, role = get_identity()
    require_role(role, {"SponsorAdmin"})
    body = get_json_body()
    sponsor_id = require_string(body, "sponsor_id")
    name = require_string(body, "name")
    risk_tier = require_enum(body, "risk_tier", RISK_TIERS)
    nav = require_int(body, "nav_per_unit_cents")
    fee_bps = require_int(body, "fee_bps")

    with LOCK:
        get_or_404(db.sponsors, sponsor_id)  # body FK existence
        # PRD 3.1: non-positive NAV rejected with ERR_POOL_NAV_INVALID.
        if nav <= 0:
            raise err("ERR_POOL_NAV_INVALID")
        pool = common_create_fields()
        pool.update({
            "sponsor_id": sponsor_id,
            "name": name,
            "risk_tier": risk_tier,
            "nav_per_unit_cents": nav,
            "fee_bps": fee_bps,
            "status": "OPEN",
        })
        db.pools[pool["id"]] = pool
    return object_response(serialize.pool(pool), status=201)


@bp.get("/daf/pools/<pool_id>")
def get_pool(pool_id):
    _, role = get_identity()
    require_role(role, POOL_READ_ROLES)
    pool = get_or_404(db.pools, pool_id)
    return object_response(serialize.pool(pool))


@bp.get("/daf/pools")
def list_pools():
    _, role = get_identity()
    require_role(role, POOL_READ_ROLES)
    limit, offset = get_pagination()
    items = filtered_sorted(db.pools, {
        "sponsor_id": request.args.get("sponsor_id"),
        "status": request.args.get("status"),
    })
    page, meta = paginate(items, limit, offset)
    return array_response([serialize.pool(p) for p in page], meta)


@bp.post("/daf/pools/<pool_id>/close")
def close_pool(pool_id):
    _, role = get_identity()
    require_role(role, {"SponsorAdmin"})
    with LOCK:
        pool = get_or_404(db.pools, pool_id)
        # status -> CLOSED (PRD 3.1). Idempotent-safe but mark state if already CLOSED.
        if pool["status"] == "CLOSED":
            raise err("ERR_INVALID_STATE")
        pool["status"] = "CLOSED"
        touch(pool)
    return object_response(serialize.pool(pool))


# ---------------- NavPeriod ----------------
@bp.post("/daf/nav-periods")
def create_nav_period():
    _, role = get_identity()
    require_role(role, {"SponsorAdmin"})
    body = get_json_body()
    pool_id = require_string(body, "investment_pool_id")
    from_q = require_int(body, "from_quarter")
    to_q = require_int(body, "to_quarter")
    nav = require_int(body, "nav_per_unit_cents")

    with LOCK:
        get_or_404(db.pools, pool_id)  # body FK existence
        if nav <= 0:
            raise err("ERR_POOL_NAV_INVALID")
        # PRD 3.1: half-open windows [from, to). Collide with existing ACTIVE iff
        # existing_start < new_end AND new_start < existing_end (strict).
        for existing in db.nav_periods.values():
            if existing["investment_pool_id"] != pool_id:
                continue
            if existing["status"] != "ACTIVE":
                continue
            if existing["from_quarter"] < to_q and from_q < existing["to_quarter"]:
                raise err("ERR_NAV_PERIOD_OVERLAP")
        period = common_create_fields()
        period.update({
            "investment_pool_id": pool_id,
            "from_quarter": from_q,
            "to_quarter": to_q,
            "nav_per_unit_cents": nav,
            "status": "ACTIVE",
        })
        db.nav_periods[period["id"]] = period
    return object_response(serialize.nav_period(period), status=201)


@bp.get("/daf/nav-periods/<nav_period_id>")
def get_nav_period(nav_period_id):
    _, role = get_identity()
    require_role(role, POOL_READ_ROLES)
    period = get_or_404(db.nav_periods, nav_period_id)
    return object_response(serialize.nav_period(period))


@bp.get("/daf/nav-periods")
def list_nav_periods():
    _, role = get_identity()
    require_role(role, POOL_READ_ROLES)
    limit, offset = get_pagination()
    items = filtered_sorted(db.nav_periods, {
        "investment_pool_id": request.args.get("investment_pool_id"),
        "status": request.args.get("status"),
    })
    page, meta = paginate(items, limit, offset)
    return array_response([serialize.nav_period(p) for p in page], meta)
