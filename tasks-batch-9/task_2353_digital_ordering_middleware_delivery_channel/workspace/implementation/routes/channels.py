"""Channel registry and configuration."""
from flask import Blueprint

import db
import errors
import middleware as M
import response
import validation
from errors import fail
from routes import common
from services import constants as K
from services import serializers

bp = Blueprint("channels", __name__)


@bp.post("/channels")
@M.endpoint(M.PLATFORM_ADMIN)
def create_channel():
    payload = validation.body()
    code = validation.req_str(payload, "code")
    name = validation.req_str(payload, "name")
    channel_type = validation.req_enum(payload, "channel_type", K.CHANNEL_TYPES)
    markup_bps = validation.req_int(payload, "markup_bps", 0, 5000)
    rounding_mode = validation.req_enum(payload, "rounding_mode", K.ROUNDING_MODES)
    service_fee = validation.req_int(payload, "service_fee_cents", 0)
    commission_bps = validation.req_int(payload, "commission_bps", 0, 5000)
    settlement_mode = validation.req_enum(payload, "settlement_mode", K.SETTLEMENT_MODES)
    eighty_six_policy = validation.req_enum(payload, "eighty_six_policy",
                                            K.EIGHTY_SIX_POLICIES)
    throttle_policy = validation.req_enum(payload, "throttle_policy", K.THROTTLE_POLICIES)
    review_mode = validation.req_enum(payload, "adjustment_review_mode",
                                      K.ADJUSTMENT_REVIEW_MODES)
    accepts_delivery = validation.opt_bool(payload, "accepts_delivery", True)

    if any(c["code"] == code for c in db.channels.values()):
        fail(errors.ERR_DUPLICATE_CHANNEL_CODE)

    channel = db.record()
    channel.update({
        "code": code,
        "name": name,
        "channel_type": channel_type,
        "markup_bps": markup_bps,
        "rounding_mode": rounding_mode,
        "service_fee_cents": service_fee,
        "commission_bps": commission_bps,
        "settlement_mode": settlement_mode,
        "eighty_six_policy": eighty_six_policy,
        "throttle_policy": throttle_policy,
        "adjustment_review_mode": review_mode,
        "accepts_delivery": accepts_delivery,
        "listing_count": 0,
    })
    db.channels[channel["id"]] = channel
    return response.object_response(serializers.channel(channel), 201)


@bp.get("/channels/<channel_id>")
@M.endpoint(M.PLATFORM_ADMIN, M.STORE_OPERATOR, M.CHANNEL_PARTNER, M.SETTLEMENT_ANALYST)
def read_channel(channel_id):
    channel = common.get_channel(channel_id)
    M.require_channel_scope(channel_id)
    return response.object_response(serializers.channel(channel))


@bp.patch("/channels/<channel_id>")
@M.endpoint(M.CHANNEL_PARTNER, M.PLATFORM_ADMIN)
def update_channel(channel_id):
    payload = validation.body()
    expected = validation.req_int(payload, "expected_channel_version")
    markup_bps = validation.opt_int(payload, "markup_bps", 0, 5000)
    rounding_mode = validation.opt_enum(payload, "rounding_mode", K.ROUNDING_MODES)
    service_fee = validation.opt_int(payload, "service_fee_cents", 0)
    commission_bps = validation.opt_int(payload, "commission_bps", 0, 5000)
    settlement_mode = validation.opt_enum(payload, "settlement_mode", K.SETTLEMENT_MODES)
    eighty_six_policy = validation.opt_enum(payload, "eighty_six_policy",
                                            K.EIGHTY_SIX_POLICIES)
    throttle_policy = validation.opt_enum(payload, "throttle_policy", K.THROTTLE_POLICIES)
    review_mode = validation.opt_enum(payload, "adjustment_review_mode",
                                      K.ADJUSTMENT_REVIEW_MODES)
    accepts_delivery = validation.opt_bool(payload, "accepts_delivery")

    channel = common.get_channel(channel_id)
    M.require_channel_scope(channel_id)
    if expected != channel["version"]:
        fail(errors.ERR_STALE_CHANNEL_VERSION)

    for field, value in (
        ("markup_bps", markup_bps),
        ("rounding_mode", rounding_mode),
        ("service_fee_cents", service_fee),
        ("commission_bps", commission_bps),
        ("settlement_mode", settlement_mode),
        ("eighty_six_policy", eighty_six_policy),
        ("throttle_policy", throttle_policy),
        ("adjustment_review_mode", review_mode),
        ("accepts_delivery", accepts_delivery),
    ):
        if value is not None:
            channel[field] = value
    # A configuration write reprices nothing that already exists.
    db.touch(channel)
    return response.object_response(serializers.channel(channel))
