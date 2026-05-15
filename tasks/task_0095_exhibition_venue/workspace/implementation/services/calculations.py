"""Calculation rules per §1.3 of SCAFFOLD and PRD §3.

All monetary values are integer cents. Rounding uses round-half-up where specified.
"""

from decimal import Decimal

from money import round_half_up_cents, round_half_up_decimal


# ---------------------------------------------------------------------------
# booth_quoted_price (§1.3.1, PRD §3.2)
# Steps pinned: tier_base * cell_multiplier * corner_multiplier, round_half_up,
# THEN add theme_addon.
# ---------------------------------------------------------------------------
TIER_BASE = {
    "STANDARD": 200000,
    "PREMIUM": 350000,
    "ISLAND": 600000,
}
THEME_ADDON_PREFIX = "PRO_"
THEME_ADDON_CENTS = 50000


def booth_quoted_price(booth: dict, exhibition: dict) -> int:
    """Compute the booth's quoted price in integer cents."""
    tier_base = TIER_BASE[booth["tier"]]
    cell_count = len(booth.get("cells", []) or [])
    if booth["tier"] == "ISLAND" and cell_count > 4:
        cell_multiplier = Decimal("1.0") + Decimal("0.10") * Decimal(cell_count - 4)
    else:
        cell_multiplier = Decimal("1.0")
    corner_multiplier = Decimal("1.15") if booth.get("is_corner") else Decimal("1.0")
    pre_theme = Decimal(tier_base) * cell_multiplier * corner_multiplier
    pre_theme_cents = round_half_up_cents(pre_theme)
    theme_code = (exhibition.get("theme_code") or "") if exhibition else ""
    addon = THEME_ADDON_CENTS if theme_code.startswith(THEME_ADDON_PREFIX) else 0
    return pre_theme_cents + addon


# ---------------------------------------------------------------------------
# application_priority_score (§1.3.2, PRD §3.3)
# Score = sponsor_weight + seniority_weight + lottery_component
# Lottery component rounded half-up to 4 decimal places.
# ---------------------------------------------------------------------------
SPONSOR_WEIGHT = {
    "NONE": 0,
    "BRONZE": 100,
    "SILVER": 250,
    "GOLD": 500,
    "PLATINUM": 1000,
}
SENIORITY_CAP_YEARS = 20
SENIORITY_PER_YEAR = 10
LOTTERY_DIVISOR = Decimal("10000")


def application_priority_score(sponsorship_level: str, seniority_years: int, lottery_token: int) -> float:
    sponsor = SPONSOR_WEIGHT.get(sponsorship_level, 0)
    seniority = min(int(seniority_years or 0), SENIORITY_CAP_YEARS) * SENIORITY_PER_YEAR
    lottery_component = Decimal(lottery_token) / LOTTERY_DIVISOR
    lottery_rounded = round_half_up_decimal(lottery_component, 4)
    total = Decimal(sponsor) + Decimal(seniority) + lottery_rounded
    return float(round_half_up_decimal(total, 4))


# ---------------------------------------------------------------------------
# work_order_billing (§1.3.3, PRD §3.6)
# Per-line rounding precedes aggregation. Cleaning (-5%) applied per line.
# ---------------------------------------------------------------------------
TAX_RATE = Decimal("0.06")
CLEANING_DISCOUNT_FACTOR = Decimal("0.95")


def work_order_billing(lines: list) -> tuple[int, int, int]:
    """Return (subtotal_cents, tax_cents, total_cents)."""
    subtotal = 0
    for line in lines:
        qty = int(line["quantity"])
        unit = int(line["unit_price_cents"])
        line_gross = Decimal(unit) * Decimal(qty)
        if line.get("service_code") == "CLEANING":
            line_amount = line_gross * CLEANING_DISCOUNT_FACTOR
        else:
            line_amount = line_gross
        subtotal += round_half_up_cents(line_amount)
    tax_cents = round_half_up_cents(Decimal(subtotal) * TAX_RATE)
    total_cents = subtotal + tax_cents
    return subtotal, tax_cents, total_cents


# ---------------------------------------------------------------------------
# ticket_price (§1.3.4, PRD §3.7)
# ---------------------------------------------------------------------------
TICKET_BASE = {
    "VISITOR": 5000,
    "PROFESSIONAL_BUYER": 12000,
    "STUDENT": 2500,
    "VIP": 30000,
}
ONSITE_SURCHARGE = Decimal("1.20")
GROUP_DISCOUNT_FACTOR = Decimal("0.85")
GROUP_THRESHOLD = 10


def ticket_price(kind: str, channel: str, group_size: int, group_id) -> int:
    base = TICKET_BASE[kind]
    if channel == "ONSITE" and kind != "VIP":
        channel_mult = ONSITE_SURCHARGE
    else:
        channel_mult = Decimal("1.0")
    if group_id is not None and group_size >= GROUP_THRESHOLD:
        group_mult = GROUP_DISCOUNT_FACTOR
    else:
        group_mult = Decimal("1.0")
    raw = Decimal(base) * channel_mult * group_mult
    return round_half_up_cents(raw)


# ---------------------------------------------------------------------------
# entitlement_make_good (§1.3.6, PRD §3.8)
# ---------------------------------------------------------------------------
MAKE_GOOD_TIER_BASE = {
    "BRONZE": 10000,
    "SILVER": 25000,
    "GOLD": 60000,
    "PLATINUM": 120000,
}
ENTITLEMENT_FACTOR = {
    "SIGNAGE": Decimal("0.5"),
    "PROGRAM_AD": Decimal("0.4"),
    "LOUNGE": Decimal("0.8"),
    "SPEAKING_SLOT": Decimal("1.0"),
    "BRANDED_GIFT": Decimal("0.3"),
}


def entitlement_make_good(sponsor_tier: str, entitlement_code: str) -> int:
    base = MAKE_GOOD_TIER_BASE[sponsor_tier]
    factor = ENTITLEMENT_FACTOR[entitlement_code]
    return round_half_up_cents(Decimal(base) * factor)


# ---------------------------------------------------------------------------
# entitlement_fulfillment_score (§1.3.5, PRD §3.8)
# Both provisional and final variants; 4 decimal places, round-half-up.
# ---------------------------------------------------------------------------
def fulfillment_score_provisional(status: str) -> float:
    """Live (in-progress) variant for the report. Does NOT mutate the row."""
    if status in ("IN_PROGRESS", "MAKE_GOOD_OFFERED", "FULFILLED"):
        v = Decimal("1.0")
    elif status == "MAKE_GOOD_ACCEPTED":
        v = Decimal("0.5")
    elif status in ("MISSED", "WAIVED"):
        v = Decimal("0.0")
    else:
        v = Decimal("1.0")
    return float(round_half_up_decimal(v, 4))


def fulfillment_score_final(final_status: str, deadline_dt, now_dt) -> float:
    """Terminal-state variant; pinned to fulfillment_score."""
    if final_status == "FULFILLED":
        v = Decimal("1.0")
    elif final_status == "MAKE_GOOD_ACCEPTED":
        v = Decimal("0.5")
    elif final_status == "WAIVED":
        v = Decimal("0.0")
    elif final_status == "MISSED":
        # Compute hours late = max(0, now - deadline) in hours
        if deadline_dt is None or now_dt is None:
            hours_late = Decimal("0")
        else:
            diff = (now_dt - deadline_dt).total_seconds()
            hours_late = Decimal(diff) / Decimal("3600")
            if hours_late < 0:
                hours_late = Decimal("0")
        days_late = int(hours_late // Decimal("24"))
        v = Decimal("0.5") - Decimal("0.1") * Decimal(days_late)
        if v < Decimal("0.0"):
            v = Decimal("0.0")
    else:
        v = Decimal("0.0")
    return float(round_half_up_decimal(v, 4))
