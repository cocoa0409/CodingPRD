"""Loyalty side effects: accrual emission and tier re-evaluation."""
import db
import serialize
import util
from services import calc


def recompute_member_tier(member):
    """Re-evaluate tier from lifetime_points (override-aware). PRD §3.2."""
    if member.get("_lifetime_override") is not None:
        lifetime = member["_lifetime_override"]
    else:
        _, lifetime = serialize.member_points(member["id"])
    member["tier"] = calc.member_tier(lifetime)


def emit_accrual(agreement, member, half_rate):
    """Emit an ACCRUAL LoyaltyAccrual for a settled agreement, then re-evaluate
    the member's tier. Order is pinned: settlement fixes final_total_cents first,
    THEN accrual reads it (caller guarantees final_total_cents is set).
    """
    earned = calc.loyalty_points_earned(
        agreement["final_total_cents"], member["tier"], half_rate
    )
    accrual = util.stamp_audit(
        {
            "member_id": member["id"],
            "agreement_id": agreement["id"],
            "kind": "ACCRUAL",
            "delta_points": earned,
        }
    )
    db.loyalty_accruals[accrual["id"]] = accrual

    # If lifetime was pinned via the test capability, add the new earnings on
    # top so the override stays consistent with the new accrual.
    if member.get("_lifetime_override") is not None:
        member["_lifetime_override"] += earned
    if member.get("_balance_override") is not None:
        member["_balance_override"] += earned

    recompute_member_tier(member)
    util.touch(member)
    return accrual
