"""Calculations pinned normatively by the PRD (section 3)."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from clock import clock
from constants import (
    ADMIN_FEE_PCT, ADMIN_TIER_MID_MAX, ADMIN_TIER_SMALL_MAX, INTAKE_WINDOW_DAYS,
    LIQUID_RANK, MEALS_TAX_PCT, MIN_MEAL_GAP_MINUTES,
    PACKAGING_FEE_CENTS, POSTURE_SUSPEND_AT, POSTURE_WATCH_AT,
    QUORUM_PARTICIPATION_PCT, RATE, REFRESH_THRESHOLD, SCORE_CEILING,
    SPONSOR_DISCOUNT_PCT, TEMP_LIMITS, TEXTURE_RANK, TICKET_TYPES, TIER_WEIGHT,
    WEIGHT_WINDOW_DAYS,
)
from db import db, sort_created
from shape import parse_date_str, parse_instant

ZERO2 = Decimal("0.00")


def rhu_cents(value):
    """Round half up to whole cents."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu2(value):
    """Round half up to 2 decimal places."""
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def rhu1(value):
    return Decimal(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


# ============================================================ ticket pricing
def ticket_billed_amount(ticket_type, meal_period, resident):
    """PRD 3.6 -- each component is rounded to whole cents on its own before
    the components are combined."""
    base_cents = RATE[ticket_type][meal_period]
    sponsor_eligible = (
        ticket_type in ("GUEST", "TAKEOUT")
        and resident is not None
        and resident["dining_status"] == "ACTIVE"
    )
    if sponsor_eligible:
        guest_discount_cents = rhu_cents(Decimal(base_cents) * SPONSOR_DISCOUNT_PCT)
    else:
        guest_discount_cents = 0
    packaging_cents = PACKAGING_FEE_CENTS if ticket_type == "TAKEOUT" else 0
    subtotal_cents = base_cents - guest_discount_cents + packaging_cents
    if ticket_type in ("GUEST", "TAKEOUT"):
        tax_cents = rhu_cents(Decimal(subtotal_cents) * MEALS_TAX_PCT)
    else:
        tax_cents = 0
    return subtotal_cents + tax_cents


# ==================================================== resident weight/intake
def _resident_observations(resident_id):
    return [o for o in db.observations.values() if o["resident_id"] == resident_id]


def _obs_sort_key(obs):
    return (obs["observation_date"], obs["created_at"], obs["_seq"])


def resident_weight_trend(resident):
    """PRD 3.8 hop 1.  Returns (rolling_30d_pct, baseline_pct, current_weight,
    avg_intake_pct_7d)."""
    clock_date = clock.date()
    observations = _resident_observations(resident["id"])

    window_start = clock_date - timedelta(days=WEIGHT_WINDOW_DAYS)
    weighted = [
        o for o in observations
        if o["weight_kg"] is not None
        and window_start <= parse_date_str("observation_date", o["observation_date"]) <= clock_date
    ]
    weighted.sort(key=_obs_sort_key)
    if len(weighted) < 2:
        rolling = ZERO2
    else:
        earliest = weighted[0]["weight_kg"]
        latest = weighted[-1]["weight_kg"]
        rolling = rhu2((latest - earliest) / earliest * Decimal(100))

    all_weighted = [o for o in observations if o["weight_kg"] is not None]
    all_weighted.sort(key=_obs_sort_key, reverse=True)
    baseline = resident["baseline_weight_kg"]
    if all_weighted:
        current_weight = all_weighted[0]["weight_kg"]
    else:
        current_weight = baseline
    baseline_pct = rhu2((current_weight - baseline) / baseline * Decimal(100))

    intake_start = clock_date - timedelta(days=INTAKE_WINDOW_DAYS - 1)
    in_window = [
        o for o in observations
        if intake_start <= parse_date_str("observation_date", o["observation_date"]) <= clock_date
    ]
    if not in_window:
        avg_intake = None
    else:
        total = sum(Decimal(o["intake_pct"]) for o in in_window)
        avg_intake = rhu2(total / Decimal(len(in_window)))

    return rolling, baseline_pct, current_weight, avg_intake


def intake_risk_score(resident, active_order):
    """PRD 3.8 -- five inputs, tiered selection, conditional multiplier."""
    rolling = resident["rolling_30d_weight_change_pct"]
    avg_intake = resident["avg_intake_pct_7d"]

    if rolling <= Decimal("-10.00"):
        weight_points = 40
    elif rolling <= Decimal("-5.00"):
        weight_points = 30
    elif rolling <= Decimal("-2.00"):
        weight_points = 15
    else:
        weight_points = 0

    if avg_intake is None:
        intake_points = 0
    elif avg_intake < Decimal("25.00"):
        intake_points = 40
    elif avg_intake < Decimal("50.00"):
        intake_points = 30
    elif avg_intake < Decimal("75.00"):
        intake_points = 15
    else:
        intake_points = 0

    if active_order is None:
        texture_points = 0
        therapeutic_points = 0
        liquid_points = 0
    else:
        texture_points = TEXTURE_RANK[active_order["texture_level"]] * 5
        therapeutic_points = min(10, 5 * len(active_order["therapeutic_codes"]))
        liquid_points = 10 if LIQUID_RANK[active_order["liquid_consistency"]] >= 2 else 0

    raw = Decimal(weight_points + intake_points + texture_points + therapeutic_points + liquid_points)
    multiplier = Decimal("0.50") if resident["dining_status"] == "ON_LEAVE" else Decimal("1.00")
    product = raw * multiplier
    clamped = min(SCORE_CEILING, max(ZERO2, product))
    return rhu2(clamped)


# ================================================================ intervals
def reservation_interval(reservation):
    return (
        parse_instant("seat_start_utc", reservation["seat_start_utc"]),
        parse_instant("seat_end_utc", reservation["seat_end_utc"]),
    )


def resident_meal_spacing_conflict(resident_id, cand_start, cand_end, exclude_id=None):
    """PRD 3.5 -- CLOSED intervals, SYMMETRIC 90 minute gap, all venues."""
    gap = timedelta(minutes=MIN_MEAL_GAP_MINUTES)
    for row in db.reservations.values():
        if row["resident_id"] != resident_id:
            continue
        if exclude_id is not None and row["id"] == exclude_id:
            continue
        if row["status"] not in ("RESERVED", "SEATED", "COMPLETED"):
            continue
        start, end = reservation_interval(row)
        occ_start = start - gap
        occ_end = end + gap
        if cand_start <= occ_end and occ_start <= cand_end:
            return True
    return False


def venue_capacity_committed(venue, service_date, cand_start, cand_end, exclude_id=None):
    """PRD 3.5 -- HALF-OPEN intervals, one-sided buffer on the incumbent."""
    buffer_delta = timedelta(minutes=venue["turnover_buffer_minutes"])
    committed = 0
    for row in db.reservations.values():
        if row["venue_id"] != venue["id"]:
            continue
        if exclude_id is not None and row["id"] == exclude_id:
            continue
        if row["service_date"] != service_date:
            continue
        if row["status"] not in ("RESERVED", "SEATED"):
            continue
        start, end = reservation_interval(row)
        if start < cand_end and cand_start < end + buffer_delta:
            committed += row["party_size"]
    return committed


def venue_committed_seats(venue_id, service_date, meal_period):
    """PRD 3.5 -- meal-period roll-up (RESERVED and SEATED only)."""
    rows = [
        r for r in db.reservations.values()
        if r["venue_id"] == venue_id
        and r["service_date"] == service_date
        and r["meal_period"] == meal_period
        and r["status"] in ("RESERVED", "SEATED")
    ]
    committed = sum(r["party_size"] for r in rows)
    return committed, sort_created(rows)


# =========================================================== temperature
def temperature_in_range(probe_point, temperature_f):
    if probe_point == "HOT_HOLDING":
        return temperature_f >= TEMP_LIMITS["HOT_HOLDING_MIN_F"]
    if probe_point == "COLD_HOLDING":
        return temperature_f <= TEMP_LIMITS["COLD_HOLDING_MAX_F"]
    return temperature_f >= TEMP_LIMITS["REHEAT_MIN_F"]


def posture_from_count(count):
    if count >= POSTURE_SUSPEND_AT:
        return "SUSPENDED"
    if count >= POSTURE_WATCH_AT:
        return "WATCH"
    return "COMPLIANT"


# ======================================================= committee refresh
def menu_refresh_index(cycle):
    """PRD 3.4 -- participation, then tier, then index, then threshold."""
    eligible = len([
        r for r in db.residents.values()
        if r["community_id"] == cycle["community_id"] and r["dining_status"] == "ACTIVE"
    ])
    ballots = [
        f for f in db.feedback.values()
        if f["menu_cycle_id"] == cycle["id"] and f["status"] == "SUBMITTED"
    ]
    negative_weight = sum(f["vote_weight"] for f in ballots if f["sentiment"] == "NEGATIVE")
    distinct_voters = len(set(f["resident_id"] for f in ballots))
    denominator = Decimal(max(1, eligible))

    participation_pct = rhu2(Decimal(distinct_voters) * Decimal(100) / denominator)
    refresh_tier = "QUORUM" if participation_pct >= QUORUM_PARTICIPATION_PCT else "ADVISORY"
    refresh_index = rhu2(
        Decimal(negative_weight) * TIER_WEIGHT[refresh_tier] * Decimal(100) / denominator
    )
    eligible_for_refresh = refresh_index >= REFRESH_THRESHOLD[refresh_tier]
    return refresh_index, refresh_tier, eligible_for_refresh


# ==================================================== meal reconciliation
def _venue_ids_of(community_id):
    return set(v["id"] for v in db.venues.values() if v["community_id"] == community_id)


def _in_period(date_str, start_str, end_str):
    return start_str <= date_str <= end_str


def meal_count_reconciliation(community_id, period_start, period_end):
    venue_ids = _venue_ids_of(community_id)

    ledger_tickets = [
        t for t in db.tickets.values()
        if t["venue_id"] in venue_ids
        and _in_period(t["service_date"], period_start, period_end)
        and t["status"] in ("SERVED", "BILLED")
    ]
    ticket_ledger_total_cents = sum(t["billed_amount_cents"] for t in ledger_tickets)
    ledger_meal_counts = dict((k, 0) for k in TICKET_TYPES)
    for ticket in ledger_tickets:
        ledger_meal_counts[ticket["ticket_type"]] += 1

    census_reservations = [
        r for r in db.reservations.values()
        if r["venue_id"] in venue_ids
        and _in_period(r["service_date"], period_start, period_end)
        and r["status"] in ("RESERVED", "SEATED", "COMPLETED")
    ]
    census_resident_cents = sum(RATE["RESIDENT"][r["meal_period"]] for r in census_reservations)
    census_guest_tickets = [
        t for t in db.tickets.values()
        if t["venue_id"] in venue_ids
        and _in_period(t["service_date"], period_start, period_end)
        and t["ticket_type"] in ("GUEST", "TAKEOUT")
        and t["status"] in ("SERVED", "BILLED")
    ]
    census_projection_total_cents = census_resident_cents + sum(
        t["billed_amount_cents"] for t in census_guest_tickets
    )
    census_meal_counts = {
        "RESIDENT": len(census_reservations),
        "GUEST": len([t for t in census_guest_tickets if t["ticket_type"] == "GUEST"]),
        "TAKEOUT": len([t for t in census_guest_tickets if t["ticket_type"] == "TAKEOUT"]),
    }

    void_credit_cents = sum(
        t["voided_amount_cents"] for t in db.tickets.values()
        if t["venue_id"] in venue_ids
        and _in_period(t["service_date"], period_start, period_end)
        and t["status"] == "VOIDED"
        and t["billed_reconciliation_id"] is not None
    )

    pre_fee_base_cents = max(0, ticket_ledger_total_cents - void_credit_cents)
    if pre_fee_base_cents <= ADMIN_TIER_SMALL_MAX:
        tier = "SMALL"
    elif pre_fee_base_cents <= ADMIN_TIER_MID_MAX:
        tier = "MID"
    else:
        tier = "LARGE"
    administrative_fee_cents = rhu_cents(Decimal(pre_fee_base_cents) * ADMIN_FEE_PCT[tier])
    net_billable_total_cents = pre_fee_base_cents + administrative_fee_cents

    return {
        "ticket_ledger_total_cents": ticket_ledger_total_cents,
        "ledger_meal_counts": ledger_meal_counts,
        "census_projection_total_cents": census_projection_total_cents,
        "census_meal_counts": census_meal_counts,
        "variance_cents": ticket_ledger_total_cents - census_projection_total_cents,
        "void_credit_cents": void_credit_cents,
        "pre_fee_base_cents": pre_fee_base_cents,
        "administrative_fee_cents": administrative_fee_cents,
        "net_billable_total_cents": net_billable_total_cents,
    }
