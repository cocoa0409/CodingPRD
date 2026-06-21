"""Invoice aging sweep (PRD §3.6).

When the clock is advanced, any invoice that is ISSUED or PARTIALLY_PAID, whose
pinned due_at the clock has now strictly passed, and which still has positive
amount_due_cents, moves to OVERDUE. Then any account that now holds an OVERDUE
invoice (or whose outstanding balance exceeds its credit limit) is cascaded to
CREDIT_HOLD.
"""
from db import store
from helpers import touch
from services.inventory import invoice_amount_due, recompute_account_balance


def run_aging_sweep():
    clock = store.clock()

    # 1) age invoices
    for inv in store.invoices.values():
        if inv["status"] in ("ISSUED", "PARTIALLY_PAID"):
            if clock > inv["due_at"] and invoice_amount_due(inv) > 0:
                inv["status"] = "OVERDUE"
                touch(inv)

    # 2) cascade account credit-hold
    for account in store.accounts.values():
        recompute_account_balance(account, bump=True)
        has_overdue = any(
            i["account_id"] == account["id"] and i["status"] == "OVERDUE"
            for i in store.invoices.values()
        )
        over_limit = account["outstanding_balance_cents"] > account["credit_limit_cents"]
        if (has_overdue or over_limit) and account["status"] != "CREDIT_HOLD":
            account["status"] = "CREDIT_HOLD"
            touch(account)
