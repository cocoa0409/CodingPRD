"""RoyaltyPool endpoints (§3.6)."""

from flask import Blueprint

import lookup
import serializers
import validation
from constants import API_PREFIX, ROLE_ROYALTY_ADMIN, SUBSCRIPTION_TIERS
from db import db, stamp_new, touch
from errors import ApiError
from middleware import require
from response import created_response, object_response, paginate_and_serialize
from services import cascades, pools as pool_service

bp = Blueprint("pools", __name__, url_prefix=API_PREFIX)


@bp.post("/pools")
@require(ROLE_ROYALTY_ADMIN)
def create_pool():
    data = validation.body()

    raw_period_id = data.get("period_id")
    period = None
    if isinstance(raw_period_id, str) and raw_period_id:
        period = lookup.period(raw_period_id)

    period_id = validation.get_id(data, "period_id")
    territory_code = validation.get_territory(
        data, "territory_code", allow_world=False)
    subscription_tier = validation.get_enum(
        data, "subscription_tier", SUBSCRIPTION_TIERS)
    subscriber_count = validation.get_int(data, "subscriber_count", minimum=0)
    gross_revenue_cents = validation.get_int(data, "gross_revenue_cents", minimum=0)

    if period is None:
        period = lookup.period(period_id)

    for existing in db.pools.values():
        if existing["period_id"] == period["id"] \
                and existing["territory_code"] == territory_code \
                and existing["subscription_tier"] == subscription_tier:
            raise ApiError("ERR_DUPLICATE_POOL")

    record = {
        "period_id": period["id"],
        "territory_code": territory_code,
        "subscription_tier": subscription_tier,
        "subscriber_count": subscriber_count,
        "gross_revenue_cents": gross_revenue_cents,
        "applied_rate_schedule_id": None,
        "revenue_share_pool_cents": 0,
        "minimum_pool_cents": 0,
        "statutory_floor_cents": 0,
        "total_play_count": 0,
        "denominator_basis": None,
        "denominator_play_count": 0,
        "distributable_cents": 0,
        "allocation_basis": None,
        "rounding_residual_cents": 0,
        "residual_payee_holder_id": None,
        "status": "DRAFT",
    }
    stamp_new(record)
    db.pools[record["id"]] = record
    return created_response(serializers.royalty_pool(record))


@bp.get("/pools/<pool_id>")
@require()
def read_pool(pool_id):
    pool = lookup.pool(pool_id)
    return object_response(serializers.royalty_pool(pool))


@bp.get("/pools")
@require()
def list_pools():
    records = lookup.apply_filters(db.pools.values(), {
        "period_id": lookup.field("period_id"),
        "applied_rate_schedule_id": lookup.field("applied_rate_schedule_id"),
        "residual_payee_holder_id": lookup.field("residual_payee_holder_id"),
        "status": lookup.field("status"),
        "territory_code": lookup.field("territory_code"),
        "subscription_tier": lookup.field("subscription_tier"),
    })
    return paginate_and_serialize(records, serializers.royalty_pool)


@bp.post("/pools/<pool_id>/calculate")
@require(ROLE_ROYALTY_ADMIN)
def calculate_pool(pool_id):
    pool = lookup.pool(pool_id)

    if pool["status"] not in ("DRAFT", "CALCULATED", "REOPENED_FOR_ADJUSTMENT"):
        raise ApiError("ERR_INVALID_POOL_STATE")

    period = db.periods.get(pool["period_id"])
    if period is None:
        raise ApiError("ERR_PERIOD_NOT_FOUND")

    if pool["status"] == "REOPENED_FOR_ADJUSTMENT":
        allowed_period_states = ("REOPENED",)
    else:
        allowed_period_states = ("USAGE_SEALED", "REOPENED")
    if period["status"] not in allowed_period_states:
        raise ApiError("ERR_INVALID_PERIOD_STATE")

    schedule = pool_service.select_rate_schedule(pool, period)
    if schedule is None:
        raise ApiError("ERR_NO_EFFECTIVE_RATE_SCHEDULE")

    pool_service.calculate_pool(pool, period, schedule)
    return object_response(serializers.royalty_pool(pool))


@bp.post("/pools/<pool_id>/finalize")
@require(ROLE_ROYALTY_ADMIN)
def finalize_pool(pool_id):
    pool = lookup.pool(pool_id)

    if pool["status"] != "CALCULATED":
        raise ApiError("ERR_INVALID_POOL_STATE")

    period = db.periods.get(pool["period_id"])
    if period is None:
        raise ApiError("ERR_PERIOD_NOT_FOUND")

    pool["residual_payee_holder_id"] = pool_service.select_residual_payee(pool, period)
    pool["status"] = "FINALIZED"
    touch(pool)

    cascades.period_bubble_distributed(period)
    return object_response(serializers.royalty_pool(pool))
