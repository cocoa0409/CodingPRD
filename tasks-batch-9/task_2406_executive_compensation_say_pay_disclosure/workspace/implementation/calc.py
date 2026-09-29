"""Pinned arithmetic (PRD §2.5 and the formulas of §3).

Everything is Decimal; every rounding is ROUND_HALF_UP.  Money and percentage
figures carry 2 decimal places, ratios carry 4.
"""

from decimal import Decimal, ROUND_HALF_UP

MONEY_PLACES = 2
RATIO_PLACES = 4


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_half_up(value, places=MONEY_PLACES):
    return dec(value).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def money(value):
    return round_half_up(value, MONEY_PLACES)


def ratio(value):
    return round_half_up(value, RATIO_PLACES)


ZERO = money(0)
HUNDRED = money(100)

# ---------------------------------------------------------------------------
# peer_size_band_fit
# ---------------------------------------------------------------------------
REVENUE_BAND_LOW = Decimal("0.5")
REVENUE_BAND_HIGH = Decimal("2.0")
MCAP_BAND_LOW = Decimal("0.25")
MCAP_BAND_HIGH = Decimal("4.0")


def size_band_fit(issuer, peer):
    revenue_ratio = ratio(dec(peer["revenue_usd"]) / dec(issuer["revenue_usd"]))
    market_cap_ratio = ratio(dec(peer["market_cap_usd"]) / dec(issuer["market_cap_usd"]))
    in_band = (
        REVENUE_BAND_LOW <= revenue_ratio <= REVENUE_BAND_HIGH
        and MCAP_BAND_LOW <= market_cap_ratio <= MCAP_BAND_HIGH
    )
    return revenue_ratio, market_cap_ratio, in_band


# ---------------------------------------------------------------------------
# peer_group_medians  (mean-of-middles for an even count)
# ---------------------------------------------------------------------------
def mean_of_middles_median(values):
    if not values:
        return None
    ordered = sorted(values)
    count = len(ordered)
    if count % 2 == 1:
        return money(ordered[(count - 1) // 2])
    return money((ordered[count // 2 - 1] + ordered[count // 2]) / dec(2))


def size_fit_score(median_revenue, issuer_revenue):
    share = abs(dec(median_revenue) - dec(issuer_revenue)) / dec(issuer_revenue)
    if share > Decimal(1):
        share = Decimal(1)
    return money((Decimal(1) - share) * dec(100))


# ---------------------------------------------------------------------------
# benchmark_target_tdc  (nearest-rank p50 — the LOWER middle for an even count)
# ---------------------------------------------------------------------------
SIZE_ADJUST_CLAMP_LOW = Decimal("0.5")
SIZE_ADJUST_CLAMP_HIGH = Decimal("2.0")


def size_adjusted_value(issuer_revenue, peer_revenue, peer_ceo_tdc):
    factor = dec(issuer_revenue) / dec(peer_revenue)
    if factor < SIZE_ADJUST_CLAMP_LOW:
        factor = SIZE_ADJUST_CLAMP_LOW
    elif factor > SIZE_ADJUST_CLAMP_HIGH:
        factor = SIZE_ADJUST_CLAMP_HIGH
    # The factor is rounded to four places BEFORE it multiplies (PRD §2.5/§3.2).
    factor = ratio(factor)
    return money(dec(peer_ceo_tdc) * factor)


def nearest_rank_p50(values):
    if not values:
        return None
    ordered = sorted(values)
    count = len(ordered)
    index = (count + 1) // 2 - 1  # ceil(0.50 * count) - 1
    return money(ordered[index])


# ---------------------------------------------------------------------------
# target_total_direct_comp
# ---------------------------------------------------------------------------
RATIO_TIER_MID = Decimal("0.80")
RATIO_TIER_HIGH = Decimal("1.20")
LTI_MULTIPLE_LOW_RATIO = Decimal("4.0")
LTI_MULTIPLE_MID_RATIO = Decimal("3.0")
LTI_MULTIPLE_HIGH_RATIO = Decimal("2.0")
POSTURE_HIGH = Decimal("1.20")
POSTURE_LOW = Decimal("0.80")
BENCHMARK_CAP_MULTIPLE = Decimal("1.50")


def performance_based_pct(lti_pct, lti_performance_share_pct, sti_pct):
    performance_lti = money(dec(lti_pct) * dec(lti_performance_share_pct) / dec(100))
    return money(performance_lti + dec(sti_pct))


def sti_target_usd(base_salary_usd, sti_target_pct):
    return money(dec(base_salary_usd) * dec(sti_target_pct) / dec(100))


def target_direct_comp(program, executive, benchmark_target_tdc_usd):
    """The five pinned steps of PRD §3.3.  Returns a dict of program fields."""
    result = {
        "performance_based_pct": performance_based_pct(
            program["lti_pct"], program["lti_performance_share_pct"], program["sti_pct"]
        )
    }
    fixed_leg = money(
        dec(executive["base_salary_usd"])
        + sti_target_usd(executive["base_salary_usd"], executive["sti_target_pct"])
    )
    result["fixed_leg_usd"] = fixed_leg

    if benchmark_target_tdc_usd is None:
        result.update(
            {
                "benchmark_ratio": None,
                "lti_multiple": None,
                "lti_target_usd": None,
                "target_tdc_usd": None,
                "benchmark_posture": "UNBENCHMARKED",
            }
        )
        return result

    benchmark = dec(benchmark_target_tdc_usd)
    benchmark_fixed_leg = money(
        benchmark * (dec(program["salary_pct"]) + dec(program["sti_pct"])) / dec(100)
    )
    benchmark_ratio = ratio(fixed_leg / benchmark_fixed_leg)
    if benchmark_ratio < RATIO_TIER_MID:
        lti_multiple = LTI_MULTIPLE_LOW_RATIO
    elif benchmark_ratio < RATIO_TIER_HIGH:
        lti_multiple = LTI_MULTIPLE_MID_RATIO
    else:
        lti_multiple = LTI_MULTIPLE_HIGH_RATIO
    lti_target = money(fixed_leg * lti_multiple)
    target_tdc = money(fixed_leg + lti_target)
    posture_ratio = ratio(target_tdc / benchmark)
    if posture_ratio >= POSTURE_HIGH:
        posture = "ABOVE_MARKET"
    elif posture_ratio <= POSTURE_LOW:
        posture = "BELOW_MARKET"
    else:
        posture = "ALIGNED"
    result.update(
        {
            "benchmark_ratio": benchmark_ratio,
            "lti_multiple": lti_multiple,
            "lti_target_usd": lti_target,
            "target_tdc_usd": target_tdc,
            "benchmark_posture": posture,
        }
    )
    return result


# ---------------------------------------------------------------------------
# metric_payout_factor
# ---------------------------------------------------------------------------
def metric_payout_factor(metric, achieved):
    achieved = dec(achieved)
    t0 = dec(metric["threshold_value"])
    t1 = dec(metric["target_value"])
    t2 = dec(metric["maximum_value"])
    p0 = dec(metric["threshold_payout_pct"])
    p1 = dec(metric["target_payout_pct"])
    p2 = dec(metric["maximum_payout_pct"])

    if metric["direction"] == "HIGHER_IS_BETTER":
        if metric["interpolation"] == "LINEAR":
            if achieved < t0:
                factor = Decimal(0)
            elif achieved < t1:
                factor = p0 + (p1 - p0) * (achieved - t0) / (t1 - t0)
            elif achieved < t2:
                factor = p1 + (p2 - p1) * (achieved - t1) / (t2 - t1)
            else:
                factor = p2
        else:
            if achieved >= t2:
                factor = p2
            elif achieved >= t1:
                factor = p1
            elif achieved >= t0:
                factor = p0
            else:
                factor = Decimal(0)
    else:
        if metric["interpolation"] == "LINEAR":
            if achieved > t0:
                factor = Decimal(0)
            elif achieved > t1:
                factor = p0 + (p1 - p0) * (t0 - achieved) / (t0 - t1)
            elif achieved > t2:
                factor = p1 + (p2 - p1) * (t1 - achieved) / (t1 - t2)
            else:
                factor = p2
        else:
            if achieved <= t2:
                factor = p2
            elif achieved <= t1:
                factor = p1
            elif achieved <= t0:
                factor = p0
            else:
                factor = Decimal(0)
    return money(factor)


def curve_is_monotonic(direction, threshold, target, maximum):
    threshold, target, maximum = dec(threshold), dec(target), dec(maximum)
    if direction == "HIGHER_IS_BETTER":
        return threshold < target < maximum
    return threshold > target > maximum


# ---------------------------------------------------------------------------
# annual_incentive_payout
# ---------------------------------------------------------------------------
def weighted_factor(metrics, factor_of):
    """Sum of per-metric contributions, each rounded to 2dp BEFORE summing."""
    total = Decimal(0)
    for metric in metrics:
        contribution = factor_of(metric)
        if contribution is None:
            return None
        total += money(dec(contribution) * dec(metric["weight_pct"]) / dec(100))
    return money(total)


def certified_vehicle_factor(metrics):
    """None when the metric set is empty or not fully certified/restated."""
    if not metrics:
        return None
    for metric in metrics:
        if metric["status"] not in ("CERTIFIED", "RESTATED"):
            return None
        if metric["payout_factor_pct"] is None:
            return None
    return weighted_factor(metrics, lambda m: m["payout_factor_pct"])


def restated_vehicle_factor(metrics):
    if not metrics:
        return None
    return weighted_factor(
        metrics,
        lambda m: m["restated_payout_factor_pct"]
        if m["restated_payout_factor_pct"] is not None
        else m["payout_factor_pct"],
    )


def annual_incentive_earned(target_amount_usd, factor_pct, sti_max_multiple):
    uncapped = money(dec(target_amount_usd) * dec(factor_pct) / dec(100))
    cap = money(dec(target_amount_usd) * dec(sti_max_multiple))
    # The cap compares two already-rounded figures (PRD §2.5).
    return uncapped if uncapped <= cap else cap


# ---------------------------------------------------------------------------
# realized_and_realizable_pay
# ---------------------------------------------------------------------------
ASSUMED_TARGET_FACTOR_PCT = money(100)


def award_values(award, share_price_usd):
    """(realized_value_usd, realizable_value_usd) for a non-clawed-back award."""
    vehicle = award["vehicle"]
    status = award["status"]
    factor = award["certified_factor_pct"]
    effective_factor = ASSUMED_TARGET_FACTOR_PCT if factor is None else dec(factor)

    if status == "FORFEITED":
        return ZERO, ZERO

    if status == "GRANTED":
        if vehicle == "ANNUAL_INCENTIVE":
            realizable = money(
                dec(award["target_amount_usd"]) * effective_factor / dec(100)
            )
        elif vehicle == "LONG_TERM_PSU":
            realizable = money(
                dec(award["units_granted"])
                * dec(share_price_usd)
                * effective_factor
                / dec(100)
            )
        else:
            realizable = money(dec(award["units_granted"]) * dec(share_price_usd))
        return ZERO, realizable

    if status == "VESTED":
        vest_price = award["vest_price_usd"]
        if vehicle == "ANNUAL_INCENTIVE":
            realized = money(dec(award["earned_amount_usd"] or 0))
        elif vehicle == "LONG_TERM_PSU":
            effective_units = money(
                dec(award["units_granted"]) * effective_factor / dec(100)
            )
            realized = money(effective_units * dec(vest_price))
        else:
            realized = money(dec(award["units_granted"]) * dec(vest_price))
        return realized, realized

    # CLAWED_BACK: realized was set at recovery time; nothing is outstanding.
    realized = money(dec(award["realized_value_usd"]))
    return realized, realized


# ---------------------------------------------------------------------------
# pay_for_performance_alignment
# ---------------------------------------------------------------------------
ALIGNED_FLOOR = Decimal("-10.00")
WATCH_FLOOR = Decimal("-30.00")
COUNTED_AWARD_STATUSES = ("GRANTED", "VESTED", "CLAWED_BACK")


def alignment(program, counted_awards, peer_ceo_tdc_values):
    realized = money(
        sum((dec(a["realized_value_usd"]) for a in counted_awards), Decimal(0))
    )
    realizable = money(
        sum((dec(a["realizable_value_usd"]) for a in counted_awards), Decimal(0))
    )
    result = {
        "realized_pay_total_usd": realized,
        "realizable_pay_total_usd": realizable,
    }
    if not peer_ceo_tdc_values or not counted_awards:
        result.update(
            {
                "pay_percentile_rank": None,
                "degree_of_alignment": None,
                "alignment_status": "UNRATED",
            }
        )
        return result
    below = sum(1 for value in peer_ceo_tdc_values if dec(value) < realized)
    rank = money(dec(below) / dec(len(peer_ceo_tdc_values)) * dec(100))
    gap = money(dec(program["tsr_percentile_rank"]) - rank)
    if gap >= ALIGNED_FLOOR:
        status = "ALIGNED"
    elif gap >= WATCH_FLOOR:
        status = "WATCH"
    else:
        status = "MISALIGNED"
    result.update(
        {
            "pay_percentile_rank": rank,
            "degree_of_alignment": gap,
            "alignment_status": status,
        }
    )
    return result


# ---------------------------------------------------------------------------
# proxy_concern_score
# ---------------------------------------------------------------------------
MISALIGN_PIVOT = money(50)
RIGOR_PER_ADJUSTMENT = money(25)
LEVEL_MEDIUM_FLOOR = money(30)
LEVEL_HIGH_FLOOR = money(60)


def concern_components(advisor, program, adjusted_metric_count):
    gap = program["degree_of_alignment"]
    gap = ZERO if gap is None else dec(gap)
    alignment_component = MISALIGN_PIVOT - gap
    if alignment_component < ZERO:
        alignment_component = ZERO
    elif alignment_component > HUNDRED:
        alignment_component = HUNDRED
    alignment_component = money(alignment_component)

    mix_component = HUNDRED - dec(program["performance_based_pct"])
    if mix_component < ZERO:
        mix_component = ZERO
    mix_component = money(mix_component)

    rigor_component = RIGOR_PER_ADJUSTMENT * dec(adjusted_metric_count)
    if rigor_component > HUNDRED:
        rigor_component = HUNDRED
    rigor_component = money(rigor_component)

    if advisor == "ISS":
        outreach_component = None
        score = money(
            Decimal("0.50") * alignment_component
            + Decimal("0.30") * mix_component
            + Decimal("0.20") * rigor_component
        )
    else:
        outreach_component = HUNDRED - dec(program["outreach_coverage_pct"])
        if outreach_component < ZERO:
            outreach_component = ZERO
        outreach_component = money(outreach_component)
        score = money(
            Decimal("0.35") * alignment_component
            + Decimal("0.15") * mix_component
            + Decimal("0.30") * rigor_component
            + Decimal("0.20") * outreach_component
        )

    if score < LEVEL_MEDIUM_FLOOR:
        level = "LOW"
    elif score < LEVEL_HIGH_FLOOR:
        level = "MEDIUM"
    else:
        level = "HIGH"
    return {
        "alignment_component": alignment_component,
        "mix_component": mix_component,
        "rigor_component": rigor_component,
        "outreach_component": outreach_component,
        "concern_score": score,
        "concern_level": level,
        "recommendation": "AGAINST" if level == "HIGH" else "FOR",
    }


# ---------------------------------------------------------------------------
# goal_adjustment_magnitude
# ---------------------------------------------------------------------------
ADJUSTMENT_LIMIT_PCT = money("15.00")


def goal_adjustment_pct(new_target, locked_target):
    return money(
        abs(dec(new_target) - dec(locked_target)) / abs(dec(locked_target)) * dec(100)
    )


# ---------------------------------------------------------------------------
# say_on_pay_support
# ---------------------------------------------------------------------------
PASS_FLOOR = money(50)
RESPONSIVENESS_FLOOR = money(70)


def support_pct(votes_for, votes_against):
    denominator = dec(votes_for) + dec(votes_against)
    return money(dec(votes_for) / denominator * dec(100))


# ---------------------------------------------------------------------------
# outreach_coverage
# ---------------------------------------------------------------------------
COVERAGE_CAP = money(100)
REMEDIATION_COVERAGE_FLOOR = money(30)


def outreach_coverage(held_engagements_in_creation_order):
    contributors = {}
    for engagement in held_engagements_in_creation_order:
        contributors.setdefault(engagement["investor_key"], engagement)
    total = sum(
        (dec(e["ownership_pct"]) for e in contributors.values()), Decimal(0)
    )
    if total > COVERAGE_CAP:
        total = COVERAGE_CAP
    return money(total)


# ---------------------------------------------------------------------------
# clawback_recoverable_amount
# ---------------------------------------------------------------------------
def clawback_amounts(realized_value_usd, original_factor_pct, restated_factor_pct):
    realized = dec(realized_value_usd)
    original = dec(original_factor_pct)
    if original == 0:
        return money(realized), ZERO
    restated_amount = money(realized * dec(restated_factor_pct) / original)
    recoverable = money(realized - restated_amount)
    if recoverable < ZERO:
        recoverable = ZERO
    return restated_amount, recoverable


# ---------------------------------------------------------------------------
# pay_mix_reallocation
# ---------------------------------------------------------------------------
MIX_TOTAL = money(100)
MIX_COMPONENT_MIN = money(5)
MIX_COMPONENT_MAX = money(80)
MIX_FIELDS = {"SALARY": "salary_pct", "STI": "sti_pct", "LTI": "lti_pct"}
