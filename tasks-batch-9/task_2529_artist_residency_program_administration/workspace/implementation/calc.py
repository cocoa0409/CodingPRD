"""The eleven declared calculations.

All money and score arithmetic goes through decimal.Decimal with ROUND_HALF_UP.
No float ever participates in a rounded result.
"""

import math
from decimal import Decimal, ROUND_HALF_UP

import store as K

TWO_PLACES = Decimal("0.01")
ONE = Decimal("1")


def round_half_up(value, places=0):
    quant = Decimal(1).scaleb(-places) if places else ONE
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def money(value):
    """Round a Decimal to whole cents, half up, and return an int."""
    return int(round_half_up(value, 0))


def pct2(value):
    """Round to 2 decimal places, half up, and return a JSON-friendly number."""
    return float(round_half_up(value, 2))


def dec2(value):
    return float(round_half_up(value, 2))


# ---------------------------------------------------------------- 1. application_composite_score
def panelist_total_100(artistic, feasibility, community, technical, expertise_matched):
    weighted_raw = (
        Decimal(K.RUBRIC_WEIGHT_ARTISTIC_MERIT) * Decimal(artistic)
        + Decimal(K.RUBRIC_WEIGHT_FEASIBILITY) * Decimal(feasibility)
        + Decimal(K.RUBRIC_WEIGHT_COMMUNITY_FIT) * Decimal(community)
        + Decimal(K.RUBRIC_WEIGHT_TECHNICAL_READINESS) * Decimal(technical)
    ) / Decimal(10)
    multiplier = Decimal(K.EXPERTISE_MATCH_MULTIPLIER) if expertise_matched \
        else Decimal(K.EXPERTISE_MISMATCH_MULTIPLIER)
    return round_half_up(weighted_raw * multiplier, 2)


def provisional_screening_score(totals):
    """Untrimmed arithmetic mean over every SCORED assignment."""
    if not totals:
        return None
    return round_half_up(sum(totals, Decimal(0)) / Decimal(len(totals)), 2)


def final_panel_score(totals, panel_quorum):
    """Quorum-gated, high/low-trimmed mean once TRIM_MIN_PANELISTS have scored."""
    n = len(totals)
    if n == 0:
        return None
    if n < panel_quorum:
        return None
    if n >= K.TRIM_MIN_PANELISTS:
        kept = list(totals)
        kept.remove(max(kept))
        kept.remove(min(kept))
        if not kept:
            return None
        return round_half_up(sum(kept, Decimal(0)) / Decimal(len(kept)), 2)
    return round_half_up(sum(totals, Decimal(0)) / Decimal(n), 2)


# ---------------------------------------------------------------- 4. residency_stipend_total
def provisional_award(weekly_rate_cents, weeks_planned):
    return int(weekly_rate_cents) * int(weeks_planned)


def weeks_served(session_start_date, settlement_date):
    days = (settlement_date - session_start_date).days + 1
    if days <= 0:
        return 0
    return int(math.ceil(days / 7.0))


def final_settled_award(weekly_rate_cents, session_start_date, settlement_date):
    return int(weekly_rate_cents) * weeks_served(session_start_date, settlement_date)


# ---------------------------------------------------------------- 5. stipend_period_split
def period_plan(weeks, session_start_date, session_end_date, weekly_rate_cents):
    """Returns a list of (period_index, start, end, weeks_in_period, gross_cents)."""
    weeks = int(weeks)
    if weeks <= 0:
        return []
    period_count = int(math.ceil(weeks / float(K.STIPEND_PERIOD_WEEKS)))
    remaining = weeks
    plan = []
    for i in range(1, period_count + 1):
        weeks_in_period = min(K.STIPEND_PERIOD_WEEKS, remaining)
        remaining -= weeks_in_period
        from datetime import timedelta
        start = session_start_date + timedelta(days=(i - 1) * K.STIPEND_PERIOD_WEEKS * 7)
        end = start + timedelta(days=K.STIPEND_PERIOD_WEEKS * 7 - 1)
        if session_end_date is not None and session_end_date < end:
            end = session_end_date
        plan.append((i, start, end, weeks_in_period, int(weekly_rate_cents) * weeks_in_period))
    return plan


# ---------------------------------------------------------------- 6. stipend_withholding
def withholding_rate(tax_form_type, treaty_country):
    """Rate selection keyed on resident tax status, never on the payment amount."""
    if tax_form_type == "W9":
        return Decimal("0.00")
    if treaty_country:
        return Decimal(K.TREATY_WITHHOLDING_RATE)
    return Decimal(K.NRA_WITHHOLDING_RATE)


def _excess(amount):
    diff = int(amount) - K.WITHHOLDING_EXEMPT_THRESHOLD_CENTS
    return diff if diff > 0 else 0


def taxable_slice(cumulative_before, gross_cents):
    cumulative_after = int(cumulative_before) + int(gross_cents)
    return _excess(cumulative_after) - _excess(cumulative_before)


def withheld_actual(cumulative_before, gross_cents, rate):
    slice_cents = taxable_slice(cumulative_before, gross_cents)
    return slice_cents, money(Decimal(slice_cents) * rate)


def statutory_liability(annual_gross_cents, rate):
    annual_taxable = _excess(annual_gross_cents)
    return annual_taxable, money(Decimal(annual_taxable) * rate)


# ---------------------------------------------------------------- 7. visa_timeline
def backlog_days_for(citizenship_country):
    if citizenship_country in K.HIGH_VOLUME_VISA_COUNTRIES:
        return K.VISA_BACKLOG_DAYS_HIGH_VOLUME
    return K.VISA_BACKLOG_DAYS_DEFAULT


def visa_case_type(session_length_weeks):
    if session_length_weeks is not None and session_length_weeks >= K.VISA_J1_MIN_SESSION_WEEKS:
        return "J1_RESEARCH_SCHOLAR"
    return "B1_SHORT_TERM"


# ---------------------------------------------------------------- 8. studio_auto_selection
def ventilation_rank(ventilation_class):
    return K.VENTILATION_RANK.get(ventilation_class, 0)


def studio_rank_key(studio):
    """Ascending on every key: prefer the LEAST over-provisioned studio."""
    return (
        ventilation_rank(studio["ventilation_class"]),
        len(studio["capability_tags"]),
        studio["max_concurrent_residents"],
        studio["code"],
    )


def studio_occupied_days(start_date, end_date):
    """Closed interval: end - start + 1."""
    return (end_date - start_date).days + 1


def studio_interval_conflict(existing_start, existing_end, start, end):
    """Closed-interval overlap extended by the two-day turnaround buffer."""
    from datetime import timedelta
    buffer_days = timedelta(days=K.STUDIO_TURNAROUND_DAYS)
    return start <= (existing_end + buffer_days) and (end + buffer_days) >= existing_start


# ---------------------------------------------------------------- 9. housing_occupancy
def bed_nights(check_in_date, check_out_date):
    """Half-open interval: check_out - check_in."""
    return (check_out_date - check_in_date).days


def housing_overlap(a_in, a_out, b_in, b_out):
    """Half-open overlap; adjacency is deliberately NOT a conflict."""
    return a_in < b_out and b_in < a_out


# ---------------------------------------------------------------- 10. obligation_provisioning
def obligation_plan(weeks):
    """Returns a list of (obligation_type, required_count)."""
    plan = [
        ("OPEN_STUDIO", K.OBLIGATION_BASE_OPEN_STUDIO),
        ("EXHIBITION", K.OBLIGATION_BASE_EXHIBITION),
        ("ARTIST_TALK", K.OBLIGATION_BASE_ARTIST_TALK),
    ]
    workshops = int(int(weeks) // K.OBLIGATION_WORKSHOP_WEEKS_PER_UNIT)
    if workshops >= 1:
        plan.append(("COMMUNITY_WORKSHOP", workshops))
    return plan


# ---------------------------------------------------------------- 2. slate_allocation
def alumni_reserved_slots(alumni_reserve_pct, cohort_target_size):
    """ceil(pct * target) -- the reserve is PINNED to the target, not to what is left."""
    product = Decimal(str(alumni_reserve_pct)) * Decimal(int(cohort_target_size))
    return int(product.to_integral_value(rounding="ROUND_CEILING"))
