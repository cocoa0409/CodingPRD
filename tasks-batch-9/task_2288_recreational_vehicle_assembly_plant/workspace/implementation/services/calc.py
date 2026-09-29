"""The twelve calculations of SCAFFOLD §1.3 / PRD §3, at the stated precision.

Every money figure is an integer number of cents. Every hours figure is a
Decimal carrying exactly two decimal places. ROUND_HALF_UP is applied exactly
where the contract says and nowhere else; the single floor in the system is
credit_utilization_bp.
"""
from decimal import Decimal, ROUND_HALF_UP

import constants as C

ZERO = Decimal("0")
TWO_DP = Decimal("0.01")


def rhu(value, places=0):
    """ROUND_HALF_UP to `places` decimals."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quant = Decimal(1).scaleb(-places)
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def rhu_cents(value):
    """A whole number of cents."""
    return int(rhu(value, 0))


def rhu2(value):
    """A two-decimal hours/score figure."""
    return rhu(value, 2)


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# 1. unit_order_configuration_totals
# ---------------------------------------------------------------------------
def complexity_factor(option_count):
    if option_count <= C.COMPLEXITY_FACTOR_TIER_1_MAX_OPTIONS:
        return C.COMPLEXITY_FACTOR_TIER_1
    if option_count <= C.COMPLEXITY_FACTOR_TIER_2_MAX_OPTIONS:
        return C.COMPLEXITY_FACTOR_TIER_2
    if option_count <= C.COMPLEXITY_FACTOR_TIER_3_MAX_OPTIONS:
        return C.COMPLEXITY_FACTOR_TIER_3
    return C.COMPLEXITY_FACTOR_TIER_4


def configuration_totals(floor_plan, options):
    option_price_total = sum(int(o["price_cents"]) for o in options)
    option_weight = sum(int(o["weight_lbs"]) for o in options)
    config_weight = int(floor_plan["base_dry_weight_lbs"]) + option_weight
    payload_remaining = int(floor_plan["gvwr_lbs"]) - config_weight
    total_amp_draw = sum(int(o["amp_draw"]) for o in options)
    total_water_demand = sum(int(o["water_demand_gal"]) for o in options)

    raw_hours = dec(floor_plan["base_station_hours"])
    for o in options:
        raw_hours += dec(o["added_station_hours"])

    surcharge = (
        C.ELECTRICAL_SURCHARGE_HOURS
        if total_amp_draw > C.ELECTRICAL_SURCHARGE_AMP_THRESHOLD
        else Decimal("0.00")
    )
    required_hours = rhu2(
        raw_hours * complexity_factor(len(options)) * C.CLASS_FACTOR[floor_plan["chassis_class"]]
        + surcharge
    )
    return {
        "option_price_total_cents": option_price_total,
        "config_weight_lbs": config_weight,
        "payload_remaining_lbs": payload_remaining,
        "total_amp_draw": total_amp_draw,
        "total_water_demand_gal": total_water_demand,
        "required_station_hours": required_hours,
    }


def water_ceiling_gal(floor_plan):
    return rhu_cents(
        dec(floor_plan["fresh_water_capacity_gal"]) * C.WATER_DEMAND_RATIO_BP / Decimal(10000)
    )


# ---------------------------------------------------------------------------
# 2. dealer_invoice_amount
# ---------------------------------------------------------------------------
def _line_net(gross_cents, bp):
    return rhu_cents(dec(gross_cents) * (Decimal(10000) - Decimal(bp)) / Decimal(10000))


def discounted_subtotal_cents(floor_plan, order_type, option_lines):
    """option_lines: iterable of (option_code, category, price_cents), any order."""
    total = _line_net(floor_plan["base_msrp_cents"], C.BASE_UNIT_DISCOUNT_BP[order_type])
    for _code, category, price in sorted(option_lines, key=lambda t: t[0]):
        total += _line_net(price, C.OPTION_DISCOUNT_BP[category])
    return total


def freight_cents(floor_plan, region):
    return (
        C.FREIGHT_BASE_CENTS
        + C.FREIGHT_PER_FOOT_CENTS * int(floor_plan["length_ft"])
        + C.REGION_SURCHARGE_CENTS[region]
    )


def invoice_cents(floor_plan, order_type, option_lines, region, build=None, required_hours=None):
    """PROVISIONAL_AT_SUBMIT when build is None, else FINAL_AT_SHIP."""
    subtotal = discounted_subtotal_cents(floor_plan, order_type, option_lines)
    freight = freight_cents(floor_plan, region)
    overtime = 0
    rework = 0
    credit = 0
    if build is not None:
        excess = dec(build["actual_station_hours"]) - dec(required_hours)
        if excess < ZERO:
            excess = ZERO
        overtime = rhu_cents(excess * Decimal(C.OT_RATE_CENTS_PER_HOUR))
        rework = int(build["rework_count"]) * C.REWORK_SURCHARGE_CENTS
        credit = min(
            int(build["defect_points_total"]) * C.QUALITY_CREDIT_PER_POINT_CENTS,
            C.QUALITY_CREDIT_CAP_CENTS,
        )
    return subtotal + freight + overtime + rework - credit


# ---------------------------------------------------------------------------
# 3. warranty_claim_reimbursement
# ---------------------------------------------------------------------------
def warranty_schedule(claim):
    """Steps 1-4: labour, parts, subtotal, authority tier."""
    billable = min(dec(claim["labor_hours"]), C.LABOR_HOUR_CAP)
    labor = rhu_cents(billable * Decimal(C.LABOR_RATE_CENTS[claim["claim_type"]]))
    parts = rhu_cents(
        dec(claim["parts_cost_cents"]) * (Decimal(10000) + Decimal(C.PARTS_HANDLING_BP)) / Decimal(10000)
    )
    subtotal = labor + parts
    if subtotal <= C.TIER_A_MAX_CENTS:
        tier = "TIER_A"
    elif subtotal <= C.TIER_B_MAX_CENTS:
        tier = "TIER_B"
    else:
        tier = "TIER_C"
    return labor, parts, subtotal, tier


def warranty_goodwill(claim, subtotal, tier, dealer_remaining):
    """Step 5."""
    candidates = [
        int(claim["goodwill_requested_cents"] or 0),
        C.GOODWILL_TIER_CAP_CENTS[tier],
        rhu_cents(dec(subtotal) * Decimal(C.GOODWILL_PCT_BP) / Decimal(10000)),
        dealer_remaining,
    ]
    if not claim["in_warranty"]:
        candidates.append(C.OUT_OF_WARRANTY_GOODWILL_CAP_CENTS)
    return max(0, min(candidates))


def warranty_total(claim, subtotal, goodwill):
    """Step 6."""
    if claim["in_warranty"]:
        return subtotal + goodwill
    return goodwill


def warranty_chargeback(claim, total, supplier_status):
    """Step 7."""
    if not claim.get("component_lot_id") or supplier_status is None:
        return 0
    bp = C.CHARGEBACK_BP[supplier_status]
    return rhu_cents(dec(total) * Decimal(bp) / Decimal(10000))


# ---------------------------------------------------------------------------
# 4. supplier_quality_score
# ---------------------------------------------------------------------------
def score_from_penalty(penalty):
    value = C.SCORE_BASE - penalty
    if value < ZERO:
        value = ZERO
    return rhu2(value)


def supplier_status_for(score):
    if score >= C.SUPPLIER_ACTIVE_MIN_SCORE:
        return "ACTIVE"
    if score >= C.SUPPLIER_PROBATION_MIN_SCORE:
        return "PROBATION"
    return "SUSPENDED"


def supplier_scores(events, now):
    """events: iterable of (timestamp, Decimal weight). Returns (rolling, lifetime)."""
    rolling = ZERO
    lifetime = ZERO
    for stamp, weight in events:
        age = (now - stamp).total_seconds() // 86400
        if age < C.ROLLING_WINDOW_DAYS:
            rolling += weight
            lifetime += weight
        else:
            lifetime += weight * C.LIFETIME_DECAY_FACTOR
    return score_from_penalty(rolling), score_from_penalty(lifetime)


# ---------------------------------------------------------------------------
# 5. dealer_credit_utilization
# ---------------------------------------------------------------------------
def credit_utilization_bp(exposure_cents, credit_limit_cents):
    if not credit_limit_cents:
        return 0
    return int(exposure_cents * 10000 // credit_limit_cents)


def credit_status_for(bp):
    if bp > C.CREDIT_HOLD_BP:
        return "CREDIT_HOLD"
    if bp > C.WATCH_BP:
        return "WATCH"
    return "GOOD_STANDING"


# ---------------------------------------------------------------------------
# 8. floor_plan_curtailment_due
# ---------------------------------------------------------------------------
def curtailment_required_bp(age_days):
    if age_days >= C.CURTAIL_STAGE_3_DAYS:
        return C.CURTAIL_STAGE_3_BP
    if age_days >= C.CURTAIL_STAGE_2_DAYS:
        return C.CURTAIL_STAGE_2_BP
    if age_days >= C.CURTAIL_STAGE_1_DAYS:
        return C.CURTAIL_STAGE_1_BP
    return 0


def curtailment_due(principal_cents, paid_cents, age_days):
    bp = curtailment_required_bp(age_days)
    required = rhu_cents(dec(principal_cents) * Decimal(bp) / Decimal(10000))
    return max(0, required - int(paid_cents))


# ---------------------------------------------------------------------------
# 9. dealer_slot_entitlement
# ---------------------------------------------------------------------------
def plant_month_hours(lines):
    total = ZERO
    for line in lines:
        if line["status"] in ("RUNNING", "PAUSED"):
            total += dec(line["daily_station_hour_capacity"])
    return rhu2(total * Decimal(C.WORKING_DAYS_PER_MONTH))


def entitlement_hours(lines, allocation_share_bp):
    month = plant_month_hours(lines)
    return rhu2(month * Decimal(allocation_share_bp) / Decimal(10000))


def tolerance_hours(entitled):
    return rhu2(
        dec(entitled)
        * (Decimal(10000) + Decimal(C.OVERSUBSCRIPTION_TOLERANCE_BP))
        / Decimal(10000)
    )


# ---------------------------------------------------------------------------
# 12. inspection_grade
# ---------------------------------------------------------------------------
def inspection_grade(inspection_type, defect_points, leak_detected):
    if leak_detected:
        return "FAIL"
    if inspection_type in ("WATER_TEST", "FUNCTIONAL"):
        if defect_points > C.WET_FAIL_MAX_POINTS:
            return "FAIL"
        if defect_points >= C.WET_CONDITIONAL_MIN_POINTS:
            return "CONDITIONAL"
        return "PASS"
    if defect_points > C.PDI_FAIL_MAX_POINTS:
        return "FAIL"
    if defect_points >= C.PDI_CONDITIONAL_MIN_POINTS:
        return "CONDITIONAL"
    return "PASS"
