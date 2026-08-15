"""Append-only credit ledger and the dispute-overturn auto-apply sweep
(PRD 2.8, 3.6; calculation credit_balance_reconciliation)."""
import db
from db import store
from util import fmt_ts

REASON_DISPUTE_OVERTURN = "DISPUTE_OVERTURN_CREDIT"
REASON_INVOICE_APPLICATION = "INVOICE_CREDIT_APPLICATION"


def recompute_balance(carrier):
    """Invariant: credit_balance_cents == SUM(credit_ledger.amount_cents)."""
    carrier["credit_balance_cents"] = sum(
        e["amount_cents"] for e in carrier["credit_ledger"]
    )


def append_ledger(carrier, amount_cents, reason, reference_id):
    carrier["credit_ledger"].append(
        {
            "amount_cents": amount_cents,
            "reason": reason,
            "reference_id": reference_id,
            "recorded_at": fmt_ts(db.now()),
        }
    )
    recompute_balance(carrier)


def refresh_standing(carrier):
    """When no PAST_DUE invoices remain, subscriptions recover CURRENT standing."""
    has_past_due = any(
        i["carrier_id"] == carrier["id"] and i["status"] == "PAST_DUE"
        for i in store.invoices.values()
    )
    if has_past_due:
        return
    for sub in store.subscriptions.values():
        if (
            sub["carrier_id"] == carrier["id"]
            and sub["payment_standing"] == "PAST_DUE"
            and sub["status"] in ("SCHEDULED", "ACTIVE", "PAUSED")
        ):
            sub["payment_standing"] = "CURRENT"
            db.bump(sub)


def auto_apply_credit(carrier):
    """Walk unpaid invoices oldest first (issued_at ASC, then creation order);
    while the balance fully covers an invoice's amount_due_cents, append the
    negative ledger entry and mark it PAID. Partial coverage is never applied."""
    unpaid = [
        i
        for i in store.invoices.values()
        if i["carrier_id"] == carrier["id"] and i["status"] in ("ISSUED", "PAST_DUE")
    ]
    unpaid.sort(key=lambda i: (i["issued_at"], i["_seq"]))
    for inv in unpaid:
        if carrier["credit_balance_cents"] >= inv["amount_due_cents"]:
            append_ledger(
                carrier,
                -inv["amount_due_cents"],
                REASON_INVOICE_APPLICATION,
                inv["id"],
            )
            inv["status"] = "PAID"
            db.bump(inv)
        else:
            break
    refresh_standing(carrier)
