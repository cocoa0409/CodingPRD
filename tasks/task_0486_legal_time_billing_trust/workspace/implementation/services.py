"""Business logic: calculations, state recomputation, cascades (PRD §3 / §1.3)."""

import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from common import touch
from clock import clock, parse_iso8601

COLLECTIONS_GRACE_DAYS = 15


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------

def round_half_up(value):
    """Round a Decimal/number half-up to the nearest integer (larger magnitude
    on an exact .5 tie). Returns int."""
    d = Decimal(value)
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# §1.3 billable_rate_resolution
# ---------------------------------------------------------------------------

def resolve_rate(matter, client, timekeeper):
    """Rate ladder: matter_rate > client_override(role_kind) > standard_rate.

    Stop at the first non-null tier.
    """
    if matter.get("matter_rate_cents") is not None:
        return matter["matter_rate_cents"]
    override = find_rate_override(client["id"], timekeeper["role_kind"])
    if override is not None:
        return override["rate_cents"]
    return timekeeper["standard_rate_cents"]


def find_rate_override(client_id, role_kind):
    for ov in db.rate_overrides.values():
        if ov["client_id"] == client_id and ov["role_kind"] == role_kind:
            return ov
    return None


# ---------------------------------------------------------------------------
# §1.3 time_entry_amount
# ---------------------------------------------------------------------------

def time_entry_amount(resolved_rate_cents, minutes):
    """6-minute increments, rounded UP for tenths; then per-entry cents rounded
    half-up. billable_tenths = ceil(minutes/6); amount = round_half_up(rate * tenths / 10).
    """
    billable_tenths = math.ceil(minutes / 6)
    amount = round_half_up(Decimal(resolved_rate_cents) * Decimal(billable_tenths) / Decimal(10))
    return amount


# ---------------------------------------------------------------------------
# WIP recomputation (provisional) — §3.4
# ---------------------------------------------------------------------------

def matter_wip(matter_id):
    """Recompute live WIP totals + counts over CAPTURED entries for a matter."""
    fees = 0
    expenses = 0
    te_count = 0
    ee_count = 0
    for te in db.time_entries.values():
        if te["matter_id"] == matter_id and te["status"] == "CAPTURED":
            fees += te["billable_amount_cents"]
            te_count += 1
    for ee in db.expense_entries.values():
        if ee["matter_id"] == matter_id and ee["status"] == "CAPTURED":
            expenses += ee["amount_cents"]
            ee_count += 1
    return fees, expenses, te_count, ee_count


def sync_matter_wip(matter):
    """Recompute and persist a matter's wip_fees_cents / wip_expenses_cents."""
    fees, expenses, _, _ = matter_wip(matter["id"])
    matter["wip_fees_cents"] = fees
    matter["wip_expenses_cents"] = expenses


# ---------------------------------------------------------------------------
# §1.3 collection_aging
# ---------------------------------------------------------------------------

def due_date_of(invoice):
    issue = parse_iso8601(invoice["issue_date"])
    return issue + timedelta(days=invoice["net_terms_days"])


def recompute_collection_status(invoice):
    """Aging per §3.7 / §1.3, against the logical clock. IN_COLLECTIONS is
    sticky (only entered/left by explicit action) and never set here.
    """
    billing = invoice["billing_status"]
    if billing in ("PAID", "WRITTEN_OFF", "VOID"):
        invoice["collection_status"] = "SETTLED"
        return
    # ISSUED / PARTIALLY_PAID — but only meaningful after issue. DRAFT invoices
    # keep CURRENT.
    if billing == "DRAFT":
        return
    # IN_COLLECTIONS is a terminal manual state; do not auto-revert it.
    if invoice["collection_status"] == "IN_COLLECTIONS":
        return

    current = clock.now()
    issue = parse_iso8601(invoice["issue_date"])
    due = due_date_of(invoice)
    grace_end = due + timedelta(days=COLLECTIONS_GRACE_DAYS)

    if current <= due:
        invoice["collection_status"] = "DUE" if current >= issue else "CURRENT"
    elif current <= grace_end:
        invoice["collection_status"] = "OVERDUE"
    else:
        invoice["collection_status"] = "OVERDUE"


def reage_all_invoices():
    """Recompute collection_status for every ISSUED/PARTIALLY_PAID invoice."""
    for inv in db.invoices.values():
        if inv["billing_status"] in ("ISSUED", "PARTIALLY_PAID"):
            recompute_collection_status(inv)


# ---------------------------------------------------------------------------
# §1.3 ar_realization — A/R + realization
# ---------------------------------------------------------------------------

def recompute_client_ar(client):
    """ar_balance_cents = sum(total - paid - written_off) over ISSUED/PARTIALLY_PAID."""
    bal = 0
    for inv in db.invoices.values():
        if inv["client_id"] == client["id"] and inv["billing_status"] in ("ISSUED", "PARTIALLY_PAID"):
            bal += inv["total_cents"] - inv["amount_paid_cents"] - inv["written_off_cents"]
    client["ar_balance_cents"] = bal


def ar_summary(client_id):
    ar_balance = 0
    billed_final = 0
    collected_final = 0
    for inv in db.invoices.values():
        if inv["client_id"] != client_id:
            continue
        if inv["billing_status"] in ("ISSUED", "PARTIALLY_PAID"):
            ar_balance += inv["total_cents"] - inv["amount_paid_cents"] - inv["written_off_cents"]
        if inv["billing_status"] in ("PAID", "WRITTEN_OFF"):
            billed_final += inv["total_cents"] + inv["written_off_cents"]
            collected_final += inv["amount_paid_cents"]
    if billed_final == 0:
        realization_pct = 0.0
    else:
        pct_x100 = round_half_up(Decimal(collected_final) * Decimal(10000) / Decimal(billed_final))
        realization_pct = pct_x100 / 100.0
    return {
        "ar_balance_cents": ar_balance,
        "realization_pct": realization_pct,
        "billed_final_cents": billed_final,
        "collected_final_cents": collected_final,
    }


# ---------------------------------------------------------------------------
# §1.3 three_way_reconcile
# ---------------------------------------------------------------------------

def reconciliation(account_id):
    account = db.trust_accounts[account_id]
    leg_book = account["book_balance_cents"]
    leg_bank = account["bank_balance_cents"]
    leg_client = 0
    for ledger in db.client_trust_ledgers.values():
        if ledger["trust_account_id"] == account_id:
            leg_client += ledger["balance_cents"]
    reconciled = (leg_book == leg_client == leg_bank)
    unconfirmed = leg_book - leg_bank
    return {
        "leg_book_cents": leg_book,
        "leg_client_cents": leg_client,
        "leg_bank_cents": leg_bank,
        "reconciled": reconciled,
        "unconfirmed_cents": unconfirmed,
    }


# ---------------------------------------------------------------------------
# Conflict gating helper — §3.2 / §1.4
# ---------------------------------------------------------------------------

def latest_conflict_check(matter_id):
    checks = [c for c in db.conflict_checks.values() if c["matter_id"] == matter_id]
    if not checks:
        return None
    checks.sort(key=lambda c: c["_seq"])
    return checks[-1]


# ---------------------------------------------------------------------------
# Billing-dimension advancement shared by payment + sweep — §3.6
# ---------------------------------------------------------------------------

def advance_billing_after_payment(invoice):
    """After amount_paid_cents changes upward, advance billing_status.

    owed = total_cents - written_off_cents.
    paid == owed -> PAID (+ collection SETTLED). 0 < paid < owed -> PARTIALLY_PAID.
    """
    owed = invoice["total_cents"] - invoice["written_off_cents"]
    paid = invoice["amount_paid_cents"]
    if paid >= owed:
        invoice["billing_status"] = "PAID"
        invoice["collection_status"] = "SETTLED"
    elif paid > 0:
        invoice["billing_status"] = "PARTIALLY_PAID"
    # paid == 0 -> stays ISSUED


def recompute_billing_after_unpay(invoice):
    """After amount_paid_cents decreases (payment reversal), recompute billing
    dimension downward and re-age collection from the clock.
    """
    owed = invoice["total_cents"] - invoice["written_off_cents"]
    paid = invoice["amount_paid_cents"]
    if paid >= owed and owed > 0:
        invoice["billing_status"] = "PAID"
    elif paid > 0:
        invoice["billing_status"] = "PARTIALLY_PAID"
    else:
        invoice["billing_status"] = "ISSUED"
    # Un-settle: re-age the collection dimension from the logical clock.
    recompute_collection_status(invoice)
