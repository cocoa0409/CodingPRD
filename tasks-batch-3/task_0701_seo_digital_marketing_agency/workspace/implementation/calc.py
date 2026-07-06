"""Calculation rules (SCAFFOLD Table 1.3 / PRD §3).

All monetary amounts are integer cents. Money calcs floor; score calcs round
half up. Decimal is used to avoid float drift.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

# ---- constants ----
BASE_COST = {"CONTENT": 3, "BACKLINK": 2, "TECHNICAL": 4}
COMPLEXITY_MULT = {"STANDARD": Decimal("1.0"), "COMPLEX": Decimal("1.5")}

AGENCY_PPC_PCT = Decimal("0.20")
TIER1_CENTS = 500000
TIER2_CENTS = 2000000
TIER1_DISCOUNT = Decimal("0.03")
TIER2_DISCOUNT = Decimal("0.06")

EARLY_TERM_RATE = Decimal("0.5")

W_TECH = Decimal("0.4")
W_CONTENT = Decimal("0.35")
W_BACKLINK = Decimal("0.25")

MOMENTUM_WEIGHT = Decimal("2.0")
OVERDUE_PENALTY = 5
DISPUTE_PENALTY = 10

UNRANKED_SENTINEL = 101


def round_half_up(value, places=0):
    """Round half-up to the given number of decimal places, returning int or float."""
    d = Decimal(str(value))
    q = Decimal(1).scaleb(-places)  # 10^-places
    r = d.quantize(q, rounding=ROUND_HALF_UP)
    if places == 0:
        return int(r)
    return float(r)


# ---------------------------------------------------------------------------
# deliverable_credit_cost
# ---------------------------------------------------------------------------


def deliverable_credit_cost(kind, complexity):
    base = Decimal(BASE_COST[kind])
    mult = COMPLEXITY_MULT[complexity]
    return int(math.ceil(base * mult))


# ---------------------------------------------------------------------------
# retainer_billing_price
# ---------------------------------------------------------------------------


def retainer_billing_price(wholesale_price_cents, reseller):
    if reseller is None:
        return int(wholesale_price_cents)
    markup = Decimal(str(reseller["markup_pct"]))
    raw = Decimal(wholesale_price_cents) * (Decimal(1) + markup)
    return int(raw.to_integral_value(rounding="ROUND_FLOOR"))


# ---------------------------------------------------------------------------
# retainer_cycle_rollover (capped carry-forward)
# ---------------------------------------------------------------------------


def capped_rollover(leftover, monthly_credits, rollover_cap_pct):
    cap = Decimal(monthly_credits) * Decimal(str(rollover_cap_pct))
    max_rollover = int(cap.to_integral_value(rounding="ROUND_FLOOR"))
    return min(leftover, max_rollover)


# ---------------------------------------------------------------------------
# ppc_management_fee (marginal tiered markup, single floor on total)
# ---------------------------------------------------------------------------


def ppc_management_fee(spent_cents, base_rate):
    base = Decimal(str(base_rate))
    rate_t1 = base
    rate_t2 = base - TIER1_DISCOUNT
    rate_t3 = base - TIER2_DISCOUNT

    spent = Decimal(spent_cents)
    # portion in tier 1: [0, TIER1_CENTS)
    p1 = min(spent, Decimal(TIER1_CENTS))
    # portion in tier 2: [TIER1_CENTS, TIER2_CENTS)
    p2 = max(Decimal(0), min(spent, Decimal(TIER2_CENTS)) - Decimal(TIER1_CENTS))
    # portion in tier 3: [TIER2_CENTS, inf)
    p3 = max(Decimal(0), spent - Decimal(TIER2_CENTS))

    total = p1 * rate_t1 + p2 * rate_t2 + p3 * rate_t3
    return int(total.to_integral_value(rounding="ROUND_FLOOR"))


# ---------------------------------------------------------------------------
# early_termination_fee
# ---------------------------------------------------------------------------


def early_termination_fee(term_cycles, cycles_elapsed, billing_price_cents):
    remaining = max(0, term_cycles - cycles_elapsed)
    if remaining == 0:
        return 0
    raw = Decimal(billing_price_cents) * Decimal(remaining) * EARLY_TERM_RATE
    raw_floored = int(raw.to_integral_value(rounding="ROUND_FLOOR"))
    return max(raw_floored, int(billing_price_cents))


# ---------------------------------------------------------------------------
# audit_composite_score
# ---------------------------------------------------------------------------


def audit_composite_score(technical_score, content_score, backlink_score):
    composite = (Decimal(technical_score) * W_TECH
                 + Decimal(content_score) * W_CONTENT
                 + Decimal(backlink_score) * W_BACKLINK)
    return round_half_up(composite, 0)


# ---------------------------------------------------------------------------
# keyword_priority_score
# ---------------------------------------------------------------------------


def keyword_priority_score(search_volume, difficulty):
    raw = Decimal(search_volume) * (Decimal(1) - Decimal(difficulty) / Decimal(100))
    return round_half_up(raw, 2)


# ---------------------------------------------------------------------------
# gbp_optimization_score
# ---------------------------------------------------------------------------


def gbp_optimization_score(location_name, service_area, status, client_status):
    score = 0
    if location_name and str(location_name).strip():
        score += 25
    if service_area and str(service_area).strip():
        score += 25
    if status in ("VERIFIED", "OPTIMIZED"):
        score += 25
    if client_status == "ACTIVE":
        score += 25
    return score
