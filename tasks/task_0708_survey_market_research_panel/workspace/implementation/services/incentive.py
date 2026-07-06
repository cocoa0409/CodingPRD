"""Incentive ledger operations (PRD §2.8 / §3.5).

A participation's HELD PROVISIONAL accrual is created at screen-in, then either
finalized to CREDITED (at QUALIFIED) or flipped to VOID (when the participation
falls out). The point value is replaced by the finalized amount at finalize.
"""
import db
from services import calc


def create_provisional(participation, study):
    """Create the HELD PROVISIONAL accrual at SCREENING->SCREENED_IN.

    Computes provisional_points = base + length_bonus, writes it onto the
    participation, and appends an IncentiveAccrual(kind=PROVISIONAL, HELD).
    """
    pts = calc.provisional_points(study["base_incentive_points"],
                                  study["estimated_minutes"])
    participation["provisional_points"] = pts

    accrual = db.base_record(common_fields=True)
    accrual.update({
        "panelist_id": participation["panelist_id"],
        "participation_id": participation["id"],
        "accrual_kind": "PROVISIONAL",
        "points": pts,
        "status": "HELD",
    })
    db.incentive_accruals[accrual["id"]] = accrual
    return accrual


def _held_provisional_for(participation_id):
    for a in db.incentive_accruals.values():
        if (a["participation_id"] == participation_id
                and a["accrual_kind"] == "PROVISIONAL"
                and a["status"] == "HELD"):
            return a
    return None


def finalize(participation, quality_score):
    """At SCREENED_IN->QUALIFIED: the HELD PROVISIONAL accrual flips to CREDITED
    and its points value is replaced by finalized_points (PRD §3.5).
    """
    accrual = _held_provisional_for(participation["id"])
    if accrual is None:
        return None
    final_pts = calc.finalized_points(participation["provisional_points"], quality_score)
    accrual["points"] = final_pts
    accrual["status"] = "CREDITED"
    db.touch(accrual)
    return accrual


def void_hold(participation):
    """When a participation falls out, its HELD PROVISIONAL accrual -> VOID."""
    accrual = _held_provisional_for(participation["id"])
    if accrual is None:
        return None
    accrual["status"] = "VOID"
    db.touch(accrual)
    return accrual
