"""Calculation rules (scaffold §1.3) — exact formulas, Decimal precision.

Covers: reproduction fees (tiered pricing + discount order), conservation
priority (preliminary/confirmed variants), digitization priority, deaccession
proceeds (per-item rounding then sum).
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

# --- reproduction_image_component constants ---------------------------------
TIER1_PAGES = 50
TIER1_RATE_CENTS = 35
TIER2_PAGES = 150
TIER2_RATE_CENTS = 25
TIER3_RATE_CENTS = 15
FORMAT_MULT = {
    "SCAN_STANDARD": Decimal("1.0"),
    "SCAN_HIGHRES": Decimal("1.8"),
    "PRINT_PHOTOGRAPH": Decimal("2.5"),
}
RUSH_MULT = Decimal("1.5")

# --- reproduction_order_total constants --------------------------------------
ACADEMIC_DISCOUNT_MIN_COMPONENT_CENTS = 5000
ACADEMIC_DISCOUNT_RATE = Decimal("0.20")
MIN_ORDER_FEE_CENTS = 500
LICENSE_FLAT_CENTS = {
    "PERSONAL": 0,
    "NONPROFIT_PUBLICATION": 1500,
    "COMMERCIAL_PUBLICATION": 7500,
}

# --- conservation_priority_score constants -----------------------------------
W_URGENCY = Decimal("0.5")
W_DEMAND = Decimal("0.3")
W_VALUE = Decimal("0.2")
DEMAND_POINTS_PER_REQUEST = 25
VALUE_STEP_CENTS = 1000
FRAGILE_URGENCY_MULT = Decimal("1.25")

# --- digitization_priority_score constants -----------------------------------
BASE_PRIORITY = Decimal("50")
CONSERVATION_WEIGHT = Decimal("0.4")
REQUEST_BOOST = Decimal("10")
REQUEST_BOOST_CAP = 3

# --- reproduction_annual_quota ------------------------------------------------
ANNUAL_PAGE_QUOTA = 500

# --- deaccession_proceeds ------------------------------------------------------
COMMISSION_RATE = Decimal("0.10")


def _round_cents(value: Decimal) -> int:
    """Round half up to whole cents."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _round_2dp(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _round_0dp(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def reproduction_image_component(pages: int, fmt: str, rush: bool) -> int:
    """Tiered page cost x format multiplier x rush multiplier; round half up."""
    tier_cost = (
        TIER1_RATE_CENTS * min(pages, TIER1_PAGES)
        + TIER2_RATE_CENTS * min(max(pages - TIER1_PAGES, 0), TIER2_PAGES)
        + TIER3_RATE_CENTS * max(pages - TIER1_PAGES - TIER2_PAGES, 0)
    )
    mult = FORMAT_MULT[fmt] * (RUSH_MULT if rush else Decimal("1.0"))
    return _round_cents(Decimal(tier_cost) * mult)


def reproduction_order_total(pages: int, fmt: str, rush: bool,
                             license_class: str, request_purpose: str) -> int:
    """Pinned evaluation order (PRD §3.7):
    (1) image component; (2) discount tier keyed on the PRE-discount component;
    (3) discount multiply (round half up); (4) minimum fee; (5) license flat.
    """
    image = reproduction_image_component(pages, fmt, rush)
    discount_rate = (
        ACADEMIC_DISCOUNT_RATE
        if (request_purpose == "ACADEMIC" and image >= ACADEMIC_DISCOUNT_MIN_COMPONENT_CENTS)
        else Decimal("0")
    )
    discounted = _round_cents(Decimal(image) * (Decimal("1") - discount_rate))
    after_minimum = max(MIN_ORDER_FEE_CENTS, discounted)
    return after_minimum + LICENSE_FLAT_CENTS[license_class]


def requote_cap(quoted_fee_cents: int) -> int:
    """floor(quoted * 1.10) in exact integer arithmetic."""
    return (quoted_fee_cents * 110) // 100


def conservation_score(urgency_score: int, condition_grade_observed: str,
                       open_request_count_snapshot: int,
                       appraised_value_cents: int | None,
                       confirmed: bool) -> float:
    """Weighted score, 2dp half up. Confirmed variant applies the FRAGILE
    urgency multiplier (rounded half up to a whole number, capped at 100)."""
    demand_score = min(100, open_request_count_snapshot * DEMAND_POINTS_PER_REQUEST)
    value_score = min(100, (appraised_value_cents or 0) // VALUE_STEP_CENTS)
    urgency_eff = urgency_score
    if confirmed and condition_grade_observed == "FRAGILE":
        urgency_eff = min(100, _round_0dp(Decimal(urgency_score) * FRAGILE_URGENCY_MULT))
    score = _round_2dp(
        W_URGENCY * urgency_eff + W_DEMAND * demand_score + W_VALUE * value_score
    )
    return float(score)


def digitization_priority(conservation_priority_score, approved_request_count: int) -> float:
    """Ticket priority snapshot: base + conservation term + capped request boost."""
    score = _round_2dp(
        BASE_PRIORITY
        + CONSERVATION_WEIGHT * Decimal(str(conservation_priority_score or 0))
        + REQUEST_BOOST * min(REQUEST_BOOST_CAP, approved_request_count)
    )
    return float(score)


def deaccession_proceeds(hammer_prices: list[dict], item_ids: list[str]) -> int:
    """Per-item round-half-up THEN sum (pinned order, PRD §3.8)."""
    price_by_item = {hp["item_id"]: hp["price_cents"] for hp in hammer_prices}
    total = 0
    for item_id in item_ids:
        line = Decimal(price_by_item[item_id]) * (Decimal("1") - COMMISSION_RATE)
        total += _round_cents(line)
    return total
