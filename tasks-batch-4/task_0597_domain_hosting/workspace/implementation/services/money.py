"""Invoices, the promotion engine, the ledger, payments and refunds (PRD 2.7 / 3.8)."""

from decimal import Decimal, ROUND_HALF_UP

import config
import db
from errors import ApiError


def round_half_up(value):
    """Round a Decimal (or numeric) half up to a whole integer."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(value):
    return Decimal(str(value))


# --------------------------------------------------------------- line items
def _new_line(invoice, spec):
    line = db.base_record(with_audit=False)
    line.update(
        {
            "invoice_id": invoice["id"],
            "item_type": spec["item_type"],
            "reference_id": spec.get("reference_id"),
            "description": spec.get("description", ""),
            "quantity": spec["quantity"],
            "unit_price_cents": spec["unit_price_cents"],
            "line_subtotal_cents": spec["quantity"] * spec["unit_price_cents"],
            "line_discount_cents": 0,
            "line_tax_cents": 0,
            "line_total_cents": 0,
        }
    )
    db.line_items[line["id"]] = line
    return line


def lines_of(invoice):
    return db.ordered(db.line_items, lambda l: l["invoice_id"] == invoice["id"])


def service_fee_for(subtotal_after_discount):
    if subtotal_after_discount < config.SERVICE_FEE_TIER1_MAX:
        return config.SERVICE_FEE_T0_CENTS
    if subtotal_after_discount < config.SERVICE_FEE_TIER2_MAX:
        return config.SERVICE_FEE_T1_CENTS
    return config.SERVICE_FEE_T2_CENTS


def recompute_invoice(invoice):
    """calculations.invoice_total: tax is rounded PER LINE, then summed."""
    lines = lines_of(invoice)
    subtotal = 0
    discount = 0
    tax = 0
    rate = Decimal(config.TAX_RATE)
    for line in lines:
        line["line_subtotal_cents"] = line["quantity"] * line["unit_price_cents"]
        base = line["line_subtotal_cents"] - line["line_discount_cents"]
        line["line_tax_cents"] = round_half_up(dec(base) * rate)
        line["line_total_cents"] = base + line["line_tax_cents"]
        subtotal += line["line_subtotal_cents"]
        discount += line["line_discount_cents"]
        tax += line["line_tax_cents"]
    invoice["subtotal_cents"] = subtotal
    invoice["discount_cents"] = discount
    invoice["service_fee_cents"] = service_fee_for(subtotal - discount)
    invoice["tax_cents"] = tax
    invoice["total_cents"] = subtotal - discount + invoice["service_fee_cents"] + tax
    return invoice


def create_invoice(account_id, line_specs, billing_period_id=None):
    invoice = db.base_record()
    invoice.update(
        {
            "account_id": account_id,
            "billing_period_id": billing_period_id,
            "status": "ISSUED",
            "applied_promo_code": None,
            "subtotal_cents": 0,
            "discount_cents": 0,
            "service_fee_cents": 0,
            "tax_cents": 0,
            "total_cents": 0,
            "amount_paid_cents": 0,
            "amount_refunded_cents": 0,
        }
    )
    db.invoices[invoice["id"]] = invoice
    for spec in line_specs:
        _new_line(invoice, spec)
    recompute_invoice(invoice)
    return invoice


# ------------------------------------------------------------- promo engine
def apply_promo(invoice, promo):
    """calculations.invoice_promo_and_service_fee. Evaluation order is pinned."""
    lines = lines_of(invoice)
    subtotal = sum(l["quantity"] * l["unit_price_cents"] for l in lines)

    eligible = [l for l in lines if l["item_type"] in promo["applies_to_item_types"]]
    eligible_subtotal = sum(l["quantity"] * l["unit_price_cents"] for l in eligible)
    if not eligible or eligible_subtotal == 0:
        raise ApiError("ERR_PROMO_NOT_APPLICABLE")
    if subtotal < promo["min_subtotal_cents"]:
        raise ApiError("ERR_PROMO_MIN_NOT_MET")

    if promo["discount_type"] == "PERCENT":
        raw_discount = round_half_up(dec(eligible_subtotal) * dec(promo["discount_value"]))
    else:
        raw_discount = min(int(promo["discount_value"]), eligible_subtotal)
    discount = min(raw_discount, promo["max_discount_cents"])

    for line in lines:
        line["line_discount_cents"] = 0
    remaining = discount
    for line in eligible:  # already created_at ASC
        allocated = min(remaining, line["quantity"] * line["unit_price_cents"])
        line["line_discount_cents"] = allocated
        remaining -= allocated

    invoice["applied_promo_code"] = promo["code"]
    recompute_invoice(invoice)
    return invoice


# ------------------------------------------------------------------- ledger
def credit_balance(account):
    return sum(
        e["amount_cents"]
        for e in db.ledger_entries.values()
        if e["account_id"] == account["id"]
        and e["entry_type"] in ("CREDIT_GRANT", "CREDIT_APPLIED")
    )


def net_cash(account):
    return sum(
        e["amount_cents"]
        for e in db.ledger_entries.values()
        if e["account_id"] == account["id"] and e["entry_type"] in ("PAYMENT", "REFUND")
    )


def write_ledger(account, entry_type, amount_cents, reference_type, reference_id=None, reason=None):
    entry = db.base_record(with_audit=False)
    entry.update(
        {
            "account_id": account["id"],
            "entry_type": entry_type,
            "amount_cents": amount_cents,
            "reference_type": reference_type,
            "reference_id": reference_id,
            "reason": reason,
            "balance_after_cents": 0,
        }
    )
    db.ledger_entries[entry["id"]] = entry
    entry["balance_after_cents"] = credit_balance(account)
    account["credit_balance_cents"] = entry["balance_after_cents"]
    account["net_cash_cents"] = net_cash(account)
    return entry


# ------------------------------------------------------------------ payment
def settle_invoice(invoice, account, use_credit):
    """The credit-first waterfall. Raises ERR_PAYMENT_METHOD_REQUIRED when no card is on file."""
    balance = credit_balance(account)
    applied_credit = min(balance, invoice["total_cents"]) if use_credit else 0
    if applied_credit < 0:
        applied_credit = 0
    cash_remainder = invoice["total_cents"] - applied_credit

    if cash_remainder > 0 and not account["payment_method_token"]:
        raise ApiError("ERR_PAYMENT_METHOD_REQUIRED")

    if applied_credit > 0:
        write_ledger(account, "CREDIT_APPLIED", -applied_credit, "INVOICE", invoice["id"])
    if cash_remainder > 0:
        write_ledger(account, "PAYMENT", cash_remainder, "INVOICE", invoice["id"])

    invoice["amount_paid_cents"] = invoice["total_cents"]
    invoice["status"] = "PAID"
    db.touch(invoice)
    return invoice
