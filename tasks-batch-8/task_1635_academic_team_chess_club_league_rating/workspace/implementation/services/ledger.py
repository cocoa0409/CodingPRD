"""Append-only club ledger: posting, balance recompute, standing auto-transition."""
from db import store, new_id, next_seq, now_iso
from services.common import club_balance, touch

ENTRY_TYPES = ("MEMBERSHIP_DUE", "ENTRY_FEE", "ENTRY_REFUND",
               "TRAVEL_STIPEND", "ADJUSTMENT", "REVERSAL")


def post_ledger(club_id, entry_type, amount_cents, posted_by_user_id,
                memo=None, membership_id=None, entry_id=None, reversal_of_id=None):
    """Append an immutable ledger row and reconcile the owning club.
    Every ledger post advances the club's version by one (OCC anchor)."""
    le = {
        "id": new_id(), "_seq": next_seq(), "created_at": now_iso(),
        "club_id": club_id, "entry_type": entry_type,
        "amount_cents": amount_cents, "memo": memo,
        "posted_by_user_id": posted_by_user_id,
        "membership_id": membership_id, "entry_id": entry_id,
        "reversal_of_id": reversal_of_id, "reversed_by_id": None,
    }
    store.ledger_entries[le["id"]] = le
    reconcile_club(club_id)
    return le


def reconcile_club(club_id):
    """Recompute derived balance; apply GOOD_STANDING <-> DELINQUENT flips.
    Posts never change a SUSPENDED club's standing."""
    club = store.clubs[club_id]
    bal = club_balance(club_id)
    club["account_balance_cents"] = bal
    if club["status"] == "GOOD_STANDING" and bal < 0:
        club["status"] = "DELINQUENT"
    elif club["status"] == "DELINQUENT" and bal >= 0:
        club["status"] = "GOOD_STANDING"
    touch(club)
