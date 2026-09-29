"""Five-step booking price waterfall (PRD 3.5)."""

from db import db
from util import apply_bps, floor_div_minutes, minutes_between

TIER_BPS = {"VALUE": 9000, "STANDARD": 10000, "PREMIUM": 11500, "SIGNATURE": 13000}
ONBOARD_ADJ_BPS = 800
PRECRUISE_ADJ_BPS = -500
PRECRUISE_EARLY_DAYS = 7
LOYALTY_BPS = {"NONE": 0, "SILVER": 250, "GOLD": 500, "PLATINUM": 800}
GROUP_LARGE_BPS = 1000
GROUP_SMALL_BPS = 500
MAX_DISCOUNT_BPS = 1200
SERVICE_FEE_BPS = 300
SERVICE_FEE_CAP_CENTS = 1500


def loyalty_bps(loyalty_tier):
    return LOYALTY_BPS.get(loyalty_tier or "NONE", 0)


def group_bps(party_size):
    if party_size >= 6:
        return GROUP_LARGE_BPS
    if party_size >= 4:
        return GROUP_SMALL_BPS
    return 0


def blended_discount_bps(loyalty_component, group_component):
    larger = max(loyalty_component, group_component)
    smaller = min(loyalty_component, group_component)
    return min(MAX_DISCOUNT_BPS, larger + smaller // 2)


def channel_adjustment_bps(channel, departure):
    if channel == "ONBOARD":
        return ONBOARD_ADJ_BPS
    minutes = minutes_between(db.now(), departure["meeting_time_utc"])
    days_to_meeting = floor_div_minutes(minutes, 1440)
    if days_to_meeting >= PRECRUISE_EARLY_DAYS:
        return PRECRUISE_ADJ_BPS
    return 0


def quote(excursion, guest, departure, channel, party_size):
    """Return the four frozen money figures for a new booking."""
    list_price = apply_bps(excursion["base_price_cents"], TIER_BPS[excursion["price_tier"]])
    channel_price = apply_bps(list_price, 10000 + channel_adjustment_bps(channel, departure))
    discount_bps = blended_discount_bps(loyalty_bps(guest.get("loyalty_tier")), group_bps(party_size))
    per_guest = apply_bps(channel_price, 10000 - discount_bps)
    quoted_total = per_guest * party_size
    service_fee = min(SERVICE_FEE_CAP_CENTS, apply_bps(quoted_total, SERVICE_FEE_BPS))
    return {
        "per_guest_price_cents": per_guest,
        "quoted_total_cents": quoted_total,
        "service_fee_cents": service_fee,
        "charge_total_cents": quoted_total + service_fee,
    }
