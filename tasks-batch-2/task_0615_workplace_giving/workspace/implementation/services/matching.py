"""Matching-gift lifecycle helpers (PRD §3.6).

Consumption is the employee's stored match_consumed_ytd_cents counter (the
running sum of matched_amount_cents over FINALIZED/SETTLED gifts for the tax
year, PRD §3.2). The estimated variant uses committed consumption at request
time; the finalized variant uses live consumption at settle time.
"""
from db import db
from services.calc import raw_match, clamp_match
from services.common import touch


def create_requested_matching_gift(program, donation, employee):
    """Create a MatchingGift in REQUESTED with estimated_match_cents computed
    from committed (FINALIZED/SETTLED) consumption (PRD §3.5/§3.6)."""
    raw = raw_match(program, donation["base_amount_cents"])
    # estimated variant: committed consumption only = stored counter (which only
    # counts FINALIZED+SETTLED, never in-flight REQUESTED matches).
    estimated = clamp_match(program, raw, employee["match_consumed_ytd_cents"])
    rec = {
        "program_id": program["id"],
        "donation_id": donation["id"],
        "employee_id": donation["employee_id"],
        "raw_match_cents": raw,
        "estimated_match_cents": estimated,
        "matched_amount_cents": 0,
        "status": "REQUESTED",
    }
    from services.common import stamp_create
    stamp_create(rec)
    db.matching_gifts[rec["id"]] = rec
    return rec


def finalize_for_donation(donation):
    """Donation AUTHORIZED->SETTLED side effect: finalize a REQUESTED gift
    using live consumption (PRD §3.6)."""
    gift = _find_requested_gift(donation["id"])
    if gift is None:
        return
    program = db.programs.get(donation["program_id"])
    employee = db.employees.get(donation["employee_id"])
    raw = raw_match(program, donation["base_amount_cents"])
    gift["raw_match_cents"] = raw
    matched = clamp_match(program, raw, employee["match_consumed_ytd_cents"])
    gift["matched_amount_cents"] = matched
    if matched > 0:
        gift["status"] = "FINALIZED"
        employee["match_consumed_ytd_cents"] += matched
        touch(employee)
    else:
        # Clamp yielded 0 (cap fully consumed) -> CAPPED, no debit.
        gift["status"] = "CAPPED"
    touch(gift)


def reverse_for_donation(donation):
    """Donation SETTLED->REFUNDED side effect: reverse a FINALIZED gift
    (compensating credit) (PRD §3.6)."""
    gift = None
    for g in db.matching_gifts.values():
        if g["donation_id"] == donation["id"] and g["status"] == "FINALIZED":
            gift = g
            break
    if gift is None:
        return
    employee = db.employees.get(donation["employee_id"])
    employee["match_consumed_ytd_cents"] -= gift["matched_amount_cents"]
    touch(employee)
    gift["status"] = "REVERSED"
    touch(gift)


def _find_requested_gift(donation_id):
    for g in db.matching_gifts.values():
        if g["donation_id"] == donation_id and g["status"] == "REQUESTED":
            return g
    return None
