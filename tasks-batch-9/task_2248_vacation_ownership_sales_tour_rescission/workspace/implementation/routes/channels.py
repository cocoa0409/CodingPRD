"""Tour generation channels (PRD 3.1)."""

from flask import Blueprint

import auth
import calc
import derive
import errors
import validators
from envelope import created, listing, ok
from errors import fail
from helpers import get_channel
from store import db

bp = Blueprint("channels", __name__)


@bp.post("/tour-channels")
def create_channel():
    auth.require(auth.MARKETING_MANAGER)
    data = validators.body()
    name = validators.string(data, "name", 1, 120)
    channel_code = validators.enum(data, "channel_code", calc.CHANNEL_CODES)
    gift = validators.integer(data, "incentive_gift_value_cents", 0, 100000)
    min_age = validators.integer(data, "min_age", 18, 99)
    min_income = validators.integer(data, "min_household_income_cents", 0)
    min_score = validators.integer(data, "min_qualification_score", 0, 100)
    requires_married = validators.boolean(
        data, "requires_married_household", required=False, default=False
    )

    for existing in db.channels.values():
        if existing["channel_code"] == channel_code:
            fail(errors.ERR_CHANNEL_CODE_TAKEN, "channel_code %s is taken" % channel_code)

    now = db.now()
    channel = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "name": name,
        "channel_code": channel_code,
        "incentive_gift_value_cents": gift,
        "min_age": min_age,
        "min_household_income_cents": min_income,
        "requires_married_household": requires_married,
        "min_qualification_score": min_score,
        "status": "ACTIVE",
        "booked_count": 0,
        "toured_count": 0,
        "no_show_count": 0,
        "historical_no_show_rate": calc.rate4(0, 0),
        "gift_liability_cents": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.channels[channel["id"]] = channel
    return created(channel)


@bp.post("/tour-channels/<channel_id>/reinstate")
def reinstate_channel(channel_id):
    auth.require(auth.MARKETING_MANAGER)
    channel = get_channel(channel_id)
    derive.setf(channel, "status", "ACTIVE")
    derive.setf(channel, "toured_count", 0)
    derive.setf(channel, "no_show_count", 0)
    derive.recompute_channel_rate(channel)
    return ok(channel)


@bp.get("/tour-channels/<channel_id>")
def read_channel(channel_id):
    auth.require_any()
    return ok(get_channel(channel_id))


@bp.get("/tour-channels/<channel_id>/no-show-summary")
def channel_no_show_summary(channel_id):
    auth.require(
        auth.MARKETING_MANAGER,
        auth.GALLERY_MANAGER,
        auth.COMPLIANCE_OFFICER,
        auth.PLATFORM_ADMIN,
    )
    channel = get_channel(channel_id)
    denominator = calc.channel_no_show_denominator(channel)
    rate = channel["historical_no_show_rate"]
    return ok(
        {
            "channel_id": channel["id"],
            "status": channel["status"],
            "booked_count": channel["booked_count"],
            "toured_count": channel["toured_count"],
            "no_show_count": channel["no_show_count"],
            "denominator": denominator,
            "historical_no_show_rate": rate,
            "gift_liability_cents": channel["gift_liability_cents"],
            "suspend_threshold_met": (
                channel["booked_count"] >= calc.NO_SHOW_MIN_SAMPLE
                and calc.to_decimal_rate(rate) >= calc.NO_SHOW_SUSPEND_THRESHOLD
            ),
        }
    )
