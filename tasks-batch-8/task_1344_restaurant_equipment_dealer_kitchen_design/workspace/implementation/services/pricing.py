"""Quote pricing engine (PRD section 3.3 / scaffold calculations table).

All money is integer cents; every rounding is ROUND_HALF_UP to whole cents,
applied exactly where each formula pins it.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

import db

# freight_tier_calc constants
TIER_1_CEILING_CENTS = 5_000_000
TIER_2_CEILING_CENTS = 25_000_000
TIER_1_RATE = Decimal("0.06")
TIER_2_RATE = Decimal("0.045")
TIER_3_RATE = Decimal("0.03")
CUSTOM_FAB_SURCHARGE_CENTS = 150_000

# installation_calc constants
BASE_INSTALL_CENTS = 250_000
PER_ITEM_CENTS = 45_000
HOOD_PREMIUM_CENTS = 120_000
COUNTY_UPLIFT = Decimal("1.10")

# startup_calc constants
STARTUP_BASE_CENTS = 180_000
STARTUP_PER_ITEM_CENTS = 30_000


def round_cents(d: Decimal) -> int:
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def snapshot_lines(layout_id: str) -> list[dict]:
    """Per-line pricing facts for non-CANCELLED items on a layout.

    Used both to freeze the PROVISIONAL snapshot at Quote creation and to
    re-read current item state for the FINAL variant at acceptance.
    """
    items = [
        it for it in db.items.values()
        if it["layout_id"] == layout_id and it["status"] != "CANCELLED"
    ]
    items.sort(key=lambda it: it["_seq"])
    return [
        {
            "quantity": int(it["quantity"]),
            "unit_price_cents": int(it["unit_price_cents"]),
            "item_kind": it["item_kind"],
            "requires_hood": bool(it.get("requires_hood", False)),
        }
        for it in items
    ]


def compute_quote_pricing(lines: list[dict], health_jurisdiction: str) -> dict:
    lines = list(lines)

    # equipment_subtotal_calc: round each line half-up FIRST, then sum.
    subtotal = 0
    for ln in lines:
        line = Decimal(ln["quantity"]) * Decimal(ln["unit_price_cents"])
        subtotal += round_cents(line)

    # freight_tier_calc: marginal tiers, inclusive lower / exclusive upper,
    # round half-up once on the marginal sum, then flat fab surcharge.
    S = Decimal(subtotal)
    if subtotal <= TIER_1_CEILING_CENTS:
        base = S * TIER_1_RATE
    elif subtotal <= TIER_2_CEILING_CENTS:
        base = (
            Decimal(TIER_1_CEILING_CENTS) * TIER_1_RATE
            + (S - TIER_1_CEILING_CENTS) * TIER_2_RATE
        )
    else:
        base = (
            Decimal(TIER_1_CEILING_CENTS) * TIER_1_RATE
            + Decimal(TIER_2_CEILING_CENTS - TIER_1_CEILING_CENTS) * TIER_2_RATE
            + (S - TIER_2_CEILING_CENTS) * TIER_3_RATE
        )
    freight = round_cents(base)
    if any(ln["item_kind"] == "CUSTOM_FABRICATION" for ln in lines):
        freight += CUSTOM_FAB_SURCHARGE_CENTS

    # installation_calc: base + per-unit + per-hood-item premium; the 10%
    # uplift applies only when jurisdiction is exactly COUNTY_HEALTH.
    qty_total = sum(ln["quantity"] for ln in lines)
    hood_count = sum(1 for ln in lines if ln["requires_hood"])
    installation = (
        BASE_INSTALL_CENTS
        + qty_total * PER_ITEM_CENTS
        + hood_count * HOOD_PREMIUM_CENTS
    )
    if health_jurisdiction == "COUNTY_HEALTH":
        installation = round_cents(Decimal(installation) * COUNTY_UPLIFT)

    # startup_calc: integer arithmetic, no rounding.
    startup = STARTUP_BASE_CENTS + len(lines) * STARTUP_PER_ITEM_CENTS

    grand = subtotal + freight + installation + startup
    return {
        "equipment_subtotal_cents": subtotal,
        "freight_cents": freight,
        "installation_cents": installation,
        "startup_cents": startup,
        "grand_total_cents": grand,
    }
