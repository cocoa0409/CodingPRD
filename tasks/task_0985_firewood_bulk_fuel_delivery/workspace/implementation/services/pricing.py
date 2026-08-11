"""Pricing pipeline per PRD §3.6 — all 14 calculation rules live here or nearby.

Stages (in order):
  1. cord_equivalent_conversion        (line_cord_equivalent, total_cord_equivalent)
  2. seasoned_grade_price_multiplier   (unit_price_cents, set at line-add time)
  3. volume_tiered_discount            (marginal tiers, extended_price_cents, volume_discount_cents, subtotal_cents)
  4. subscription_discount             (subscription_discount_cents)
  5. loyalty_tier_discount             (loyalty_discount_cents)
  6. seasonal_surcharge                (seasonal_surcharge_cents)
  7. stacking_fee                      (stacking_fee_cents)
  8. delivery_fee                      (delivery_fee_cents)
  9. order_total                       (total_cents)

Auxiliary calculations (not part of order recompute):
 10. cancellation_fee
 11. subscription_shortfall_penalty
 12. subscription_early_termination_clawback
 13. moisture_pass_fail
 14. invoice_amount_snapshot
"""

import math
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import errors
from db import db
from util import dec, round_half_up_int, round_half_up_3dp

# --- Constants (PRD §3.6) ---
CORD_EQUIVALENT_PER_UNIT = {
    "CORD": Decimal("1.0"),
    "HALF_CORD": Decimal("0.5"),
    "PELLET_TON": Decimal("0.8"),
    "PELLET_BAG": Decimal("0.016"),
}

GRADE_MULTIPLIER = {
    "GREEN": Decimal("0.75"),
    "SEMI_SEASONED": Decimal("1.00"),
    "KILN_DRIED": Decimal("1.35"),
}

# Volume tiers: (lower_bound_ce_inclusive, rate)
VOLUME_TIERS = [
    (Decimal("0"),   Decimal("8.0"),  "T3", Decimal("0.11")),
    (Decimal("0"),   Decimal("4.0"),  "T2", Decimal("0.07")),
    (Decimal("0"),   Decimal("2.0"),  "T1", Decimal("0.04")),
    (Decimal("0"),   Decimal("0"),    "T0", Decimal("0")),
]
# Marginal boundaries: [0,2)=0%, [2,4)=4%, [4,8)=7%, [8,inf)=11%
TIER_BOUNDARIES = [
    (Decimal("0"),   Decimal("2.0"),  "T0", Decimal("0")),
    (Decimal("2.0"), Decimal("4.0"),  "T1", Decimal("0.04")),
    (Decimal("4.0"), Decimal("8.0"),  "T2", Decimal("0.07")),
    (Decimal("8.0"), None,            "T3", Decimal("0.11")),
]

LOYALTY_RATE = {"STANDARD": Decimal("0"), "SILVER": Decimal("0.02"), "GOLD": Decimal("0.04")}
SURCHARGE_RATE = {"STANDARD": Decimal("0.12"), "SILVER": Decimal("0.08"), "GOLD": Decimal("0")}

PEAK_START = (12, 15)  # Dec 15
PEAK_END = (2, 15)     # Feb 15

STACKING_FLAT_CENTS = 3500
STACKING_PER_CORD_CENTS = 1200

ZONE_FEES = {"A": 4500, "B": 6500, "C": 9500}
BULK_T1 = Decimal("4.0")
BULK_T2 = Decimal("8.0")
BULK_SURCHARGE = 1500


def compute_unit_price_cents(product):
    """seasoned_grade_price_multiplier: base * multiplier, round half-up to int cents."""
    mult = GRADE_MULTIPLIER[product["seasoned_grade"]]
    return round_half_up_int(dec(product["base_price_cents"]) * mult)


def line_cord_equivalent(product_kind, quantity):
    """cord_equivalent_conversion at line level; round half-up 3dp."""
    factor = CORD_EQUIVALENT_PER_UNIT[product_kind]
    return round_half_up_3dp(dec(quantity) * factor)


def _tier_for_ce(ce):
    """Tier name for a cumulative cord-equivalent position (lower bound inclusive)."""
    if ce >= Decimal("8.0"):
        return "T3"
    if ce >= Decimal("4.0"):
        return "T2"
    if ce >= Decimal("2.0"):
        return "T1"
    return "T0"


def _price_line_marginal(line, cumulative_before):
    """Compute extended_price_cents for one line using marginal tier allocation.

    cumulative_before: Decimal cord-equivalents consumed by earlier lines.
    Portions are summed unrounded; the line total is rounded half-up once.
    Returns (extended_price_cents, tier_applied) where tier_applied is the tier
    reached by the cumulative position at the END of this line.
    """
    line_ce = dec(line["line_cord_equivalent"])
    per_unit = dec(line["cord_equivalent_per_unit"])
    unit_price = dec(line["unit_price_cents"])
    line_end = cumulative_before + line_ce

    total = Decimal("0")
    for low, high, _tname, rate in TIER_BOUNDARIES:
        span_start = max(cumulative_before, low)
        span_end = min(line_end, high) if high is not None else line_end
        if span_end > span_start:
            portion_ce = span_end - span_start
            portion_units = portion_ce / per_unit
            total += unit_price * portion_units * (Decimal("1") - rate)

    extended = round_half_up_int(total)
    # Tier reached at the line's cumulative end. A line ending exactly on a
    # boundary (e.g. cumulative == 2.0) has reached the tier whose range starts
    # at that boundary.
    tier_applied = _tier_for_ce(line_end)
    return extended, tier_applied


def compute_order_volume(lines):
    """Sum line_cord_equivalent over lines."""
    total = Decimal("0")
    for ln in lines:
        total += dec(ln["line_cord_equivalent"])
    return float(total)


def in_winter_peak(date_str):
    """Dec 15 through Feb 15 inclusive (window wraps year end)."""
    m, d = int(date_str[5:7]), int(date_str[8:10])
    md = (m, d)
    return md >= PEAK_START or md <= PEAK_END


def season_window_contains(sub, date_str):
    """Check requested_delivery_date within [Nov 1 season_year, Mar 31 season_year+1]."""
    y = sub["season_year"]
    start = date(y, 11, 1)
    end = date(y + 1, 3, 31)
    d = date(int(date_str[0:4]), int(date_str[5:7]), int(date_str[8:10]))
    return start <= d <= end


def select_route_for_postal(postal_code):
    """delivery_fee route selection: longest-prefix match over ACTIVE routes.

    Tie-breaks: smaller capacity_cord_equivalent, then smaller route_code.
    Returns (route, matched_prefix_len) or raises ERR_NO_ROUTE.
    """
    candidates = []
    for r in db.delivery_routes.values():
        if not r.get("active", True):
            continue
        best = 0
        for p in r.get("service_postal_prefixes", []):
            if postal_code.startswith(p) and len(p) > best:
                best = len(p)
        if best > 0:
            candidates.append((r, best))
    if not candidates:
        raise errors.no_route()
    candidates.sort(key=lambda t: (-t[1], dec(t[0]["capacity_cord_equivalent"]), t[0]["route_code"]))
    return candidates[0]


def zone_fee_for_prefix_len(n):
    if n >= 5:
        return ZONE_FEES["A"]
    if n >= 3:
        return ZONE_FEES["B"]
    return ZONE_FEES["C"]


def compute_delivery_fee(order):
    """delivery_fee: provisional (longest-prefix route) vs final (bound window's route)."""
    total_ce = dec(order["total_cord_equivalent"])
    fee = 0
    if order.get("delivery_window_id"):
        window = db.delivery_windows.get(order["delivery_window_id"])
        if window:
            route = db.delivery_routes.get(window["route_id"])
            if route:
                best = 0
                for p in route.get("service_postal_prefixes", []):
                    if order["delivery_postal_code"].startswith(p) and len(p) > best:
                        best = len(p)
                fee = zone_fee_for_prefix_len(best if best > 0 else 1)
    else:
        _route, prefix_len = select_route_for_postal(order["delivery_postal_code"])
        fee = zone_fee_for_prefix_len(prefix_len)
    if total_ce > BULK_T1:
        fee += BULK_SURCHARGE
    if total_ce > BULK_T2:
        fee += BULK_SURCHARGE
    return fee


def recompute_order_pricing(order, lines):
    """Full pricing pipeline over an order and its current lines. Mutates order + lines."""
    # Stage 1: cord-equivalents (already set on lines at add/update time; total here)
    total_ce = Decimal("0")
    for ln in lines:
        total_ce += dec(ln["line_cord_equivalent"])
    order["total_cord_equivalent"] = float(total_ce)

    # Stage 3: marginal volume pricing — lines sorted created_at ASC, line_ce DESC on tie
    sorted_lines = sorted(
        lines,
        key=lambda l: (l["created_at"], -dec(l["line_cord_equivalent"])),
    )
    cumulative = Decimal("0")
    subtotal = 0
    extended_sum = 0
    for ln in sorted_lines:
        extended, tier = _price_line_marginal(ln, cumulative)
        ln["extended_price_cents"] = extended
        ln["volume_tier_applied"] = tier
        undiscounted = round_half_up_int(dec(ln["unit_price_cents"]) * dec(ln["quantity"]))
        # PRD §3.6: subtotal_cents is the gross sum of the per-line extended
        # (unit_price x quantity) amounts; volume_discount_cents is the
        # undiscounted amount minus the discounted extended_price_cents.
        # Downstream stages consume "the subtotal net of the volume discount"
        # (i.e. subtotal - volume_discount == sum of extended_price_cents),
        # and the grand total subtracts each discount exactly once.
        subtotal += undiscounted
        extended_sum += extended
        cumulative += dec(ln["line_cord_equivalent"])
    order["subtotal_cents"] = subtotal
    order["volume_discount_cents"] = subtotal - extended_sum

    # Stage 4: subscription discount
    customer = db.customers.get(order["customer_id"])
    sub = db.subscriptions.get(order["subscription_id"]) if order.get("subscription_id") else None
    sub_qualifies = (
        sub is not None
        and sub["status"] == "ACTIVE"
        and season_window_contains(sub, order["requested_delivery_date"])
    )
    base_after_volume = subtotal - order["volume_discount_cents"]
    if sub_qualifies:
        order["subscription_discount_cents"] = round_half_up_int(
            dec(base_after_volume) * dec(sub["discount_pct"])
        )
    else:
        order["subscription_discount_cents"] = 0

    # Stage 5: loyalty discount
    base_after_subs = base_after_volume - order["subscription_discount_cents"]
    tier = customer["loyalty_tier"] if customer else "STANDARD"
    order["loyalty_discount_cents"] = round_half_up_int(
        dec(base_after_subs) * LOYALTY_RATE[tier]
    )

    # Stage 6: seasonal surcharge
    base_after_all = base_after_subs - order["loyalty_discount_cents"]
    if in_winter_peak(order["requested_delivery_date"]):
        order["seasonal_surcharge_cents"] = round_half_up_int(
            dec(base_after_all) * SURCHARGE_RATE[tier]
        )
    else:
        order["seasonal_surcharge_cents"] = 0

    # Stage 7: stacking fee
    if not order.get("stacking_addon", False):
        order["stacking_fee_cents"] = 0
    elif sub_qualifies and sub.get("stacking_included", False):
        order["stacking_fee_cents"] = 0
    else:
        whole_cords = math.ceil(float(total_ce)) if total_ce > 0 else 0
        order["stacking_fee_cents"] = STACKING_FLAT_CENTS + round_half_up_int(
            dec(whole_cords) * dec(STACKING_PER_CORD_CENTS)
        )

    # Stage 8: delivery fee
    order["delivery_fee_cents"] = compute_delivery_fee(order)

    # Stage 9: total (no further rounding)
    order["total_cents"] = (
        order["subtotal_cents"]
        - order["volume_discount_cents"]
        - order["subscription_discount_cents"]
        - order["loyalty_discount_cents"]
        + order["seasonal_surcharge_cents"]
        + order["stacking_fee_cents"]
        + order["delivery_fee_cents"]
    )


# --- 10. cancellation_fee ---
def compute_cancellation_fee(order, window, actor_role, now_dt):
    """10% of total_cents when admin override OR < 72 hours until service; else 0."""
    if actor_role == "OperationsManager":
        return round_half_up_int(dec(order["total_cents"]) * Decimal("0.10"))
    service_dt = datetime(
        int(window["service_date"][0:4]),
        int(window["service_date"][5:7]),
        int(window["service_date"][8:10]),
        window["start_hour"], 0, 0, tzinfo=timezone.utc,
    )
    delta = service_dt - now_dt
    hours = math.floor(delta.total_seconds() / 3600)
    if hours < 72:
        return round_half_up_int(dec(order["total_cents"]) * Decimal("0.10"))
    return 0


# --- 11. subscription_shortfall_penalty ---
def compute_shortfall_penalty(sub):
    """20% of shortfall CE times reference price (weighted avg of KILN_DRIED CORD
    unit prices on customer's DELIVERED orders this season; fallback: highest
    KILN_DRIED CORD base_price * 1.35)."""
    shortfall_ce = dec(sub["commitment_cord_equivalent"]) - dec(sub["delivered_cord_equivalent"])
    if shortfall_ce <= 0:
        return 0
    # Weighted average over KILN_DRIED CORD lines on DELIVERED orders this season
    total_weight = Decimal("0")
    total_value = Decimal("0")
    for order in db.orders.values():
        if order["customer_id"] != sub["customer_id"]:
            continue
        if order["fulfillment_status"] != "DELIVERED":
            continue
        if not season_window_contains(sub, order["requested_delivery_date"]):
            continue
        for line in db.order_lines.values():
            if line["order_id"] != order["id"]:
                continue
            product = db.products.get(line["product_id"])
            if not product:
                continue
            if product["product_kind"] == "CORD" and product["seasoned_grade"] == "KILN_DRIED":
                q = dec(line["quantity"])
                total_weight += q
                total_value += dec(line["unit_price_cents"]) * q
    if total_weight > 0:
        avg_price = total_value / total_weight
    else:
        best = None
        for p in db.products.values():
            if p["product_kind"] == "CORD" and p["seasoned_grade"] == "KILN_DRIED":
                v = dec(p["base_price_cents"])
                if best is None or v > best:
                    best = v
        if best is None:
            avg_price = Decimal("0")
        else:
            avg_price = best * Decimal("1.35")
    return round_half_up_int(shortfall_ce * avg_price * Decimal("0.20"))


# --- 12. subscription_early_termination_clawback ---
def compute_clawback(sub):
    """Sum subscription_discount_cents over DELIVERED orders referencing this
    subscription, plus flat 5000-cent admin fee."""
    total = 0
    for order in db.orders.values():
        if order.get("subscription_id") == sub["id"] and order["fulfillment_status"] == "DELIVERED":
            total += order.get("subscription_discount_cents", 0)
    return total + 5000


# --- 13. moisture_pass_fail ---
def compute_reading_pass(moisture_pct, product):
    return dec(moisture_pct) <= dec(product["moisture_ceiling_pct"])


# --- 14. invoice_amount_snapshot ---
def next_invoice_number(season_year):
    seq = db.invoice_seq_by_year.get(season_year, 0) + 1
    db.invoice_seq_by_year[season_year] = seq
    return f"INV-{season_year}-{seq:06d}"


def invoice_due_date(requested_delivery_date):
    d = date(
        int(requested_delivery_date[0:4]),
        int(requested_delivery_date[5:7]),
        int(requested_delivery_date[8:10]),
    )
    return (d + timedelta(days=7)).isoformat()
