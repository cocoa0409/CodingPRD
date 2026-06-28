"""RewardClaim lifecycle + cascade helpers (PRD §3.5, §3.6, §3.9).

PENDING -> AVAILABLE (maturation)
AVAILABLE -> RESERVED (cash-out reserves)
RESERVED -> PAID (cash-out settles PAID)
RESERVED -> AVAILABLE (cash-out fails / reverts)
AVAILABLE -> EXPIRED (clock reaches expires_at)
PENDING/AVAILABLE/RESERVED -> CLAWED_BACK (return event)
"""
from clock import parse_iso
from db import touch
from services.ledger import emit_ledger
from services.referrals import maybe_qualify_referrals_for
from services.streak import recompute_streak, week_index_of


def mature_claim(store, claim):
    """PENDING -> AVAILABLE. Emits CLAIM_MATURED, recomputes the owning member's
    bonus streak. Caller ensures the claim is PENDING and matures_at reached."""
    claim["status"] = "AVAILABLE"
    # Record the week the claim reached AVAILABLE (current clock) for streak.
    claim["_matured_week_index"] = week_index_of(store.clock.get())
    touch(store, claim)
    emit_ledger(
        store,
        claim["member_id"],
        "CLAIM_MATURED",
        claim["amount_cents"],
        reward_claim_id=claim["id"],
    )
    recompute_streak(store, claim["member_id"])
    # A now-AVAILABLE claim may push the member's cumulative qualifying total
    # over a referral threshold (referee qualification, PRD §3.7).
    maybe_qualify_referrals_for(store, claim["member_id"])


def expire_claim(store, claim):
    """AVAILABLE -> EXPIRED. Emits CLAIM_EXPIRED (-amount)."""
    claim["status"] = "EXPIRED"
    touch(store, claim)
    emit_ledger(
        store,
        claim["member_id"],
        "CLAIM_EXPIRED",
        -claim["amount_cents"],
        reward_claim_id=claim["id"],
    )


def reserve_available_claims(store, member_id, cashout_id, target_cents):
    """Reserve a member's AVAILABLE claims, oldest created_at first, until the
    reserved set sums to at least target_cents.

    Returns the list of reserved claims on success, or None if no set of available
    claims can sum to target_cents (caller raises ERR_CASHOUT_NOT_RESERVABLE).
    Does NOT mutate anything until it has confirmed the set is reservable
    (atomicity).
    """
    available = [
        c for c in store.reward_claims.values()
        if c["member_id"] == member_id and c["status"] == "AVAILABLE"
    ]
    available.sort(key=lambda c: (c["created_at"], c["_seq"]))

    chosen = []
    total = 0
    for c in available:
        if total >= target_cents:
            break
        chosen.append(c)
        total += c["amount_cents"]

    if total < target_cents:
        return None  # not reservable

    for c in chosen:
        c["status"] = "RESERVED"
        c["cashout_id"] = cashout_id
        touch(store, c)
    return chosen


def settle_claims_paid(store, cashout):
    """All claims with cashout_id == cashout.id : RESERVED -> PAID."""
    for c in store.reward_claims.values():
        if c.get("cashout_id") == cashout["id"] and c["status"] == "RESERVED":
            c["status"] = "PAID"
            touch(store, c)


def revert_claims_available(store, cashout):
    """All claims with cashout_id == cashout.id : RESERVED -> AVAILABLE, clear
    cashout_id."""
    for c in store.reward_claims.values():
        if c.get("cashout_id") == cashout["id"] and c["status"] == "RESERVED":
            c["status"] = "AVAILABLE"
            c["cashout_id"] = None
            touch(store, c)


def clawback_claim(store, claim, clawback_cents):
    """Move a claim to CLAWED_BACK and emit CLAIM_CLAWBACK (-clawback_cents).

    If the claim was RESERVED, cascade: owning cash-out -> FAILED, sibling reserved
    claims revert to AVAILABLE. (PRD §3.9.)
    """
    prior_status = claim["status"]
    owning_cashout_id = claim.get("cashout_id")

    claim["status"] = "CLAWED_BACK"
    claim["cashout_id"] = None
    touch(store, claim)
    emit_ledger(
        store,
        claim["member_id"],
        "CLAIM_CLAWBACK",
        -clawback_cents,
        reward_claim_id=claim["id"],
    )

    if prior_status == "RESERVED" and owning_cashout_id is not None:
        cashout = store.cashouts.get(owning_cashout_id)
        if cashout is not None and cashout["status"] in ("REQUESTED", "PROCESSING"):
            # CASCADE step 1: owning cash-out -> FAILED.
            cashout["status"] = "FAILED"
            touch(store, cashout)
            # CASCADE step 2: every OTHER reserved claim reverts to AVAILABLE.
            revert_claims_available(store, cashout)
