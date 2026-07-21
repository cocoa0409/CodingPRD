"""Budget ledger, program budget position and the lock/unlock cascade.

PRD §3.1 pins the evaluation order of the budget position.
"""
from decimal import Decimal

import db

# entry types whose recompute may fire ACTIVE -> BUDGET_LOCKED
LOCK_TRIGGERS = {"COMMIT", "BUDGET_ADJUSTMENT"}
# entry types whose recompute may fire BUDGET_LOCKED -> ACTIVE
UNLOCK_TRIGGERS = {"RELEASE", "ESCHEAT_REVERSAL", "BUDGET_ADJUSTMENT"}


def committed_cents(program):
    total = 0
    for e in db.entries_of_program(program["id"]):
        if e["entry_type"] == "COMMIT":
            total += e["amount_cents"]
        elif e["entry_type"] in ("RELEASE", "ESCHEAT_REVERSAL"):
            total -= e["amount_cents"]
    return total


def pending_provisional_cents(program, subject_claim_id=None):
    total = 0
    for c in db.claims_of_program(program["id"]):
        if c["id"] == subject_claim_id:
            continue
        if c["adjudication_status"] in db.CLAIM_OPEN_ADJ:
            total += c["provisional_rebate_cents"] or 0
    return total


def paid_cents(program):
    total = 0
    for e in db.entries_of_program(program["id"]):
        if e["entry_type"] != "PAYMENT":
            continue
        claim = db.claims.get(e["claim_id"])
        if claim is not None and claim["payment_status"] in ("PAID", "ESCHEATED"):
            total += e["amount_cents"]
    return total


def escheat_recovered_cents(program):
    return sum(
        e["amount_cents"] for e in db.entries_of_program(program["id"])
        if e["entry_type"] == "ESCHEAT_REVERSAL"
    )


def position(program, subject_claim_id=None):
    """PRD §3.1 - the five pinned steps."""
    committed = committed_cents(program)
    pending = pending_provisional_cents(program, subject_claim_id)
    reserve = db.round_half_up(db.RESERVE_FACTOR * Decimal(pending))
    available = program["budget_total_cents"] - committed - reserve
    budget_total = program["budget_total_cents"]
    if budget_total == 0:
        utilization = Decimal("0.0000")
    else:
        utilization = db.round4(
            Decimal(committed + reserve) / Decimal(budget_total)
        )
    return {
        "committed_cents": committed,
        "pending_provisional_cents": pending,
        "reserve_cents": reserve,
        "available_cents": available,
        "utilization_pct": utilization,
    }


def append_entry(program, entry_type, amount_cents, claim_id=None, memo=None):
    entry = db.base_record(versioned=False)
    entry.update({
        "program_id": program["id"],
        "claim_id": claim_id,
        "entry_type": entry_type,
        "amount_cents": int(amount_cents),
        "memo": memo,
    })
    db.budget_entries[entry["id"]] = entry
    entry["committed_after_cents"] = committed_cents(program)
    return entry


def recompute(program, trigger=None, subject_claim_id=None):
    """Recompute the budget position and apply the lock / unlock transitions."""
    pos = position(program, subject_claim_id)
    util = pos["utilization_pct"]
    if trigger in LOCK_TRIGGERS and program["status"] == "ACTIVE" and util >= db.BUDGET_HARD_PCT:
        _lock(program)
    elif trigger in UNLOCK_TRIGGERS and program["status"] == "BUDGET_LOCKED" and util < db.BUDGET_HARD_PCT:
        program["status"] = "ACTIVE"
        db.touch(program)
    return pos


def _lock(program):
    """ACTIVE -> BUDGET_LOCKED plus hops 2 and 3 (PRD §3.1)."""
    program["status"] = "BUDGET_LOCKED"
    db.touch(program)
    for offer in db.offers_of_program(program["id"]):
        if offer["status"] == "PUBLISHED":
            suspend_offer(offer)


def suspend_offer(offer):
    """PUBLISHED -> SUSPENDED plus its DRAFT-claim void cascade (PRD §3.2)."""
    offer["status"] = "SUSPENDED"
    db.touch(offer)
    for claim in db.claims_of_offer(offer["id"]):
        if claim["adjudication_status"] == "DRAFT":
            claim["adjudication_status"] = "VOIDED"
            db.touch(claim)
