"""UsageBatch and UsageLine endpoints (§3.2, §3.3)."""

from flask import Blueprint

import lookup
import serializers
import validation
from constants import (
    API_PREFIX,
    ROLE_REGULATORY_OFFICER,
    ROLE_RIGHTS_OPS_ANALYST,
    ROLE_ROYALTY_ADMIN,
    SUBSCRIPTION_TIERS,
)
from db import db, stamp_new, touch
from errors import ApiError
from middleware import current_user_id, require
from response import created_response, object_response, paginate_and_serialize
from services import cascades, derive, matching

bp = Blueprint("usage", __name__, url_prefix=API_PREFIX)

READ_ROLES = (ROLE_ROYALTY_ADMIN, ROLE_RIGHTS_OPS_ANALYST, ROLE_REGULATORY_OFFICER)


# --------------------------------------------------------------------------
# UsageBatch
# --------------------------------------------------------------------------

@bp.post("/usage-batches")
@require(ROLE_RIGHTS_OPS_ANALYST, ROLE_ROYALTY_ADMIN)
def create_batch():
    data = validation.body()

    period_id = data.get("period_id")
    if isinstance(period_id, str) and period_id:
        period = lookup.period(period_id)
    else:
        period = None

    period_id = validation.get_id(data, "period_id")
    source_label = validation.get_string(data, "source_label", max_len=120)
    if period is None:
        period = lookup.period(period_id)

    if period["status"] != "OPEN":
        raise ApiError("ERR_INVALID_PERIOD_STATE")

    record = {
        "period_id": period["id"],
        "source_label": source_label,
        "status": "OPEN",
    }
    stamp_new(record)
    db.batches[record["id"]] = record
    return created_response(serializers.usage_batch(record))


@bp.get("/usage-batches/<batch_id>")
@require(*READ_ROLES)
def read_batch(batch_id):
    batch = lookup.batch(batch_id)
    return object_response(serializers.usage_batch(batch))


@bp.get("/usage-batches")
@require(*READ_ROLES)
def list_batches():
    records = lookup.apply_filters(db.batches.values(), {
        "period_id": lookup.field("period_id"),
        "status": lookup.field("status"),
    })
    return paginate_and_serialize(records, serializers.usage_batch)


@bp.post("/usage-batches/<batch_id>/lines")
@require(ROLE_RIGHTS_OPS_ANALYST)
def append_line(batch_id):
    batch = lookup.batch(batch_id)
    data = validation.body()

    reported_title = validation.get_string(data, "reported_title", max_len=300)
    reported_isrc = validation.get_string(
        data, "reported_isrc", required=False, default=None, nullable=True, max_len=32)
    reported_artist = validation.get_string(
        data, "reported_artist", required=False, default=None, nullable=True)
    territory_code = validation.get_territory(
        data, "territory_code", allow_world=False)
    subscription_tier = validation.get_enum(
        data, "subscription_tier", SUBSCRIPTION_TIERS)
    play_count = validation.get_int(data, "play_count")

    if batch["status"] != "OPEN":
        raise ApiError("ERR_INVALID_USAGE_BATCH_STATE")

    if play_count < 1:
        raise ApiError("ERR_ZERO_PLAY_COUNT")

    record = {
        "batch_id": batch["id"],
        "work_id": None,
        "reported_isrc": reported_isrc,
        "reported_title": reported_title,
        "reported_artist": reported_artist,
        "territory_code": territory_code,
        "subscription_tier": subscription_tier,
        "play_count": play_count,
        "match_status": "UNMATCHED",
        "match_confidence_bps": 0,
        "attributed_revenue_cents": 0,
    }
    stamp_new(record)
    db.usage_lines[record["id"]] = record
    touch(batch)
    return created_response(serializers.usage_line(record))


@bp.post("/usage-batches/<batch_id>/seal")
@require(ROLE_RIGHTS_OPS_ANALYST)
def seal_batch(batch_id):
    batch = lookup.batch(batch_id)
    if batch["status"] != "OPEN":
        raise ApiError("ERR_INVALID_USAGE_BATCH_STATE")
    if derive.batch_line_count(batch["id"]) < 1:
        raise ApiError("ERR_EMPTY_USAGE_BATCH")
    batch["status"] = "SEALED"
    touch(batch)
    return object_response(serializers.usage_batch(batch))


@bp.post("/usage-batches/<batch_id>/match")
@require(ROLE_RIGHTS_OPS_ANALYST)
def match_batch(batch_id):
    batch = lookup.batch(batch_id)
    if batch["status"] != "SEALED":
        raise ApiError("ERR_INVALID_USAGE_BATCH_STATE")
    matching.run_batch_match(batch, current_user_id())
    cascades.period_bubble_usage_sealed(db.periods.get(batch["period_id"]))
    return object_response(serializers.usage_batch(batch))


# --------------------------------------------------------------------------
# UsageLine
# --------------------------------------------------------------------------

@bp.get("/usage-lines/<line_id>")
@require(*READ_ROLES)
def read_line(line_id):
    line = lookup.usage_line(line_id)
    return object_response(serializers.usage_line(line))


@bp.get("/usage-lines")
@require(*READ_ROLES)
def list_lines():
    records = lookup.apply_filters(db.usage_lines.values(), {
        "batch_id": lookup.field("batch_id"),
        "work_id": lookup.field("work_id"),
        "match_status": lookup.field("match_status"),
        "territory_code": lookup.field("territory_code"),
        "subscription_tier": lookup.field("subscription_tier"),
    })
    return paginate_and_serialize(records, serializers.usage_line)
