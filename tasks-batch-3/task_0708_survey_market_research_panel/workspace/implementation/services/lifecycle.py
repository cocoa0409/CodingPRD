"""Shared state-transition helpers and cascades (PRD §3.3 / §3.4 / §3.6).

The void cascade (leave the reserving set, free the seat, void the hold) is
reused by abandon, study close, panelist suspend, and mark_churned. Seat release
falls out of recomputing cell counts from current state — it is not a separate
write — so voiding only requires flipping the participation's screening_status
and voiding its HELD accrual.
"""
import db
from services import incentive


def void_participation(participation):
    """Force a SCREENING/SCREENED_IN participation to VOIDED, voiding its hold.

    Releasing the reserved seat is implicit: cell counts are derived from the
    current screening_status, so once it is VOIDED the seat is no longer counted.
    """
    if participation["screening_status"] in ("SCREENING", "SCREENED_IN"):
        participation["screening_status"] = "VOIDED"
        incentive.void_hold(participation)
        db.touch(participation)
        return True
    return False


def cascade_void_for_study(study_id):
    """Study-closure cascade (PRD §3.4): every participation on the study still
    in SCREENING/SCREENED_IN -> VOIDED.
    """
    for p in db.participations.values():
        if p["study_id"] == study_id:
            void_participation(p)


def cascade_void_for_panelist(panelist_id):
    """Panelist suspend / mark_churned cascade (PRD §3.4 / §3.6): every
    participation of the panelist still in SCREENING/SCREENED_IN -> VOIDED.
    """
    for p in db.participations.values():
        if p["panelist_id"] == panelist_id:
            void_participation(p)
