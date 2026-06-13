"""Ledger & account-state services: arrears aging, oldest-unpaid tracking,
payment waterfall, bill-status recompute, grant lifecycle, and the
disconnect-cancel cascade (PRD §2.8, §3.5, §3.6, §3.8, §3.9).

These helpers mutate db records in place. The account.version is bumped via
db.touch wherever the PRD says version increments; callers are responsible for
the top-level account.version bump on their own write where applicable.
"""
from db import db, touch, now_iso
from services.common import parse_dt

ARREARS_DAYS = 45


# ---------------------------------------------------------------------------
# Oldest-unpaid-bill tracking
# ---------------------------------------------------------------------------
def unpaid_bills_for(account_id):
    """Account bills in ISSUED or PARTIALLY_PAID status (PAID/VOID excluded)."""
    return [
        b for b in db.bills.values()
        if b["account_id"] == account_id
        and b["status"] in ("ISSUED", "PARTIALLY_PAID")
    ]


def recompute_oldest_unpaid(account):
    """Set account.oldest_unpaid_bill_due_date to the earliest due_date among
    unpaid bills, ties broken by created_at ASC (never by id) (PRD §2.8).
    """
    unpaid = unpaid_bills_for(account["id"])
    if not unpaid:
        account["oldest_unpaid_bill_due_date"] = None
        return
    # Order by (due_date, created_at); the winner's due_date is recorded.
    unpaid.sort(key=lambda b: (b["due_date"], b["created_at"], b["_seq"]))
    account["oldest_unpaid_bill_due_date"] = unpaid[0]["due_date"]


# ---------------------------------------------------------------------------
# Arrears aging (PRD §2.8). Returns True if financial_status changed.
# ---------------------------------------------------------------------------
def _days_past_due(current_utc_str, due_date_str):
    current = parse_dt(current_utc_str)
    due = parse_dt(due_date_str)
    if current is None or due is None:
        return None
    delta = current - due
    # floor of the difference in whole days (may be negative).
    total_seconds = delta.total_seconds()
    return int(total_seconds // 86400)


def compute_financial_status(account):
    """Compute the target financial_status from arrears age (PRD §2.8).

    Reads SystemClock.current_utc. When the clock is unset or there is no
    oldest unpaid bill, the account is CURRENT.
    """
    recompute_oldest_unpaid(account)
    oldest = account["oldest_unpaid_bill_due_date"]
    if oldest is None:
        return "CURRENT"
    current_utc = db.clock["current_utc"]
    if current_utc is None:
        # No clock set yet: nothing is past due.
        return "CURRENT"
    days = _days_past_due(current_utc, oldest)
    if days is None:
        return "CURRENT"
    if days >= ARREARS_DAYS:
        return "IN_ARREARS"
    if days > 0:
        return "DELINQUENT"
    return "CURRENT"


def reage_account(account):
    """Recompute and apply financial_status. Returns True if it changed.

    Does NOT bump version itself — the caller decides whether a version bump is
    warranted for the change (PRD §2.8 clock advance bumps version on change).
    """
    new_status = compute_financial_status(account)
    if new_status != account["financial_status"]:
        account["financial_status"] = new_status
        return True
    return False


# ---------------------------------------------------------------------------
# Bill-status recompute from amount_paid_cents (PRD §3.5)
# ---------------------------------------------------------------------------
def recompute_bill_status(bill):
    """Recompute a non-terminal bill's status from amount_paid_cents.

    Only applies to bills currently in ISSUED/PARTIALLY_PAID/PAID (not DRAFT,
    not VOID). PAID when amount_paid >= total_due; PARTIALLY_PAID when 0 <
    amount_paid < total_due; ISSUED when amount_paid == 0.
    """
    if bill["status"] in ("DRAFT", "VOID"):
        return
    paid = bill["amount_paid_cents"]
    due = bill["total_due_cents"]
    if paid >= due:
        bill["status"] = "PAID"
    elif paid > 0:
        bill["status"] = "PARTIALLY_PAID"
    else:
        bill["status"] = "ISSUED"


# ---------------------------------------------------------------------------
# Payment waterfall (PRD §3.5, scaffold payment_waterfall)
# ---------------------------------------------------------------------------
def apply_payment_waterfall(account, amount_cents):
    """Allocate amount_cents across unpaid bills oldest-due-first.

    Returns the ordered allocations list [{bill_id, applied_cents}].
    Mutates each touched bill's amount_paid_cents and status. Reduces the
    account balance by the FULL payment amount (overpayment -> credit).
    """
    unpaid = unpaid_bills_for(account["id"])
    unpaid.sort(key=lambda b: (b["due_date"], b["created_at"], b["_seq"]))
    remaining = amount_cents
    allocations = []
    for b in unpaid:
        owed = b["total_due_cents"] - b["amount_paid_cents"]
        applied = min(remaining, owed)
        if applied > 0:
            allocations.append({"bill_id": b["id"], "applied_cents": applied})
            b["amount_paid_cents"] += applied
            recompute_bill_status(b)
            touch(b)
            remaining -= applied
        if remaining == 0:
            break
    # Full payment reduces balance (overpayment drives it negative -> credit).
    account["balance_cents"] -= amount_cents
    return allocations


def recompute_amount_paid_from_postings(bill):
    """Recompute a bill's amount_paid_cents from all POSTED payment allocations
    touching it (used on reversal, PRD §3.5)."""
    total = 0
    for p in db.payments.values():
        if p["status"] != "POSTED":
            continue
        for alloc in p.get("allocations", []):
            if alloc["bill_id"] == bill["id"]:
                total += alloc["applied_cents"]
    bill["amount_paid_cents"] = total
    recompute_bill_status(bill)


# ---------------------------------------------------------------------------
# Disconnect-cancel cascade triggered by a clearing payment (PRD §3.5, §3.6)
# ---------------------------------------------------------------------------
def cancel_scheduled_disconnect(account):
    """If the account is DISCONNECT_PENDING, cancel its SCHEDULED DISCONNECT
    service order and revert service_status to ACTIVE. Returns True if it acted.
    """
    if account["service_status"] != "DISCONNECT_PENDING":
        return False
    acted = False
    for so in db.service_orders.values():
        if (
            so["account_id"] == account["id"]
            and so["order_type"] == "DISCONNECT"
            and so["status"] == "SCHEDULED"
        ):
            so["status"] = "CANCELLED"
            touch(so)
            acted = True
    account["service_status"] = "ACTIVE"
    return acted


# ---------------------------------------------------------------------------
# AssistanceGrant lifecycle on consumption / refund (PRD §3.8)
# ---------------------------------------------------------------------------
def consume_grant(grant, amount_cents):
    """Debit a grant by amount_cents and advance its lifecycle.

    PLEDGED -> APPLIED  when 0 < remaining < pledged
    PLEDGED -> EXHAUSTED when remaining reaches 0 in one step
    APPLIED -> EXHAUSTED when remaining reaches 0
    """
    if amount_cents <= 0:
        return
    grant["remaining_cents"] -= amount_cents
    if grant["remaining_cents"] < 0:
        grant["remaining_cents"] = 0
    if grant["remaining_cents"] == 0:
        grant["status"] = "EXHAUSTED"
    else:
        # remaining is between 0 and pledged -> APPLIED
        grant["status"] = "APPLIED"
    touch(grant)


def refund_grant(grant, amount_cents):
    """Refund amount_cents back into a grant on bill void (PRD §3.8).

    EXHAUSTED -> APPLIED (or PLEDGED when remaining restored to pledged).
    """
    if amount_cents <= 0:
        return
    grant["remaining_cents"] += amount_cents
    if grant["remaining_cents"] >= grant["pledged_cents"]:
        grant["remaining_cents"] = grant["pledged_cents"]
        grant["status"] = "PLEDGED"
    else:
        grant["status"] = "APPLIED"
    touch(grant)
