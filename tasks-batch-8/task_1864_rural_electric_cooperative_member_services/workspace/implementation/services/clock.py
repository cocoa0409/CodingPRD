"""Logical clock management and escheatment sweep."""
from datetime import timezone

import db
from db import store


def set_clock(to_iso8601):
    """Set the logical clock and fire the escheatment sweep."""
    dt = db.parse_iso(to_iso8601)
    db.set_logical_clock(dt)
    _escheat_sweep(dt)
    return {"current_utc": db.iso_logical(dt)}


def _escheat_sweep(now):
    """Transition UNCLAIMED -> ESCHEATED for every payout whose claim_deadline <= now."""
    for payout in store.capital_credit_payouts.values():
        if payout.get("status") == "UNCLAIMED":
            deadline = db.parse_iso(payout["claim_deadline"])
            if deadline <= now:
                payout["status"] = "ESCHEATED"
                db.touch(payout)
                member = store.members.get(payout["member_id"])
                if member:
                    member["unclaimed_credit_cents"] = max(
                        0, member.get("unclaimed_credit_cents", 0) - payout["payout_cents"]
                    )
                    db.touch(member)
                store.escheat_ledger.append({
                    "payout_id": payout["id"],
                    "member_id": payout["member_id"],
                    "payout_cents": payout["payout_cents"],
                    "escheated_at": db.iso_logical(now),
                })
