"""FeeInvoice routes, including CASCADE-C (PRD 3.9)."""

from datetime import timedelta

from flask import Blueprint, g

from core import (
    ApiError, READ_ROLES, ROLE_BILLING_OFFICER, arg, body_json, clock, db,
    lookup, new_row, ok, paged, qfilter, require_roles, serialize, touch,
    v_dt, v_int, v_str, whole_days,
)
from calc import PAYMENT_TERM_DAYS, compute_fee_invoice, half_open_collides
from entities import guard_not_written_off, recompute_block_membership

bp = Blueprint("billing", __name__)


@bp.post("/sma/fee-invoices")
@require_roles(ROLE_BILLING_OFFICER)
def create_invoice():
    body = body_json()

    account = None
    if isinstance(body.get("account_id"), str):
        account = lookup(db.accounts, body["account_id"], "ERR_ACCOUNT_NOT_FOUND")

    v_str(body, "account_id")
    period_start = v_dt(body, "period_start")
    period_end = v_dt(body, "period_end")
    if period_end <= period_start:
        raise ApiError("ERR_INVALID_REQUEST",
                       "'period_end' must be strictly later than 'period_start'.")
    average_daily_value_cents = v_int(body, "average_daily_value_cents", minimum=0)

    guard_not_written_off(account)

    for existing in db.fee_invoices.values():
        if existing["account_id"] != account["id"]:
            continue
        if existing["status"] == "VOIDED":
            continue
        if half_open_collides(period_start, period_end,
                              existing["period_start"], existing["period_end"]):
            raise ApiError("ERR_BILLING_PERIOD_OVERLAP",
                           "The billing period collides with an existing invoice.")

    model = db.models.get(account["model_id"])
    sponsor = db.sponsors.get(account["sponsor_id"])
    billing_days = whole_days(period_start, period_end)
    figures = compute_fee_invoice(model, sponsor, billing_days, average_daily_value_cents)

    row = new_row(
        account_id=account["id"],
        period_start=period_start,
        period_end=period_end,
        billing_days=billing_days,
        average_daily_value_cents=average_daily_value_cents,
        tier1_fee_cents=figures["tier1_fee_cents"],
        tier2_fee_cents=figures["tier2_fee_cents"],
        tier3_fee_cents=figures["tier3_fee_cents"],
        gross_fee_cents=figures["gross_fee_cents"],
        sponsor_share_cents=figures["sponsor_share_cents"],
        platform_share_cents=figures["platform_share_cents"],
        manager_share_cents=figures["manager_share_cents"],
        status="DRAFT",
        issued_at=None,
        paid_at=None,
        voided_at=None,
        void_reason=None,
    )
    db.fee_invoices[row["id"]] = row
    return ok(serialize(row), 201)


@bp.get("/sma/fee-invoices/<fee_invoice_id>")
@require_roles(*READ_ROLES)
def get_invoice(fee_invoice_id):
    row = lookup(db.fee_invoices, fee_invoice_id, "ERR_INVOICE_NOT_FOUND")
    return ok(serialize(row))


@bp.get("/sma/fee-invoices")
@require_roles(*READ_ROLES)
def list_invoices():
    rows = qfilter(db.fee_invoices.values(),
                   account_id=arg("account_id"),
                   status=arg("status"))
    return paged(rows)


@bp.post("/sma/fee-invoices/<fee_invoice_id>/issue")
@require_roles(ROLE_BILLING_OFFICER)
def issue_invoice(fee_invoice_id):
    invoice = lookup(db.fee_invoices, fee_invoice_id, "ERR_INVOICE_NOT_FOUND")
    account = db.accounts.get(invoice["account_id"])
    if invoice["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT invoice may be issued.")
    if account is not None and account["billing_status"] != "CURRENT":
        raise ApiError("ERR_INVALID_STATE",
                       "The account's billing status must be CURRENT to issue an invoice.")
    invoice["status"] = "ISSUED"
    invoice["issued_at"] = clock()
    touch(invoice)
    if account is not None:
        account["fees_billed_ytd_cents"] += invoice["gross_fee_cents"]
        account["billing_status"] = "INVOICED"
        touch(account)
    return ok(serialize(invoice))


@bp.post("/sma/fee-invoices/<fee_invoice_id>/pay")
@require_roles(ROLE_BILLING_OFFICER)
def pay_invoice(fee_invoice_id):
    invoice = lookup(db.fee_invoices, fee_invoice_id, "ERR_INVOICE_NOT_FOUND")
    account = db.accounts.get(invoice["account_id"])
    if invoice["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", "Only an ISSUED invoice may be paid.")
    if account is not None and account["cash_cents"] < invoice["gross_fee_cents"]:
        raise ApiError("ERR_INSUFFICIENT_CASH",
                       "The account's cash does not cover the invoice.")
    invoice["status"] = "PAID"
    invoice["paid_at"] = clock()
    touch(invoice)
    if account is not None:
        account["cash_cents"] -= invoice["gross_fee_cents"]
        account["billing_status"] = "CURRENT"
        touch(account)
    return ok(serialize(invoice))


@bp.post("/sma/fee-invoices/<fee_invoice_id>/void")
@require_roles(ROLE_BILLING_OFFICER)
def void_invoice(fee_invoice_id):
    invoice = lookup(db.fee_invoices, fee_invoice_id, "ERR_INVOICE_NOT_FOUND")
    body = body_json()
    void_reason = v_str(body, "void_reason")
    if invoice["status"] not in ("DRAFT", "ISSUED"):
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT or ISSUED invoice may be voided.")

    account = db.accounts.get(invoice["account_id"])
    was_issued = invoice["status"] == "ISSUED"
    invoice["status"] = "VOIDED"
    invoice["voided_at"] = clock()
    invoice["void_reason"] = void_reason
    touch(invoice)
    if was_issued and account is not None:
        account["fees_billed_ytd_cents"] -= invoice["gross_fee_cents"]
        account["billing_status"] = "CURRENT"
        touch(account)
    return ok(serialize(invoice))


@bp.post("/sma/fee-invoices/<fee_invoice_id>/mark-delinquent")
@require_roles(ROLE_BILLING_OFFICER)
def mark_delinquent(fee_invoice_id):
    invoice = lookup(db.fee_invoices, fee_invoice_id, "ERR_INVOICE_NOT_FOUND")
    account = db.accounts.get(invoice["account_id"])
    if invoice["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", "Only an ISSUED invoice may be marked delinquent.")
    if account is not None and account["billing_status"] != "INVOICED":
        raise ApiError("ERR_INVALID_STATE",
                       "The account's billing status must be INVOICED.")
    if clock() < invoice["period_end"] + timedelta(days=PAYMENT_TERM_DAYS):
        raise ApiError("ERR_PAYMENT_TERM_NOT_ELAPSED",
                       "The 30-day payment term has not elapsed.")
    if account is not None:
        account["billing_status"] = "DELINQUENT"
        touch(account)
    return ok(serialize(invoice))


@bp.post("/sma/fee-invoices/<fee_invoice_id>/write-off")
@require_roles(ROLE_BILLING_OFFICER)
def write_off_invoice(fee_invoice_id):
    invoice = lookup(db.fee_invoices, fee_invoice_id, "ERR_INVOICE_NOT_FOUND")
    account = db.accounts.get(invoice["account_id"])
    if invoice["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", "Only an ISSUED invoice may be written off.")
    if account is not None and account["billing_status"] != "DELINQUENT":
        raise ApiError("ERR_INVALID_STATE",
                       "The account's billing status must be DELINQUENT to write off.")

    # --- CASCADE-C ---------------------------------------------------------
    invoice["status"] = "WRITTEN_OFF"
    touch(invoice)

    if account is None:
        return ok(serialize(invoice))

    account["billing_status"] = "WRITTEN_OFF"
    account["implementation_status"] = "SUSPENDED"
    touch(account)

    affected_blocks = set()
    for order in db.trade_orders.values():
        if order["account_id"] != account["id"]:
            continue
        if order["status"] not in ("PROPOSED", "BLOCKED"):
            continue
        block_id = order.get("block_id")
        order["status"] = "CANCELLED"
        order["block_id"] = None
        touch(order)
        if block_id:
            affected_blocks.add(block_id)
    for block_id in affected_blocks:
        block = db.blocks.get(block_id)
        if block is not None:
            recompute_block_membership(block)

    return ok(serialize(invoice))
