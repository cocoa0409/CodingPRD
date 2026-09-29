"""The eight named calculations of the wet-lease domain (PRD 2.5, 3.4, 3.6-3.10)."""

import calendar
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------- constants
MIN_BILLABLE_BLOCK_MINUTES = 60

OVERRUN_TIER1_FRACTION_OF_MGH = Decimal("0.10")
OVERRUN_TIER2_FRACTION_OF_MGH = Decimal("0.15")
OVERRUN_TIER1_MULTIPLIER = Decimal("1.00")
OVERRUN_TIER2_MULTIPLIER = Decimal("1.15")
OVERRUN_TIER3_MULTIPLIER = Decimal("1.35")
LESSEE_CANCEL_CREDIT_PCT = Decimal("0.50")

GUARANTEED_TDR_PCT = Decimal("99.00")
TDR_DEFICIT_DIVISOR = Decimal("5.0")
MAX_DEFICIT_FACTOR = Decimal("10.0")
PENALTY_TIER1_GROSS_CENTS = 5000000
PENALTY_TIER2_GROSS_CENTS = 25000000
PENALTY_TIER1_PCT = Decimal("0.02")
PENALTY_TIER2_PCT = Decimal("0.035")
PENALTY_TIER3_PCT = Decimal("0.05")

TECHNICAL_DELAY_THRESHOLD_MINUTES = 15

SEAT_TOLERANCE = 5
MAX_HOURS_SINCE_CHECK_FOR_SUB = Decimal("400.00")

PRE_POST_DUTY_MINUTES = 105
MAX_DUTY_MINUTES_7D = 3600
MAX_BLOCK_MINUTES_28D = 5400
DUTY_WINDOW = timedelta(hours=168)
BLOCK_WINDOW = timedelta(hours=672)

TURNAROUND_BUFFER = timedelta(minutes=45)

HOURS_OVER_RATE_CENTS = Decimal("2500")
CYCLES_OVER_RATE_CENTS = 18000
FUEL_RATE_CENTS_PER_KG = Decimal("95")
MIN_DISCREPANCY_FEE_CENTS = 250000

HULL_LIMIT_FLOOR_CENTS = 5000000000
LIABILITY_LIMIT_FLOOR_CENTS = 50000000000

LIVE_LEG_STATUSES = ("SCHEDULED", "DISPATCHED", "COMPLETED")


# ---------------------------------------------------------------- numeric helpers

def D(value):
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal(0)
    return Decimal(str(value))


def rhu(value, places):
    """Round half up to `places` decimal places."""
    quant = Decimal(1).scaleb(-places)
    return D(value).quantize(quant, rounding=ROUND_HALF_UP)


def cents(value):
    return int(rhu(value, 0))


def hours4(value):
    return float(rhu(value, 4))


def pct2(value):
    return float(rhu(value, 2))


def money2(value):
    return float(rhu(value, 2))


def floor_minutes(later, earlier):
    """Whole minutes between two instants, remaining seconds discarded."""
    delta = later - earlier
    total = delta.total_seconds()
    if total < 0:
        return -int((-total) // 60)
    return int(total // 60)


def month_of(dt):
    return "%04d-%02d" % (dt.year, dt.month)


def parse_month(period_month):
    return int(period_month[0:4]), int(period_month[5:7])


def month_days(period_month):
    year, month = parse_month(period_month)
    return calendar.monthrange(year, month)[1]


def next_month(period_month):
    year, month = parse_month(period_month)
    if month == 12:
        return "%04d-%02d" % (year + 1, 1)
    return "%04d-%02d" % (year, month + 1)


def month_first_day(period_month):
    year, month = parse_month(period_month)
    return date(year, month, 1)


def midnight_utc(day):
    return datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------- 1. leg minutes

def leg_billable_block_minutes(leg_class, block_minutes):
    if leg_class == "MAINTENANCE_FERRY":
        return 0
    if leg_class == "REPOSITIONING":
        return block_minutes
    # REVENUE — minimum billable block of one hour, inclusive comparison
    if block_minutes >= MIN_BILLABLE_BLOCK_MINUTES:
        return block_minutes
    return MIN_BILLABLE_BLOCK_MINUTES


def scheduled_contribution_minutes(leg):
    """Minute contribution of a not-yet-completed leg under the PROVISIONAL variant."""
    leg_class = leg["leg_class"]
    scheduled = leg["scheduled_block_minutes"]
    if leg_class == "MAINTENANCE_FERRY":
        return Decimal(0)
    if leg_class == "REVENUE" and scheduled < MIN_BILLABLE_BLOCK_MINUTES:
        return Decimal(MIN_BILLABLE_BLOCK_MINUTES)
    return Decimal(scheduled)


# ---------------------------------------------------------------- 2. monthly charge

def mgh_effective_hours(lease, period_month):
    days = month_days(period_month)
    first = month_first_day(period_month)
    last = date(first.year, first.month, days)
    term_start = date_from_iso(lease["term_start_date"])
    term_end = date_from_iso(lease["term_end_date"])
    lo = max(first, term_start)
    hi = min(last, term_end)
    covered = (hi - lo).days + 1 if hi >= lo else 0
    value = D(lease["min_guaranteed_block_hours_per_month"]) * Decimal(covered) / Decimal(days)
    return rhu(value, 4)


def date_from_iso(text):
    return date(int(text[0:4]), int(text[5:7]), int(text[8:10]))


def _month_legs(legs, period_month):
    rows = [leg for leg in legs if month_of(leg["_scheduled_out"]) == period_month]
    rows.sort(key=lambda leg: (leg["_scheduled_out"], leg.get("created_at") or "",
                               leg.get("_seq") or 0))
    return rows


def overrun_tiers(mgh, overrun):
    tier1_cap = rhu(mgh * OVERRUN_TIER1_FRACTION_OF_MGH, 4)
    tier2_cap = rhu(mgh * OVERRUN_TIER2_FRACTION_OF_MGH, 4)
    t1 = min(overrun, tier1_cap)
    t2 = min(tier2_cap, max(overrun - tier1_cap, Decimal(0)))
    t3 = max(overrun - tier1_cap - tier2_cap, Decimal(0))
    return t1, t2, t3


def deficit_factor(tdr_pct):
    raw = (GUARANTEED_TDR_PCT - D(tdr_pct)) / TDR_DEFICIT_DIVISOR
    clamped = min(MAX_DEFICIT_FACTOR, max(Decimal(0), raw))
    return rhu(clamped, 4)


def penalty_rate_for_gross(gross_cents):
    if gross_cents < PENALTY_TIER1_GROSS_CENTS:
        return PENALTY_TIER1_PCT
    if gross_cents < PENALTY_TIER2_GROSS_CENTS:
        return PENALTY_TIER2_PCT
    return PENALTY_TIER3_PCT


def reliability_penalty_cents(gross_cents, accepted_report):
    if accepted_report is None:
        return 0
    factor = deficit_factor(accepted_report["technical_dispatch_reliability_pct"])
    if factor == 0:
        return 0
    rate = penalty_rate_for_gross(gross_cents)
    return cents(D(gross_cents) * rate * factor)


def monthly_utilization_charge(lease, period_month, legs, variant, accepted_report):
    """Return every charge component for one lease-month under one variant."""
    rate = D(lease["block_hour_rate_usd_cents"])
    mgh = mgh_effective_hours(lease, period_month)
    rows = _month_legs(legs, period_month)

    contributions = []
    lessor_cancelled_minutes = Decimal(0)
    for leg in rows:
        status = leg["status"]
        if status == "CANCELLED_LESSOR":
            lessor_cancelled_minutes += Decimal(leg["scheduled_block_minutes"])
        if variant == "PROVISIONAL":
            if status not in LIVE_LEG_STATUSES:
                continue
            if status == "COMPLETED":
                contributions.append(Decimal(leg["billable_block_minutes"]))
            else:
                contributions.append(scheduled_contribution_minutes(leg))
        else:
            if status == "COMPLETED":
                contributions.append(Decimal(leg["billable_block_minutes"]))
            elif status == "CANCELLED_LESSEE":
                contributions.append(
                    Decimal(leg["scheduled_block_minutes"]) * LESSEE_CANCEL_CREDIT_PCT)

    # Step three: round per leg, then sum.
    credited_hours = Decimal(0)
    minute_total = Decimal(0)
    for contribution in contributions:
        credited_hours += rhu(contribution / Decimal(60), 4)
        minute_total += contribution
    credited_hours = rhu(credited_hours, 4)
    credited_block_minutes = int(rhu(minute_total, 0))

    # Step four
    if credited_hours < mgh:
        shortfall_hours = rhu(mgh - credited_hours, 4)
        overrun_hours = Decimal("0.0000")
    else:
        shortfall_hours = Decimal("0.0000")
        overrun_hours = rhu(credited_hours - mgh, 4)
    lessor_cancelled_hours = rhu(lessor_cancelled_minutes / Decimal(60), 4)
    lessor_attributable = min(shortfall_hours, lessor_cancelled_hours)

    # Step five
    base_charge_cents = cents(mgh * rate)
    shortfall_credit_cents = cents(
        lessor_attributable * rate * D(lease["shortfall_credit_pct"]))
    t1, t2, t3 = overrun_tiers(mgh, overrun_hours)
    tier1_cents = cents(t1 * rate * OVERRUN_TIER1_MULTIPLIER)
    tier2_cents = cents(t2 * rate * OVERRUN_TIER2_MULTIPLIER)
    tier3_cents = cents(t3 * rate * OVERRUN_TIER3_MULTIPLIER)
    overrun_charge_cents = tier1_cents + tier2_cents + tier3_cents
    gross_charge_cents = base_charge_cents - shortfall_credit_cents + overrun_charge_cents

    # Step six
    penalty = reliability_penalty_cents(gross_charge_cents, accepted_report)
    net = gross_charge_cents - penalty

    return {
        "mgh_effective_hours": float(mgh),
        "credited_block_minutes": credited_block_minutes,
        "credited_hours": float(credited_hours),
        "shortfall_hours": float(shortfall_hours),
        "lessor_attributable_shortfall_hours": float(lessor_attributable),
        "overrun_hours": float(overrun_hours),
        "base_charge_cents": base_charge_cents,
        "shortfall_credit_cents": shortfall_credit_cents,
        "overrun_charge_cents": overrun_charge_cents,
        "gross_charge_cents": gross_charge_cents,
        "reliability_penalty_cents": penalty,
        "net_charge_cents": net,
        "variant_applied": variant,
        "tier_hours": (float(t1), float(t2), float(t3)),
        "tier_cents": (tier1_cents, tier2_cents, tier3_cents),
    }


# ---------------------------------------------------------------- 4. reliability

def technical_dispatch_reliability(lease, legs):
    revenue_departures = 0
    scheduled_revenue_legs = 0
    technical_delay_events = 0
    technical_cancellations = 0
    for leg in legs:
        if leg["leg_class"] != "REVENUE":
            continue
        status = leg["status"]
        if status in ("DISPATCHED", "COMPLETED"):
            revenue_departures += 1
        if status in ("SCHEDULED", "DISPATCHED", "COMPLETED", "CANCELLED_LESSOR"):
            scheduled_revenue_legs += 1
        if (leg.get("technical_delay_minutes") or 0) > TECHNICAL_DELAY_THRESHOLD_MINUTES:
            technical_delay_events += 1
        if status == "CANCELLED_LESSOR" and leg.get("cancel_reason") == "TECHNICAL":
            technical_cancellations += 1

    if revenue_departures == 0:
        departure_basis = Decimal("100.00")
    else:
        departure_basis = rhu(
            Decimal(100) * Decimal(revenue_departures - technical_delay_events)
            / Decimal(revenue_departures), 2)
    if scheduled_revenue_legs == 0:
        scheduled_basis = Decimal("100.00")
    else:
        scheduled_basis = rhu(
            Decimal(100) * Decimal(
                scheduled_revenue_legs - technical_delay_events - technical_cancellations)
            / Decimal(scheduled_revenue_legs), 2)

    headline = departure_basis if lease["reliability_basis"] == "DEPARTURE" else scheduled_basis
    return {
        "revenue_departures": revenue_departures,
        "scheduled_revenue_legs": scheduled_revenue_legs,
        "technical_delay_events": technical_delay_events,
        "technical_cancellations": technical_cancellations,
        "tdr_departure_basis_pct": float(departure_basis),
        "tdr_scheduled_basis_pct": float(scheduled_basis),
        "technical_dispatch_reliability_pct": float(headline),
    }


# ---------------------------------------------------------------- 5. substitute selection

def substitute_is_eligible(candidate, original, lease):
    if candidate["id"] == original["id"]:
        return False
    if candidate["status"] != "AVAILABLE":
        return False
    if candidate["assigned_lease_id"] is not None:
        return False
    if candidate["type_family"] != original["type_family"]:
        return False
    if candidate["maintenance_program_ref"] != lease["required_maintenance_program_ref"]:
        return False
    if candidate["seat_count"] < original["seat_count"] - SEAT_TOLERANCE:
        return False
    if rhu(candidate["hours_since_last_check"], 2) > MAX_HOURS_SINCE_CHECK_FOR_SUB:
        return False
    return True


def rank_substitutes(candidates, original):
    return sorted(candidates, key=lambda a: (
        abs(a["seat_count"] - original["seat_count"]),
        D(a["hours_since_last_check"]),
        a.get("created_at") or "",
        a.get("_seq") or 0,
    ))


# ---------------------------------------------------------------- 6. crew exposure

def crew_legs(crew_id, all_legs):
    return [leg for leg in all_legs
            if leg["captain_id"] == crew_id or leg["first_officer_id"] == crew_id]


def rolling_exposure(crew_id, all_legs, now):
    duty = 0
    block = 0
    for leg in crew_legs(crew_id, all_legs):
        if leg["status"] not in LIVE_LEG_STATUSES:
            continue
        out = leg["_scheduled_out"]
        if (now - DUTY_WINDOW) <= out < now:
            duty += leg["scheduled_block_minutes"] + PRE_POST_DUTY_MINUTES
        if (now - BLOCK_WINDOW) <= out < now:
            block += leg["scheduled_block_minutes"]
    return duty, block


def projected_exposure(crew_id, all_legs, anchor, candidate_minutes, exclude_leg_id=None):
    duty = candidate_minutes + PRE_POST_DUTY_MINUTES
    block = candidate_minutes
    for leg in crew_legs(crew_id, all_legs):
        if exclude_leg_id is not None and leg["id"] == exclude_leg_id:
            continue
        if leg["status"] not in LIVE_LEG_STATUSES:
            continue
        out = leg["_scheduled_out"]
        if (anchor - DUTY_WINDOW) <= out < anchor:
            duty += leg["scheduled_block_minutes"] + PRE_POST_DUTY_MINUTES
        if (anchor - BLOCK_WINDOW) <= out < anchor:
            block += leg["scheduled_block_minutes"]
    return duty, block


# ---------------------------------------------------------------- 7. return discrepancies

def return_discrepancy_cost(lease, hours_at_return, cycles_at_return, fuel_kg,
                            discrepancy_codes):
    hours_over = max(Decimal(0), D(hours_at_return) - D(lease["return_hours_since_check_max"]))
    cycles_over = max(0, int(cycles_at_return or 0) - int(lease["return_cycles_since_check_max"]))
    fuel_short = max(Decimal(0), D(lease["return_fuel_kg_required"]) - D(fuel_kg))

    airframe_component = cents(hours_over * HOURS_OVER_RATE_CENTS)
    cycles_component = cycles_over * CYCLES_OVER_RATE_CENTS
    fuel_component = cents(fuel_short * FUEL_RATE_CENTS_PER_KG)
    raw = airframe_component + cycles_component + fuel_component
    capped = min(raw, int(lease["return_liability_cap_cents"]))

    if raw == 0 and not discrepancy_codes:
        cost = 0
    else:
        cost = max(capped, MIN_DISCREPANCY_FEE_CENTS)

    deposit = int(lease["return_deposit_cents"])
    applied = min(cost, deposit)
    remaining = deposit - applied
    billed = cost - applied
    return {
        "discrepancy_cost_cents": cost,
        "return_deposit_applied_cents": applied,
        "return_deposit_remaining_cents": remaining,
        "billed_to_lessee_cents": billed,
    }


# ---------------------------------------------------------------- occupancy

def occupancy_conflict(candidate_out, candidate_in, existing_legs):
    for leg in existing_legs:
        if leg["status"] not in LIVE_LEG_STATUSES:
            continue
        start = leg["_scheduled_out"] - TURNAROUND_BUFFER
        end = leg["_scheduled_in"] + TURNAROUND_BUFFER
        if candidate_out < end and start < candidate_in:
            return leg
    return None
