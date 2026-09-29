"""Return refund valuation, both variants (PRD 3.9)."""
from decimal import Decimal

import clock
import db
from errors import ApiError
from services import stock as stock_svc
from services import tier as tier_svc
from services.money import round_half_up

RETURN_WINDOW_DAYS = 90
RESTOCK_FREE_WINDOW_DAYS = 30
QUOTED_MATERIAL_RESTOCK_FLOOR_PCT = Decimal("0.15")
AGE_RESTOCK_PCT = Decimal("0.10")


def elapsed_whole_days(order):
    fulfilled_at = order.get("_fulfilled_at")
    if fulfilled_at is None:
        return 0
    return clock.whole_days_between(clock.get_now(), fulfilled_at)


def value(request, order):
    """Pin valuation_mode and compute every refund figure onto the request."""
    account = db.get("pro_accounts", order["pro_account_id"])
    store = db.get("stores", order["fulfillment_store_id"])
    age_days = elapsed_whole_days(order)
    if age_days > RETURN_WINDOW_DAYS:
        raise ApiError("ERR_RETURN_WINDOW_CLOSED", 422)

    now = clock.get_now()
    quote = db.get("job_quotes", order["job_quote_id"]) if order.get("job_quote_id") else None
    quote_still_binding = (
        quote is not None
        and quote.get("_term_end") is not None
        and now <= quote["_term_end"]
    )
    mode = "QUOTED_TERM" if quote_still_binding else "CURRENT_LIST"

    # Returned lines are processed in their order lines' created_at ascending order.
    entries = []
    for req_line in request["lines"]:
        line = db.get("order_lines", req_line["order_line_id"])
        entries.append((line, req_line["qty_units"]))
    entries.sort(key=lambda pair: pair[0]["_seq"])

    gross = 0
    any_quoted = False
    for line, qty in entries:
        if line.get("price_source") == "QUOTED":
            any_quoted = True
        if mode == "QUOTED_TERM":
            refund_unit = line["effective_unit_price_cents"]
        else:
            stock = stock_svc.find_stock(order["fulfillment_store_id"], line["sku"])
            list_unit = (
                stock["list_unit_price_cents"] if stock is not None
                else line["list_unit_price_cents"]
            )
            discount = tier_svc.persisted_discount(account)
            refund_unit = round_half_up(Decimal(list_unit) * (Decimal(1) - discount))
        gross += refund_unit * qty

    age_pct = Decimal("0.00") if age_days <= RESTOCK_FREE_WINDOW_DAYS else AGE_RESTOCK_PCT
    floor_pct = QUOTED_MATERIAL_RESTOCK_FLOOR_PCT if any_quoted else Decimal("0.00")
    fee_pct = max(age_pct, floor_pct)
    fee_cents = round_half_up(Decimal(gross) * fee_pct)
    net_goods = gross - fee_cents
    if order.get("tax_exempt_applied"):
        tax_refund = 0
    else:
        tax_refund = round_half_up(Decimal(net_goods) * Decimal(str(store["tax_rate_pct"])))

    request["valuation_mode"] = mode
    request["gross_refund_cents"] = gross
    request["restocking_fee_pct"] = float(fee_pct)
    request["restocking_fee_cents"] = fee_cents
    request["tax_refund_cents"] = tax_refund
    request["refund_total_cents"] = net_goods + tax_refund
    return request


def recompute_order_refunds(order):
    """Hop one of the credit cascade."""
    credited = db.where("return_requests", pro_order_id=order["id"], status="CREDITED")
    order["credited_refund_cents"] = sum(r["refund_total_cents"] or 0 for r in credited)
    order["credited_gross_refund_cents"] = sum(r["gross_refund_cents"] or 0 for r in credited)
    order["net_volume_cents"] = (order.get("subtotal_cents") or 0) - order["credited_gross_refund_cents"]
    db.touch(order)
    return order
