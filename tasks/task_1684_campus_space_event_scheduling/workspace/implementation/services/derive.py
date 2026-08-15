"""Derived fields (SCAFFOLD ``source: computed``): standings, balances, key
counters.  All are computed on read from the live store."""

import db
from constants import (
    GRANT_OUTSTANDING_STATUSES,
    INVOICE_OPEN_STATUSES,
    PROBATION_NO_SHOW_COUNT,
    STANDING_GOOD,
    STANDING_PROBATION,
    STANDING_SUSPENDED,
    SUSPENDED_NO_SHOW_COUNT,
)


def derive_standing(org):
    """standing_threshold: SUSPENDED if count >= 3, PROBATION if == 2, else
    GOOD."""
    count = org.get("no_show_count", 0)
    if count >= SUSPENDED_NO_SHOW_COUNT:
        return STANDING_SUSPENDED
    if count == PROBATION_NO_SHOW_COUNT:
        return STANDING_PROBATION
    return STANDING_GOOD


def _org_id_of_grant(grant):
    event = db.event_reservations.get(grant.get("event_id"))
    return event.get("requester_org_id") if event else None


def org_deposit_held_cents(org):
    """Sum of deposit_cents over the org's grants in ISSUED or OVERDUE."""
    total = 0
    for grant in db.access_grants.values():
        if grant.get("status") in GRANT_OUTSTANDING_STATUSES and _org_id_of_grant(grant) == org["id"]:
            total += grant.get("deposit_cents", 0)
    return total


def org_outstanding_balance_cents(org):
    """Sum over the org's invoices in PROVISIONAL/FINALIZED/PARTIALLY_PAID of
    (total - paid - waived)."""
    total = 0
    for invoice in db.invoices.values():
        if invoice.get("org_id") != org["id"]:
            continue
        if invoice.get("status") not in INVOICE_OPEN_STATUSES:
            continue
        total += (
            invoice.get("total_cents", 0)
            - invoice.get("paid_cents", 0)
            - invoice.get("waived_cents", 0)
        )
    return total


def room_keys_issued(room):
    """Count of the room's PHYSICAL_KEY grants in ISSUED or OVERDUE."""
    count = 0
    for grant in db.access_grants.values():
        if (
            grant.get("room_id") == room["id"]
            and grant.get("grant_type") == "PHYSICAL_KEY"
            and grant.get("status") in GRANT_OUTSTANDING_STATUSES
        ):
            count += 1
    return count


def room_keys_lost_total(room):
    """Cumulative PHYSICAL_KEY grants of this room marked LOST."""
    count = 0
    for grant in db.access_grants.values():
        if (
            grant.get("room_id") == room["id"]
            and grant.get("grant_type") == "PHYSICAL_KEY"
            and grant.get("status") == "LOST"
        ):
            count += 1
    return count
