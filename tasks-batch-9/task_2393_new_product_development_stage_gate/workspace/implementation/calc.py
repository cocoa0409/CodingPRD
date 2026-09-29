"""The ten calculations of PRD §3, plus the single rounding primitive.

Every computed number is produced by round half up — ties away from zero — at
the scale §2.7 pins for it, and rounding is applied at each named step rather
than once at the end. All arithmetic uses ``decimal.Decimal``; no float ever
touches a stored figure.
"""

from decimal import Decimal, ROUND_HALF_UP

ZERO = Decimal("0")
D2 = Decimal("0.01")
D4 = Decimal("0.0001")
D0 = Decimal("1")

# --- constants --------------------------------------------------------------
MARGIN_TARGET_PCT = Decimal("40")
SCREENING_PASS_FLOOR = Decimal("60.00")
SCREENING_WEIGHTS = {
    "NEW_BRAND": (Decimal("0.30"), Decimal("0.30"), Decimal("0.25"), Decimal("0.15")),
    "LINE_EXTENSION": (Decimal("0.30"), Decimal("0.25"), Decimal("0.30"), Decimal("0.15")),
    "RENOVATION": (Decimal("0.20"), Decimal("0.35"), Decimal("0.25"), Decimal("0.20")),
}

INTENT_WEIGHT = Decimal("0.60")
UNIQUE_WEIGHT = Decimal("0.40")

WEEKS_PER_YEAR = Decimal("52")
GROWTH_Y2 = Decimal("1.15")
GROWTH_Y3 = Decimal("1.08")
PAYBACK_NEVER = 999
PAYBACK_HORIZON_MONTHS = 36

EMPTY_CHECKLIST_RESULT = Decimal("100.00")

READINESS_WEIGHTS = {
    "NEW_BRAND": (Decimal("0.35"), Decimal("0.30"), Decimal("0.20"), Decimal("0.15")),
    "LINE_EXTENSION": (Decimal("0.30"), Decimal("0.25"), Decimal("0.25"), Decimal("0.20")),
    "RENOVATION": (Decimal("0.40"), Decimal("0.20"), Decimal("0.20"), Decimal("0.20")),
}
CATEGORY_FACTOR = {
    "BEVERAGE": Decimal("1.00"),
    "SNACK": Decimal("1.00"),
    "DAIRY": Decimal("0.95"),
    "HOUSEHOLD": Decimal("1.05"),
}
INDEX_CAP = Decimal("100.00")

PILOT_YIELD_FLOOR_PCT = Decimal("85.00")
STABILITY_TARGET_FLOOR = Decimal("70.00")
STABILITY_ABSOLUTE_FLOOR = Decimal("60.00")

LAUNCH_READINESS_WEIGHTS = {
    "MANUFACTURING_READINESS": Decimal("0.35"),
    "DISTRIBUTION_READINESS": Decimal("0.25"),
    "MARKETING_LAUNCH_PLAN": Decimal("0.20"),
    "SALES_SELL_IN_PLAN": Decimal("0.20"),
}
LOCK_LEAD_DAYS = 45

PERIODS_PER_YEAR = Decimal("4")
CONTINUE_FLOOR_PCT = Decimal("90.00")
FIX_FLOOR_PCT = Decimal("70.00")

HUNDRED = Decimal("100")


def rhu(value, places=2):
    """Round half up — ties away from zero — at ``places`` decimals."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    exp = Decimal(1).scaleb(-places)
    return value.quantize(exp, rounding=ROUND_HALF_UP)


def money(value):
    return rhu(value, 2)


def price(value):
    return rhu(value, 4)


def whole(value):
    return int(rhu(value, 0))


# ---------------------------------------------------------------------------
# 1. screening_score
# ---------------------------------------------------------------------------
def screening_score(project_type, strategic_fit, consumer_need,
                    target_gross_margin_pct, category_attractiveness):
    margin_norm = rhu(target_gross_margin_pct / MARGIN_TARGET_PCT * HUNDRED, 4)
    if margin_norm > HUNDRED:
        margin_norm = HUNDRED
    w_fit, w_need, w_margin, w_cat = SCREENING_WEIGHTS[project_type]
    total = (
        w_fit * strategic_fit * Decimal("10")
        + w_need * consumer_need * Decimal("10")
        + w_margin * margin_norm
        + w_cat * category_attractiveness * Decimal("10")
    )
    return money(total)


# ---------------------------------------------------------------------------
# 2. concept_score
# ---------------------------------------------------------------------------
def concept_score(purchase_intent_top2_pct, uniqueness_pct, sample_size):
    if sample_size >= 300:
        confidence = Decimal("1.00")
    elif sample_size >= 100:
        confidence = Decimal("0.95")
    else:
        confidence = Decimal("0.85")
    blended = INTENT_WEIGHT * purchase_intent_top2_pct + UNIQUE_WEIGHT * uniqueness_pct
    return money(blended * confidence)


# ---------------------------------------------------------------------------
# 3. forecast_volume_and_revenue
# ---------------------------------------------------------------------------
def forecast_line_figures(line):
    """Per-line units and revenue, each rounded BEFORE any summation."""
    effective_weeks = (
        WEEKS_PER_YEAR
        + Decimal(line["promo_weeks"]) * line["promo_lift_pct"] / HUNDRED
    )
    raw_units = (
        Decimal(line["store_count"])
        * line["base_velocity_units_per_store_week"]
        * effective_weeks
    )
    line_units = whole(raw_units)
    line_revenue = money(Decimal(line_units) * line["list_price_usd"])
    return line_units, line_revenue


def forecast_volume_and_revenue(case, lines):
    """Returns ``(annual_units, gross_revenue_usd, avg_list_price_usd)``."""
    total_stores = sum(Decimal(l["store_count"]) for l in lines)
    if lines and total_stores > 0:
        weighted = sum(l["list_price_usd"] * Decimal(l["store_count"]) for l in lines)
        avg_list_price = price(weighted / total_stores)
    else:
        avg_list_price = price(ZERO)

    if not lines:
        return 0, money(ZERO), avg_list_price

    if case["variant_mode"] == "BOTTOM_UP":
        annual_units = sum(l["line_units"] for l in lines)
        gross_revenue = money(sum(l["line_revenue_usd"] for l in lines))
    else:
        annual_units = whole(
            Decimal(case["category_size_units_year"]) * case["target_share_pct"] / HUNDRED
        )
        gross_revenue = money(Decimal(annual_units) * avg_list_price)
    return annual_units, gross_revenue, avg_list_price


# ---------------------------------------------------------------------------
# 4. business_case_financials
# ---------------------------------------------------------------------------
def trade_spend_rate(gross_revenue_usd):
    if gross_revenue_usd >= Decimal("5000000.00"):
        return Decimal("15.00")
    if gross_revenue_usd >= Decimal("1000000.00"):
        return Decimal("12.00")
    return Decimal("10.00")


def business_case_financials(annual_units, gross_revenue_usd, cogs_per_unit_usd,
                             slotting_fees_usd, capex_usd, discount_rate_pct):
    rate = trade_spend_rate(gross_revenue_usd)
    trade_spend = money(gross_revenue_usd * rate / HUNDRED)
    net_revenue = money(gross_revenue_usd - trade_spend - slotting_fees_usd)
    cogs_total = money(Decimal(annual_units) * cogs_per_unit_usd)
    gross_margin = money(net_revenue - cogs_total)
    if net_revenue == 0:
        gross_margin_pct = money(ZERO)
    else:
        gross_margin_pct = money(gross_margin / net_revenue * HUNDRED)

    cf1 = gross_margin
    cf2 = money(cf1 * GROWTH_Y2)
    cf3 = money(cf2 * GROWTH_Y3)

    factor = Decimal("1") + discount_rate_pct / HUNDRED
    npv = money(
        money(cf1 / factor)
        + money(cf2 / (factor * factor))
        + money(cf3 / (factor * factor * factor))
        - capex_usd
    )

    payback = PAYBACK_NEVER
    running = money(ZERO)
    flows = (cf1, cf2, cf3)
    for month in range(1, PAYBACK_HORIZON_MONTHS + 1):
        flow = flows[(month - 1) // 12]
        running = running + money(flow / Decimal("12"))
        if running >= capex_usd:
            payback = month
            break

    return {
        "trade_spend_rate_pct": rate,
        "trade_spend_usd": trade_spend,
        "net_revenue_usd": net_revenue,
        "cogs_total_usd": cogs_total,
        "gross_margin_usd": gross_margin,
        "gross_margin_pct": gross_margin_pct,
        "npv_usd": npv,
        "payback_months": payback,
    }


# ---------------------------------------------------------------------------
# 5. deliverable_completeness_pct
# ---------------------------------------------------------------------------
def deliverable_completeness_pct(required_types, satisfied_types):
    if not required_types:
        return EMPTY_CHECKLIST_RESULT
    satisfied = sum(1 for t in required_types if t in satisfied_types)
    return money(Decimal(satisfied) / Decimal(len(required_types)) * HUNDRED)


# ---------------------------------------------------------------------------
# 6. gate_readiness_index
# ---------------------------------------------------------------------------
def gate_readiness_index(project_type, category, completeness, concept, hurdle, yield_sub):
    if yield_sub > INDEX_CAP:
        yield_sub = INDEX_CAP
    w_c, w_k, w_h, w_y = READINESS_WEIGHTS[project_type]
    base = w_c * completeness + w_k * concept + w_h * hurdle + w_y * yield_sub
    value = money(base * CATEGORY_FACTOR[category])
    return value if value <= INDEX_CAP else INDEX_CAP


# ---------------------------------------------------------------------------
# 7. shelf_life_verdict
# ---------------------------------------------------------------------------
def shelf_life_verdict(timepoints, min_quality_score, target_shelf_life_days):
    target_point = None
    for point in timepoints:
        if point["day_index"] <= target_shelf_life_days:
            if target_point is None or point["day_index"] > target_point["day_index"]:
                target_point = point
    if (
        target_point is not None
        and target_point["quality_score"] >= STABILITY_TARGET_FLOOR
        and min_quality_score is not None
        and min_quality_score >= STABILITY_ABSOLUTE_FLOOR
    ):
        return "PASS"
    return "FAIL"


# ---------------------------------------------------------------------------
# 8. yield_pct
# ---------------------------------------------------------------------------
def yield_pct(actual_units, planned_units):
    return money(Decimal(actual_units) / Decimal(planned_units) * HUNDRED)


# ---------------------------------------------------------------------------
# 9. launch_readiness_pct
# ---------------------------------------------------------------------------
def launch_readiness_pct(required_types, approved_types):
    denominator = sum(
        (LAUNCH_READINESS_WEIGHTS[t] for t in required_types), ZERO
    )
    if denominator == 0:
        return money(ZERO)
    numerator = sum(
        (LAUNCH_READINESS_WEIGHTS[t] for t in required_types if t in approved_types),
        ZERO,
    )
    return money(numerator / denominator * HUNDRED)


# ---------------------------------------------------------------------------
# 10. post_launch_attainment
# ---------------------------------------------------------------------------
def plan_units_per_period(annual_units):
    return money(Decimal(annual_units) / PERIODS_PER_YEAR)


def post_launch_attainment(plan_units, cumulative_actual, actual_units, period_index):
    if plan_units == 0:
        return money(ZERO), money(ZERO)
    cumulative = money(
        Decimal(cumulative_actual) / (plan_units * Decimal(period_index)) * HUNDRED
    )
    trailing = money(Decimal(actual_units) / plan_units * HUNDRED)
    return cumulative, trailing


def post_launch_decision(attainment_pct):
    if attainment_pct >= CONTINUE_FLOOR_PCT:
        return "CONTINUE"
    if attainment_pct >= FIX_FLOOR_PCT:
        return "FIX"
    return "DISCONTINUE"


# ---------------------------------------------------------------------------
# committed_development_budget
# ---------------------------------------------------------------------------
LIVE_RUN_STATUSES = ("SCHEDULED", "RUNNING", "COMPLETED")
LIVE_STUDY_STATUSES = ("ACTIVE", "PASSED", "FAILED")


def committed_development_budget(run_costs, study_costs):
    return money(sum(run_costs, ZERO) + sum(study_costs, ZERO))
