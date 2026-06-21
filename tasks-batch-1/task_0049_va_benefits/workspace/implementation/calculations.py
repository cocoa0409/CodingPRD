"""Calculation engine for the VA Benefits API.

Every function here implements one calculation rule from SCAFFOLD §1.3 and the
matching PRD §3 narrative. Monetary intermediates use Decimal with ROUND_HALF_UP
(PRD §2.5): a value whose fractional remainder is exactly one half rounds upward.
"""

from decimal import Decimal, ROUND_HALF_UP


# ---------------------------------------------------------------------------
# Constants (SCAFFOLD §1.3 constants blocks; PRD §3.8 / §3.10).
# ---------------------------------------------------------------------------

MAX_REMANDS = 2            # appeal cap (PRD §3.4 / §3.5)
VOC_REHAB_MIN_RATING = 20  # PRD §3.14
ROUND_TO_NEAREST = 10      # combined rating snap (PRD §3.6)
BILATERAL_FACTOR_PCT = 10  # PRD §3.7

# Monthly compensation base schedule keyed by combined_rating_pct (PRD §3.8).
BASE_RATE_CENTS = {
    0: 0, 10: 17500, 20: 34600, 30: 53600, 40: 77200, 50: 109900,
    60: 139500, 70: 175800, 80: 204400, 90: 229600, 100: 383150,
}
SPOUSE_ADD_CENTS = 10000
PARENT_ADD_CENTS = 8000
CHILD_UNDER18_ADD_CENTS = 7000
CHILD_SCHOOL_ADD_CENTS = 23000

DEPENDENT_THRESHOLD = 30   # dependent additions only when rating >= 30 (PRD §3.8)

# GI Bill tier day thresholds (PRD §3.10).
DAYS_36_MONTHS = 1095
DAYS_30_MONTHS = 912
DAYS_24_MONTHS = 730
DAYS_18_MONTHS = 547
DAYS_12_MONTHS = 365
DAYS_90 = 90

RATE_OF_PURSUIT_FLOOR_PCT = 50  # MHA paid only when strictly greater (PRD §3.11)


def round_half_up(value):
    """Round a numeric value to the nearest whole integer, rounding a value
    whose fractional remainder is exactly one half upward (PRD §2.5)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# gi_bill_tier (PRD §3.10 / SCAFFOLD §1.3)
# ---------------------------------------------------------------------------

def gi_bill_tier(total_active_duty_days, discharged_for_service_disability):
    """Post-9/11 GI Bill benefit tier from aggregate creditable active-duty days.

    A veteran discharged_for_service_disability who served at least 30 days
    short-circuits to the full 100 percent tier regardless of total days.
    Otherwise a threshold function, each threshold inclusive at its lower bound.
    """
    if discharged_for_service_disability and total_active_duty_days >= 30:
        return 100
    d = total_active_duty_days
    if d >= DAYS_36_MONTHS:
        return 100
    if d >= DAYS_30_MONTHS:
        return 90
    if d >= DAYS_24_MONTHS:
        return 80
    if d >= DAYS_18_MONTHS:
        return 70
    if d >= DAYS_12_MONTHS:
        return 60
    if d >= DAYS_90:
        return 50
    return 0


# ---------------------------------------------------------------------------
# va_combined_rating (PRD §3.6 / §3.7 / SCAFFOLD §1.3)
# ---------------------------------------------------------------------------

def _combine_efficiency(ratings):
    """Walk the ratings (descending) accumulating disability against remaining
    efficiency. Returns the raw (un-rounded) total disability as a float.

    ratings: list of integer percentages already filtered to > 0 and sorted
    descending (with the caller's tie-break already applied).
    """
    remaining_efficiency = 100.0
    for r in ratings:
        contributed = remaining_efficiency * (r / 100.0)
        remaining_efficiency -= contributed
    return 100.0 - remaining_efficiency


def _sort_ratings(conditions, get_rating):
    """Return (rating_list_desc, ...) for conditions, dropping 0 ratings, sorted
    descending with tie-break older created_at first (PRD §3.6).

    conditions: list of condition dicts. get_rating: callable -> int.
    """
    enriched = []
    for c in conditions:
        r = get_rating(c)
        if r and r > 0:
            enriched.append((r, c.get("created_at", ""), c.get("_seq", 0), c))
    # sort: rating DESC, then created_at ASC, then _seq ASC (stable determinism)
    enriched.sort(key=lambda t: (-t[0], t[1], t[2]))
    return enriched


def va_combined_rating(conditions, get_rating):
    """Compute the combined disability rating over the supplied condition set.

    conditions: list of condition dicts to include.
    get_rating: callable extracting the percentage to use for each condition
                (final_rating_pct for the finalized variant, or a mix of
                final/proposed for the provisional variant — the caller decides
                which conditions and which getter to pass).

    Implements PRD §3.6 (efficiency reduction + snap to nearest 10, clamp 0..100)
    and the §3.7 bilateral-factor variant.
    """
    enriched = _sort_ratings(conditions, get_rating)
    if not enriched:
        return 0

    # Determine the bilateral set: included is_extremity conditions, with at
    # least one LEFT and at least one RIGHT body_side (PRD §3.7).
    extremity = [t for t in enriched if t[3].get("is_extremity")]
    sides = {t[3].get("body_side") for t in extremity}
    bilateral_applies = (
        len(extremity) >= 2 and "LEFT" in sides and "RIGHT" in sides
    )

    if not bilateral_applies:
        # schedular_only: combine all, then round.
        ratings = [t[0] for t in enriched]
        total = _combine_efficiency(ratings)
        return _snap_to_ten(total)

    # bilateral_factor variant (PRD §3.7):
    #  1. combine the qualifying bilateral extremity ratings among themselves,
    #  2. add 10% of that bilateral subtotal,
    #  3. treat the result as a single rating folded with the remaining
    #     (non-bilateral) ratings via the same efficiency-reduction method,
    #  4. round to nearest 10 last.
    bilateral_ratings = [t[0] for t in extremity]
    bilateral_subtotal = _combine_efficiency(bilateral_ratings)
    bilateral_with_factor = bilateral_subtotal + bilateral_subtotal * (BILATERAL_FACTOR_PCT / 100.0)

    non_bilateral = [t[0] for t in enriched if not t[3].get("is_extremity")]
    # Fold the bilateral combined-with-factor figure together with the remaining
    # non-bilateral ratings. To preserve the non-linear efficiency reduction with
    # a fractional bilateral figure, sort descending and combine.
    combined_inputs = sorted([bilateral_with_factor] + non_bilateral, reverse=True)
    total = _combine_efficiency(combined_inputs)
    return _snap_to_ten(total)


def _snap_to_ten(total_disability):
    """Snap raw total disability to nearest multiple of 10 (round-half-up),
    clamped to [0, 100] (PRD §3.6)."""
    snapped = round_half_up(total_disability / 10.0) * 10
    if snapped < 0:
        snapped = 0
    if snapped > 100:
        snapped = 100
    return snapped


# ---------------------------------------------------------------------------
# monthly_compensation (PRD §3.8 / SCAFFOLD §1.3)
# ---------------------------------------------------------------------------

def monthly_compensation(combined_rating_pct, active_dependents):
    """Monthly disability compensation: step-function base plus scaled dependent
    additions that switch on only at combined_rating_pct >= 30 (PRD §3.8).

    active_dependents: list of dependent dicts with status == ACTIVE.
    """
    base = BASE_RATE_CENTS.get(combined_rating_pct, 0)
    if combined_rating_pct < DEPENDENT_THRESHOLD:
        # Below the dependent threshold: flat base, no dependent bumps at all.
        return base

    spouse_count = sum(1 for d in active_dependents if d["relationship"] == "SPOUSE")
    parent_count = sum(1 for d in active_dependents if d["relationship"] == "PARENT")
    child_under18 = sum(
        1 for d in active_dependents
        if d["relationship"] == "CHILD" and not d.get("in_school_18_to_23", False)
    )
    child_school = sum(
        1 for d in active_dependents
        if d["relationship"] == "CHILD" and d.get("in_school_18_to_23", False)
    )

    spouse_amt = SPOUSE_ADD_CENTS if spouse_count == 1 else 0
    parent_amt = PARENT_ADD_CENTS * parent_count
    child_amt = CHILD_UNDER18_ADD_CENTS * child_under18
    schoolchild_amt = CHILD_SCHOOL_ADD_CENTS * child_school

    dep_sum = spouse_amt + parent_amt + child_amt + schoolchild_amt
    dep_scaled = round_half_up(Decimal(dep_sum) * Decimal(combined_rating_pct) / Decimal(100))
    return base + dep_scaled


# ---------------------------------------------------------------------------
# rate_of_pursuit + housing_allowance (PRD §3.11 / §3.12 / SCAFFOLD §1.3)
# ---------------------------------------------------------------------------

def rate_of_pursuit(credit_hours, full_time_credit_hours):
    """round_half_up(100 * credit_hours / full_time_credit_hours) (PRD §3.11)."""
    value = Decimal(str(100)) * Decimal(str(credit_hours)) / Decimal(str(full_time_credit_hours))
    return round_half_up(value)


def housing_allowance(monthly_housing_rate_cents, gi_bill_tier_pct, rate_of_pursuit_pct):
    """Monthly Housing Allowance for a term (PRD §3.11 / §3.12).

    Paid only when rate_of_pursuit_pct is strictly greater than 50. Two pinned
    rounding steps: round the tier basis first, then round after scaling by the
    rate of pursuit.
    """
    if rate_of_pursuit_pct <= RATE_OF_PURSUIT_FLOOR_PCT:
        return 0
    tier_basis = round_half_up(
        Decimal(monthly_housing_rate_cents) * Decimal(gi_bill_tier_pct) / Decimal(100)
    )
    mha = round_half_up(
        Decimal(tier_basis) * Decimal(rate_of_pursuit_pct) / Decimal(100)
    )
    return mha


# ---------------------------------------------------------------------------
# yellow_ribbon_match (PRD §3.12 / SCAFFOLD §1.3)
# ---------------------------------------------------------------------------

def yellow_ribbon_match(tuition_charged_cents, school_max_contribution_cents, gi_bill_tier_pct):
    """VA Yellow Ribbon match (PRD §3.12).

    Only a veteran at the full 100 percent tier is eligible. The school's
    contribution is the smaller of half the uncovered tuition and the school's
    per-student cap, rounded half-up; the VA matches it dollar-for-dollar, so the
    stored match equals that rounded school contribution.
    """
    if gi_bill_tier_pct != 100:
        return 0
    uncovered = tuition_charged_cents
    half = Decimal(uncovered) / Decimal(2)
    school_contrib_raw = min(half, Decimal(school_max_contribution_cents))
    school_contrib = round_half_up(school_contrib_raw)
    return school_contrib  # VA matches dollar-for-dollar
