"""Derived-field recomputation and hierarchical propagation (PRD §2.5, §2.9).

These functions recompute computed fields from children/ledger. They are the
single source of truth for:
  - Troop.registered_youth_count, cleared_leader_count, dues_account_cents,
    recharter_posture
  - Council.fund_cash_cents, fund_liability_cents
  - Member.dues_paid_cents
  - Advancement.completion_pct
  - Event.confirmed_count
  - Fundraiser.allocated_units, available_units
"""
from datetime import datetime, timezone

from db import db
from clock import clock
from util import iso_now

# Pinned recharter minimums (PRD §2.5 / SCAFFOLD Troop.recharter_posture).
MIN_YOUTH = 5
MIN_LEADERS = 2


def _touch(entity):
    """Refresh updated_at to logical-clock-independent wall time."""
    entity["updated_at"] = iso_now(datetime.now(timezone.utc))


def bump_troop_version(troop):
    """Increment a troop's version and refresh updated_at (PRD §2.4, §2.5)."""
    troop["version"] += 1
    _touch(troop)


# ---------------------------------------------------------------------------
# Troop derived counts
# ---------------------------------------------------------------------------
def compute_registered_youth_count(troop_id):
    return sum(
        1
        for m in db.members.values()
        if m["troop_id"] == troop_id
        and m["member_type"] == "YOUTH"
        and m["registration_status"] == "REGISTERED"
    )


def compute_cleared_leader_count(troop_id):
    """Adult members whose LeaderCredential is CLEARED and TRAINED (PRD §2.5)."""
    count = 0
    for m in db.members.values():
        if m["troop_id"] != troop_id or m["member_type"] != "ADULT":
            continue
        # An adult counts if ANY of their credentials is cleared-and-trained.
        for cred in db.leader_credentials.values():
            if (
                cred["member_id"] == m["id"]
                and cred["bgcheck_status"] == "CLEARED"
                and cred["training_status"] == "TRAINED"
            ):
                count += 1
                break
    return count


def compute_troop_dues_account_cents(troop_id):
    return sum(
        e["amount_cents"]
        for e in db.fund_ledger_entries.values()
        if e["account"] == "TROOP_DUES" and e["troop_id"] == troop_id
    )


def compute_recharter_posture(troop):
    """Compound derived gate (PRD §2.5).

    READY iff registered_youth_count >= 5 AND cleared_leader_count >= 2; else
    BLOCKED. Independently, EXPIRED once charter_expires_at < clock_now.
    """
    expires = troop.get("_charter_expires_dt")
    if expires is not None and expires < clock.now():
        return "EXPIRED"
    if (
        troop["registered_youth_count"] >= MIN_YOUTH
        and troop["cleared_leader_count"] >= MIN_LEADERS
    ):
        return "READY"
    return "BLOCKED"


def recompute_troop_counts(troop, bump=False):
    """Recompute all troop-derived fields in place. Optionally bump version.

    PRD §2.5: any child-driven recompute refreshes the counts, the posture,
    dues_account_cents, refreshes updated_at, and increments version by one.
    """
    troop["registered_youth_count"] = compute_registered_youth_count(troop["id"])
    troop["cleared_leader_count"] = compute_cleared_leader_count(troop["id"])
    troop["dues_account_cents"] = compute_troop_dues_account_cents(troop["id"])
    troop["recharter_posture"] = compute_recharter_posture(troop)
    if bump:
        bump_troop_version(troop)


def refresh_troop_read(troop):
    """Recompute derived fields for a GET (no version bump). PRD §2.5."""
    troop["registered_youth_count"] = compute_registered_youth_count(troop["id"])
    troop["cleared_leader_count"] = compute_cleared_leader_count(troop["id"])
    troop["dues_account_cents"] = compute_troop_dues_account_cents(troop["id"])
    troop["recharter_posture"] = compute_recharter_posture(troop)


# ---------------------------------------------------------------------------
# Council fund balances
# ---------------------------------------------------------------------------
def compute_council_fund_cash(council_id):
    return sum(
        e["amount_cents"]
        for e in db.fund_ledger_entries.values()
        if e["council_id"] == council_id and e["account"] == "COUNCIL_CASH"
    )


def compute_council_fund_liability(council_id):
    return sum(
        e["amount_cents"]
        for e in db.fund_ledger_entries.values()
        if e["council_id"] == council_id and e["account"] == "PRODUCT_LIABILITY"
    )


def refresh_council_read(council):
    council["fund_cash_cents"] = compute_council_fund_cash(council["id"])
    council["fund_liability_cents"] = compute_council_fund_liability(council["id"])


# ---------------------------------------------------------------------------
# Member dues_paid_cents
# ---------------------------------------------------------------------------
def compute_member_dues_paid(member_id):
    return sum(
        p["amount_cents"]
        for p in db.payments.values()
        if p["member_id"] == member_id and p["status"] == "POSTED"
    )


def refresh_member_read(member):
    member["dues_paid_cents"] = compute_member_dues_paid(member["id"])


# ---------------------------------------------------------------------------
# Event confirmed_count
# ---------------------------------------------------------------------------
def compute_event_confirmed_count(event_id):
    return sum(
        1
        for r in db.event_registrations.values()
        if r["event_id"] == event_id and r["status"] == "CONFIRMED"
    )


def refresh_event_read(event):
    event["confirmed_count"] = compute_event_confirmed_count(event["id"])


# ---------------------------------------------------------------------------
# Fundraiser inventory
# ---------------------------------------------------------------------------
def compute_allocated_units(fundraiser_id):
    """Sum of units across orders in PLACED or FILLED status (PRD §3.7)."""
    return sum(
        o["units"]
        for o in db.fundraiser_orders.values()
        if o["fundraiser_id"] == fundraiser_id and o["status"] in ("PLACED", "FILLED")
    )


def refresh_fundraiser_inventory(fundraiser):
    allocated = compute_allocated_units(fundraiser["id"])
    fundraiser["allocated_units"] = allocated
    fundraiser["available_units"] = fundraiser["total_inventory_units"] - allocated
