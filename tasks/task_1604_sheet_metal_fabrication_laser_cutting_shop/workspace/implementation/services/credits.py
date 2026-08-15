"""Scrap credit posting and the payment-time FIFO application waterfall."""
from decimal import Decimal

from db import store, new_id, touch, new_common
from errors import ApiError
from services.pricing import dec, rhu, money

STANDARD_SHEET_AREA_CM2 = Decimal("28800")
CREDIT_CAP_FRACTION = Decimal("0.10")
MAX_CREDIT_AREA_PER_EVENT = Decimal("90000")


def post_scrap_credit(customer, sheet):
    """Polymorphic source: REMNANT surrendered from inventory (-> SCRAPPED) or a
    walk-in sheet with no source order (-> DROPPED_OFF)."""
    if sheet["status"] != "AVAILABLE":
        raise ApiError("ERR_SCRAP_SOURCE_INVALID", 422,
                       "Source sheet is not AVAILABLE")
    if sheet["source_order_id"] is not None:
        order = store.orders.get(sheet["source_order_id"])
        if order is None or order["customer_id"] != customer["id"]:
            raise ApiError("ERR_SCRAP_SOURCE_INVALID", 422,
                           "Remnant belongs to a different customer")
        new_sheet_status = "SCRAPPED"
    else:
        new_sheet_status = "DROPPED_OFF"

    grade = store.material_grades[sheet["grade_id"]]
    sheet_area = Decimal(sheet["width_mm"] * sheet["height_mm"]) / Decimal(100)
    credited_area = min(sheet_area, CREDIT_CAP_FRACTION * STANDARD_SHEET_AREA_CM2,
                        MAX_CREDIT_AREA_PER_EVENT)
    credited_area = rhu(credited_area, 1)
    credit_cents = money(credited_area * dec(grade["scrap_rate_cents_per_cm2"]))

    sheet["status"] = new_sheet_status
    touch(sheet)
    customer["scrap_credit_balance_cents"] += credit_cents
    touch(customer)

    credit = {
        "id": new_id(),
        "customer_id": customer["id"],
        "sheet_stock_id": sheet["id"],
        "credited_area_cm2": float(credited_area),
        "credit_cents": credit_cents,
        "status": "POSTED",
    }
    new_common(credit)
    store.scrap_credits[credit["id"]] = credit
    return credit


def apply_scrap_credit(customer, amount):
    """Drain the customer's POSTED credits FIFO by created_at ASC. Whole rows are
    consumed; the final partial row is split: the original becomes APPLIED and a
    VOID replacement row carries the unconsumed remainder."""
    rows = [c for c in store.scrap_credits.values()
            if c["customer_id"] == customer["id"] and c["status"] == "POSTED"]
    rows.sort(key=lambda c: (c["created_at"], c["_seq"]))
    remaining = amount
    for row in rows:
        if remaining <= 0:
            break
        if row["credit_cents"] <= remaining:
            remaining -= row["credit_cents"]
            row["status"] = "APPLIED"
            touch(row)
        else:
            consumed = remaining
            remainder = row["credit_cents"] - consumed
            original_area = dec(row["credited_area_cm2"])
            if row["credit_cents"] > 0:
                consumed_area = rhu(original_area
                                    * Decimal(consumed) / Decimal(row["credit_cents"]), 1)
            else:
                consumed_area = Decimal(0)
            remainder_area = original_area - consumed_area
            row["credit_cents"] = consumed
            row["credited_area_cm2"] = float(consumed_area)
            row["status"] = "APPLIED"
            touch(row)
            split = {
                "id": new_id(),
                "customer_id": customer["id"],
                "sheet_stock_id": row["sheet_stock_id"],
                "credited_area_cm2": float(remainder_area),
                "credit_cents": remainder,
                "status": "VOID",
            }
            new_common(split)
            store.scrap_credits[split["id"]] = split
            remaining = 0
    customer["scrap_credit_balance_cents"] -= amount
    touch(customer)
