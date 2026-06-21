"""Capital-call issuance & allocation (PRD §3.3, allocate_capital_call).

Participation: Commitment.status == ACTIVE, unfunded_cents > 0, and LP not
excused from this purpose by an EXECUTED side letter.

The aggregate called_amount_cents must not exceed the sum of unfunded_cents of
participating commitments (ERR_CALL_EXCEEDS_UNFUNDED). Empty participant set
-> ERR_NO_PARTICIPATING_COMMITMENTS.

Split: floor pro-rata by unfunded_cents, leftover by largest fractional
remainder, ties by created_at ASC. No commitment allocated more than its
unfunded_cents.
"""
import db
import errors
from services import allocation, derive, sideletters


def participating_commitments(fund_id, purpose):
    parts = []
    for c in db.commitments.values():
        if c["fund_id"] != fund_id:
            continue
        if c["status"] != "ACTIVE":
            continue
        if derive.commitment_unfunded(c) <= 0:
            continue
        if sideletters.lp_excused(c["lp_id"], fund_id, purpose):
            continue
        parts.append(c)
    return parts


def issue_call(fund, purpose, called_amount_cents, due_date):
    """Create the call + its allocations. Caller holds db.lock and has already
    validated OCC, due_date, and called_amount_cents >= 1.
    """
    participants = participating_commitments(fund["id"], purpose)
    if not participants:
        errors.fail(
            errors.ERR_NO_PARTICIPATING_COMMITMENTS,
            "No participating commitment for this call.",
        )

    unfunded = {c["id"]: derive.commitment_unfunded(c) for c in participants}
    total_unfunded = sum(unfunded.values())
    if called_amount_cents > total_unfunded:
        errors.fail(
            errors.ERR_CALL_EXCEEDS_UNFUNDED,
            "Call exceeds aggregate unfunded capacity.",
        )

    allocated = allocation.largest_remainder_split(
        called_amount_cents, participants, unfunded
    )

    # Create the call.
    call = db.stamp_new(
        {
            "fund_id": fund["id"],
            "call_number": db.next_call_number(fund["id"]),
            "purpose": purpose,
            "called_amount_cents": called_amount_cents,
            "due_date": due_date,
            "status": "ISSUED",
        }
    )
    db.capital_calls[call["id"]] = call

    # Create allocations. No commitment over its unfunded (split already bounded
    # by pro-rata of unfunded; guard defensively).
    for c in participants:
        amt = min(allocated[c["id"]], unfunded[c["id"]])
        alloc = db.stamp_new(
            {
                "capital_call_id": call["id"],
                "commitment_id": c["id"],
                "allocated_amount_cents": amt,
                "paid_amount_cents": 0,
                "status": "PENDING",
            }
        )
        db.capital_call_allocations[alloc["id"]] = alloc

    return call
