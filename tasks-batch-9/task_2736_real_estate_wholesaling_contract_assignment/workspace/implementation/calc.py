"""All eight calculation rules (PRD §3.4, §3.3, §3.6, §3.7, §3.8, §3.9 and
SCAFFOLD §1.3). Every monetary amount is an integer number of cents; all
arithmetic goes through Decimal so no float ever touches money.
"""
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

# --- arv_and_mao -----------------------------------------------------------
DISTANCE_MAX_MILES = Decimal("0.50")
RECENCY_MAX_DAYS = 180
GLA_TOLERANCE_PCT_INT = 20
CONSERVATIVE_ARV_MULTIPLIER = Decimal("0.70")
AGGRESSIVE_ARV_MULTIPLIER = Decimal("0.75")
CONTINGENCY_MULTIPLIER = Decimal("1.10")
MIN_ASSIGNMENT_MARGIN_CENTS = 1000000
MIN_QUALIFYING_COMPS = 3

# --- seller_equity_exposure ----------------------------------------------
SELLER_CLOSING_COST_PCT = Decimal("0.08")
HIGH_EQUITY_PCT = Decimal("0.35")

# --- assignment_fee_settlement -------------------------------------------
TITLE_HOLDBACK_RATE = Decimal("0.0325")
STATE_TRANSFER_SURCHARGE_RATE = Decimal("0.0075")
MARKETING_RECOVERY_RATE = Decimal("0.0155")

# --- double_close_funding_schedule ---------------------------------------
CLOSING_COST_GROSS_UP_RATE = Decimal("0.021")
TIER_1_CEILING_CENTS = 15000000
TIER_2_CEILING_CENTS = 30000000
TIER_1_RATE = Decimal("0.0300")
TIER_2_RATE = Decimal("0.0225")
TIER_3_RATE = Decimal("0.0175")
TIER_1_MIN_FEE_CENTS = 25000
TIER_2_MIN_FEE_CENTS = 45000
TIER_3_MIN_FEE_CENTS = 70000

# --- assignment_fee_cap ---------------------------------------------------
FEE_CAP_PCT_STANDARD = Decimal("0.12")
FEE_CAP_PCT_ELEVATED = Decimal("0.08")
FEE_CAP_PCT_PROTECTED = Decimal("0.05")

# --- buyer_committed_capital ---------------------------------------------
PRIORITY_TIER_MIN_AVAILABLE_CENTS = 25000000
LIVE_OFFER_STATUSES = (
    "SUBMITTED",
    "COUNTERED_BY_WHOLESALER",
    "REVISED_BY_BUYER",
    "ACCEPTED",
)

# --- contract_deadlines ---------------------------------------------------
ASSIGNMENT_CUTOFF_HOURS = 48
PROTECTED_COOLING_OFF_HOURS = 72
DOUBLE_CLOSE_BUFFER_HOURS = 48

# --- other domain constants ----------------------------------------------
COMPLIANCE_HOLD_THRESHOLD = 2
MAX_NEGOTIATION_ROUNDS = 4
EQUITY_FLOOR_PCT = Decimal("0.60")
ONE = Decimal(1)


def round_half_up(value):
    """Quantize to a whole cent, halves going away from zero."""
    return int(Decimal(value).quantize(ONE, rounding=ROUND_HALF_UP))


def floor_int(value):
    """Mathematical floor toward negative infinity."""
    return int(Decimal(value).quantize(ONE, rounding=ROUND_FLOOR))


# ---------------------------------------------------------------------------
# arv_and_mao (PRD §3.4)
# ---------------------------------------------------------------------------
def adjusted_price(comp):
    return int(comp["sale_price_cents"]) + int(comp["adjustment_cents"])


def comp_qualifies(comp, subject_gla_sqft):
    if Decimal(str(comp["distance_miles"])) > DISTANCE_MAX_MILES:
        return False
    if int(comp["closed_days_ago"]) > RECENCY_MAX_DAYS:
        return False
    delta = abs(int(comp["gla_sqft"]) - int(subject_gla_sqft))
    if delta * 100 > int(subject_gla_sqft) * GLA_TOLERANCE_PCT_INT:
        return False
    return True


def qualifying_comps(comparables, subject_gla_sqft):
    """Returns [(original_index, comp)] for the comparables passing all filters."""
    return [
        (idx, comp)
        for idx, comp in enumerate(comparables)
        if comp_qualifies(comp, subject_gla_sqft)
    ]


def count_qualifying_comps(comparables, subject_gla_sqft):
    return len(qualifying_comps(comparables, subject_gla_sqft))


def _arv_conservative(quals):
    ordered = sorted(
        quals,
        key=lambda pair: (
            adjusted_price(pair[1]),
            int(pair[1]["closed_days_ago"]),
            pair[0],
        ),
    )
    count = len(ordered)
    mid = count // 2
    if count % 2 == 1:
        return adjusted_price(ordered[mid][1])
    lower = adjusted_price(ordered[mid - 1][1])
    upper = adjusted_price(ordered[mid][1])
    return floor_int(Decimal(lower + upper) / Decimal(2))


def _arv_aggressive(quals):
    numerator = Decimal(0)
    denominator = Decimal(0)
    for _idx, comp in quals:
        weight = Decimal(RECENCY_MAX_DAYS + 1 - int(comp["closed_days_ago"]))
        numerator += Decimal(adjusted_price(comp)) * weight
        denominator += weight
    return round_half_up(numerator / denominator)


def arv_and_mao(comparables, repair_scope_items, subject_gla_sqft, variant):
    """Returns (arv_cents, repair_estimate_cents, max_allowable_offer_cents)."""
    quals = qualifying_comps(comparables, subject_gla_sqft)
    if variant == "CONSERVATIVE":
        arv_cents = _arv_conservative(quals)
        high_total = sum(int(item["high_cents"]) for item in repair_scope_items)
        repair_estimate_cents = round_half_up(
            Decimal(high_total) * CONTINGENCY_MULTIPLIER
        )
        multiplier = CONSERVATIVE_ARV_MULTIPLIER
    else:
        arv_cents = _arv_aggressive(quals)
        repair_estimate_cents = sum(
            int(item["low_cents"]) for item in repair_scope_items
        )
        multiplier = AGGRESSIVE_ARV_MULTIPLIER
    mao = (
        floor_int(Decimal(arv_cents) * multiplier)
        - repair_estimate_cents
        - MIN_ASSIGNMENT_MARGIN_CENTS
    )
    return arv_cents, repair_estimate_cents, mao


# ---------------------------------------------------------------------------
# seller_equity_exposure (PRD §3.3)
# ---------------------------------------------------------------------------
def seller_equity_exposure(lead, variant):
    """Returns (net_equity_cents, equity_pct Decimal(4dp), protection_tier)."""
    market_value = int(lead["estimated_market_value_cents"])
    senior = int(lead["recorded_senior_lien_cents"])
    if variant == "STATUTORY":
        net = market_value - senior
    else:
        allowance = round_half_up(Decimal(market_value) * SELLER_CLOSING_COST_PCT)
        net = (
            market_value
            - senior
            - int(lead["junior_lien_cents"])
            - int(lead["delinquent_property_tax_cents"])
            - allowance
        )
    equity_pct = (Decimal(net) / Decimal(market_value)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    flags = len(set(lead["distress_flags"]))
    high_equity = equity_pct >= HIGH_EQUITY_PCT
    if high_equity and flags >= 2:
        tier = "PROTECTED"
    elif (high_equity and flags == 1) or ((not high_equity) and flags >= 2):
        tier = "ELEVATED"
    else:
        tier = "STANDARD"
    return net, equity_pct, tier


def equity_floor_cents(lead):
    """PRD §3.5 — floor((MV - SENIOR) * 0.60) + SENIOR."""
    market_value = int(lead["estimated_market_value_cents"])
    senior = int(lead["recorded_senior_lien_cents"])
    return floor_int(Decimal(market_value - senior) * EQUITY_FLOOR_PCT) + senior


# ---------------------------------------------------------------------------
# assignment_fee_settlement (PRD §3.8)
# ---------------------------------------------------------------------------
def assignment_fee_settlement(fee_cents):
    """Each component rounded on its own BEFORE any subtraction."""
    fee = Decimal(int(fee_cents))
    title_holdback = round_half_up(fee * TITLE_HOLDBACK_RATE)
    state_surcharge = round_half_up(fee * STATE_TRANSFER_SURCHARGE_RATE)
    marketing_recovery = round_half_up(fee * MARKETING_RECOVERY_RATE)
    net = int(fee_cents) - title_holdback - state_surcharge - marketing_recovery
    return title_holdback, state_surcharge, marketing_recovery, net


# ---------------------------------------------------------------------------
# double_close_funding_schedule (PRD §3.8)
# ---------------------------------------------------------------------------
def double_close_funding_schedule(purchase_price_cents):
    """Returns (funding_base_cents, transactional_lender_fee_cents, total)."""
    price = int(purchase_price_cents)
    base = price + round_half_up(Decimal(price) * CLOSING_COST_GROSS_UP_RATE)
    if base < TIER_1_CEILING_CENTS:
        rate, min_fee = TIER_1_RATE, TIER_1_MIN_FEE_CENTS
    elif base < TIER_2_CEILING_CENTS:
        rate, min_fee = TIER_2_RATE, TIER_2_MIN_FEE_CENTS
    else:
        rate, min_fee = TIER_3_RATE, TIER_3_MIN_FEE_CENTS
    fee = max(min_fee, round_half_up(Decimal(base) * rate))
    return base, fee, base + fee


# ---------------------------------------------------------------------------
# assignment_fee_cap (PRD §3.7)
# ---------------------------------------------------------------------------
def fee_cap_cents(purchase_price_cents, protection_tier):
    if protection_tier == "PROTECTED":
        pct = FEE_CAP_PCT_PROTECTED
    elif protection_tier == "ELEVATED":
        pct = FEE_CAP_PCT_ELEVATED
    else:
        pct = FEE_CAP_PCT_STANDARD
    return floor_int(Decimal(int(purchase_price_cents)) * pct)


def fee_exceeds_cap(buyer_price_cents, purchase_price_cents, protection_tier):
    implied = int(buyer_price_cents) - int(purchase_price_cents)
    return implied > fee_cap_cents(purchase_price_cents, protection_tier)


# ---------------------------------------------------------------------------
# escrow_disposition (PRD §2.11, §3.9)
# ---------------------------------------------------------------------------
def apply_disposition(deposit, event):
    """Transfer between buckets; never mint, never burn."""
    if event == "FORFEIT":
        deposit["forfeited_to_seller_cents"] += deposit["held_cents"]
        deposit["held_cents"] = 0
        deposit["status"] = "FORFEITED_TO_SELLER"
    elif event == "CANCEL_REFUND":
        deposit["refunded_to_wholesaler_cents"] += deposit["held_cents"]
        deposit["held_cents"] = 0
        deposit["status"] = "REFUNDED_TO_WHOLESALER"
    elif event == "APPLY_AT_CLOSING":
        deposit["applied_at_closing_cents"] += deposit["held_cents"]
        deposit["held_cents"] = 0
        deposit["status"] = "APPLIED_AT_CLOSING"
    deposit["disposition_event_count"] += 1


def apply_dispute_award(deposit, award):
    """Returns (award_seller_cents, award_wholesaler_cents)."""
    amount = int(deposit["amount_cents"])
    if award == "SELLER_KEEPS_EARNEST_MONEY":
        award_seller = deposit["forfeited_to_seller_cents"]
        award_wholesaler = 0
    elif award == "REFUND_TO_WHOLESALER":
        deposit["refunded_to_wholesaler_cents"] += deposit["forfeited_to_seller_cents"]
        deposit["forfeited_to_seller_cents"] = 0
        deposit["status"] = "REFUNDED_TO_WHOLESALER"
        award_seller = 0
        award_wholesaler = amount
    else:  # SPLIT_50_50
        seller_share = floor_int(Decimal(amount) / Decimal(2))
        deposit["forfeited_to_seller_cents"] = seller_share
        deposit["refunded_to_wholesaler_cents"] = amount - seller_share
        deposit["status"] = "SPLIT_SETTLED"
        award_seller = seller_share
        award_wholesaler = amount - seller_share
    deposit["disposition_event_count"] += 1
    return award_seller, award_wholesaler
