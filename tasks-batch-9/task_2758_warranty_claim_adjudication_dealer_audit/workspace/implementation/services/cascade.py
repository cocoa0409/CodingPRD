"""Shared cascades: the ledger, dealer posture, claim edits and parts-return waivers."""

import db
from services import calc


# ---------------------------------------------------------------- claim edits
def append_edit(claim, edit_code, severity, detail, conflicting_claim_id=None):
    return db.new_record(
        db.claim_edits,
        versioned=False,
        claim_id=claim["id"],
        conflicting_claim_id=conflicting_claim_id,
        edit_code=edit_code,
        severity=severity,
        detail=detail,
        resolved_at=None,
    )


def edits_of(claim_id):
    return [e for e in db.ordered(db.claim_edits) if e["claim_id"] == claim_id]


def open_edits(claim_id):
    return [e for e in edits_of(claim_id) if e["resolved_at"] is None]


def open_suspend_edits(claim_id):
    return [e for e in open_edits(claim_id) if e["severity"] == "SUSPEND"]


def resolve_open_edits(claim, only_code=None):
    stamp = db.iso3(db.now())
    for edit in open_edits(claim["id"]):
        if only_code is not None and edit["edit_code"] != only_code:
            continue
        edit["resolved_at"] = stamp


def recount_suspend_edits(claim):
    claim["suspend_edit_count"] = len(open_suspend_edits(claim["id"]))
    return claim["suspend_edit_count"]


# ---------------------------------------------------------------- ledger + posture
def append_ledger(dealer, source_type, source_id, claim_id, amount_cents):
    """Append one signed ledger row, then recompute balance and posture.

    The dealer's own version counter is advanced once per triggering operation by
    the caller, not once per appended row.
    """
    balance = dealer["chargeback_balance_cents"] + amount_cents
    entry = db.new_record(
        db.ledger_entries,
        versioned=False,
        dealer_id=dealer["id"],
        source_type=source_type,
        source_id=source_id,
        claim_id=claim_id,
        amount_cents=amount_cents,
        balance_after_cents=balance,
    )
    dealer["chargeback_balance_cents"] = balance
    recompute_posture(dealer)
    return entry


def recompute_posture(dealer):
    """PRD 2.8: posture is a pure function of the balance, recomputed on append only."""
    previous = dealer["status"]
    updated = calc.posture_for(dealer["chargeback_balance_cents"])
    if updated == previous:
        return previous
    dealer["status"] = updated
    if calc.POSTURE_RANK[updated] > calc.POSTURE_RANK[previous] and calc.POSTURE_RANK[updated] >= 1:
        suspend_submitted_claims(dealer)
    elif updated == "ACTIVE":
        release_posture_held_claims(dealer)
    return updated


def dealer_claims(dealer_id):
    return [c for c in db.ordered(db.claims) if c["dealer_id"] == dealer_id]


def suspend_submitted_claims(dealer):
    """Hop 4 of the posture cascade: every SUBMITTED claim picks up a hold."""
    for claim in dealer_claims(dealer["id"]):
        if claim["status"] != "SUBMITTED":
            continue
        append_edit(
            claim,
            "DEALER_POSTURE_HOLD",
            "SUSPEND",
            "Dealer posture %s holds this claim out of adjudication and payment." % dealer["status"],
        )
        claim["status"] = "SUSPENDED"
        claim["suspend_edit_count"] = claim["suspend_edit_count"] + 1
        db.touch(claim)


def release_posture_held_claims(dealer):
    """Release only claims whose open suspending edits are all posture holds."""
    for claim in dealer_claims(dealer["id"]):
        if claim["status"] != "SUSPENDED":
            continue
        suspending = open_suspend_edits(claim["id"])
        if not suspending:
            continue
        if any(edit["edit_code"] != "DEALER_POSTURE_HOLD" for edit in suspending):
            continue
        stamp = db.iso3(db.now())
        for edit in suspending:
            edit["resolved_at"] = stamp
        claim["suspend_edit_count"] = 0
        claim["status"] = "SUBMITTED"
        db.touch(claim)


# ---------------------------------------------------------------- claim money
def debit_claim(claim, amount_cents):
    claim["debited_amount_cents"] = claim["debited_amount_cents"] + amount_cents
    claim["payment_status"] = "DEBITED"
    db.touch(claim)


def reinstate_claim(claim, amount_cents):
    claim["reinstated_amount_cents"] = claim["reinstated_amount_cents"] + amount_cents
    claim["payment_status"] = "CREDIT_REINSTATED"
    db.touch(claim)


# ---------------------------------------------------------------- parts returns
def returns_of_claim(claim_id):
    return [r for r in db.ordered(db.parts_returns) if r["claim_id"] == claim_id]


def waive_open_returns(claim, dealer):
    """PRD 3.6 / 3.7: a DENIED or VOID claim waives its REQUESTED obligations."""
    waived = 0
    for row in returns_of_claim(claim["id"]):
        if row["status"] != "REQUESTED":
            continue
        row["status"] = "WAIVED"
        db.touch(row)
        waived += 1
    if waived:
        dealer["open_parts_return_count"] = dealer["open_parts_return_count"] - waived
        db.touch(dealer)
    return waived


# ---------------------------------------------------------------- audit hold
def recompute_audit_hold(dealer):
    live = any(
        audit["dealer_id"] == dealer["id"] and audit["status"] in ("IN_FIELD", "FINDINGS_ISSUED", "APPEALED")
        for audit in db.audits.values()
    )
    dealer["audit_hold"] = live
    return live
