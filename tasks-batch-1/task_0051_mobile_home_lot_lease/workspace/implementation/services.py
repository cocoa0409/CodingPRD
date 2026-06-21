"""Shared business logic: computed-field derivations and ledger posting.

Kept free of Flask request handling so serializers and routes can both call in.
"""
from db import db, new_record


# ---------------------------------------------------------------------------
# Computed fields (PRD §2.5)
# ---------------------------------------------------------------------------

def occupied_lot_count(community_id):
    """Number of a community's lots in OCCUPIED status (PRD §2.5)."""
    return sum(
        1 for lot in db.lots.values()
        if lot["community_id"] == community_id and lot["status"] == "OCCUPIED"
    )


def current_rent_cents(lot):
    """A lot's current rent = the new_rent_cents of its currently EFFECTIVE rent
    schedule, falling back to base_rent_cents when none is effective (PRD §2.5).

    When multiple schedules are EFFECTIVE over the lot's life, the most recent
    one (by effective_date, then created order) governs.
    """
    effective = [
        s for s in db.rent_schedules.values()
        if s["lot_id"] == lot["id"] and s["status"] == "EFFECTIVE"
    ]
    if not effective:
        return lot["base_rent_cents"]
    effective.sort(key=lambda s: (s["effective_date"], s["_seq"]))
    return effective[-1]["new_rent_cents"]


def resident_arrears(resident_id):
    """arrears_cents = max(0, sum of signed ledger amounts on the resident's
    ACTIVE lease) (PRD §3.6). Entries on TRANSFERRED/TERMINATED leases excluded.
    """
    active_lease = active_lease_for_resident(resident_id)
    if active_lease is None:
        return 0
    total = sum(
        e["amount_cents"] for e in db.lot_ledger_entries.values()
        if e["lease_id"] == active_lease["id"]
    )
    return max(0, total)


def active_lease_for_resident(resident_id):
    for lease in db.lot_leases.values():
        if lease["resident_id"] == resident_id and lease["status"] == "ACTIVE":
            return lease
    return None


def yes_count(vote_id):
    """Count of YES ballots for a conversion vote (PRD §3.8)."""
    return sum(
        1 for b in db.conversion_ballots.values()
        if b["conversion_vote_id"] == vote_id and b["choice"] == "YES"
    )


# ---------------------------------------------------------------------------
# Ledger posting (PRD §3.6)
# ---------------------------------------------------------------------------

def post_ledger_entry(lease, entry_type, amount_cents):
    """Append an immutable ledger entry for a lease. Charges positive, payments
    negative. id + created_at only (PRD §2.4)."""
    rec = new_record()
    rec.update({
        "lease_id": lease["id"],
        "resident_id": lease["resident_id"],
        "entry_type": entry_type,
        "amount_cents": amount_cents,
    })
    db.lot_ledger_entries[rec["id"]] = rec
    return rec
