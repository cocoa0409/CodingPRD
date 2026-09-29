"""order_line_pricing + order_total_assembly (PRD 3.6)."""
from decimal import Decimal

import clock
import db
from errors import ApiError
from services import stock as stock_svc
from services import tier as tier_svc
from services.money import round_half_up

FREIGHT_BASE_SURCHARGE_CENTS = 8900
FREIGHT_WAIVER_SUBTOTAL_CENTS = 250000
LIFT_GATE_FEE_CENTS = 4500


def order_lines_of(order):
    return db.where("order_lines", pro_order_id=order["id"])


def _quote_line_for(quote, sku):
    for line in db.where("quote_lines", job_quote_id=quote["id"]):
        if line["sku"] == sku:
            return line
    return None


def compute(order, persist=False):
    """Run the whole pricing computation against the current clock and tier.

    Returns the computed figures; writes them onto the order and its lines only
    when persist is true (the pricing preview persists nothing).
    """
    account = db.get("pro_accounts", order["pro_account_id"])
    store = db.get("stores", order["fulfillment_store_id"])
    lines = order_lines_of(order)

    # --- step 1a: list prices from the FULFILLMENT store, in line creation order ---
    line_plan = []
    list_subtotal = 0
    for line in lines:
        stock = stock_svc.find_stock(order["fulfillment_store_id"], line["sku"])
        if stock is None:
            raise ApiError("ERR_SKU_NOT_STOCKED", 422)
        list_unit = stock["list_unit_price_cents"]
        list_subtotal += list_unit * line["qty_units"]
        line_plan.append({"line": line, "list_unit_price_cents": list_unit})

    # --- step 1b: the tier that prices this order (variant per tier_review_mode) ---
    tier = tier_svc.pricing_tier(account, list_subtotal)
    discount = tier["discount_pct"]

    quote = db.get("job_quotes", order["job_quote_id"]) if order.get("job_quote_id") else None
    pricing_instant = clock.get_now()
    quote_term_open = False
    if quote is not None:
        term_start = quote.get("_term_start")
        term_end = quote.get("_term_end")
        quote_term_open = (
            term_start is not None and term_end is not None
            and term_start <= pricing_instant <= term_end
        )

    subtotal = 0
    for plan in line_plan:
        line = plan["line"]
        quote_line = _quote_line_for(quote, line["sku"]) if quote is not None else None
        binds = (
            quote_line is not None
            and quote_line.get("negotiated_unit_price_cents") is not None
            and quote_term_open
        )
        if binds:
            plan["price_source"] = "QUOTED"
            plan["effective_unit_price_cents"] = quote_line["negotiated_unit_price_cents"]
        else:
            plan["price_source"] = "TIER_DISCOUNTED"
            # Rounding is pinned at the UNIT price, then multiplied by qty.
            plan["effective_unit_price_cents"] = round_half_up(
                Decimal(plan["list_unit_price_cents"]) * (Decimal(1) - discount)
            )
        plan["line_subtotal_cents"] = plan["effective_unit_price_cents"] * line["qty_units"]
        subtotal += plan["line_subtotal_cents"]

    discount_cents = list_subtotal - subtotal

    # --- freight: waiver keyed on subtotal_cents only, inclusive threshold ---
    base_freight = FREIGHT_BASE_SURCHARGE_CENTS if order["delivery_mode"] == "DELIVERY" else 0
    if base_freight > 0 and subtotal >= FREIGHT_WAIVER_SUBTOTAL_CENTS:
        freight = 0
    else:
        freight = base_freight

    # --- lift gate: never waived ---
    lift_gate = (
        LIFT_GATE_FEE_CENTS
        if (order["delivery_mode"] == "DELIVERY" and order.get("lift_gate_required"))
        else 0
    )

    exempt_states = tier_svc.tax_exempt_state_codes(account)
    tax_exempt_applied = bool(order.get("resale_purchase")) and store["state_code"] in exempt_states
    tax_base = subtotal + freight + lift_gate
    if tax_exempt_applied:
        tax = 0
    else:
        tax = round_half_up(Decimal(tax_base) * Decimal(str(store["tax_rate_pct"])))

    total = subtotal + freight + lift_gate + tax

    result = {
        "tier_code_applied": tier["tier_code"],
        "list_subtotal_cents": list_subtotal,
        "subtotal_cents": subtotal,
        "discount_cents": discount_cents,
        "freight_surcharge_cents": freight,
        "lift_gate_fee_cents": lift_gate,
        "tax_exempt_applied": tax_exempt_applied,
        "tax_cents": tax,
        "total_cents": total,
    }

    if persist:
        for plan in line_plan:
            line = plan["line"]
            line["list_unit_price_cents"] = plan["list_unit_price_cents"]
            line["price_source"] = plan["price_source"]
            line["effective_unit_price_cents"] = plan["effective_unit_price_cents"]
            line["line_subtotal_cents"] = plan["line_subtotal_cents"]
            db.touch(line)
        order.update(result)
    return result
