"""Pure calculations (PRD sections 2.6, 3.2, 3.5, 3.7, 3.9).

Every quotient here is either floored (truncated toward zero) or rounded half up
away from zero.  The two behaviours are never interchanged.
"""

from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------- constants
CREDIT_PER_UNIT_CENTS = 3
VOLUME_CREDIT_CAP_BPS = 4000
ADMIN_TIER_1_MAX_CENTS = 5000000
ADMIN_BPS_TIER_1 = 250
ADMIN_BPS_TIER_2 = 150

MIN_SHELF_LIFE_DAYS = 30
MAX_NEGOTIATION_ROUNDS = 3
MAX_REFILES = 2
MAX_REVIEW_REOPENS = 1
MIN_SUBSTANTIATION_DOCS = 2
FUNDING_TOLERANCE_BPS = 11000
SHORTAGE_ALLOWANCE_BPS = 5000

WATCH_RATIO_BPS = 5000
RESTRICTED_RATIO_BPS = 7500
RESTRICTED_AT_RISK_COUNT = 2


# ---------------------------------------------------------------- rounding
def floor_div(numerator, denominator):
    """Truncate the quotient toward zero."""
    if denominator == 0:
        return 0
    quotient = abs(numerator) // abs(denominator)
    if (numerator < 0) != (denominator < 0):
        return -quotient
    return quotient


def round_half_up(numerator, denominator):
    """Round the quotient half up (away from zero) to a whole number."""
    if denominator == 0:
        return 0
    value = Decimal(numerator) / Decimal(denominator)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2(numerator, denominator):
    """Round the quotient half up to exactly two decimal places."""
    if denominator == 0:
        return None
    value = Decimal(numerator) / Decimal(denominator)
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def ceil_div(numerator, denominator):
    if denominator == 0:
        return 0
    return -((-numerator) // denominator)


# ------------------------------------------------------------ slotting quote
def slotting_quote(fee_per_store, store_count, item_count, forecast_units):
    """The six-step quote ladder of PRD section 3.5."""
    gross = fee_per_store * store_count * item_count
    raw_credit = forecast_units * CREDIT_PER_UNIT_CENTS
    cap = floor_div(gross * VOLUME_CREDIT_CAP_BPS, 10000)
    credit = raw_credit if raw_credit < cap else cap
    net = gross - credit
    admin_bps = ADMIN_BPS_TIER_1 if net <= ADMIN_TIER_1_MAX_CENTS else ADMIN_BPS_TIER_2
    admin = round_half_up(net * admin_bps, 10000)
    return {
        "gross_fee_cents": gross,
        "volume_credit_cents": credit,
        "net_before_admin_cents": net,
        "admin_fee_cents": admin,
        "quoted_fee_cents": net + admin,
    }


# ------------------------------------------------------- slotting amortization
def amortization_amount(deal, reported_case_volume):
    """The amount one distribution posting amortizes against a deal."""
    accepted = deal["accepted_fee_cents"]
    periods = deal["amortization_periods"]
    posted = deal["periods_posted"]
    balance = deal["unamortized_balance_cents"]

    if deal["amortization_method"] == "FORECAST_STRAIGHT":
        base = floor_div(accepted, periods)
        if posted + 1 < periods:
            amount = base
        else:
            amount = accepted - base * (periods - 1)
    else:
        target = ceil_div(deal["forecast_annual_units"], periods)
        if target == 0:
            ratio = 0
        else:
            ratio = floor_div(reported_case_volume * 10000, target)
            if ratio > 10000:
                ratio = 10000
        amount = round_half_up(accepted * ratio, 10000 * periods)

    if amount > balance:
        amount = balance
    if amount < 0:
        amount = 0
    return amount


# -------------------------------------------------------------- void rate
def void_metrics(basis, authorized_store_count, latest):
    """Distribution counters under one basis.

    `latest` is the latest live POSTING entry, or None when none exists.
    """
    distributed = latest["distributed_store_count"] if latest is not None else 0

    if basis == "STORE_COUNT_BASIS":
        void = authorized_store_count - distributed
        if latest is None or authorized_store_count == 0:
            rate = 0
        else:
            rate = floor_div(void * 10000, authorized_store_count)
        return {
            "distributed_store_count": distributed,
            "void_store_count": void,
            "pending_store_count": 0,
            "void_rate_bps": rate,
        }

    if latest is None:
        return {
            "distributed_store_count": 0,
            "void_store_count": 0,
            "pending_store_count": authorized_store_count,
            "void_rate_bps": 0,
        }

    reported = latest["reported_store_count"]
    void = reported - distributed
    rate = 0 if reported == 0 else floor_div(void * 10000, reported)
    return {
        "distributed_store_count": distributed,
        "void_store_count": void,
        "pending_store_count": authorized_store_count - distributed - void,
        "void_rate_bps": rate,
    }


# ------------------------------------------------------- share allocation
def slotting_share_allocation(accepted_fee_cents, count):
    """Whole-cent shares that sum to accepted_fee_cents exactly."""
    if count <= 0:
        return []
    base = floor_div(accepted_fee_cents, count)
    remainder = accepted_fee_cents - base * count
    return [base + 1 if index < remainder else base for index in range(count)]


# --------------------------------------------------------- credit posture
def liability_ratio_bps(open_slotting_liability_cents, open_deduction_cents, budget_cents):
    if budget_cents == 0:
        return 0
    return floor_div((open_slotting_liability_cents + open_deduction_cents) * 10000, budget_cents)


def credit_posture(at_risk_count, ratio_bps):
    if at_risk_count >= RESTRICTED_AT_RISK_COUNT or ratio_bps >= RESTRICTED_RATIO_BPS:
        return "RESTRICTED"
    if at_risk_count >= 1 or ratio_bps >= WATCH_RATIO_BPS:
        return "WATCH"
    return "NORMAL"


# ------------------------------------------------------ post-audit recovery
def recoverable_amount(deduction, promotion_event):
    """How much of a deduction an approved claim recovers (PRD section 3.9)."""
    reason = deduction["reason_code"]
    claim = deduction["claim_amount_cents"]
    amount = deduction["amount_cents"]

    if reason == "DUPLICATE_BILLBACK":
        return claim
    if reason == "PROMO_BILLBACK":
        substantiated = 0
        if promotion_event is not None and promotion_event["state"] in ("EXECUTED", "SETTLED"):
            substantiated = promotion_event.get("actual_funding_cents") or 0
        excess = amount - substantiated
        if excess < 0:
            excess = 0
        return claim if claim < excess else excess
    if reason == "SHORTAGE":
        allowance = floor_div(amount * SHORTAGE_ALLOWANCE_BPS, 10000)
        return claim if claim < allowance else allowance
    return 0


# ------------------------------------------------------ commission statement
def commission_lines(lines, base_bps, threshold_cents, tier_bps):
    """Running tier walk over lines already ordered by upc ascending.

    Each element of `lines` is a dict carrying item_id, upc and line_shipped_cents.
    """
    running = 0
    total_shipped = 0
    total_commission = 0
    output = []
    for line in lines:
        shipped = line["line_shipped_cents"]
        headroom = threshold_cents - running
        if headroom < 0:
            headroom = 0
        tier1 = shipped if shipped < headroom else headroom
        if tier1 < 0:
            tier1 = 0
        tier2 = shipped - tier1
        raw = Decimal(tier1 * base_bps) / Decimal(10000) + Decimal(tier2 * tier_bps) / Decimal(10000)
        commission = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        output.append({
            "item_id": line["item_id"],
            "upc": line["upc"],
            "line_shipped_cents": shipped,
            "tier1_part_cents": tier1,
            "tier2_part_cents": tier2,
            "line_commission_cents": commission,
        })
        running += shipped
        total_shipped += shipped
        total_commission += commission
    return output, total_shipped, total_commission
