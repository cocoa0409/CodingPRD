"""Pricing engine: markdowns, effective unit price, loyalty, totals, fees, floors.

Implements scaffold §1.3 / PRD §3.2, §3.5, §3.6, §3.9, §3.11, §3.7 exactly.
All monetary amounts are integer cents. Percentage discounts use round_half_up;
the price-match floor uses ceiling (PRD §2.8).
"""

from clock import parse_iso8601
from db import db
from helpers import round_half_up, round_ceil

EMBROIDERY_SURCHARGE_CENTS = 500

LOYALTY_PCT = {"BRONZE": 0, "SILVER": 5, "GOLD": 10, "PLATINUM": 15}

SERVICE_BASE_CENTS = {"SKATE_SHARPEN": 1000, "RACKET_STRING": 2500}

RESIDENT_FEE_CENTS = 2500
NONRESIDENT_FEE_CENTS = 6500

PRICE_MATCH_FLOOR_PCT = 50


# ---------------------------------------------------------------------------
# Markdown status against a clock instant
# ---------------------------------------------------------------------------
def markdown_status(markdown, clock_dt):
    """SCHEDULED before effective_from, ACTIVE within [from, until), EXPIRED at/after until."""
    eff_from = parse_iso8601(markdown["effective_from"])
    eff_until = parse_iso8601(markdown["effective_until"])
    if clock_dt < eff_from:
        return "SCHEDULED"
    if clock_dt >= eff_until:
        return "EXPIRED"
    return "ACTIVE"


def active_markdown_for_sku(sku_id, clock_dt):
    """Return the winning ACTIVE markdown for a SKU at the given instant, or None.

    Tie-break (PRD §3.2): greatest percent_off, then earliest created_at.
    """
    candidates = []
    for m in db.markdowns.values():
        if m["sku_id"] != sku_id:
            continue
        if markdown_status(m, clock_dt) == "ACTIVE":
            candidates.append(m)
    if not candidates:
        return None
    candidates.sort(key=lambda m: (-m["percent_off"], m["created_at"], m.get("_seq", 0)))
    return candidates[0]


def effective_unit_price(sku, clock_dt):
    """Base price, or markdown-discounted price if a markdown is ACTIVE (§3.2)."""
    base = sku["base_price_cents"]
    m = active_markdown_for_sku(sku["id"], clock_dt)
    if m is None:
        return base
    return round_half_up(base * (100 - m["percent_off"]), 100)


# ---------------------------------------------------------------------------
# Loyalty
# ---------------------------------------------------------------------------
def loyalty_tier_for_points(points):
    """Derive tier from points (inclusive lower bounds, §3.5)."""
    if points >= 5000:
        return "PLATINUM"
    if points >= 2000:
        return "GOLD"
    if points >= 500:
        return "SILVER"
    return "BRONZE"


def loyalty_discount(tier, subtotal_cents):
    """Tier percentage off a subtotal, rounded half up ONCE on the whole subtotal."""
    pct = LOYALTY_PCT[tier]
    if pct == 0:
        return 0
    return round_half_up(subtotal_cents * pct, 100)


# ---------------------------------------------------------------------------
# Order totals (per-line-then-sum; PRD §3.6)
# ---------------------------------------------------------------------------
def _order_lines_sorted(order_id):
    lines = [l for l in db.order_lines.values() if l["order_id"] == order_id]
    lines.sort(key=lambda l: (l["created_at"], l.get("_seq", 0)))
    return lines


def order_total_provisional(order, customer, clock_dt):
    """Provisional total at placement: markdown snapshot at placement, ignores claims.

    Captures each line's unit_price_cents. Returns provisional_total_cents.
    """
    merchandise_subtotal = 0
    for line in _order_lines_sorted(order["id"]):
        sku = db.skus[line["sku_id"]]
        eff_unit = effective_unit_price(sku, clock_dt)
        line["unit_price_cents"] = eff_unit
        line_cents = eff_unit * line["quantity"]
        embroidery = (EMBROIDERY_SURCHARGE_CENTS * line["quantity"]) if line.get("embroidery_text") else 0
        merchandise_subtotal += line_cents + embroidery
    disc = loyalty_discount(customer["loyalty_tier"], merchandise_subtotal)
    return merchandise_subtotal - disc


def order_total_final(order, customer, clock_dt):
    """Final total at fulfillment. Returns (final_total_cents, merchandise_subtotal).

    For lines with an APPROVED price-match claim, use approved_unit_price_cents;
    otherwise re-snapshot the markdown at fulfillment time (§3.6).
    """
    # Index approved claims by order_line_id (latest-approved wins if multiple).
    approved_by_line = {}
    for claim in db.price_match_claims.values():
        if claim["order_id"] != order["id"] or claim["status"] != "APPROVED":
            continue
        approved_by_line[claim["order_line_id"]] = claim["approved_unit_price_cents"]

    merchandise_subtotal = 0
    for line in _order_lines_sorted(order["id"]):
        if line["id"] in approved_by_line:
            eff_unit = approved_by_line[line["id"]]
        else:
            sku = db.skus[line["sku_id"]]
            eff_unit = effective_unit_price(sku, clock_dt)
        line_cents = eff_unit * line["quantity"]
        embroidery = (EMBROIDERY_SURCHARGE_CENTS * line["quantity"]) if line.get("embroidery_text") else 0
        merchandise_subtotal += line_cents + embroidery
    disc = loyalty_discount(customer["loyalty_tier"], merchandise_subtotal)
    return merchandise_subtotal - disc, merchandise_subtotal


# ---------------------------------------------------------------------------
# Team bulk discount (PRD §3.11)
# ---------------------------------------------------------------------------
def team_bulk_percent(total_units):
    if total_units >= 100:
        return 20
    if total_units >= 50:
        return 12
    if total_units >= 20:
        return 6
    return 0


def team_order_provisional(team_order, customer, clock_dt):
    """Spawned order provisional total: bulk discount first, then loyalty on reduced base."""
    bulk_pct = team_bulk_percent(team_order["total_units"])
    lines = [l for l in db.team_order_lines.values() if l["team_order_id"] == team_order["id"]]
    lines.sort(key=lambda l: (l["created_at"], l.get("_seq", 0)))
    merchandise_subtotal = 0
    for line in lines:
        sku = db.skus[line["sku_id"]]
        eff = effective_unit_price(sku, clock_dt)
        # Team lines are always embroidered (team_name default).
        embroidery = EMBROIDERY_SURCHARGE_CENTS * line["quantity"]
        merchandise_subtotal += eff * line["quantity"] + embroidery
    bulk_disc = round_half_up(merchandise_subtotal * bulk_pct, 100)
    disc = loyalty_discount(customer["loyalty_tier"], merchandise_subtotal - bulk_disc)
    return merchandise_subtotal - bulk_disc - disc


# ---------------------------------------------------------------------------
# Service fee (PRD §3.9)
# ---------------------------------------------------------------------------
def service_fee(service_type, tier):
    base = SERVICE_BASE_CENTS[service_type]
    pct = LOYALTY_PCT[tier]
    return round_half_up(base * (100 - pct), 100)


# ---------------------------------------------------------------------------
# License fee (PRD §3.4)
# ---------------------------------------------------------------------------
def license_fee(residency):
    return RESIDENT_FEE_CENTS if residency == "RESIDENT" else NONRESIDENT_FEE_CENTS


# ---------------------------------------------------------------------------
# Price-match floor (PRD §3.7)
# ---------------------------------------------------------------------------
def price_match_floor(unit_price_cents):
    """Ceiling of 50% of the line's unit_price_cents."""
    return round_ceil(unit_price_cents * PRICE_MATCH_FLOOR_PCT, 100)


def approved_unit_price(unit_price_cents, competitor_price_cents):
    floor = price_match_floor(unit_price_cents)
    return max(competitor_price_cents, floor)
