"""Invoices and invoice lines."""

import calc
import common
import serialize
from core import ApiError, F, db, endpoint


def _invoice_account(ctx):
    return ctx.path["invoice_id"]["account_id"]


@endpoint("GET", "/water-service/invoices/<invoice_id>",
          ["PlatformAdmin", "BillingClerk", "Dispatcher", "CustomerContact"],
          read=True, path_params=[("invoice_id", "Invoice")],
          scope=common.scope(customer=_invoice_account))
def read_invoice(ctx):
    return serialize.dump(ctx.path["invoice_id"])


@endpoint("GET", "/water-service/invoices",
          ["PlatformAdmin", "BillingClerk", "Dispatcher"], read=True, paginated=True,
          filters=["account_id", "work_order_id", "status", "variant"])
def list_invoices(ctx):
    return db.all("Invoice")


@endpoint("GET", "/water-service/invoices/<invoice_id>/lines",
          ["PlatformAdmin", "BillingClerk", "Dispatcher", "CustomerContact"],
          read=True, paginated=True, path_params=[("invoice_id", "Invoice")],
          scope=common.scope(customer=_invoice_account))
def invoice_lines(ctx):
    rows = common.rows_where("InvoiceLine", invoice_id=ctx.path["invoice_id"]["id"])
    return sorted(rows, key=lambda r: r["sequence_no"])


@endpoint("POST", "/water-service/invoices/<invoice_id>/issue", ["BillingClerk"],
          path_params=[("invoice_id", "Invoice")],
          g5=common.state_gate("invoice_id", "status", ("DRAFT",),
                               "ERR_INVOICE_INVALID_STATE"))
def issue_invoice(ctx):
    invoice = ctx.path["invoice_id"]
    work_order = db.get("WorkOrder", invoice["work_order_id"])
    if work_order is None or work_order["fulfillment_status"] != "COMPLETED":
        raise ApiError("ERR_WORK_ORDER_INVALID_FULFILLMENT_STATE",
                       "The linked work order is not COMPLETED.")
    invoice["status"] = "ISSUED"
    invoice["issued_at"] = db.clock
    ctx.touch(invoice)

    account = db.get("Account", invoice["account_id"])
    if account is not None:
        account["balance_cents"] += invoice["total_cents"]
        account["lifetime_invoiced_cents"] += invoice["total_cents"]
        calc.rederive_credit_hold(account)
        ctx.touch(account)
    if work_order["billing_status"] == "PENDING_INVOICE":
        work_order["billing_status"] = "INVOICED"
        ctx.touch(work_order)
    return serialize.dump(invoice)


@endpoint("POST", "/water-service/invoices/<invoice_id>/payments", ["BillingClerk"],
          path_params=[("invoice_id", "Invoice")],
          g5=common.state_gate("invoice_id", "status", ("ISSUED", "PARTIALLY_PAID"),
                               "ERR_INVOICE_INVALID_STATE"),
          occ=("expected_invoice_version", "ERR_STALE_INVOICE_VERSION",
               lambda c: c.path["invoice_id"]),
          fields=[F("amount_cents", "integer", nonneg=True),
                  F("expected_invoice_version", "integer")])
def record_payment(ctx):
    invoice = ctx.path["invoice_id"]
    amount = ctx.body["amount_cents"]
    if amount == 0:
        raise ApiError("ERR_PAYMENT_AMOUNT_INVALID", "A payment must be positive.")
    outstanding = invoice["total_cents"] - invoice["amount_paid_cents"]
    if amount > outstanding:
        raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE",
                       "The payment exceeds the outstanding amount.")

    invoice["amount_paid_cents"] += amount
    settled = amount == outstanding
    invoice["status"] = "PAID_IN_FULL" if settled else "PARTIALLY_PAID"
    ctx.touch(invoice)

    account = db.get("Account", invoice["account_id"])
    if account is not None:
        account["balance_cents"] -= amount
        account["lifetime_paid_cents"] += amount
        calc.rederive_credit_hold(account)
        ctx.touch(account)
    if settled:
        work_order = db.get("WorkOrder", invoice["work_order_id"])
        if work_order is not None and work_order["billing_status"] == "INVOICED":
            work_order["billing_status"] = "SETTLED"
            ctx.touch(work_order)
    return serialize.dump(invoice)


@endpoint("POST", "/water-service/invoices/<invoice_id>/void", ["BillingClerk"],
          path_params=[("invoice_id", "Invoice")],
          g5=common.state_gate("invoice_id", "status", ("ISSUED", "PARTIALLY_PAID"),
                               "ERR_INVOICE_INVALID_STATE"))
def void_invoice(ctx):
    invoice = ctx.path["invoice_id"]
    account = db.get("Account", invoice["account_id"])
    if account is not None:
        account["balance_cents"] -= invoice["total_cents"] - invoice["amount_paid_cents"]
        account["lifetime_invoiced_cents"] -= invoice["total_cents"]
        account["lifetime_paid_cents"] -= invoice["amount_paid_cents"]
        calc.rederive_credit_hold(account)
        ctx.touch(account)
    invoice["status"] = "VOID"
    ctx.touch(invoice)
    work_order = db.get("WorkOrder", invoice["work_order_id"])
    if work_order is not None and work_order["billing_status"] == "INVOICED":
        work_order["billing_status"] = "WRITTEN_OFF"
        ctx.touch(work_order)
    return serialize.dump(invoice)


# ==========================================================================
# 4.22 Invoice lines
# ==========================================================================

@endpoint("GET", "/water-service/invoice-lines/<invoice_line_id>",
          ["PlatformAdmin", "BillingClerk", "CustomerContact"], read=True,
          path_params=[("invoice_line_id", "InvoiceLine")])
def read_invoice_line(ctx):
    return serialize.dump(ctx.path["invoice_line_id"])


@endpoint("GET", "/water-service/invoice-lines", ["PlatformAdmin", "BillingClerk"],
          read=True, paginated=True,
          filters=["invoice_id", "parts_consumption_entry_id", "line_type"])
def list_invoice_lines(ctx):
    return db.all("InvoiceLine")
