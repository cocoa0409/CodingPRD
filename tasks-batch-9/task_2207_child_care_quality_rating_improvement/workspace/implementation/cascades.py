"""Cascades. They run to completion inside the triggering request (PRD §2.10)."""

from decimal import Decimal

import calculations as calc
import store
from validation import as_date


def provider_of(record):
    return store.DB.providers.get(record.get("provider_id"))


def cycles_of(provider_id):
    return [c for c in store.DB.rating_cycles.values() if c["provider_id"] == provider_id]


def allocations_of(provider_id):
    return [a for a in store.DB.coaching_allocations.values()
            if a["provider_id"] == provider_id]


def sessions_of(allocation_id):
    return [s for s in store.DB.coaching_sessions.values()
            if s["coaching_allocation_id"] == allocation_id]


def grants_of(provider_id):
    return [g for g in store.DB.improvement_grants.values()
            if g["provider_id"] == provider_id]


def expenditures_of(grant_id):
    return [e for e in store.DB.grant_expenditures.values()
            if e["improvement_grant_id"] == grant_id]


def claims_of(provider_id):
    return [c for c in store.DB.subsidy_claims.values() if c["provider_id"] == provider_id]


def appeals_of(cycle_id):
    return [a for a in store.DB.appeals.values() if a["rating_cycle_id"] == cycle_id]


OPEN_APPEAL_STATES = ("FILED", "UNDER_REVIEW", "INFO_REQUESTED")


def has_open_appeal(cycle_id):
    return any(a["status"] in OPEN_APPEAL_STATES for a in appeals_of(cycle_id))


def refresh_public_listing(provider):
    """public_listing_visible is true exactly when the current cycle is PUBLISHED."""
    cycle_id = provider.get("current_rating_cycle_id")
    visible = False
    if cycle_id:
        cycle = store.DB.rating_cycles.get(cycle_id)
        visible = bool(cycle and cycle.get("publication_status") == "PUBLISHED")
    provider["public_listing_visible"] = visible


# --------------------------------------------------------------- session hops


def cancel_scheduled_sessions(allocation):
    """Cancel every SCHEDULED session, returning its hours to the allocation."""
    for session in sessions_of(allocation["id"]):
        if session["status"] != "SCHEDULED":
            continue
        hours = calc.dec(session["scheduled_hours"])
        session["status"] = "CANCELLED"
        store.touch(session)
        allocation["scheduled_hours"] = calc.dec(allocation["scheduled_hours"]) - hours
        allocation["remaining_hours"] = calc.dec(allocation["remaining_hours"]) + hours


def suspend_allocation(allocation):
    """ACTIVE -> SUSPENDED, cancelling its scheduled sessions (third-order hop)."""
    if allocation["status"] != "ACTIVE":
        return
    allocation["status"] = "SUSPENDED"
    cancel_scheduled_sessions(allocation)
    store.touch(allocation)


def suspend_provider_allocations(provider):
    for allocation in allocations_of(provider["id"]):
        suspend_allocation(allocation)


def reactivate_provider_allocations(provider):
    for allocation in allocations_of(provider["id"]):
        if allocation["status"] == "SUSPENDED":
            allocation["status"] = "ACTIVE"
            store.touch(allocation)


def close_allocations_for_grant(grant):
    for allocation in store.DB.coaching_allocations.values():
        if allocation.get("funding_grant_id") != grant["id"]:
            continue
        if allocation["status"] in ("PROPOSED", "ACTIVE", "SUSPENDED"):
            allocation["status"] = "CLOSED"
            store.touch(allocation)


def void_allocations_for_declined_grant(grant):
    for allocation in store.DB.coaching_allocations.values():
        if allocation.get("funding_grant_id") != grant["id"]:
            continue
        if allocation["status"] == "PROPOSED":
            allocation["status"] = "VOID"
            store.touch(allocation)


def suspend_allocations_for_grant(grant):
    for allocation in store.DB.coaching_allocations.values():
        if allocation.get("funding_grant_id") != grant["id"]:
            continue
        suspend_allocation(allocation)


# ----------------------------------------------------------------- grant hops


def void_submitted_expenditures(grant):
    total = 0
    for line in expenditures_of(grant["id"]):
        if line["status"] != "SUBMITTED":
            continue
        line["status"] = "VOIDED"
        store.touch(line)
        total += int(line["amount_cents"])
    if total:
        grant["available_cents"] = int(grant["available_cents"]) + total
        grant["committed_cents"] = int(grant["committed_cents"]) - total


def freeze_grant(grant):
    """OPEN -> FROZEN: void submitted expenditures, suspend funded allocations."""
    if grant["status"] != "OPEN":
        return False
    grant["status"] = "FROZEN"
    void_submitted_expenditures(grant)
    suspend_allocations_for_grant(grant)
    store.touch(grant)
    return True


# ----------------------------------------------------------------- cycle hops


def recompute_allocation_spend_caps(provider):
    """A tier change retightens every ACTIVE allocation's spend_cap_cents (PRD §3.5)."""
    for allocation in allocations_of(provider["id"]):
        if allocation["status"] != "ACTIVE":
            continue
        grant = store.DB.improvement_grants.get(allocation.get("funding_grant_id"))
        allocation["spend_cap_cents"] = calc.compute_spend_cap(
            provider, allocation["funding_source"], grant)
        store.touch(allocation)


def promote_cycle_to_active(cycle):
    """AWARDED -> ACTIVE plus the three-part supersession cascade (PRD §3.5)."""
    provider = provider_of(cycle)
    cycle["status"] = "ACTIVE"
    store.touch(cycle)
    for other in cycles_of(cycle["provider_id"]):
        if other["id"] == cycle["id"] or other["status"] != "ACTIVE":
            continue
        other["status"] = "SUPERSEDED"
        other["superseded_by_cycle_id"] = cycle["id"]
        other["publication_status"] = "WITHDRAWN"
        store.touch(other)
    if provider is not None:
        provider["current_rating_cycle_id"] = cycle["id"]
        provider["current_tier"] = cycle.get("awarded_tier")
        if provider["status"] == "ENROLLED":
            provider["status"] = "ACTIVE"
        refresh_public_listing(provider)
        store.touch(provider)
        recompute_allocation_spend_caps(provider)


def expire_cycle(cycle):
    """ACTIVE -> EXPIRED plus its four hops (PRD §3.5)."""
    provider = provider_of(cycle)
    cycle["status"] = "EXPIRED"
    cycle["publication_status"] = "WITHDRAWN"
    store.touch(cycle)
    if provider is None:
        return
    if provider.get("current_rating_cycle_id") == cycle["id"]:
        provider["current_rating_cycle_id"] = None
        provider["current_tier"] = None
    provider["public_listing_visible"] = False
    store.touch(provider)
    suspend_provider_allocations(provider)
    for grant in grants_of(provider["id"]):
        if grant["status"] == "OPEN":
            freeze_grant(grant)


def withdraw_provider_cycles(provider):
    terminal = ("EXPIRED", "SUPERSEDED", "WITHDRAWN")
    for cycle in cycles_of(provider["id"]):
        if cycle["status"] in terminal:
            continue
        cycle["status"] = "WITHDRAWN"
        cycle["publication_status"] = "WITHDRAWN"
        store.touch(cycle)


# ---------------------------------------------------------- appeal / subsidy


def flag_paid_claims_for_reconciliation(cycle, provider):
    """Second and third hop of a sustained appeal (PRD §3.6)."""
    start = as_date(cycle.get("effective_date"))
    end = as_date(cycle.get("expires_on"))
    if start is None or end is None:
        return
    from validation import month_first_day
    for claim in claims_of(provider["id"]):
        if claim["status"] != "PAID":
            continue
        first = month_first_day(claim["service_month"])
        if first < start or first > end:
            continue
        paid_amount = int(claim.get("reimbursement_cents") or 0)
        _, reconciled = calc.compute_subsidy(
            provider, claim, "RECONCILED", admit_cycle_ids=(cycle["id"],)
        )
        claim["status"] = "RECONCILE_REQUIRED"
        claim["_paid_reimbursement_cents"] = paid_amount
        # Recorded so the later reconciled payment can return the conserved balance
        # to exactly its pre-cascade value (PRD §2.10, §3.7).
        claim["_reconcile_adjustment_cents"] = reconciled - paid_amount
        store.touch(claim)
        provider["reimbursement_adjustment_cents"] = \
            int(provider["reimbursement_adjustment_cents"]) + (reconciled - paid_amount)
        store.touch(provider)
