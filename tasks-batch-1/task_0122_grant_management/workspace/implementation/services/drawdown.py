"""Drawdown waterfall derivation (PRD §3.5)."""
import db


def derive_waterfall(award_id, amount_cents):
    """Derive the canonical allocation for a drawdown of amount_cents against
    the award's restricted funds (PRD §3.5).

    Every fund participates regardless of category or status. Funds are taken in
    ascending priority_order, with created_at (creation order) ascending as the
    tie-break. Each fund absorbs min(remaining, headroom) where headroom is
    budgeted_cents - allocated_cents; a line is recorded only when take > 0.

    Returns (lines, remaining) where lines is a list of
    {restricted_fund_id, amount_cents} in waterfall order, and remaining is the
    undistributed cash (> 0 means insufficient total headroom). Caller holds
    db.LOCK. This is a pure derivation: it mutates nothing.
    """
    funds = [f for f in db.restricted_funds.values() if f["award_id"] == award_id]
    funds.sort(key=lambda f: (f["priority_order"], f["_seq"]))

    remaining = amount_cents
    lines = []
    for fund in funds:
        if remaining <= 0:
            break
        headroom = fund["budgeted_cents"] - fund["allocated_cents"]
        if headroom <= 0:
            continue
        take = min(remaining, headroom)
        if take > 0:
            lines.append({"restricted_fund_id": fund["id"], "amount_cents": take})
            remaining -= take
    return lines, remaining


def plans_match(derived_lines, plan_lines):
    """True iff the server-derived waterfall equals the requester's
    allocation_plan line-for-line: same fund ids, same amounts, same order
    (PRD §3.5)."""
    if len(derived_lines) != len(plan_lines):
        return False
    for d, p in zip(derived_lines, plan_lines):
        if d["restricted_fund_id"] != p.get("restricted_fund_id"):
            return False
        if d["amount_cents"] != p.get("amount_cents"):
            return False
    return True
