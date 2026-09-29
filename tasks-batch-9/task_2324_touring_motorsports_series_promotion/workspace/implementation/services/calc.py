"""All fourteen calculation rules (PRD 2.5, 3.x)."""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db
from validate import parse_datetime

# --- domain constants (PRD 3.x) ------------------------------------------- #
HEAVY_RIG_WEIGHT_LBS = 9000
MAX_NEGOTIATION_ROUNDS = 3
MAX_TECH_ATTEMPTS = 3
MAX_BRANDING_SLOTS_PER_VEHICLE = 4
BOOKING_LEAD_TIME_DAYS = 45
RESET_GAP_MINUTES = 8
BUNDLE_DISCOUNT_PCT = Decimal("0.15")
SPONSOR_HOLDBACK_PCT = Decimal("0.50")
PURSE_PER_STAGED_ENTRY_CENTS = 150000
ALS_COST_CENTS = 45000
BLS_COST_CENTS = 28000
AMBULANCE_COST_CENTS = 120000
BARRIER_COST_CENTS_PER_FOOT = 350
STOP_MARKETING_CAP_PCT = Decimal("0.20")
CHANNEL_CAP_PCT = {
    "RADIO": Decimal("0.40"),
    "DIGITAL": Decimal("0.60"),
    "GRASSROOTS": Decimal("0.30"),
}
STAGING_WINDOW_OPEN_HOURS = 8
STAGING_WINDOW_CLOSE_HOURS = 2
HAUL_MILES_PER_HOUR = 50
HAUL_CREW_REST_HOURS = 10
HAUL_RISK_BLOCK_MILES = 500
HAUL_RISK_POINTS = 5
SCHEDULE_PENALTY_POINTS = 15
FAILED_ATTEMPT_PENALTY_POINTS = 25
CONDITIONAL_PENALTY_POINTS = 10


# --- rounding primitives -------------------------------------------------- #
def round_half_up_cents(value):
    """Round a Decimal to whole cents, half away from zero."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pct_of_cents(amount_cents, pct):
    return round_half_up_cents(Decimal(int(amount_cents)) * to_decimal(pct))


def to_decimal(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def margin_pct(numerator_cents, denominator_cents):
    if denominator_cents is None or denominator_cents <= 0:
        return 0.0
    quotient = (Decimal(int(numerator_cents)) / Decimal(int(denominator_cents))) * Decimal(100)
    return float(quotient.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def dt(raw):
    if raw is None:
        return None
    return parse_datetime(raw)


# --- ticket order amounts (frozen at creation) ---------------------------- #
def ticket_order_amounts(tier, stop, booking, qty, is_group, addon_qty):
    line_subtotal = tier["price_cents"] * qty
    if is_group and qty >= tier["group_min_qty"]:
        group_discount = pct_of_cents(line_subtotal, tier["group_discount_pct"])
    else:
        group_discount = 0
    addon_subtotal = stop["pit_party_price_cents"] * addon_qty
    if addon_qty > 0 and addon_qty == qty:
        addon_discount = pct_of_cents(addon_subtotal, BUNDLE_DISCOUNT_PCT)
    else:
        addon_discount = 0
    facility_fee = booking["per_ticket_facility_fee_cents"] * qty
    total = line_subtotal - group_discount + addon_subtotal - addon_discount + facility_fee
    return {
        "line_subtotal_cents": line_subtotal,
        "group_discount_cents": group_discount,
        "addon_subtotal_cents": addon_subtotal,
        "addon_discount_cents": addon_discount,
        "facility_fee_cents": facility_fee,
        "total_cents": total,
    }


# --- readiness scoring ---------------------------------------------------- #
def readiness_score(entry, stop, variant, last_inspection=None, failed_attempts=0):
    haul_risk = HAUL_RISK_POINTS * (entry["haul_distance_miles"] // HAUL_RISK_BLOCK_MILES)
    schedule_penalty = 0
    inspection_penalty = 0
    if variant == "PRE_STAGING":
        show_start = dt(stop["show_start_utc"])
        scheduled = dt(entry["scheduled_arrival_utc"])
        if show_start is not None and scheduled is not None:
            staging_close = show_start - timedelta(hours=STAGING_WINDOW_CLOSE_HOURS)
            if scheduled > staging_close:
                schedule_penalty = SCHEDULE_PENALTY_POINTS
    else:
        scheduled = dt(entry["scheduled_arrival_utc"])
        actual = dt(entry["actual_arrival_utc"])
        if scheduled is not None and actual is not None and actual > scheduled:
            schedule_penalty = SCHEDULE_PENALTY_POINTS
        inspection_penalty = FAILED_ATTEMPT_PENALTY_POINTS * failed_attempts
        if last_inspection is not None and last_inspection["result"] == "CONDITIONAL":
            inspection_penalty += CONDITIONAL_PENALTY_POINTS
    score = 100 - haul_risk - schedule_penalty - inspection_penalty
    return max(0, min(100, score))


# --- required safety provisioning ----------------------------------------- #
def required_safety_provisioning(attendance, live_entry_count, heavy_present, floor_type):
    required_als = 1 + (1 if attendance >= 6000 else 0) + (1 if live_entry_count >= 12 else 0)
    required_bls = max(2, int(math.ceil(attendance / 2500.0))) + (
        1 if floor_type == "CONCRETE" else 0
    )
    required_ambulance = max(1, int(math.ceil(live_entry_count / 10.0)))
    required_fence = 8 if heavy_present else 6
    required_lanes = 1 + (1 if attendance >= 6000 else 0)
    required_barrier = max(1200, 900 + 75 * live_entry_count)
    return {
        "required_als_staff_count": required_als,
        "required_bls_staff_count": required_bls,
        "required_ambulance_count": required_ambulance,
        "required_catch_fence_height_ft": required_fence,
        "required_emergency_access_lanes": required_lanes,
        "required_barrier_linear_feet": required_barrier,
    }


def safety_cost_cents(plan):
    return (
        plan["medical_als_staff_count"] * ALS_COST_CENTS
        + plan["medical_bls_staff_count"] * BLS_COST_CENTS
        + plan["ambulance_count"] * AMBULANCE_COST_CENTS
        + plan["barrier_linear_feet"] * BARRIER_COST_CENTS_PER_FOOT
    )


# --- run order timeline --------------------------------------------------- #
def run_order_timeline(segments):
    """Walk segments in ascending position; returns (assignments, end_offset)."""
    assignments = {}
    offset = 0
    previous_type = None
    for segment in sorted(segments, key=lambda s: s["run_order_position"]):
        if previous_type == "COMPETITION" and segment["segment_type"] == "COMPETITION":
            reset_gap = RESET_GAP_MINUTES
        else:
            reset_gap = 0
        offset += reset_gap
        start_offset = offset
        end_offset = offset + segment["duration_minutes"]
        offset = end_offset
        previous_type = segment["segment_type"]
        assignments[segment["id"]] = {
            "reset_gap_minutes": reset_gap,
            "start_offset_minutes": start_offset,
            "end_offset_minutes": end_offset,
        }
    return assignments, offset


# --- venue occupancy ------------------------------------------------------ #
def occupancy_conflict(venue, candidate_start, candidate_end, other_bookings):
    pad = timedelta(hours=venue["turnaround_hours"])
    for other in other_bookings:
        blocked_start = dt(other["load_in_start_utc"]) - pad
        blocked_end = dt(other["tear_down_end_utc"]) + pad
        if candidate_start <= blocked_end and blocked_start <= candidate_end:
            return True
    return False


# --- market rotation cooldown --------------------------------------------- #
def rotation_conflict(season, candidate_date, other_dates):
    cooldown = season["market_rotation_cooldown_days"]
    for other_date in other_dates:
        gap_days = abs((candidate_date - other_date).days)
        if gap_days < cooldown:
            return True
    return False


# --- haul buffer ---------------------------------------------------------- #
def required_haul_hours(haul_distance_miles):
    return (
        int(math.ceil(haul_distance_miles / float(HAUL_MILES_PER_HOUR))) + HAUL_CREW_REST_HOURS
    )


def earliest_load_in(preceding_booking, haul_distance_miles):
    return dt(preceding_booking["tear_down_end_utc"]) + timedelta(
        hours=required_haul_hours(haul_distance_miles)
    )


# --- staging bay selector ------------------------------------------------- #
def select_staging_bay(venue, occupied_bays, vehicle_weight_lbs):
    candidates = [
        index
        for index in range(1, venue["staging_bay_count"] + 1)
        if index not in occupied_bays
    ]
    if not candidates:
        return None
    if vehicle_weight_lbs >= HEAVY_RIG_WEIGHT_LBS:
        return max(candidates)
    return min(candidates)


# --- marketing admission -------------------------------------------------- #
def stop_marketing_cap(season):
    return pct_of_cents(season["total_marketing_budget_cents"], STOP_MARKETING_CAP_PCT)


def channel_cap(season, channel):
    return pct_of_cents(stop_marketing_cap(season), CHANNEL_CAP_PCT[channel])


# --- settlement ----------------------------------------------------------- #
def coop_credit_rate(rental_due_pre_credit_cents):
    if rental_due_pre_credit_cents >= 5000000:
        return 0.06
    if rental_due_pre_credit_cents >= 2500000:
        return 0.04
    return 0.02


def compute_settlement_figures(variant, included_orders, activations, marketing_committed,
                               plan_cost_cents, staged_entry_count, booking,
                               stop_marketing_committed_cents):
    ticket_revenue = sum(
        o["line_subtotal_cents"] - o["group_discount_cents"] for o in included_orders
    )
    addon_revenue = sum(
        o["addon_subtotal_cents"] - o["addon_discount_cents"] for o in included_orders
    )
    facility_fee_total = sum(o["facility_fee_cents"] for o in included_orders)

    sponsorship_revenue = 0
    for activation in activations:
        if variant == "PROVISIONAL":
            sponsorship_revenue += activation["fee_cents"]
        else:
            if activation["state"] == "FULFILLED":
                sponsorship_revenue += activation["fee_cents"]
            else:
                sponsorship_revenue += pct_of_cents(
                    activation["fee_cents"], SPONSOR_HOLDBACK_PCT
                )

    purse = PURSE_PER_STAGED_ENTRY_CENTS * staged_entry_count

    share_component = pct_of_cents(ticket_revenue, booking["revenue_share_pct"])
    rental_due_pre_credit = max(booking["rental_base_cents"], share_component) + facility_fee_total
    credit_pct = coop_credit_rate(rental_due_pre_credit)
    coop_credit = min(
        pct_of_cents(rental_due_pre_credit, credit_pct), stop_marketing_committed_cents
    )
    venue_due = rental_due_pre_credit - coop_credit

    collected_cash = ticket_revenue + addon_revenue + facility_fee_total + sponsorship_revenue
    net_to_promoter = (
        collected_cash - venue_due - plan_cost_cents - marketing_committed - purse
    )

    remaining = collected_cash
    payout_venue = min(remaining, venue_due)
    remaining -= payout_venue
    payout_safety = min(remaining, plan_cost_cents)
    remaining -= payout_safety
    payout_marketing = min(remaining, marketing_committed)
    remaining -= payout_marketing
    payout_purse = min(remaining, purse)
    remaining -= payout_purse
    promoter_remainder = remaining
    shortfall = (
        (venue_due - payout_venue)
        + (plan_cost_cents - payout_safety)
        + (marketing_committed - payout_marketing)
        + (purse - payout_purse)
    )

    return {
        "ticket_revenue_cents": ticket_revenue,
        "addon_revenue_cents": addon_revenue,
        "facility_fee_cents": facility_fee_total,
        "sponsorship_revenue_cents": sponsorship_revenue,
        "marketing_spend_cents": marketing_committed,
        "safety_cost_cents": plan_cost_cents,
        "purse_cents": purse,
        "rental_due_pre_credit_cents": rental_due_pre_credit,
        "coop_credit_pct": credit_pct,
        "coop_credit_cents": coop_credit,
        "venue_due_cents": venue_due,
        "collected_cash_cents": collected_cash,
        "net_to_promoter_cents": net_to_promoter,
        "payout_venue_cents": payout_venue,
        "payout_safety_cents": payout_safety,
        "payout_marketing_cents": payout_marketing,
        "payout_purse_cents": payout_purse,
        "promoter_remainder_cents": promoter_remainder,
        "shortfall_cents": shortfall,
        "profitability_margin_pct": margin_pct(net_to_promoter, collected_cash),
    }


def clock_now():
    return db.clock_dt
