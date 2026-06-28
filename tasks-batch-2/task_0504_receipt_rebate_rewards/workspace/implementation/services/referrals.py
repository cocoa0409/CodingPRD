"""Referral lifecycle helpers (PRD §3.7)."""
from db import touch
from services.wallet import cumulative_qualifying_cents


def maybe_qualify_referrals_for(store, member_id):
    """A referral moves SIGNED_UP -> QUALIFIED when the referee's cumulative
    (AVAILABLE + PAID) reward cents reaches referee_qualifying_cents.

    Called after any change that may raise a member's qualifying total.
    """
    cumulative = None
    for r in store.referrals.values():
        if r["status"] != "SIGNED_UP":
            continue
        if r.get("referee_member_id") != member_id:
            continue
        if cumulative is None:
            cumulative = cumulative_qualifying_cents(store, member_id)
        if cumulative >= r["referee_qualifying_cents"]:
            r["status"] = "QUALIFIED"
            touch(store, r)
