"""Ledger posting, account recomputation, past-due evaluation, hold evaluation.

Implements calculations: account_ledger_recompute, past_due_evaluation,
hold_evaluation (PRD section 2.5 / 2.6).
"""
from datetime import date

from db import store, new_id, now_iso, next_seq, base_fields, touch, clock_date

CHARGE_FAMILY = {"CHARGE", "CHARGE_REVERSAL", "LATE_FEE", "PLAN_FEE", "COLLECTIONS_FEE"}
POSITIVE_CHARGE_TYPES = {"CHARGE", "LATE_FEE", "PLAN_FEE", "COLLECTIONS_FEE"}

# Balance signs per PRD section 2.5.
SIGN = {
    "CHARGE": +1, "LATE_FEE": +1, "PLAN_FEE": +1, "COLLECTIONS_FEE": +1,
    "PAYMENT_REVERSAL": +1, "WAIVER_REVERSAL": +1, "SPONSOR_REVERSAL": +1,
    "REFUND_PAYOUT": +1,
    "CHARGE_REVERSAL": -1, "PAYMENT": -1, "WAIVER": -1, "SPONSOR_CHARGE": -1,
    "WRITE_OFF": -1,
}

AUTO_HOLD_REASON = "PAST_DUE_BALANCE"
AUTO_RELEASED_REASON = "AUTO_CURED"


def post_entry(account_id, entry_type, amount_cents, due_date=None,
               charge_kind=None, enrollment_id=None, source_ref="", memo=""):
    e = {
        "id": new_id(),
        "account_id": account_id,
        "entry_type": entry_type,
        "charge_kind": charge_kind,
        "amount_cents": amount_cents,
        "due_date": due_date,
        "enrollment_id": enrollment_id,
        "source_ref": source_ref,
        "memo": memo,
        "created_at": now_iso(),
        "_seq": next_seq(),
    }
    store.ledger_entries[e["id"]] = e
    return e


def account_entries(account_id):
    rows = [e for e in store.ledger_entries.values() if e["account_id"] == account_id]
    rows.sort(key=lambda e: e["_seq"])
    return rows


def find_account(student_id, term_id):
    for a in store.accounts.values():
        if a["student_id"] == student_id and a["term_id"] == term_id:
            return a
    return None


def get_or_create_account(student_id, term_id):
    a = find_account(student_id, term_id)
    if a is not None:
        return a, False
    a = base_fields()
    a.update({
        "student_id": student_id, "term_id": term_id, "status": "OPEN",
        "charges_total_cents": 0, "payments_total_cents": 0,
        "waivers_total_cents": 0, "sponsor_total_cents": 0,
        "writeoffs_total_cents": 0, "balance_cents": 0, "past_due_cents": 0,
        "writeoff_status": "NONE", "writeoff_requester_id": None,
    })
    store.accounts[a["id"]] = a
    return a, True


def open_amount(entry):
    """Open amount of a positive charge-family entry: amount minus allocations
    referencing it from POSTED payments and POSTED waivers."""
    total = entry["amount_cents"]
    for p in store.payments.values():
        if p["account_id"] == entry["account_id"] and p["status"] == "POSTED":
            for a in p["allocations"]:
                if a["ledger_entry_id"] == entry["id"]:
                    total -= a["amount_cents"]
    for w in store.waivers.values():
        if w["account_id"] == entry["account_id"] and w["status"] == "POSTED":
            for a in w["allocations"]:
                if a["ledger_entry_id"] == entry["id"]:
                    total -= a["amount_cents"]
    return total


def waterfall_targets(account_id):
    """Charge-family positive entries with open amount > 0, ordered
    due_date ASC then created_at ASC (creation sequence tie-break)."""
    rows = [e for e in account_entries(account_id)
            if e["entry_type"] in POSITIVE_CHARGE_TYPES and open_amount(e) > 0]
    rows.sort(key=lambda e: (e["due_date"], e["_seq"]))
    return rows


def _bucket_sums(entries):
    charges = payments = waivers = sponsor = writeoffs = payouts = 0
    for e in entries:
        t = e["entry_type"]
        amt = e["amount_cents"]
        if t in ("CHARGE", "LATE_FEE", "PLAN_FEE", "COLLECTIONS_FEE"):
            charges += amt
        elif t == "CHARGE_REVERSAL":
            charges -= amt
        elif t == "PAYMENT":
            payments += amt
        elif t == "PAYMENT_REVERSAL":
            payments -= amt
        elif t == "WAIVER":
            waivers += amt
        elif t == "WAIVER_REVERSAL":
            waivers -= amt
        elif t == "SPONSOR_CHARGE":
            sponsor += amt
        elif t == "SPONSOR_REVERSAL":
            sponsor -= amt
        elif t == "WRITE_OFF":
            writeoffs += amt
        elif t == "REFUND_PAYOUT":
            payouts += amt
    return charges, payments, waivers, sponsor, writeoffs, payouts


def compute_balance(entries):
    """balance_cents = sum(sign * amount_cents over all entries), with the
    fixed sign convention of PRD section 2.5. A REFUND_PAYOUT contributes
    positively, so a payout of |pre-payout balance| lands the account at
    exactly zero."""
    return sum(SIGN[e["entry_type"]] * e["amount_cents"] for e in entries)


def compute_past_due(account):
    """past_due_evaluation per PRD section 2.6 (with plan-default acceleration)."""
    entries = [e for e in account_entries(account["id"])
               if e["entry_type"] in CHARGE_FAMILY]
    today = clock_date()
    accelerated = any(p["account_id"] == account["id"] and p["status"] == "DEFAULTED"
                      for p in store.plans.values())
    total = 0
    for e in entries:
        contrib = -e["amount_cents"] if e["entry_type"] == "CHARGE_REVERSAL" \
            else open_amount(e)
        if accelerated:
            total += contrib
        else:
            dd = date.fromisoformat(e["due_date"]) if e["due_date"] else None
            if dd is not None and dd < today:
                total += contrib
    return max(0, total)


def evaluate_holds(account, term):
    """hold_evaluation: runs immediately after every past_due_evaluation.
    Inclusive >= threshold places AUTO holds of both types; below it releases
    every ACTIVE AUTO hold. MANUAL holds are never auto-released.
    Returns (placed_count, released_count)."""
    if account["status"] in ("WRITTEN_OFF", "CLOSED"):
        return 0, 0
    placed = released = 0
    active = [h for h in store.holds.values()
              if h["account_id"] == account["id"] and h["status"] == "ACTIVE"]
    if account["past_due_cents"] >= term["hold_threshold_cents"]:
        for ht in ("REGISTRATION", "TRANSCRIPT"):
            if not any(h["hold_type"] == ht for h in active):
                h = base_fields()
                h.update({
                    "account_id": account["id"], "hold_type": ht,
                    "origin": "AUTO", "reason": AUTO_HOLD_REASON,
                    "status": "ACTIVE", "released_reason": None,
                })
                store.holds[h["id"]] = h
                placed += 1
    else:
        for h in active:
            if h["origin"] == "AUTO":
                h["status"] = "RELEASED"
                h["released_reason"] = AUTO_RELEASED_REASON
                touch(h)
                released += 1
    return placed, released


def recompute_account(account, force_bump=False):
    """account_ledger_recompute + past_due_evaluation + hold_evaluation.
    Pinned order: bucket sums first, then balance derived from the buckets.
    Returns (holds_placed, holds_released)."""
    entries = account_entries(account["id"])
    charges, payments, waivers, sponsor, writeoffs, payouts = _bucket_sums(entries)
    balance = compute_balance(entries)
    past_due = compute_past_due(account)

    changed = (
        account["charges_total_cents"] != charges or
        account["payments_total_cents"] != payments or
        account["waivers_total_cents"] != waivers or
        account["sponsor_total_cents"] != sponsor or
        account["writeoffs_total_cents"] != writeoffs or
        account["balance_cents"] != balance or
        account["past_due_cents"] != past_due
    )
    account["charges_total_cents"] = charges
    account["payments_total_cents"] = payments
    account["waivers_total_cents"] = waivers
    account["sponsor_total_cents"] = sponsor
    account["writeoffs_total_cents"] = writeoffs
    account["balance_cents"] = balance
    account["past_due_cents"] = past_due

    # System status transitions: OPEN -> PAST_DUE when past_due > 0;
    # PAST_DUE -> OPEN when past_due reaches 0.
    if past_due > 0 and account["status"] == "OPEN":
        account["status"] = "PAST_DUE"
        changed = True
    elif past_due == 0 and account["status"] == "PAST_DUE":
        account["status"] = "OPEN"
        changed = True

    term = store.terms.get(account["term_id"])
    placed = released = 0
    if term is not None:
        placed, released = evaluate_holds(account, term)
        if placed or released:
            changed = True

    if changed or force_bump:
        touch(account)
    return placed, released
