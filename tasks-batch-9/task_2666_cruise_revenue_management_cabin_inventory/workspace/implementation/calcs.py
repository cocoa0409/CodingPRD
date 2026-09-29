"""The twelve declared calculations, as pure functions over plain values.

  1  booking_fare_buildup          fare_buildup()
  2  booking_onboard_projection    onboard_projection()
  3  sailing_ralbd                 ralbd()
  4  cancellation_settlement       penalty_pct() / penalty_cents()
  5  oversell_availability         availability()
  6  group_attrition_release       attrition_release()
  7  upgrade_bid_floor             bid_floor()
  8  sailing_occupancy_posture     occupancy_pct() / posture() / final_payment_risk()
  9  guest_loyalty_tier            loyalty()
 10  waitlist_promotion_selector   waitlist_order()
 11  itinerary_compensation        compensation_terms() / refund_grant()
 12  upgrade_chain_depth           chain_length()
"""

import math
from decimal import Decimal

from store import dec, rhu2, rhu_int

# --------------------------------------------------------------------------
# Constants, verbatim from the calculation and validation tables.
# --------------------------------------------------------------------------
SINGLE_SUPPLEMENT_MULT = Decimal("1.75")
BERTH_TIER_1_FLOOR_CENTS = 250000
BERTH_TIER_1_PCT = Decimal("0.10")
BERTH_TIER_2_FLOOR_CENTS = 400000
BERTH_TIER_2_PCT = Decimal("0.20")
BERTH_TIER_3_FLOOR_CENTS = 600000
BERTH_TIER_3_PCT = Decimal("0.30")
DEPOSIT_PCT = Decimal("0.20")
DEPOSIT_MIN_PER_GUEST_CENTS = 25000

RALBD_ALERT_FLOOR_CENTS = 20000

PENALTY_FREE_DAYS = 120
PENALTY_T1_DAYS = 90
PENALTY_T1_PCT = Decimal("0.25")
PENALTY_T2_DAYS = 60
PENALTY_T2_PCT = Decimal("0.50")
PENALTY_T3_DAYS = 30
PENALTY_T3_PCT = Decimal("0.75")
DELINQUENCY_GRACE_DAYS = 7

OVERSELL_PCT_CAP = Decimal("0.10")

ATTRITION_RETAIN_PCT = Decimal("0.5")
REVIEW_EXTENSION_DAYS = 14

BID_FLOOR_PCT = Decimal("0.40")
BID_WINDOW_MIN_DAYS = 3
BID_WINDOW_MAX_DAYS = 60

POSTURE_RESTRICTED_PCT = Decimal("90.00")
POSTURE_FROZEN_PCT = Decimal("100.00")

MEMBER_FLOOR = 1
MEMBER_PCT = 0.00
GOLD_FLOOR = 3
GOLD_PCT = 0.03
PLATINUM_FLOOR = 6
PLATINUM_PCT = 0.05

OBC_LOW_PER_GUEST_CENTS = 2500
OBC_HIGH_PER_GUEST_CENTS = 5000
REFUND_PCT_PORT = Decimal("0.05")
REFUND_PCT_SHORTENED = Decimal("0.10")

PROMO_CADENCE_GAP_DAYS = 7
MAX_SALES_SUSPENSIONS = 2
MAX_COUNTER_ROUNDS = 2
MAX_REVIEW_EXTENSIONS = 2

ACTIVE_BOOKING_STATUSES = ("OPTION", "CONFIRMED", "SAILED")
FENCING_BLOCK_STATUSES = ("TENTATIVE", "DEFINITE", "PARTIALLY_RELEASED")


# --------------------------------------------------------------------------
# 5 of 12 - oversell_availability
# --------------------------------------------------------------------------
def allowance_cap(physical_cabins):
    """ceil(physical_cabins * OVERSELL_PCT_CAP) - the ceiling is taken BEFORE the min."""
    return int(math.ceil(dec(physical_cabins) * OVERSELL_PCT_CAP))


def effective_oversell(physical_cabins, oversell_allowance, is_guarantee):
    if not is_guarantee:
        return 0
    return max(0, min(oversell_allowance, allowance_cap(physical_cabins)))


def availability(physical_cabins, effective_oversell_cabins, booked_cabins,
                 group_held_cabins):
    sellable = physical_cabins + effective_oversell_cabins
    return max(0, sellable - booked_cabins - group_held_cabins)


# --------------------------------------------------------------------------
# 1 of 12 - booking_fare_buildup
# --------------------------------------------------------------------------
def berth_discount_pct(lower_berth_subtotal_cents):
    """Chosen from the lower-berth subtotal ALONE, highest tier first."""
    if lower_berth_subtotal_cents >= BERTH_TIER_3_FLOOR_CENTS:
        return BERTH_TIER_3_PCT
    if lower_berth_subtotal_cents >= BERTH_TIER_2_FLOOR_CENTS:
        return BERTH_TIER_2_PCT
    if lower_berth_subtotal_cents >= BERTH_TIER_1_FLOOR_CENTS:
        return BERTH_TIER_1_PCT
    return Decimal("0.00")


def fare_buildup(rule, occupancy_adults, third_berth_guests, fourth_berth_guests,
                 discount_pct, repeat_guest_offer_pct):
    """Steps 3 to 11 of the pinned buildup. Returns a dict of money fields."""
    base = rule["base_lower_berth_fare_cents"]

    # Step 3: lower-berth subtotal.
    if occupancy_adults == 2:
        lower_subtotal = base * 2
    else:
        lower_subtotal = rhu_int(dec(base) * SINGLE_SUPPLEMENT_MULT)

    # Step 4: berth discount tier, keyed on the lower-berth subtotal alone.
    berth_pct = berth_discount_pct(lower_subtotal)

    # Step 5: upper-berth net fares (the berth discount touches upper berths only).
    keep = Decimal("1") - berth_pct
    third_net = rhu_int(dec(rule["third_berth_fare_cents"]) * keep) * third_berth_guests
    fourth_net = rhu_int(dec(rule["fourth_berth_fare_cents"]) * keep) * fourth_berth_guests

    # Step 6: gross ticket.
    gross = lower_subtotal + third_net + fourth_net

    # Step 7: promotional discount, rounded per component then summed.
    promo_pct = dec(discount_pct) if discount_pct else Decimal("0")
    promo_lower = rhu_int(dec(lower_subtotal) * promo_pct)
    promo_third = rhu_int(dec(third_net) * promo_pct)
    promo_fourth = rhu_int(dec(fourth_net) * promo_pct)
    promo_discount = promo_lower + promo_third + promo_fourth

    # Step 8: post-promotion components.
    post_lower = lower_subtotal - promo_lower
    post_third = third_net - promo_third
    post_fourth = fourth_net - promo_fourth

    # Step 9: loyalty discount, rounded per post-promotion component then summed.
    loyalty_pct = dec(repeat_guest_offer_pct) if repeat_guest_offer_pct else Decimal("0")
    loyalty_discount = (
        rhu_int(dec(post_lower) * loyalty_pct)
        + rhu_int(dec(post_third) * loyalty_pct)
        + rhu_int(dec(post_fourth) * loyalty_pct)
    )

    # Step 10: net ticket.
    net = gross - promo_discount - loyalty_discount

    guest_count = occupancy_adults + third_berth_guests + fourth_berth_guests

    # Step 11: deposit.
    deposit = max(
        DEPOSIT_MIN_PER_GUEST_CENTS * guest_count,
        rhu_int(dec(net) * DEPOSIT_PCT),
    )

    return {
        "lower_berth_subtotal_cents": lower_subtotal,
        "berth_discount_pct": float(berth_pct),
        "third_berth_net_cents": third_net,
        "fourth_berth_net_cents": fourth_net,
        "gross_ticket_cents": gross,
        "promo_discount_cents": promo_discount,
        "loyalty_discount_cents": loyalty_discount,
        "net_ticket_cents": net,
        "deposit_due_cents": deposit,
        "guest_count": guest_count,
    }


def fare_window_contains(rule, days_to_sail):
    """The half-open window [window_close_days_to_sail, window_open_days_to_sail)."""
    return (rule["window_close_days_to_sail"] <= days_to_sail
            < rule["window_open_days_to_sail"])


# --------------------------------------------------------------------------
# 2 of 12 - booking_onboard_projection
# --------------------------------------------------------------------------
def onboard_projection(nights, category, occupancy_adults, third_berth_guests,
                       fourth_berth_guests, obc_cents):
    upper_guests = third_berth_guests + fourth_berth_guests
    gross = nights * (
        occupancy_adults * category["onboard_spend_lower_per_night_cents"]
        + upper_guests * category["onboard_spend_upper_per_night_cents"]
    )
    return gross, max(0, gross - obc_cents)


# --------------------------------------------------------------------------
# 3 of 12 - sailing_ralbd
# --------------------------------------------------------------------------
def ralbd(total_revenue_cents, available_lower_berth_days):
    if available_lower_berth_days <= 0:
        return 0
    return rhu_int(dec(total_revenue_cents) / dec(available_lower_berth_days))


def revenue_alert(ralbd_net_cents):
    return ralbd_net_cents < RALBD_ALERT_FLOOR_CENTS


# --------------------------------------------------------------------------
# 4 of 12 - cancellation_settlement
# --------------------------------------------------------------------------
def penalty_pct(days_to_sail):
    if days_to_sail >= PENALTY_FREE_DAYS:
        return Decimal("0.00")
    if days_to_sail >= PENALTY_T1_DAYS:
        return PENALTY_T1_PCT
    if days_to_sail >= PENALTY_T2_DAYS:
        return PENALTY_T2_PCT
    if days_to_sail >= PENALTY_T3_DAYS:
        return PENALTY_T3_PCT
    return Decimal("1.00")


def penalty_cents(net_ticket_cents, upgrade_charge_cents, days_to_sail):
    base = net_ticket_cents + upgrade_charge_cents
    return rhu_int(dec(base) * penalty_pct(days_to_sail))


# --------------------------------------------------------------------------
# 6 of 12 - group_attrition_release
# --------------------------------------------------------------------------
def attrition_release(cabins_held, picked_up_cabins, release_policy):
    unpicked = max(0, cabins_held - picked_up_cabins)
    if release_policy == "FULL_RELEASE":
        return unpicked
    return int(math.floor(dec(unpicked) * ATTRITION_RETAIN_PCT))


# --------------------------------------------------------------------------
# 7 of 12 - upgrade_bid_floor
# --------------------------------------------------------------------------
def bid_floor(source_rule, target_rule, source_category, target_category, nights,
              guest_count):
    fare_gap = max(0, target_rule["base_lower_berth_fare_cents"]
                   - source_rule["base_lower_berth_fare_cents"])
    uplift = nights * guest_count * max(
        0,
        target_category["onboard_spend_upper_per_night_cents"]
        - source_category["onboard_spend_upper_per_night_cents"],
    )
    gap_share = rhu_int(dec(fare_gap) * BID_FLOOR_PCT)
    per_guest_uplift = rhu_int(dec(uplift) / dec(guest_count))
    return max(0, gap_share - per_guest_uplift)


def bid_window_open(days_to_sail):
    return BID_WINDOW_MIN_DAYS <= days_to_sail <= BID_WINDOW_MAX_DAYS


# --------------------------------------------------------------------------
# 8 of 12 - sailing_occupancy_posture
# --------------------------------------------------------------------------
def occupancy_pct(lower_berths_sold, total_lower_berths):
    if total_lower_berths <= 0:
        return 0.0
    return rhu2(dec(lower_berths_sold) / dec(total_lower_berths) * Decimal("100"))


def posture(occupancy_pct_value):
    value = dec(occupancy_pct_value)
    if value >= POSTURE_FROZEN_PCT:
        return "FROZEN"
    if value >= POSTURE_RESTRICTED_PCT:
        return "RESTRICTED"
    return "OPEN"


def final_payment_risk(confirmed_bookings_count, paid_in_full_bookings_count):
    return (confirmed_bookings_count > 0
            and paid_in_full_bookings_count * 2 < confirmed_bookings_count)


# --------------------------------------------------------------------------
# 9 of 12 - guest_loyalty_tier
# --------------------------------------------------------------------------
def loyalty(prior_sailings_count):
    if prior_sailings_count >= PLATINUM_FLOOR:
        return "PLATINUM", PLATINUM_PCT
    if prior_sailings_count >= GOLD_FLOOR:
        return "GOLD", GOLD_PCT
    if prior_sailings_count >= MEMBER_FLOOR:
        return "MEMBER", MEMBER_PCT
    return "NONE", 0.00


# --------------------------------------------------------------------------
# 10 of 12 - waitlist_promotion_selector
# --------------------------------------------------------------------------
def waitlist_order(bookings):
    """created_at ASC, then net_ticket_cents DESC, then third_berth_guests DESC."""
    return sorted(
        bookings,
        key=lambda b: (b["created_at"], -b["net_ticket_cents"], -b["third_berth_guests"]),
    )


# --------------------------------------------------------------------------
# 11 of 12 - itinerary_compensation
# --------------------------------------------------------------------------
def compensation_terms(kind, compensation_policy):
    if compensation_policy == "OBC_PLUS_REFUND_PCT":
        obc = OBC_HIGH_PER_GUEST_CENTS
    else:
        obc = OBC_LOW_PER_GUEST_CENTS
    if compensation_policy == "OBC_ONLY":
        pct = Decimal("0.00")
    elif kind == "ITINERARY_SHORTENED":
        pct = REFUND_PCT_SHORTENED
    else:
        pct = REFUND_PCT_PORT
    return obc, float(pct)


def refund_grant(net_ticket_cents, refund_pct):
    return rhu_int(dec(net_ticket_cents) * dec(refund_pct))


# --------------------------------------------------------------------------
# 12 of 12 - upgrade_chain_depth
# --------------------------------------------------------------------------
def chain_length(target_category):
    if target_category is None:
        return 0
    return 1 + target_category["upgrade_chain_length"]
