"""The pricing engine (PRD 3.5) and the accrual / settlement calculations."""
from decimal import Decimal

from db import db, in_creation_order, touch
from util import dec, floor_int, rhu

TIER_DISCOUNT_PCT = {"INSIDER": Decimal("0.00"), "VIB": Decimal("0.10"), "ROUGE": Decimal("0.15")}
TIER_MULTIPLIER = {"INSIDER": Decimal("1.0"), "VIB": Decimal("1.5"), "ROUGE": Decimal("2.0")}
TIER_RANK = {"INSIDER": 0, "VIB": 1, "ROUGE": 2}

TIER_THRESHOLD_VIB_CENTS = 35000
TIER_THRESHOLD_ROUGE_CENTS = 100000

POINTS_REDEEM_BLOCK = 100
POINTS_REDEEM_VALUE_CENTS = 500

SKINCARE_BONUS_POINTS = 50
SKINCARE_BONUS_MIN_LINE_NET = 5000
POINTS_EARN_CAP_PER_ORDER = 5000

RESTOCK_FEE_PCT_TESTER_APPLIED = Decimal("0.10")


def order_lines(order_id, line_type=None):
    lines = [l for l in db.order_lines.values() if l["order_id"] == order_id]
    if line_type is not None:
        lines = [l for l in lines if l["line_type"] == line_type]
    return in_creation_order(lines)


def sale_lines(order_id):
    return order_lines(order_id, "SALE")


# --------------------------------------------------------------------------
# promotion selectors
# --------------------------------------------------------------------------

def select_bundle(lines, qty_of):
    """Highest bundle_discount_pct wins; ties by priority ASC then created_at ASC."""
    present = set(l["variant_id"] for l in lines if qty_of(l) >= 1)
    candidates = []
    for promo in db.promotions.values():
        if promo["promo_type"] != "BUNDLE" or promo["status"] != "ACTIVE":
            continue
        members = promo.get("bundle_variant_ids") or []
        if not members:
            continue
        if all(vid in present for vid in members):
            candidates.append(promo)
    if not candidates:
        return None
    candidates.sort(key=lambda p: (-dec(p["bundle_discount_pct"]), p["priority"], p["_seq"]))
    return candidates[0]


def select_gwp(discounted_subtotal_cents):
    """Largest threshold_cents at or below the discounted subtotal wins;
    ties by priority ASC then created_at ASC."""
    candidates = [
        p for p in db.promotions.values()
        if p["promo_type"] == "GWP" and p["status"] == "ACTIVE"
        and p["threshold_cents"] <= discounted_subtotal_cents
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda p: (-p["threshold_cents"], p["priority"], p["_seq"]))
    return candidates[0]


def eligible_samples(discounted_subtotal_cents):
    candidates = [
        p for p in db.promotions.values()
        if p["promo_type"] == "SAMPLE" and p["status"] == "ACTIVE"
        and p["threshold_cents"] <= discounted_subtotal_cents
    ]
    return in_creation_order(candidates)


# --------------------------------------------------------------------------
# the pinned pricing pass
# --------------------------------------------------------------------------

def compute(lines, qty_of, tier, points_redeemed):
    """Pure evaluation of the six pinned steps of PRD 3.5.  `lines` are the SALE
    lines; `qty_of(line)` gives the quantity this pass should price."""
    bundle = select_bundle(lines, qty_of)
    members = set(bundle["bundle_variant_ids"]) if bundle else set()

    per_line = {}
    subtotal = 0
    for line in lines:
        quantity = qty_of(line)
        gross = line["unit_price_cents"] * quantity
        if bundle and line["variant_id"] in members:
            discount = rhu(dec(gross) * dec(bundle["bundle_discount_pct"]))
        else:
            discount = 0
        net = gross - discount
        per_line[line["id"]] = {
            "quantity": quantity,
            "line_gross_cents": gross,
            "line_discount_cents": discount,
            "line_net_cents": net,
        }
        subtotal += net

    tier_discount = rhu(dec(subtotal) * TIER_DISCOUNT_PCT[tier])
    discounted_subtotal = subtotal - tier_discount
    gwp = select_gwp(discounted_subtotal)
    points_value = (points_redeemed // POINTS_REDEEM_BLOCK) * POINTS_REDEEM_VALUE_CENTS
    total_due = discounted_subtotal - points_value

    return {
        "bundle": bundle,
        "per_line": per_line,
        "subtotal_cents": subtotal,
        "tier_discount_cents": tier_discount,
        "discounted_subtotal_cents": discounted_subtotal,
        "gwp": gwp,
        "gwp_eligible": gwp is not None,
        "points_value_cents": points_value,
        "total_due_cents": total_due,
    }


def apply_pricing(order, lines, result, pricing_variant):
    """Write the computed money onto the order and its SALE lines."""
    for line in lines:
        values = result["per_line"][line["id"]]
        changed = (
            line["quantity"] != values["quantity"]
            or line["line_gross_cents"] != values["line_gross_cents"]
            or line["line_discount_cents"] != values["line_discount_cents"]
            or line["line_net_cents"] != values["line_net_cents"]
        )
        line["quantity"] = values["quantity"]
        line["line_gross_cents"] = values["line_gross_cents"]
        line["line_discount_cents"] = values["line_discount_cents"]
        line["line_net_cents"] = values["line_net_cents"]
        if changed:
            touch(line)

    order["subtotal_cents"] = result["subtotal_cents"]
    order["tier_discount_cents"] = result["tier_discount_cents"]
    order["discounted_subtotal_cents"] = result["discounted_subtotal_cents"]
    order["gwp_eligible"] = result["gwp_eligible"]
    order["points_value_cents"] = result["points_value_cents"]
    order["total_due_cents"] = result["total_due_cents"]
    order["pricing_variant"] = pricing_variant


def reprice_provisional(order):
    """PROVISIONAL pass: requested quantities verbatim, stock never consulted,
    priced at the customer's tier as it stands right now, nothing materialised."""
    customer = db.customers[order["customer_id"]]
    lines = sale_lines(order["id"])
    result = compute(lines, lambda l: l["quantity"], customer["tier"], order["points_redeemed"])
    apply_pricing(order, lines, result, "PROVISIONAL")
    return result


# --------------------------------------------------------------------------
# points accrual (PRD 3.7)
# --------------------------------------------------------------------------

def points_accrual(order):
    base_points = order["total_due_cents"] // 100
    multiplier = TIER_MULTIPLIER[order["tier_at_reserve"]]
    tier_points = floor_int(dec(base_points) * multiplier)

    bonus = 0
    for line in sale_lines(order["id"]):
        variant = db.variants.get(line["variant_id"])
        if not variant:
            continue
        product = db.products.get(variant["product_id"])
        if not product:
            continue
        if product["category"] == "SKINCARE" and line["line_net_cents"] >= SKINCARE_BONUS_MIN_LINE_NET:
            bonus = SKINCARE_BONUS_POINTS
            break

    return min(tier_points + bonus, POINTS_EARN_CAP_PER_ORDER)


# --------------------------------------------------------------------------
# refund settlement (PRD 3.9)
# --------------------------------------------------------------------------

def refund_settlement(order, line, quantity):
    refund_line_cents = rhu(dec(line["line_net_cents"]) * dec(quantity) / dec(line["quantity"]))

    if order["subtotal_cents"] > 0:
        tier_share_cents = rhu(
            dec(order["tier_discount_cents"]) * dec(refund_line_cents) / dec(order["subtotal_cents"])
        )
    else:
        tier_share_cents = 0

    hygiene = line["hygiene_class"]
    if hygiene == "TESTER_APPLIED":
        restocking_fee_cents = rhu(dec(refund_line_cents) * RESTOCK_FEE_PCT_TESTER_APPLIED)
    else:
        restocking_fee_cents = 0

    refund_cents = refund_line_cents - tier_share_cents - restocking_fee_cents
    multiplier = TIER_MULTIPLIER[order["tier_at_reserve"]]
    points_clawback = floor_int(dec(refund_cents // 100) * multiplier)
    disposition = "RESTOCK" if hygiene == "SEALED" else "DESTROY"

    return {
        "refund_line_cents": refund_line_cents,
        "restocking_fee_cents": restocking_fee_cents,
        "refund_cents": refund_cents,
        "points_clawback": points_clawback,
        "disposition": disposition,
    }
