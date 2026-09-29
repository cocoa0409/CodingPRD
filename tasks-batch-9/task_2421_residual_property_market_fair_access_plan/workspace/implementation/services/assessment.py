"""The assessment allocation waterfall and settlement cascade (PRD 3.9).

Rounding order is pinned: each member's raw share is rounded half-up to whole
cents FIRST, and only then is the residue reconciled onto a single absorber.
"""

from db import db, new_record, sorted_records, touch
from util import D, rhu_cents
from services.constants import (
    CREDIT_UNIT_CENTS,
    MAX_CREDIT_OFFSET_PCT,
)


def allocations_of(event_id):
    return sorted_records(None, [a for a in db.assessment_allocations.values()
                                 if a["assessment_event_id"] == event_id])


def allocations_of_member(member_id):
    return sorted_records(None, [a for a in db.assessment_allocations.values()
                                 if a["member_insurer_id"] == member_id])


def eligible_members():
    """status ACTIVE or RUNOFF; WITHDRAWN carriers are excluded."""
    return [m for m in sorted_records(db.member_insurers)
            if m["status"] in ("ACTIVE", "RUNOFF")]


def weight_of(member, allocation_basis):
    if allocation_basis == "MARKET_SHARE":
        return D(member["market_share_pct"])
    return D(member["written_premium_share_pct"])


def recompute_member_cumulative(member):
    """Sum of net_due_cents over that member's PENDING or PAID allocations."""
    total = 0
    for allocation in db.assessment_allocations.values():
        if (allocation["member_insurer_id"] == member["id"]
                and allocation["status"] in ("PENDING", "PAID")):
            total += allocation["net_due_cents"]
    member["cumulative_assessed_cents"] = total
    return member


def recompute_allocated_total(event):
    """Sum of gross_share_cents over the event's non-ABATED allocations."""
    total = 0
    for allocation in allocations_of(event["id"]):
        if allocation["status"] != "ABATED":
            total += allocation["gross_share_cents"]
    event["allocated_total_cents"] = total
    return total


def abate_pending(event, touched):
    for allocation in allocations_of(event["id"]):
        if allocation["status"] == "PENDING":
            allocation["status"] = "ABATED"
            touch(allocation)
            touched.add(allocation["member_insurer_id"])


def run_allocation(event):
    """Build a fresh allocation set from the members' current weights.

    Caller has already enforced the state, OCC and fiscal gates.
    """
    basis = event["allocation_basis"]
    members = eligible_members()
    weights = {m["id"]: weight_of(m, basis) for m in members}
    total_weight = sum(weights.values(), D(0))
    amount = event["assessable_amount_cents"]

    touched = set()
    abate_pending(event, touched)

    rounded = {}
    for member in members:
        raw = D(amount) * weights[member["id"]] / total_weight
        rounded[member["id"]] = rhu_cents(raw)

    remainder = amount - sum(rounded.values())

    # The absorber is the eligible member with the greatest weight; a tie on
    # equal weight is broken in favour of the earliest created_at.
    absorber = sorted(
        members,
        key=lambda m: (-weights[m["id"]], m["created_at"], m["_seq"]),
    )[0]

    for member in members:
        gross = rounded[member["id"]]
        if member["id"] == absorber["id"]:
            gross += remainder
        credit_cap = rhu_cents(D(gross) * MAX_CREDIT_OFFSET_PCT)
        credit_available = member["takeout_credit_count"] * CREDIT_UNIT_CENTS
        applied = credit_cap if credit_cap < credit_available else credit_available
        net_due = gross - applied
        consumed = applied // CREDIT_UNIT_CENTS
        allocation = new_record({
            "assessment_event_id": event["id"],
            "member_insurer_id": member["id"],
            "basis_weight_pct": weights[member["id"]],
            "gross_share_cents": gross,
            "takeout_credit_applied_cents": applied,
            "net_due_cents": net_due,
            "credits_consumed": consumed,
            "status": "PENDING",
            "paid_at": None,
        })
        db.assessment_allocations[allocation["id"]] = allocation
        touched.add(member["id"])

    recompute_allocated_total(event)
    event["remainder_cents"] = remainder
    event["allocation_run_count"] += 1
    event["status"] = "ALLOCATED"
    touch(event)

    for member_id in touched:
        member = db.member_insurers.get(member_id)
        if member is not None:
            recompute_member_cumulative(member)
            touch(member)
    return event


def settle_if_complete(event):
    """Hop 2/3 of a payment: the event settles when no allocation is PENDING,
    and settlement spends every allocation's credits_consumed."""
    if event["status"] != "INVOICED":
        return False
    rows = allocations_of(event["id"])
    if any(row["status"] == "PENDING" for row in rows):
        return False
    event["status"] = "SETTLED"
    touch(event)
    touched = set()
    for allocation in rows:
        member = db.member_insurers.get(allocation["member_insurer_id"])
        if member is None:
            continue
        member["takeout_credit_count"] -= allocation["credits_consumed"]
        touched.add(member["id"])
    for member_id in touched:
        touch(db.member_insurers[member_id])
    return True
