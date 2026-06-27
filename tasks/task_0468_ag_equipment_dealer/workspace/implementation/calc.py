"""Calculation rules (PRD §3, SCAFFOLD Table 1.3). All money is integer cents.
Rounding is round-half-up via decimal.Decimal — never float for the final
rounding step.
"""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value):
    """Round a number (int / float / Decimal / str) to the nearest integer,
    halves rounding up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- Trade-in appraisal (calc 3, PRD §3.3) -------------------------------------
GRADE_FACTOR = {
    "EXCELLENT": Decimal("1.00"),
    "GOOD": Decimal("0.85"),
    "FAIR": Decimal("0.65"),
    "POOR": Decimal("0.40"),
}


def trade_in_appraisal(base_value_cents, condition_grade, engine_hours):
    grade_factor = GRADE_FACTOR[condition_grade]
    # 1% off base per full 100 engine_hours, capped at 40%
    hour_penalty_pct = min(Decimal("0.40"), (engine_hours // 100) * Decimal("0.01"))
    adjusted = Decimal(base_value_cents) * grade_factor * (Decimal(1) - hour_penalty_pct)
    return round_half_up(adjusted)


# --- Deal amount due: SALE / AUCTION_SALE (calc 4, PRD §3.4) -------------------
TAX_RATE = Decimal("0.0725")


def deal_amount_due(sale_price_cents, trade_allowance_cents, tax_exempt):
    taxable_base = max(0, sale_price_cents - trade_allowance_cents)
    if tax_exempt:
        tax_cents = 0
    else:
        tax_cents = round_half_up(Decimal(taxable_base) * TAX_RATE)
    amount_due_cents = taxable_base + tax_cents
    return tax_cents, amount_due_cents


# --- Lease monthly payment (calc 5, PRD §3.4) ---------------------------------
RESIDUAL_PCT = {
    "PRIME": Decimal("0.55"),
    "STANDARD": Decimal("0.50"),
    "SUBPRIME": Decimal("0.45"),
}
MONEY_FACTOR = {
    "PRIME": Decimal("0.0010"),
    "STANDARD": Decimal("0.0015"),
    "SUBPRIME": Decimal("0.0022"),
}


def lease_monthly_payment(sale_price_cents, trade_allowance_cents, credit_tier,
                          lease_term_months):
    residual_pct = RESIDUAL_PCT[credit_tier]
    cap_cost = Decimal(sale_price_cents) - Decimal(trade_allowance_cents)
    # ROUND #1: residual on the sale price (MSRP), not cap_cost
    residual_cents = round_half_up(Decimal(sale_price_cents) * residual_pct)
    depreciation = cap_cost - Decimal(residual_cents)
    money_factor = MONEY_FACTOR[credit_tier]
    base_monthly = depreciation / Decimal(lease_term_months)  # keep fractional
    rent_charge = (cap_cost + Decimal(residual_cents)) * money_factor
    # ROUND #2: sum-then-round
    monthly_payment_cents = round_half_up(base_monthly + rent_charge)
    return monthly_payment_cents


# --- Floor-plan interest accrual (calc 2, PRD §3.2) ---------------------------
def floor_plan_interest(principal_cents, curtailment_paid_cents, annual_rate_bps,
                        days_outstanding):
    daily_rate = Decimal(annual_rate_bps) / Decimal(10000) / Decimal(365)
    outstanding = Decimal(principal_cents - curtailment_paid_cents)
    interest = outstanding * daily_rate * Decimal(days_outstanding)
    return round_half_up(interest)


# --- Curtailment schedule (calc 8b, PRD §3.2) ---------------------------------
CURTAIL_PCT_PER_STAGE = Decimal("0.10")


def curtailment_stage(days_outstanding):
    stage = 0
    if days_outstanding >= 90:
        stage = 1
    if days_outstanding >= 180:
        stage = 2
    if days_outstanding >= 270:
        stage = 3
    return stage


def required_cumulative_curtailment(principal_cents, stage):
    return round_half_up(Decimal(principal_cents) * CURTAIL_PCT_PER_STAGE * Decimal(stage))


def curtailment_shortfall(principal_cents, stage, curtailment_paid_cents):
    required = required_cumulative_curtailment(principal_cents, stage)
    return max(0, required - curtailment_paid_cents)


# --- Labor charge (calc 1, PRD §3.6) ------------------------------------------
def labor_charge(hours, labor_rate_cents):
    return round_half_up(Decimal(str(hours)) * Decimal(labor_rate_cents))


# --- Whole-goods deposit & net price (calc 6, PRD §3.8) -----------------------
DISCOUNT_PCT = {
    "EARLY_ORDER": Decimal("0.12"),
    "IN_SEASON": Decimal("0.05"),
    "LATE": Decimal("0.00"),
}
DEPOSIT_PCT = Decimal("0.10")
DEPOSIT_FLOOR_PER_UNIT_CENTS = 50000


def whole_goods_net_price(unit_msrp_cents, season_program):
    discount = DISCOUNT_PCT[season_program]
    return round_half_up(Decimal(unit_msrp_cents) * (Decimal(1) - discount))


def whole_goods_deposit(net_price_cents, quantity):
    order_total = net_price_cents * quantity
    pct_deposit = round_half_up(Decimal(order_total) * DEPOSIT_PCT)
    floor_deposit = DEPOSIT_FLOOR_PER_UNIT_CENTS * quantity
    return max(pct_deposit, floor_deposit)


# --- Warranty reimbursement (calc 7, PRD §3.7) --------------------------------
WARRANTY_LABOR_CAP_PCT = Decimal("0.90")
PARTIAL_FACTOR = Decimal("0.50")


def warranty_full_approved(claimed_cents, claim_type):
    if claim_type in ("PIP", "RECALL"):
        return claimed_cents
    return round_half_up(Decimal(claimed_cents) * WARRANTY_LABOR_CAP_PCT)


def warranty_approved(claimed_cents, claim_type, decision):
    full = warranty_full_approved(claimed_cents, claim_type)
    if decision == "FULL":
        return full
    if decision == "PARTIAL":
        return round_half_up(Decimal(full) * PARTIAL_FACTOR)
    return 0  # DENY
