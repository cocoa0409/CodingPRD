"""parts_order_pricing (PRD 3.6) — exact rational arithmetic, one rounding point."""
from fractions import Fraction

import db
from db import setf
from services.compliance import published_revision
from util import round_half_up

ONE = Fraction(1)

BUYER_MULTIPLIER = {
    "SELF_REPAIR_CONSUMER": ONE,
    "AUTHORIZED_PROVIDER": Fraction(82, 100),
}

TIER_SURCHARGE = {
    "TIER_A_SELF_SERVICE": ONE,
    "TIER_B_GUIDED": Fraction(105, 100),
    "TIER_C_AUTHORIZED_ONLY": Fraction(112, 100),
    "TIER_D_NON_SERVICEABLE": ONE,
}

CONSUMER_CORE_DEPOSIT_CAP_CENTS = 50000


def volume_multiplier(quantity):
    if quantity >= 25:
        return Fraction(85, 100)
    if quantity >= 10:
        return Fraction(92, 100)
    return ONE


def order_lines(order_id):
    return db.ordered([l for l in db.db.lines.all() if l["order_id"] == order_id])


def core_face_value_cents(order_id):
    """Sum of core_credit_cents * quantity over every core-return-required line."""
    total = 0
    for line in order_lines(order_id):
        part = db.db.parts.get(line["part_id"])
        if part is not None and part.get("core_return_required"):
            total += part["core_credit_cents"] * line["quantity"]
    return total


def core_face_value_by_part(order_id):
    per_part = {}
    for line in order_lines(order_id):
        part = db.db.parts.get(line["part_id"])
        if part is not None and part.get("core_return_required"):
            per_part[part["id"]] = per_part.get(part["id"], 0) + (
                part["core_credit_cents"] * line["quantity"]
            )
    return per_part


def prospective_core_deposit(order, extra_part=None, extra_quantity=0):
    total = core_face_value_cents(order["id"])
    if extra_part is not None and extra_part.get("core_return_required"):
        total += extra_part["core_credit_cents"] * extra_quantity
    return total


def documentation_fee_cents(order):
    profile = None
    for candidate in db.db.profiles.all():
        if candidate["region_code"] == order["region_code"]:
            profile = candidate
            break
    if profile is None:
        return 0
    if profile.get("requires_public_manual"):
        return 0
    guide = published_revision(order["model_id"], "DISASSEMBLY_GUIDE")
    warnings = guide["safety_warning_count"] if guide is not None else 0
    return min(profile["max_documentation_fee_cents"], 500 + 120 * warnings)


def price_line(line, order, model, part):
    buyer = BUYER_MULTIPLIER.get(order["buyer_class"], ONE)
    volume = volume_multiplier(line["quantity"])
    tier = TIER_SURCHARGE.get(model["repairability_tier"], ONE)
    unit_effective = Fraction(part["list_price_cents"]) * buyer * volume * tier
    setf(line, "buyer_multiplier", buyer)
    setf(line, "volume_multiplier", volume)
    setf(line, "tier_surcharge_multiplier", tier)
    setf(line, "unit_price_cents", round_half_up(unit_effective))
    setf(line, "line_total_cents", round_half_up(unit_effective * line["quantity"]))


def price_order(order):
    """Recompute every line and every order-level money field from scratch."""
    model = db.db.models.get(order["model_id"])
    lines = order_lines(order["id"])

    parts_subtotal = 0
    tool_purchase = 0
    rental_deposit = 0
    core_deposit = 0

    for line in lines:
        part = db.db.parts.get(line["part_id"])
        if part is None or model is None:
            continue
        price_line(line, order, model, part)
        part_class = part["part_class"]
        if part_class in ("COMPONENT", "CONSUMABLE"):
            parts_subtotal += line["line_total_cents"]
        elif part_class == "TOOL":
            tool_purchase += line["line_total_cents"]
        if part_class == "RENTAL_KIT":
            rental_deposit += part["rental_deposit_cents"] * line["quantity"]
        if part.get("core_return_required"):
            core_deposit += part["core_credit_cents"] * line["quantity"]

    doc_fee = documentation_fee_cents(order)

    setf(order, "parts_subtotal_cents", parts_subtotal)
    setf(order, "tool_purchase_cents", tool_purchase)
    setf(order, "rental_deposit_cents", rental_deposit)
    setf(order, "documentation_fee_cents", doc_fee)
    setf(order, "core_deposit_cents", core_deposit)
    setf(order, "total_due_cents",
         parts_subtotal + tool_purchase + rental_deposit + doc_fee + core_deposit)
