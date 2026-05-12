"""Existence-check helpers (PRD §2.7 / §2.8 priority 3).

Each `find_*` helper raises ERR_NOT_FOUND when missing. Path-parameter
validation is left-to-right per PRD §2.7.
"""

from __future__ import annotations

from db import db
from errors import err


def find_budget_account(rid: str) -> dict:
    row = db.budget_accounts.get(rid)
    if row is None:
        raise err("ERR_NOT_FOUND", f"BudgetAccount {rid} not found.")
    return row


def find_supplier(rid: str) -> dict:
    row = db.suppliers.get(rid)
    if row is None:
        raise err("ERR_NOT_FOUND", f"Supplier {rid} not found.")
    return row


def find_requirement(rid: str) -> dict:
    row = db.requirements.get(rid)
    if row is None:
        raise err("ERR_NOT_FOUND", f"Requirement {rid} not found.")
    return row


def find_quote(rid: str) -> dict:
    row = db.quotes.get(rid)
    if row is None:
        raise err("ERR_NOT_FOUND", f"Quote {rid} not found.")
    return row


def find_purchase_order(rid: str) -> dict:
    row = db.purchase_orders.get(rid)
    if row is None:
        raise err("ERR_NOT_FOUND", f"PurchaseOrder {rid} not found.")
    return row


def find_approval_step(rid: str) -> dict:
    row = db.approval_steps.get(rid)
    if row is None:
        raise err("ERR_NOT_FOUND", f"ApprovalStep {rid} not found.")
    return row


def find_contract(rid: str) -> dict:
    row = db.contracts.get(rid)
    if row is None:
        raise err("ERR_NOT_FOUND", f"Contract {rid} not found.")
    return row


def find_clause_template(rid: str) -> dict:
    row = db.clause_templates.get(rid)
    if row is None:
        raise err("ERR_NOT_FOUND", f"ClauseTemplate {rid} not found.")
    return row


def find_receipt(rid: str) -> dict:
    row = db.receipts.get(rid)
    if row is None:
        raise err("ERR_NOT_FOUND", f"Receipt {rid} not found.")
    return row


def find_payment(rid: str) -> dict:
    row = db.payments.get(rid)
    if row is None:
        raise err("ERR_NOT_FOUND", f"Payment {rid} not found.")
    return row


def find_payment_schedule(rid: str) -> dict:
    row = db.payment_schedules.get(rid)
    if row is None:
        raise err("ERR_NOT_FOUND", f"PaymentSchedule {rid} not found.")
    return row


def find_invoice(rid: str) -> dict:
    row = db.invoices.get(rid)
    if row is None:
        raise err("ERR_NOT_FOUND", f"Invoice {rid} not found.")
    return row
