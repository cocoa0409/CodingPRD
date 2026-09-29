"""Calculation rules. Integer cents throughout; Decimal for every rounded step."""
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP, getcontext

getcontext().prec = 60

# ---- safe ledger signs (PRD section 2.6) -----------------------------------
DIRECTION_SIGN = {
    "OPENING_BALANCE": 1,
    "STARTING_BANK_ISSUE": -1,
    "MID_SHIFT_DROP": 1,
    "CLOSING_DROP": 1,
    "SMART_DEPOSIT": 1,
    "DEPOSIT_REMOVAL": -1,
    "DEPOSIT_RETURN": 1,
    "CHANGE_ORDER_RECEIPT": 1,
    "VARIANCE_ADJUSTMENT": -1,
}

TXN_TYPES = tuple(DIRECTION_SIGN.keys())

# ---- constants -------------------------------------------------------------
COACHING_GRACE_HOURS = 72
ESCALATION_PATTERN_DAYS = 90
VALIDATED_MIN_DENOMINATION_CENTS = 500
CARRIER_BASE_FEE_CENTS = 1200
CARRIER_PER_THOUSAND_FEE_CENTS = 35
PER_TXN_FEE_CENTS = 12
TIER_1_RATE = Decimal("0.0250")
TIER_2_RATE = Decimal("0.0220")
TIER_3_RATE = Decimal("0.0195")
TIER_2_FLOOR_CENTS = 5000000
TIER_3_FLOOR_CENTS = 20000000
AMEX_ADDER = Decimal("0.0035")
SEASONAL_MULTIPLIER = {
    "BASELINE": Decimal("1.00"),
    "BACK_TO_SCHOOL": Decimal("1.35"),
    "HOLIDAY": Decimal("1.80"),
}
DENOM_MIX = (
    {"denomination_cents": 2000, "mix_pct": Decimal("0.50"), "strap_units": 25},
    {"denomination_cents": 1000, "mix_pct": Decimal("0.20"), "strap_units": 25},
    {"denomination_cents": 500, "mix_pct": Decimal("0.15"), "strap_units": 50},
    {"denomination_cents": 100, "mix_pct": Decimal("0.10"), "strap_units": 50},
    {"denomination_cents": 25, "mix_pct": Decimal("0.05"), "strap_units": 40},
)
ATTRIBUTION_BUCKETS = ("REGISTER", "SAFE", "BANK")


def round_half_up(value):
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def ceil_div_decimal(value):
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_CEILING))


def effective_amount(row):
    basis = row["verified_amount_cents"]
    if basis is None:
        basis = row["declared_amount_cents"]
    return DIRECTION_SIGN[row["txn_type"]] * basis


# ---- bank_credit_reconciliation (pinned evaluation order) ------------------
def carrier_fee_cents(declared_total_cents):
    increments = ceil_div_decimal(Decimal(declared_total_cents) / Decimal(100000))
    return CARRIER_BASE_FEE_CENTS + CARRIER_PER_THOUSAND_FEE_CENTS * increments


def expected_credit_cents(declared_total_cents):
    return declared_total_cents - carrier_fee_cents(declared_total_cents)


# ---- provisional_credit ----------------------------------------------------
def smart_provisional_credit(counted_lines, suspect_note_cents, cap_cents):
    validated = sum(
        line["denomination_cents"] * line["quantity"]
        for line in counted_lines
        if line["denomination_cents"] >= VALIDATED_MIN_DENOMINATION_CENTS
    )
    return min(validated - suspect_note_cents, cap_cents)


def carrier_provisional_credit(declared_total_cents, cap_cents):
    return min(declared_total_cents, cap_cents)


# ---- card_settlement_reconciliation ---------------------------------------
def tier_rate(monthly_volume_cents):
    if monthly_volume_cents < TIER_2_FLOOR_CENTS:
        return TIER_1_RATE
    if monthly_volume_cents < TIER_3_FLOOR_CENTS:
        return TIER_2_RATE
    return TIER_3_RATE


def card_settlement(gross_card_sales_cents, txn_count, chargeback_cents,
                    monthly_volume_cents, funded_amount_cents, card_network):
    rate = tier_rate(monthly_volume_cents)
    adder = AMEX_ADDER if card_network == "AMEX" else Decimal("0.0000")
    percentage_component = round_half_up(Decimal(gross_card_sales_cents) * (rate + adder))
    expected_fee = percentage_component + PER_TXN_FEE_CENTS * txn_count
    expected_funded = gross_card_sales_cents - expected_fee - chargeback_cents
    variance = funded_amount_cents - expected_funded
    return {
        "expected_fee_cents": expected_fee,
        "expected_funded_cents": expected_funded,
        "settlement_variance_cents": variance,
        "settlement_status": "MATCHED" if variance == 0 else "VARIANCE",
    }


# ---- change_order_denomination_plan ---------------------------------------
def forecast_demand(baseline_daily_cash_demand_cents, days_covered, profile, growth_pct):
    multiplier = SEASONAL_MULTIPLIER[profile]
    raw = (
        Decimal(baseline_daily_cash_demand_cents)
        * Decimal(days_covered)
        * multiplier
        * (Decimal(1) + Decimal(growth_pct))
    )
    return round_half_up(raw)


def denomination_plan(forecast_demand_cents):
    lines = []
    for row in DENOM_MIX:
        raw_units = Decimal(forecast_demand_cents) * row["mix_pct"] / Decimal(row["denomination_cents"])
        strap_count = ceil_div_decimal(raw_units / Decimal(row["strap_units"]))
        units = strap_count * row["strap_units"]
        lines.append(
            {
                "denomination_cents": row["denomination_cents"],
                "strap_count": strap_count,
                "units": units,
                "planned_cents": units * row["denomination_cents"],
            }
        )
    total = sum(line["planned_cents"] for line in lines)
    return lines, total


# ---- till_over_short ------------------------------------------------------
def till_expected_cash(starting_bank_cents, pos_cash_sales_cents, pos_paid_out_cents, drop_total):
    return (
        starting_bank_cents
        + pos_cash_sales_cents
        - (pos_paid_out_cents or 0)
        - drop_total
    )
