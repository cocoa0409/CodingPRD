"""Derived-total recomputation for a StudioVisit (PRD §2.6, §3.2).

bisque_subtotal_cents = sum of bisque_price_cents over non-VOIDED pieces.
supplies_subtotal_cents = sum of non-voided supply-line charge_cents.
provisional_total_cents = studio_fee + bisque_subtotal + supplies_subtotal
                          (no discount, no redemption).
"""

from db import db
from services import calculations


def pieces_on_visit(visit_id):
    return [p for p in db.bisque_pieces.values() if p["studio_visit_id"] == visit_id]


def supply_lines_on_visit(visit_id):
    return [l for l in db.supply_lines.values() if l["visit_id"] == visit_id]


def recompute_bisque_subtotal(visit):
    total = 0
    for p in pieces_on_visit(visit["id"]):
        if p["status"] != "VOIDED":
            total += p["bisque_price_cents"]
    visit["bisque_subtotal_cents"] = total
    return total


def recompute_supplies_subtotal(visit):
    total = 0
    for line in supply_lines_on_visit(visit["id"]):
        if not line["voided"]:
            total += line["charge_cents"]
    visit["supplies_subtotal_cents"] = total
    return total


def recompute_provisional(visit):
    """Recompute the provisional total from current subtotals (provisional
    variant: gross, no discount, no loyalty)."""
    visit["provisional_total_cents"] = calculations.provisional_total(
        visit["studio_fee_cents"],
        visit["bisque_subtotal_cents"],
        visit["supplies_subtotal_cents"],
    )
    return visit["provisional_total_cents"]


def recompute_all(visit):
    recompute_bisque_subtotal(visit)
    recompute_supplies_subtotal(visit)
    recompute_provisional(visit)
