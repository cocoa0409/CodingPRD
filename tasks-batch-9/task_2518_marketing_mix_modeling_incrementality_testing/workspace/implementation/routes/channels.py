"""Media channels (PRD section 3.1)."""

from flask import Blueprint, request

import db as store
from db import base_row, db, touch
from errors import ApiError
from lookup import must, must_field
from middleware import DATA_ENGINEER, READ_ROLES, authenticate
from response import created, listing, ok
from services import ordering
from validation import field_decimal, field_enum, field_int, field_string, get_body, invalid

bp = Blueprint("channels", __name__)

CODE_PATTERN = r"^[A-Z][A-Z0-9_]{2,31}$"
CHANNEL_TYPES = ("SEARCH", "SOCIAL", "VIDEO", "DISPLAY", "OOH", "TV", "RETAIL_MEDIA")
CHANNEL_STATUSES = ("ACTIVE", "PAUSED", "RETIRED")


@bp.post("/mmm/media-channels")
def create_channel():
    authenticate((DATA_ENGINEER,))
    body = get_body()
    channel_code = field_string(body, "channel_code", pattern=CODE_PATTERN)
    channel_type = field_enum(body, "channel_type", CHANNEL_TYPES)
    decay = field_decimal(body, "adstock_decay_rate", minimum=0, maximum="0.95", max_places=2)
    max_lag = field_int(body, "adstock_max_lag_periods", minimum=0, maximum=8)
    half_point = field_int(body, "saturation_half_point_cents", minimum=1)
    ceiling = field_int(body, "response_ceiling_units", minimum=0)
    min_spend = field_int(body, "min_spend_cents", minimum=0)
    max_spend = field_int(body, "max_spend_cents", minimum=0)
    status = field_enum(body, "status", CHANNEL_STATUSES, required=False, default="ACTIVE")
    market = must_field("markets", body, "market_id")

    if max_spend < min_spend:
        raise invalid("max_spend_cents must not be below min_spend_cents.")

    for existing in store.channels_of_market(market["id"]):
        if existing["channel_code"] == channel_code:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "channel_code '%s' is already used in this market." % channel_code)

    row = base_row("media_channels")
    row.update({
        "market_id": market["id"],
        "channel_code": channel_code,
        "channel_type": channel_type,
        "adstock_decay_rate": decay,
        "adstock_max_lag_periods": max_lag,
        "saturation_half_point_cents": half_point,
        "response_ceiling_units": ceiling,
        "min_spend_cents": min_spend,
        "max_spend_cents": max_spend,
        "status": status,
    })
    db.add("media_channels", row)
    return created(row)


@bp.get("/mmm/media-channels")
def list_channels():
    authenticate(READ_ROLES)
    rows = db.all("media_channels")
    market_id = request.args.get("market_id")
    if market_id:
        rows = [r for r in rows if r["market_id"] == market_id]
    channel_code = request.args.get("channel_code")
    if channel_code:
        rows = [r for r in rows if r["channel_code"] == channel_code]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return listing(ordering.sort_rows("media_channels", rows), request.args)


@bp.get("/mmm/media-channels/<channel_id>")
def get_channel(channel_id):
    authenticate(READ_ROLES)
    return ok(must("media_channels", channel_id))


@bp.patch("/mmm/media-channels/<channel_id>")
def patch_channel(channel_id):
    authenticate((DATA_ENGINEER,))
    channel = must("media_channels", channel_id)
    body = get_body()

    updates = {}
    if "status" in body and body["status"] is not None:
        updates["status"] = field_enum(body, "status", CHANNEL_STATUSES)
    if "adstock_decay_rate" in body and body["adstock_decay_rate"] is not None:
        updates["adstock_decay_rate"] = field_decimal(
            body, "adstock_decay_rate", minimum=0, maximum="0.95", max_places=2)
    if "adstock_max_lag_periods" in body and body["adstock_max_lag_periods"] is not None:
        updates["adstock_max_lag_periods"] = field_int(
            body, "adstock_max_lag_periods", minimum=0, maximum=8)
    if "saturation_half_point_cents" in body and body["saturation_half_point_cents"] is not None:
        updates["saturation_half_point_cents"] = field_int(
            body, "saturation_half_point_cents", minimum=1)
    if "response_ceiling_units" in body and body["response_ceiling_units"] is not None:
        updates["response_ceiling_units"] = field_int(body, "response_ceiling_units", minimum=0)
    if "min_spend_cents" in body and body["min_spend_cents"] is not None:
        updates["min_spend_cents"] = field_int(body, "min_spend_cents", minimum=0)
    if "max_spend_cents" in body and body["max_spend_cents"] is not None:
        updates["max_spend_cents"] = field_int(body, "max_spend_cents", minimum=0)

    resulting_min = updates.get("min_spend_cents", channel["min_spend_cents"])
    resulting_max = updates.get("max_spend_cents", channel["max_spend_cents"])
    if resulting_max < resulting_min:
        raise invalid("max_spend_cents must not be below min_spend_cents.")

    # A revision is never retroactive: already-fitted runs keep their figures.
    channel.update(updates)
    touch(channel)
    return ok(channel)
