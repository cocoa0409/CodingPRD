"""Creating a recruitment: the reservation and its side effects (PRD 3.4)."""
from calc import (
    recompute_participant,
    recompute_pool,
    recompute_study_counters,
    reservation_amount,
    set_field,
    study_recruitments,
)
from clock import clock
from errors import ApiError
from store import db


def create_recruitment(study, pool, participant, screening_answers):
    """One invitation, with the reservation applied against the pool state as it
    stands before this call."""
    amount = reservation_amount(pool, study)
    if amount > pool["incentive_available_cents"]:
        raise ApiError(
            "ERR_INCENTIVE_BUDGET_EXCEEDED",
            "The reservation exceeds the pool's available incentive budget.",
        )
    first_recruitment = len(study_recruitments(study)) == 0
    row = db.new("recruitments", {
        "study_id": study["id"],
        "participant_id": participant["id"],
        "screening_answers": screening_answers,
        "screen_score": None,
        "status": "INVITED",
        "incentive_state": "RESERVED",
        "reserved_cents": amount,
        "paid_cents": 0,
        "scheduled_start": None,
        "scheduled_end": None,
        "moderator_user_id": None,
        "guide_version_pinned": study["guide_version_pinned"],
        "actual_duration_min": None,
        "reschedule_count": 0,
        "closure_reason": None,
    })
    set_field(pool, "incentive_reserved_cents", pool["incentive_reserved_cents"] + amount)
    set_field(participant, "last_contacted_at", clock.now())
    recompute_participant(participant)
    recompute_pool(pool)
    recompute_study_counters(study)
    if first_recruitment and study["recruitment_status"] == "NOT_STARTED":
        set_field(study, "recruitment_status", "RECRUITING")
    return row


def affordable(pool, study):
    return reservation_amount(pool, study) <= pool["incentive_available_cents"]
