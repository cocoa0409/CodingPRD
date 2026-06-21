"""Record lifecycle helpers: create base record, touch (bump version + ts),
and FK/path existence lookups that raise ERR_NOT_FOUND."""
import errors
from db import db, new_id, now_iso


def make_record(with_version=True):
    """Create a fresh record carrying common server-managed fields."""
    ts = now_iso()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "_seq": db.next_seq(),
    }
    if with_version:
        rec["version"] = 1
    return rec


def touch(record):
    """Mutation bookkeeping: refresh updated_at and increment version.

    Applies to any record that carries a version (everything except ClaimDocument,
    which is never mutated)."""
    record["updated_at"] = now_iso()
    if "version" in record:
        record["version"] += 1


# --------------------------------------------------------------------------
# Existence lookups (raise ERR_NOT_FOUND on miss)
# --------------------------------------------------------------------------
def get_plan(plan_id):
    rec = db.plans.get(plan_id)
    if rec is None:
        raise errors.not_found("Plan not found.")
    return rec


def get_traveler(traveler_id):
    rec = db.travelers.get(traveler_id)
    if rec is None:
        raise errors.not_found("Traveler not found.")
    return rec


def get_policy(policy_id):
    rec = db.policies.get(policy_id)
    if rec is None:
        raise errors.not_found("Policy not found.")
    return rec


def get_insured(insured_id):
    rec = db.insured_travelers.get(insured_id)
    if rec is None:
        raise errors.not_found("Insured traveler not found.")
    return rec


def get_named_storm(storm_id):
    rec = db.named_storms.get(storm_id)
    if rec is None:
        raise errors.not_found("Named storm not found.")
    return rec


def get_claim(claim_id):
    rec = db.claims.get(claim_id)
    if rec is None:
        raise errors.not_found("Claim not found.")
    return rec


def get_payout(payout_id):
    rec = db.payouts.get(payout_id)
    if rec is None:
        raise errors.not_found("Payout not found.")
    return rec


def get_refund(refund_id):
    rec = db.refunds.get(refund_id)
    if rec is None:
        raise errors.not_found("Refund not found.")
    return rec


# --------------------------------------------------------------------------
# Collection helpers
# --------------------------------------------------------------------------
def covered_insured_for_policy(policy_id):
    return [
        it for it in db.insured_travelers.values()
        if it["policy_id"] == policy_id and it["status"] == "COVERED"
    ]


def all_insured_for_policy(policy_id):
    return [it for it in db.insured_travelers.values() if it["policy_id"] == policy_id]


def expenses_for_claim(claim_id):
    return [e for e in db.claim_expenses.values() if e["claim_id"] == claim_id]


def documents_for_claim(claim_id):
    return [d for d in db.claim_documents.values() if d["claim_id"] == claim_id]


def claims_for_policy(policy_id):
    return [c for c in db.claims.values() if c["policy_id"] == policy_id]


def completed_refunds_for_policy(policy_id):
    return [
        r for r in db.refunds.values()
        if r["policy_id"] == policy_id and r["status"] == "COMPLETED"
    ]
