"""Shared ledger / snapshot side-effect helpers (PRD §3.10, §3.11)."""
import clock
import db
from common import new_record, touch


def bank_for_driver(driver_id):
    for b in db.discount_banks.values():
        if b["driver_id"] == driver_id:
            return b
    return None


def _recompute_available(bank):
    bank["available_cents"] = bank["earned_cents"] - bank["redeemed_cents"]


def post_grant(bank, leg, amount_cents, source_reason):
    """Append an immutable DiscountGrant leg (PRD §3.10)."""
    grant = new_record(
        {
            "discount_bank_id": bank["id"],
            "leg": leg,
            "amount_cents": amount_cents,
            "source_reason": source_reason,
            "granted_at": clock.iso_now(),
        },
        common=False,
    )
    db.discount_grants[grant["id"]] = grant
    return grant


def earn(bank, amount_cents, source_reason):
    bank["earned_cents"] += amount_cents
    _recompute_available(bank)
    touch(bank)
    return post_grant(bank, "EARN", amount_cents, source_reason)


def redeem(bank, amount_cents, source_reason):
    bank["redeemed_cents"] += amount_cents
    _recompute_available(bank)
    touch(bank)
    return post_grant(bank, "REDEEM", amount_cents, source_reason)


def reverse(bank, amount_cents, source_reason):
    """Reversal of a previously earned grant — reduces earned_cents (PRD §3.5)."""
    bank["earned_cents"] -= amount_cents
    _recompute_available(bank)
    touch(bank)
    return post_grant(bank, "REVERSAL", amount_cents, source_reason)


def append_snapshot(policy, trigger_reason):
    """Append an immutable RiskScoreSnapshot (PRD §3.11)."""
    snap = new_record(
        {
            "policy_id": policy["id"],
            "trigger_reason": trigger_reason,
            "risk_score": policy["current_risk_score"],
            "risk_multiplier": policy["current_risk_multiplier"],
            "snapshot_at": clock.iso_now(),
        },
        common=False,
    )
    db.risk_snapshots[snap["id"]] = snap
    return snap
