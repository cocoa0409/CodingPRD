"""Every calculation rule of the housing program (PRD 2.7 and section 3).

All money is whole cents.  Money derived from a fraction rounds half up.  Room
nights derived from a fractional threshold round up.  Party shares of a
collected amount truncate toward zero with the remainder reassigned in full.
"""

import math
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

# --- constants (scaffold calculations[].constants) --------------------------
MAX_PLAYERS_PER_ROOM = 4
MAX_STAFF_PER_ROOM = 2
MAX_OCCUPANTS_PER_ROOM = 4
LOCAL_TEAM_RADIUS_MILES = 30
MAX_EXCEPTION_APPEALS = 1
BLOCK_RESTRICT_UTILIZATION = Decimal("0.90")
BLOCK_WINDOW_PAD_DAYS = 2

CANCEL_FREE_TIER_DAYS = 45
CANCEL_QUARTER_TIER_DAYS = 21
CANCEL_HALF_TIER_DAYS = 7
CANCEL_QUARTER_PCT = Decimal("0.25")
CANCEL_HALF_PCT = Decimal("0.50")

REBATE_TIER_1_MAX_NIGHTS = 30
REBATE_TIER_2_MAX_NIGHTS = 90
REBATE_TIER_1_RATE_CENTS = 500
REBATE_TIER_2_RATE_CENTS = 750
REBATE_TIER_3_RATE_CENTS = 1000

ADMIN_TIER_1_MAX_CENTS = 50000
ADMIN_TIER_2_MAX_CENTS = 200000
ADMIN_TIER_1_PCT = Decimal("0.08")
ADMIN_TIER_2_PCT = Decimal("0.06")
ADMIN_TIER_3_PCT = Decimal("0.045")

RATE_ADJUSTMENT_PCT = Decimal("0.10")

ONE = Decimal("1")


def dec(value):
    """Exact Decimal from an int / float / Decimal without binary noise."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_half_up_cents(value):
    return int(dec(value).quantize(ONE, rounding=ROUND_HALF_UP))


def ceil_int(value):
    return int(dec(value).quantize(ONE, rounding=ROUND_CEILING))


def floor_int(value):
    return int(dec(value).quantize(ONE, rounding=ROUND_FLOOR))


def ceil_div(numerator, denominator):
    return -((-numerator) // denominator)


def ratio_4dp(numerator, denominator):
    if denominator == 0:
        return Decimal("0.0000")
    return (dec(numerator) / dec(denominator)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )


# --- roster room requirements (PRD 3.3) ------------------------------------

def segregated_rooms(player_count, staff_count):
    player_rooms = ceil_div(player_count, MAX_PLAYERS_PER_ROOM)
    staff_rooms = ceil_div(staff_count, MAX_STAFF_PER_ROOM)
    return player_rooms + staff_rooms


def pooled_rooms(player_count, staff_count):
    return ceil_div(player_count + staff_count, MAX_PLAYERS_PER_ROOM)


# --- attrition floor of a block (PRD 3.2) ---------------------------------

def block_threshold_room_nights(block_size_rooms, nights, attrition_threshold_pct):
    return ceil_int(dec(block_size_rooms) * dec(nights) * dec(attrition_threshold_pct))


# --- cancellation penalty tiers (PRD 3.5) ---------------------------------

def penalty_days_out(check_in_midnight, logical_now):
    delta = (check_in_midnight - logical_now).total_seconds()
    return int(math.floor(delta / 86400.0))


def penalty_room_nights(projected_room_nights, days_out):
    if days_out >= CANCEL_FREE_TIER_DAYS:
        return 0
    if days_out >= CANCEL_QUARTER_TIER_DAYS:
        return ceil_int(dec(projected_room_nights) * CANCEL_QUARTER_PCT)
    if days_out >= CANCEL_HALF_TIER_DAYS:
        return ceil_int(dec(projected_room_nights) * CANCEL_HALF_PCT)
    return projected_room_nights


# --- rebate lines (PRD 3.7) -----------------------------------------------

def tiered_rate_cents(contract_total_nights):
    if contract_total_nights < REBATE_TIER_1_MAX_NIGHTS:
        return REBATE_TIER_1_RATE_CENTS
    if contract_total_nights < REBATE_TIER_2_MAX_NIGHTS:
        return REBATE_TIER_2_RATE_CENTS
    return REBATE_TIER_3_RATE_CENTS


def rebate_line_cents(contract, room_nights, contract_total_nights):
    model = contract["rebate_model"]
    if model == "PER_ROOM_NIGHT_FLAT":
        return room_nights * contract["rebate_flat_cents_per_room_night"]
    if model == "PERCENT_OF_ROOM_REVENUE":
        return round_half_up_cents(
            dec(room_nights)
            * dec(contract["negotiated_nightly_rate_cents"])
            * dec(contract["rebate_percent"])
        )
    return room_nights * tiered_rate_cents(contract_total_nights)


# --- revenue split waterfall (PRD 3.9) ------------------------------------

def admin_fee_pct(gross_collected_cents):
    if gross_collected_cents < ADMIN_TIER_1_MAX_CENTS:
        return ADMIN_TIER_1_PCT
    if gross_collected_cents < ADMIN_TIER_2_MAX_CENTS:
        return ADMIN_TIER_2_PCT
    return ADMIN_TIER_3_PCT


def revenue_split(gross_collected_cents, share_organizer, share_rights_holder, share_destination):
    pct = admin_fee_pct(gross_collected_cents)
    fee = round_half_up_cents(dec(gross_collected_cents) * pct)
    distributable = gross_collected_cents - fee
    organizer_base = floor_int(dec(distributable) * dec(share_organizer))
    rights_holder = floor_int(dec(distributable) * dec(share_rights_holder))
    destination = floor_int(dec(distributable) * dec(share_destination))
    remainder = distributable - organizer_base - rights_holder - destination
    return {
        "admin_fee_pct": float(pct),
        "admin_fee_cents": fee,
        "distributable_cents": distributable,
        "organizer_cents": organizer_base + remainder,
        "rights_holder_cents": rights_holder,
        "destination_cents": destination,
        "rounding_remainder_cents": remainder,
    }


# --- complaint remedy credit (PRD 3.9) ------------------------------------

def rate_adjustment_credit(projected_room_nights, nightly_rate_cents):
    return round_half_up_cents(
        dec(projected_room_nights) * dec(nightly_rate_cents) * RATE_ADJUSTMENT_PCT
    )
