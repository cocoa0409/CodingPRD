"""Contract price resolution and order total aggregation (scaffold §1.3).

Exactly one rounding event exists in the pricing pipeline: the contract unit
price is rounded half-up to a whole cent at the very end of the unit-price
calculation (the discounted base is never rounded). Line totals are integer
multiplications; the subtotal is the sum of rounded line totals.
"""
from decimal import Decimal, ROUND_HALF_UP

import db


def resolve_unit_price(cust, product, qty):
    """Snapshot unit price for one line at confirm time, against the clock."""
    book_id = cust.get("price_book_id")
    if book_id:
        book = db.store.price_books.get(book_id)
        if book is not None and book["status"] == "ACTIVE":
            now = db.clock_now()
            if book["_from"] <= now < book["_to"]:
                base = (Decimal(product["retail_price_cents"])
                        * (Decimal(1) - Decimal(str(book["default_discount_pct"]))))
                extra = 0
                qualifying = [t for t in (book.get("volume_tiers") or [])
                              if t["min_qty"] <= qty]
                if qualifying:
                    best = max(qualifying, key=lambda t: t["min_qty"])
                    extra = best["extra_discount_pct"]
                unit = (base * (Decimal(1) - Decimal(str(extra)))).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP)
                return int(unit)
    return product["retail_price_cents"]


def price_lines(cust, lines):
    """Attach unit_price_cents / line_total_cents snapshots to each line."""
    for line in lines:
        product = db.store.products[line["product_id"]]
        unit = resolve_unit_price(cust, product, line["qty"])
        line["unit_price_cents"] = unit
        line["line_total_cents"] = unit * line["qty"]


def aggregate_totals(order):
    """Pinned evaluation order: subtotal, delivery fee, hazmat fee, total."""
    subtotal = sum(l["line_total_cents"] for l in order["lines"])
    if order["fulfillment"] == "ROUTE" and subtotal < db.FREE_DELIVERY_THRESHOLD_CENTS:
        delivery = db.DELIVERY_FEE_CENTS
    else:
        delivery = 0
    hazmat = db.HAZMAT_FEE_CENTS if any(
        db.store.products[l["product_id"]]["hazmat"] for l in order["lines"]) else 0
    order["subtotal_cents"] = subtotal
    order["delivery_fee_cents"] = delivery
    order["hazmat_fee_cents"] = hazmat
    order["total_cents"] = subtotal + delivery + hazmat
