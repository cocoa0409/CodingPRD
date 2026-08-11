"""The money axis: authorization estimate, capture arithmetic and refunds."""

from decimal import Decimal

from core.constants import (CREDIT_MAX_OFFSET_PCT, PAYMENT_AUTH_BUFFER_PCT,
                            PAYMENT_VARIANCE_TOLERANCE_FLOOR_CENTS,
                            PAYMENT_VARIANCE_TOLERANCE_PCT)
from core.money import floor_pct, round_half_up
from core.store import DB, touch
from services import recompute

AUTHORIZE_FULFILMENT_STATES = ("LOCKED", "FILLED", "SHORT_FILLED")
AUTHORIZE_CYCLE_STATES = ("LOCKED", "SUBMITTED", "RECEIVED", "CONSOLIDATED", "DELIVERED")
CAPTURE_FULFILMENT_STATES = ("FILLED", "SHORT_FILLED", "DELIVERED")
CAPTURE_CYCLE_STATES = ("CONSOLIDATED", "DELIVERED")


def authorization_estimate(order):
    """payment_authorization_estimate: confirmed_units drive the figure and
    freight plus the reefer surcharge are deliberately excluded."""
    _, estimated_total = recompute.estimated_total(order)
    authorized = round_half_up(Decimal(estimated_total)
                               * (Decimal("1") + Decimal(PAYMENT_AUTH_BUFFER_PCT)))
    return estimated_total, authorized


def create_payment(order, kind, method, amount_cents, status):
    return DB.insert("Payment", {
        "member_order_id": order["id"],
        "kind": kind,
        "method": method,
        "amount_cents": amount_cents,
        "status": status,
    })


def capture_figures(order):
    """member_order_totals STEPS 1-5, computed without mutating anything so the
    fiscal rungs can refuse before a single field is written."""
    gross = 0
    split_fee = 0
    for line in recompute.lines_of_order(order):
        if line["status"] in recompute.MONEY_LINE_STATES:
            gross += line["allocated_units"] * line["unit_price_cents"]
            split_fee += line["allocated_units"] * line["split_fee_per_unit_cents"]
    discount = round_half_up(Decimal(gross) * recompute.discount_pct(order))
    pre_credit = (gross - discount + order["freight_alloc_cents"]
                  + order["reefer_alloc_cents"])
    cap = floor_pct(pre_credit, CREDIT_MAX_OFFSET_PCT)
    return {"gross_cents": gross, "split_fee_cents": split_fee,
            "tier_discount_cents": discount, "pre_credit_total_cents": pre_credit,
            "credit_cap": cap}


def variance_band(authorized_amount_cents):
    return max(PAYMENT_VARIANCE_TOLERANCE_FLOOR_CENTS,
               round_half_up(Decimal(authorized_amount_cents)
                             * Decimal(PAYMENT_VARIANCE_TOLERANCE_PCT)))


def commit_capture(order, figures, credit_applied):
    order["gross_cents"] = figures["gross_cents"]
    order["split_fee_cents"] = figures["split_fee_cents"]
    order["tier_discount_cents"] = figures["tier_discount_cents"]
    order["pre_credit_total_cents"] = figures["pre_credit_total_cents"]
    order["credit_applied_cents"] = credit_applied
    order["actual_total_cents"] = figures["pre_credit_total_cents"] - credit_applied
    if credit_applied > 0:
        create_payment(order, "CAPTURE", "STORE_CREDIT", credit_applied, "SUCCEEDED")
    if order["actual_total_cents"] > 0:
        create_payment(order, "CAPTURE", "CARD", order["actual_total_cents"], "SUCCEEDED")
    order["captured_cents"] = credit_applied + order["actual_total_cents"]
    order["payment_status"] = "CAPTURED"
    touch(order)
    return order
