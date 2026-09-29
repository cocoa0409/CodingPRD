"""Every calculation rule of PRD section 3, with the pinned rounding moments."""

from decimal import Decimal, ROUND_HALF_UP

ZERO = Decimal(0)
ONE = Decimal(1)


def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value):
    """Round half up to a whole cent (integer)."""
    return int(D(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def ceil_to_multiple(value, multiple):
    return -((-int(value)) // int(multiple)) * int(multiple)


# ---------------------------------------------------------------------------
# facility_fee (PRD section 3.1)
# ---------------------------------------------------------------------------
MAX_COMBINED_DISCOUNT_PCT = D("0.30")
CAPACITY_SURCHARGE_FREE_SEATS = 1200
CAPACITY_SURCHARGE_CENTS_PER_SEAT = 25


def facility_fee(space, performance_day_count, load_in_day_count, is_nonprofit):
    base_cents = (
        space["base_facility_fee_cents"] * performance_day_count
        + space["load_in_day_fee_cents"] * load_in_day_count
    )
    if performance_day_count >= 5:
        multi_day_pct = D("0.15")
    elif performance_day_count >= 3:
        multi_day_pct = D("0.10")
    else:
        multi_day_pct = ZERO
    nonprofit_pct = D("0.20") if is_nonprofit else ZERO
    combined_pct = min(MAX_COMBINED_DISCOUNT_PCT, multi_day_pct + nonprofit_pct)
    discounted_cents = rhu(D(base_cents) * (ONE - combined_pct))
    surcharge = (
        max(0, space["seat_capacity"] - CAPACITY_SURCHARGE_FREE_SEATS)
        * CAPACITY_SURCHARGE_CENTS_PER_SEAT
    )
    return discounted_cents + surcharge


# ---------------------------------------------------------------------------
# deposit_requirement (PRD section 3.1)
# ---------------------------------------------------------------------------
DEPOSIT_FLOOR_CENTS = 50000
DEPOSIT_ROUNDING_MULTIPLE_CENTS = 100
DEPOSIT_PCT = {"A": D("0.25"), "B": D("0.50"), "C": D("1.00")}


def deposit_requirement(engagement, client):
    if engagement["engagement_type"] == "PRESENTED":
        return 0
    deposit_pct = DEPOSIT_PCT[client["credit_rating"]]
    core_cents = engagement["facility_fee_cents"] + engagement["labor_estimate_total_cents"]
    raw_cents = rhu(deposit_pct * D(core_cents))
    if client["outstanding_balance_cents"] > 0:
        raw_cents = raw_cents + engagement["additional_equipment_cost_cents"]
    rounded_up = ceil_to_multiple(raw_cents, DEPOSIT_ROUNDING_MULTIPLE_CENTS)
    return max(DEPOSIT_FLOOR_CENTS, rounded_up)


# ---------------------------------------------------------------------------
# labor_cost (PRD section 3.4)
# ---------------------------------------------------------------------------
OVERTIME_THRESHOLD_HOURS = D(8)
DOUBLETIME_THRESHOLD_HOURS = D(12)
MEAL_BREAK_LIMIT_HOURS = D(5)


def labor_cost(department, hours, crew_size, variant, meal_break_taken=None):
    h = D(hours)
    billable_h = max(h, D(department["call_minimum_hours"]))
    st_h = min(billable_h, OVERTIME_THRESHOLD_HOURS)
    ot_h = min(
        max(billable_h - OVERTIME_THRESHOLD_HOURS, ZERO),
        DOUBLETIME_THRESHOLD_HOURS - OVERTIME_THRESHOLD_HOURS,
    )
    dt_h = max(billable_h - DOUBLETIME_THRESHOLD_HOURS, ZERO)
    rate = D(department["straight_hourly_rate_cents"])
    per_crew_cents = (
        rhu(st_h * rate)
        + rhu(ot_h * rate * D(department["overtime_multiplier"]))
        + rhu(dt_h * rate * D(department["doubletime_multiplier"]))
    )
    penalty_cents = 0
    if variant == "ACTUAL" and h > MEAL_BREAK_LIMIT_HOURS and meal_break_taken is False:
        penalty_cents = department["meal_penalty_cents"]
    return (per_crew_cents + penalty_cents) * crew_size


def scheduled_hours(start_dt, end_dt):
    hours = D((end_dt - start_dt).total_seconds()) / D(3600)
    return hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# engagement_margin (PRD section 3.5)
# ---------------------------------------------------------------------------
MARKETING_FLAT_CENTS = 250000


def projected_gross(active_tiers_in_order, sell_through):
    total = 0
    st = D(sell_through)
    for tier in active_tiers_in_order:
        total += rhu(D(tier["base_price_cents"]) * D(tier["seats_allocated"]) * st)
    return total


def projected_costs(fee_basis_cents, engagement):
    return (
        fee_basis_cents
        + engagement["labor_estimate_total_cents"]
        + engagement["additional_equipment_cost_cents"]
        + MARKETING_FLAT_CENTS
    )


# ---------------------------------------------------------------------------
# financial_risk_score (PRD section 3.5)
# ---------------------------------------------------------------------------
ROUTING_SLACK_TARGET_DAYS = D(14)
LEAD_TARGET_DAYS = D(120)
CREDIT_FACTOR = {"C": D("1.00"), "B": D("0.50"), "A": D("0.00")}


def presented_risk_score(fee_basis_cents, gross_cents, routing_slack_days, lead_days,
                         historical_sell_through_pct):
    fee_exposure_ratio = D(fee_basis_cents) / D(max(1, gross_cents))
    term1 = D("0.45") * min(ONE, fee_exposure_ratio)
    slack = max(D(0), D(routing_slack_days))
    term2 = D("0.25") * (ONE - min(ONE, slack / ROUTING_SLACK_TARGET_DAYS))
    lead = max(D(0), D(lead_days))
    term3 = D("0.20") * (ONE - min(ONE, lead / LEAD_TARGET_DAYS))
    term4 = D("0.10") * (ONE - D(historical_sell_through_pct))
    return rhu(D(100) * (term1 + term2 + term3 + term4))


def rental_risk_score(credit_rating, outstanding_balance_cents, deposit_required_cents, lead_days):
    credit_factor = CREDIT_FACTOR[credit_rating]
    arrears_ratio = D(outstanding_balance_cents) / D(max(1, deposit_required_cents))
    term1 = D("0.50") * credit_factor
    term2 = D("0.30") * min(ONE, arrears_ratio)
    lead = max(D(0), D(lead_days))
    term3 = D("0.20") * (ONE - min(ONE, lead / LEAD_TARGET_DAYS))
    return rhu(D(100) * (term1 + term2 + term3))


def risk_band(score):
    if score >= 75:
        return "PROHIBITIVE"
    if score >= 55:
        return "HIGH"
    if score >= 35:
        return "MODERATE"
    return "LOW"


def resolve_clearance(tier, override_escalation, current_clearance):
    if tier == "PROHIBITIVE":
        return "BLOCKED"
    if tier == "HIGH" and override_escalation is True and current_clearance == "ESCALATED":
        return "ESCALATED_APPROVED"
    if tier == "HIGH":
        return "ESCALATED"
    return "CLEARED"


# ---------------------------------------------------------------------------
# technical_capability_assessment (PRD section 3.3)
# ---------------------------------------------------------------------------
RIGGING_NEAR_LIMIT_PCT = D("0.90")


def capability_assessment(rider, space):
    if rider["submitted_rigging_kg"] > space["rigging_capacity_kg"]:
        return "REJECTED_INFEASIBLE", ["RIGGING_OVER_CAPACITY"]
    gaps = []
    near_limit_threshold_kg = rhu(RIGGING_NEAR_LIMIT_PCT * D(space["rigging_capacity_kg"]))
    if rider["submitted_rigging_kg"] >= near_limit_threshold_kg:
        gaps.append("RIGGING_NEAR_LIMIT")
    if rider["requested_power_amps"] > space["house_power_amps"]:
        gaps.append("POWER_SHORTFALL")
    if rider["requested_dmx_universes"] > space["dmx_universes"]:
        gaps.append("DMX_SHORTFALL")
    return ("GAP_IDENTIFIED" if gaps else "CAPABLE"), gaps


# ---------------------------------------------------------------------------
# dynamic_single_ticket_price (PRD section 3.6)
# ---------------------------------------------------------------------------
DYNAMIC_MID_BAND = D("0.60")
DYNAMIC_HIGH_BAND = D("0.85")
DYNAMIC_MID_MULTIPLIER = D("1.15")
DYNAMIC_HIGH_MULTIPLIER = D("1.30")
CAPITAL_RESTORATION_FEE_CENTS = 200


def dynamic_price(tier, qty):
    sell_through_before = (
        D(tier["sold_qty"]) / D(tier["seats_allocated"])
    ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    if tier["dynamic_pricing_enabled"] is False:
        multiplier = D("1.00")
    elif sell_through_before >= DYNAMIC_HIGH_BAND:
        multiplier = DYNAMIC_HIGH_MULTIPLIER
    elif sell_through_before >= DYNAMIC_MID_BAND:
        multiplier = DYNAMIC_MID_MULTIPLIER
    else:
        multiplier = D("1.00")
    unit_price_cents = min(rhu(D(tier["base_price_cents"]) * multiplier), tier["price_ceiling_cents"])
    gross_cents = unit_price_cents * qty
    restoration_fee_cents = CAPITAL_RESTORATION_FEE_CENTS * qty
    return sell_through_before, multiplier, unit_price_cents, gross_cents, restoration_fee_cents


# ---------------------------------------------------------------------------
# subscription_price_allocation (PRD section 3.6)
# ---------------------------------------------------------------------------
def subscription_allocation(ordered_pairs, package_price_cents, seats_per_order):
    """ordered_pairs: [(engagement, tier)] already in the pinned order."""
    faces = [tier["base_price_cents"] * seats_per_order for _eng, tier in ordered_pairs]
    face_total = sum(faces)
    allocations = []
    for face in faces:
        if face_total <= 0:
            allocations.append(0)
        else:
            allocations.append(int((D(package_price_cents) * D(face)) / D(face_total)))
    remainder = package_price_cents - sum(allocations)
    if allocations:
        allocations[0] += remainder
    return allocations


# ---------------------------------------------------------------------------
# settlement_financials (PRD section 3.8)
# ---------------------------------------------------------------------------
EXPENSE_CAP_BAND1_MAX = 2000000
EXPENSE_CAP_BAND1_CENTS = 300000
EXPENSE_CAP_BAND2_MAX = 5000000
EXPENSE_CAP_BAND2_CENTS = 600000
EXPENSE_CAP_HIGH_PCT = D("0.12")
RESERVE_HIGH_BAND_CENTS = 1000000
RESERVE_HIGH_PCT = D("0.10")
RESERVE_BASE_PCT = D("0.05")
SERVICE_MARKUP_PCT = D("0.15")


def _reserve_pct(net_to_center_cents):
    if net_to_center_cents >= RESERVE_HIGH_BAND_CENTS:
        return RESERVE_HIGH_PCT
    if net_to_center_cents >= 0:
        return RESERVE_BASE_PCT
    return ZERO


def settlement_presented(settlement, artist_share_pct):
    out = {}
    adjusted = settlement["box_office_gross_cents"] - settlement["restoration_fees_cents"]
    out["adjusted_gross_cents"] = adjusted
    if adjusted < EXPENSE_CAP_BAND1_MAX:
        cap = EXPENSE_CAP_BAND1_CENTS
    elif adjusted < EXPENSE_CAP_BAND2_MAX:
        cap = EXPENSE_CAP_BAND2_CENTS
    else:
        cap = rhu(EXPENSE_CAP_HIGH_PCT * D(adjusted))
    out["reimbursable_expense_cap_cents"] = cap
    eligible = settlement["actual_marketing_cents"] + settlement["actual_equipment_cents"]
    reimbursable = min(eligible, cap)
    out["reimbursable_expenses_cents"] = reimbursable
    overage = max(0, adjusted - settlement["guarantee_cents"] - reimbursable)
    artist_share = rhu(D(artist_share_pct) * D(overage))
    out["artist_share_cents"] = artist_share
    net = (
        adjusted
        - settlement["guarantee_cents"]
        - reimbursable
        - artist_share
        - settlement["actual_labor_cents"]
    )
    out["net_to_center_cents"] = net
    out["reserve_contribution_cents"] = (
        rhu(_reserve_pct(net) * D(max(0, net))) + settlement["restoration_fees_cents"]
    )
    out["amount_payable_to_artist_cents"] = settlement["guarantee_cents"] + artist_share
    out["balance_due_from_client_cents"] = 0
    return out


def settlement_rental(settlement, facility_fee_cents, deposit_paid_cents):
    out = {
        "adjusted_gross_cents": 0,
        "guarantee_cents": 0,
        "reimbursable_expense_cap_cents": 0,
        "reimbursable_expenses_cents": 0,
        "artist_share_cents": 0,
    }
    service_charges = rhu(
        (ONE + SERVICE_MARKUP_PCT)
        * D(settlement["actual_labor_cents"] + settlement["actual_equipment_cents"])
    )
    charges = facility_fee_cents + service_charges + settlement["actual_marketing_cents"]
    out["balance_due_from_client_cents"] = charges - deposit_paid_cents
    net = charges - settlement["actual_labor_cents"] - settlement["actual_equipment_cents"]
    out["net_to_center_cents"] = net
    out["reserve_contribution_cents"] = rhu(_reserve_pct(net) * D(max(0, net)))
    out["amount_payable_to_artist_cents"] = 0
    return out


# ---------------------------------------------------------------------------
# education_subsidy_allowance (PRD section 3.7)
# ---------------------------------------------------------------------------
SUBSIDY_BASE = {
    "STUDENT_MATINEE": 400000,
    "MASTERCLASS": 150000,
    "COMMUNITY_WORKSHOP": 250000,
}
SUBSIDY_PER_PARTICIPANT_CENTS = 1500
EDUCATION_RESERVE_FLOOR_CENTS = 5000000


def education_subsidy(program_type, participant_capacity, subsidy_requested_cents):
    base_cents = SUBSIDY_BASE[program_type]
    allowance_cents = base_cents + SUBSIDY_PER_PARTICIPANT_CENTS * participant_capacity
    return min(subsidy_requested_cents, allowance_cents)


# ---------------------------------------------------------------------------
# cancellation_fee (PRD section 3.9)
# ---------------------------------------------------------------------------
CANCEL_BAND_NEAR_DAYS = 30
CANCEL_BAND_MID_DAYS = 90
CANCEL_NEAR_PCT = D("0.75")
CANCEL_MID_PCT = D("0.40")
CANCEL_FAR_PCT = D("0.10")


def cancellation_fee(days_to_performance, facility_fee_cents, negotiated_fee_cents):
    if days_to_performance < CANCEL_BAND_NEAR_DAYS:
        retained_pct = CANCEL_NEAR_PCT
    elif days_to_performance < CANCEL_BAND_MID_DAYS:
        retained_pct = CANCEL_MID_PCT
    else:
        retained_pct = CANCEL_FAR_PCT
    exposure_cents = facility_fee_cents + negotiated_fee_cents
    return rhu(retained_pct * D(exposure_cents))
