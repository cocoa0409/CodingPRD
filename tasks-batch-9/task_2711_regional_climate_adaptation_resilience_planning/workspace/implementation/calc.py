"""Every calculation in PRD 3, with PRD 2.6's decimal discipline.

Magnitudes round half up to their declared precision; basis-point shares are
always floored; every band is read off the ROUNDED value; all floors inclusive.
"""

from decimal import Decimal

from core import bps_share, dec, floor_int, hours, round_half_up

ONE = Decimal("1")
ZERO = Decimal("0")

# --- 3.1 social vulnerability banding ---------------------------------------

SVI_MULTIPLIER = {
    "LOW": Decimal("1.00"),
    "MODERATE": Decimal("1.10"),
    "HIGH": Decimal("1.25"),
    "SEVERE": Decimal("1.40"),
}


def svi_tier(score):
    value = dec(score)
    if value >= Decimal("0.75"):
        return "SEVERE"
    if value >= Decimal("0.50"):
        return "HIGH"
    if value >= Decimal("0.25"):
        return "MODERATE"
    return "LOW"


def disadvantaged(tier):
    return tier in ("HIGH", "SEVERE")


# --- 3.3 vulnerability score -------------------------------------------------

SUBJECT_UPLIFT = {
    "INFRASTRUCTURE": Decimal("0.00"),
    "POPULATION": Decimal("0.05"),
    "ECONOMIC_SECTOR": Decimal("0.03"),
}


def vulnerability(method, exposure_index, sensitivity, adaptive_capacity,
                  svi_overlay_applied, owner_tier, subject_type):
    exposure = dec(exposure_index)
    sens = dec(sensitivity)
    gap = ONE - dec(adaptive_capacity)
    if method == "COMPOSITE_MULTIPLICATIVE":
        rawv = exposure * sens * gap
    else:
        rawv = (Decimal("0.40") * exposure) + (Decimal("0.35") * sens) + (Decimal("0.25") * gap)
    multiplier = SVI_MULTIPLIER.get(owner_tier, ONE) if svi_overlay_applied else ONE
    value = (rawv * multiplier) + SUBJECT_UPLIFT.get(subject_type, ZERO)
    # the clamp is applied to the UNROUNDED value, then the value is rounded
    if value < ZERO:
        value = ZERO
    if value > ONE:
        value = ONE
    score = round_half_up(value, 2)
    return score, vulnerability_band(score)


def vulnerability_band(score):
    value = dec(score)
    if value >= Decimal("0.75"):
        return "EXTREME"
    if value >= Decimal("0.50"):
        return "HIGH"
    if value >= Decimal("0.25"):
        return "MODERATE"
    return "LOW"


# --- 3.4 asset criticality ---------------------------------------------------

MILLION_DOLLARS_CENTS = Decimal("100000000")
POPULATION_CAP = Decimal("250000")


def consequence(replacement_value_cents, redundancy_factor, peak_vulnerability,
                dependency_depth, is_shared, service_population):
    exposure_value_cents = round_half_up(
        dec(replacement_value_cents) * (ONE - dec(redundancy_factor)), 0
    )
    value_term = dec(exposure_value_cents) / MILLION_DOLLARS_CENTS
    capped_depth = min(int(dependency_depth), 3)
    cascade_factor = ONE + (Decimal("0.15") * capped_depth)
    sharing_factor = Decimal("1.20") if is_shared else Decimal("1.00")
    population = dec(min(int(service_population), 250000))
    population_weight = population / POPULATION_CAP
    score = round_half_up(
        value_term
        * dec(peak_vulnerability)
        * cascade_factor
        * sharing_factor
        * (ONE + population_weight),
        2,
    )
    return int(exposure_value_cents), score, criticality_tier(score)


def criticality_tier(score):
    value = dec(score)
    if value >= Decimal("25.00"):
        return "TIER_1"
    if value >= Decimal("8.00"):
        return "TIER_2"
    return "TIER_3"


TIER_POINTS = {
    "TIER_1": Decimal("1.00"),
    "TIER_2": Decimal("0.60"),
    "TIER_3": Decimal("0.30"),
}


# --- 3.5 pinned five-step cost stack ----------------------------------------

ESCALATION_BPS = {"PROTECT": 1200, "ACCOMMODATE": 800, "RETREAT": 1500, "AVOID": 500}
SCREEN_NORMALIZER_CENTS = Decimal("200000000")
SCREEN_FLOOR = Decimal("0.4500")


def admin_rate_for(escalated_cost_cents):
    """Keyed on the STEP 1 result, never on the eventual total."""
    value = int(escalated_cost_cents)
    if value < 50000000:
        return 900
    if value < 500000000:
        return 600
    return 350


def match_share_for(total_program_cost_cents):
    value = int(total_program_cost_cents)
    if value < 100000000:
        return 2500
    if value < 1000000000:
        return 3000
    return 3500


def cost_stack(base_cost_cents, strategy_type):
    escalation_bps = ESCALATION_BPS[strategy_type]
    escalated = int(
        round_half_up(dec(base_cost_cents) * (ONE + (dec(escalation_bps) / Decimal("10000"))), 0)
    )
    admin_rate_bps = admin_rate_for(escalated)
    admin_fee = int(round_half_up(dec(escalated) * (dec(admin_rate_bps) / Decimal("10000")), 0))
    total = escalated + admin_fee
    return escalated, admin_rate_bps, admin_fee, total, match_share_for(total)


def screen_score(total_program_cost_cents, cobenefit_points, feasibility_score):
    ratio = dec(total_program_cost_cents) / SCREEN_NORMALIZER_CENTS
    if ratio > ONE:
        ratio = ONE
    cost_component = ONE - ratio
    cobenefit_component = dec(cobenefit_points) / Decimal("20")
    feasibility_component = dec(feasibility_score)
    return round_half_up(
        (Decimal("0.40") * cost_component)
        + (Decimal("0.25") * cobenefit_component)
        + (Decimal("0.35") * feasibility_component),
        4,
    )


# --- 3.6 benefit-cost analysis ----------------------------------------------

OM_RATE = Decimal("0.02")


def annuity_factor(discount_rate_bps, horizon_years):
    """(1 - (1 + r) ** -n) / r, carried at full precision and never rounded."""
    rate = dec(discount_rate_bps) / Decimal("10000")
    if rate == ZERO:
        return dec(horizon_years)
    return (ONE - ((ONE + rate) ** (-int(horizon_years)))) / rate


def benefit_cost(method, discount_rate_bps, horizon_years, capital_cents, link_amounts):
    """link_amounts must already be in link_sequence ascending order."""
    capital = dec(capital_cents)
    if method == "DISCOUNTED_NPV":
        factor = annuity_factor(discount_rate_bps, horizon_years)
        benefit = 0
        for amount in link_amounts:
            benefit += int(round_half_up(dec(amount) * factor, 0))
        om = int(round_half_up(capital * OM_RATE * factor, 0))
        cost = int(capital_cents) + om
    else:
        benefit = int(sum(int(amount) for amount in link_amounts))
        annual_capital = int(round_half_up(capital / dec(horizon_years), 0))
        annual_om = int(round_half_up(capital * OM_RATE, 0))
        cost = annual_capital + annual_om
    bcr = round_half_up(dec(benefit) / dec(cost), 4) if cost != 0 else Decimal("0.0000")
    return benefit, cost, bcr, bcr >= Decimal("1.0000")


def equity_benefit_share_bps(link_rows):
    total = sum(int(row["avoided_loss_annual_cents"]) for row in link_rows)
    reaching = sum(
        int(row["avoided_loss_annual_cents"])
        for row in link_rows
        if row.get("benefit_reaches_disadvantaged")
    )
    return bps_share(reaching, total)


# --- 3.7 priority score, ledger and posture ---------------------------------

def priority_score(bcr, tiers, equity_share_bps):
    ratio = dec(bcr)
    if ratio > Decimal("3.0000"):
        ratio = Decimal("3.0000")
    ratio_component = ratio / Decimal("3.0000")
    criticality_component = ZERO
    for tier in tiers:
        points = TIER_POINTS.get(tier)
        if points is not None and points > criticality_component:
            criticality_component = points
    equity_component = dec(equity_share_bps) / Decimal("10000")
    if equity_component > Decimal("1.0000"):
        equity_component = Decimal("1.0000")
    return round_half_up(
        (Decimal("0.45") * ratio_component)
        + (Decimal("0.30") * criticality_component)
        + (Decimal("0.25") * equity_component),
        4,
    )


def funding_posture(available_cents, authorized_cents):
    if int(available_cents) == 0:
        return "CLOSED"
    if int(available_cents) > 0:
        headroom_bps = bps_share(int(available_cents), int(authorized_cents))
        if headroom_bps < 1000:
            return "OVERSUBSCRIBED"
    return "OPEN"


def indicator_attainment(reported_value, target_value):
    return round_half_up((Decimal("100") * dec(reported_value)) / dec(target_value), 2)


def implementation_status(attainment_pct):
    value = dec(attainment_pct)
    if value >= Decimal("90.00"):
        return "ON_TRACK"
    if value >= Decimal("70.00"):
        return "AT_RISK"
    return "OFF_TRACK"


# --- 3.8 engagement and endorsement -----------------------------------------

SESSION_BUFFER = hours(24)


def sessions_conflict(candidate_start, candidate_end, existing_start, existing_end):
    """Closed intervals plus a symmetric 24h travel buffer; both bounds inclusive."""
    return (
        candidate_start <= existing_end + SESSION_BUFFER
        and existing_start <= candidate_end + SESSION_BUFFER
    )


def equity_reach_bps(disadvantaged_attendee_count, attendee_count):
    return bps_share(int(disadvantaged_attendee_count), int(attendee_count))


def tally(active_weights, endorsements):
    """Returns (total_active_weight, supporting_weight, veto_weight, achieved_bps)."""
    denominator = sum(int(weight) for weight in active_weights)
    endorsed = 0
    conditioned = 0
    vetoed = 0
    for row in endorsements:
        weight = int(row.get("weight_at_cast") or 0)
        if row.get("decision") == "ENDORSED":
            endorsed += weight
        elif row.get("decision") == "CONDITIONED":
            conditioned += weight
        elif row.get("decision") == "VETOED":
            vetoed += weight
    # the halving is floored and applied ONCE to the sum of conditioned weights
    supporting = endorsed + floor_int(dec(conditioned) / Decimal("2"))
    achieved_bps = bps_share(supporting, denominator)
    return denominator, supporting, vetoed, achieved_bps


def tally_outcome(veto_weight, achieved_bps, quorum_weight_bps):
    if int(veto_weight) >= 3:
        return "BLOCKED"
    if int(achieved_bps) >= int(quorum_weight_bps):
        return "ADOPTED"
    return "SHORT"


# --- 3.9 mutual aid peak load -----------------------------------------------

def peak_unit_load(windows):
    """windows: iterable of (window_start, window_end, committed_units).

    Half-open intervals. The load is evaluated at every distinct window_start,
    summing every window that has started at or before that instant and has not
    yet ended; the peak is the largest such sum.
    """
    rows = list(windows)
    if not rows:
        return 0
    peak = 0
    for instant in sorted({row[0] for row in rows}):
        load = 0
        for start, end, units in rows:
            if start <= instant and end > instant:
                load += int(units)
        if load > peak:
            peak = load
    return peak


def peak_overlap_count(windows):
    """Largest count of simultaneously occupied half-open windows, at window starts."""
    rows = list(windows)
    if not rows:
        return 0
    peak = 0
    for instant in sorted({row[0] for row in rows}):
        count = 0
        for start, end, _units in rows:
            if start <= instant and end > instant:
                count += 1
        if count > peak:
            peak = count
    return peak
