"""The promotion waterfall at cardinality zero: two different ways of having no
candidate, both of them silent."""
from test_helpers import (
    DOB_AGE_60,
    create_athlete,
    create_entry,
    get_athlete,
    get_edition,
    get_entry,
    get_event,
    ops_run,
    pay_fees,
    screen_athlete,
    setup_open_edition,
    take_up_and_accept,
    take_up_and_waitlist,
)


def _two_seat_event_with_one_ineligible_waitlister() -> dict:
    """An event of capacity two holding one accepted entry and one waitlisted entry
    whose athlete has neither paid nor been screened, so exactly one seat is free
    and no candidate qualifies for it.
    """
    ctx = setup_open_edition(event={"capacity": 2, "min_entries_to_stage": 1})
    edition_id = ctx["edition"]["id"]
    event_id = ctx["event"]["id"]
    ada = create_athlete(edition_id, full_name="Ada Frost", date_of_birth=DOB_AGE_60)
    bruno = create_athlete(edition_id, full_name="Bruno Vega", date_of_birth="1963-07-18")
    ada_entry = create_entry(ada["id"], event_id)
    bruno_entry = create_entry(bruno["id"], event_id)
    pay_fees(ada["id"], 15500)
    screen_athlete(ada["id"])
    take_up_and_accept(ada_entry["id"])
    take_up_and_waitlist(bruno_entry["id"])
    return {
        "edition_id": edition_id, "event_id": event_id,
        "ada_entry": ada_entry, "bruno": bruno, "bruno_entry": bruno_entry,
    }


def test_a_free_seat_with_no_eligible_candidate_is_a_silent_no_op():
    """PRD §3.3: "Within each event, the candidate set is that event's entries currently
    `WAITLISTED` whose athlete is `REGISTERED` and whose athlete's `medical_status` is
    one of `SCREENED_CLEARED`, `SCREENED_RESTRICTED` or `CLEARED_BY_APPEAL`."
    PRD §3.3: "An event with no eligible candidate is simply skipped: that is not an
    error, and the checkpoint carries on."
    PRD §3.9: "First, the edition's `ops_epoch` is incremented by one, stamping the
    run."
    PRD §3.9: "Sixth, and only now that heads and stays have settled,
    `provisional_impact_cents` is recomputed."
    PRD §3.9: "Its head count, reported as `registered_heads`, is the number of athletes
    in the edition whose `registration_status` is `PENDING_PAYMENT`, `REGISTERED` or
    `CHECKED_IN` — everyone who has entered and not fallen away."
    PRD §3.9: "Direct spend is the sum of athlete heads and visitor heads, multiplied by
    the daily spend of eighteen thousand five hundred cents and by the projected four
    nights, and that product is rounded to whole cents with a half cent going up."
    PRD §3.9: "`provisional_impact_cents` is then that rounded direct spend multiplied
    by one point four five and rounded again to whole cents, half up."

    The waterfall visits the event because a seat is free, finds its only
    waitlisted entry fails the eligibility filter, and simply carries on: no error,
    no promotion, and the ineligible athlete is skipped rather than expired.  The
    run's own bookkeeping still happens — the epoch advances to one and the
    projection is recomputed for the two live heads at 600880 cents.

    Design: Difficulty/boundary_precision_check/waitlist_promotion_empty_candidate_set_boundary_is_a_silent_noop
    """
    ctx = _two_seat_event_with_one_ineligible_waitlister()

    ops_run(ctx["edition_id"])

    assert get_entry(ctx["bruno_entry"]["id"])["status"] == "WAITLISTED"
    event = get_event(ctx["event_id"])
    assert event["accepted_entry_count"] == 1
    assert event["available_slots"] == 1
    edition = get_edition(ctx["edition_id"])
    assert edition["ops_epoch"] == 1
    assert edition["status"] == "REGISTRATION_OPEN"
    assert edition["provisional_impact_cents"] == 600880
    assert get_athlete(ctx["bruno"]["id"])["registration_status"] == "PENDING_PAYMENT"


def test_the_candidate_set_becomes_non_empty_the_moment_the_filter_is_satisfied():
    """PRD §3.3: "Within each event, the candidate set is that event's entries currently
    `WAITLISTED` whose athlete is `REGISTERED` and whose athlete's `medical_status` is
    one of `SCREENED_CLEARED`, `SCREENED_RESTRICTED` or `CLEARED_BY_APPEAL`."
    PRD §3.3: "Candidates are promoted in that rank order while the event still has
    `available_slots` greater than zero; each promotion moves the entry `WAITLISTED` →
    `ACCEPTED`, increments `accepted_entry_count` by one, decrements `available_slots`
    by one, and lifts the event `UNDERSUBSCRIBED` → `OPEN` when the floor is reached."
    PRD §3.2: "On success the recomputed `fee_total_cents` and `fee_breakdown` are
    stored, `fee_paid_cents` is set equal to `fee_total_cents`, and the registration
    dimension advances `PENDING_PAYMENT` → `REGISTERED`."
    PRD §3.4: "A `CLEARED` recommendation moves the athlete `NOT_SCREENED` →
    `SCREENED_CLEARED` and touches nothing else; the athlete's entries stand as they
    are."
    PRD §3.9: "First, the edition's `ops_epoch` is incremented by one, stamping the
    run."

    Paying and screening the waitlisted athlete lifts the candidate set from zero
    to one, and the very next checkpoint promotes exactly that entry, filling the
    last seat.

    Design: Difficulty/boundary_precision_check/waitlist_promotion_empty_candidate_set_boundary_is_a_silent_noop
    """
    ctx = _two_seat_event_with_one_ineligible_waitlister()
    ops_run(ctx["edition_id"])

    pay_fees(ctx["bruno"]["id"], 15500)
    screen_athlete(ctx["bruno"]["id"], systolic_bp=120, resting_hr=68)
    bruno = get_athlete(ctx["bruno"]["id"])
    assert bruno["registration_status"] == "REGISTERED"
    assert bruno["fee_total_cents"] == 15500
    assert bruno["medical_status"] == "SCREENED_CLEARED"

    ops_run(ctx["edition_id"])

    assert get_entry(ctx["bruno_entry"]["id"])["status"] == "ACCEPTED"
    event = get_event(ctx["event_id"])
    assert event["accepted_entry_count"] == 2
    assert event["available_slots"] == 0
    assert get_edition(ctx["edition_id"])["ops_epoch"] == 2


def test_an_event_with_no_free_seat_is_skipped_and_the_run_still_stamps_itself():
    """PRD §3.3: "At each operations checkpoint the sport events of the edition whose
    status is `OPEN`, `SEEDED` or `UNDERSUBSCRIBED` and whose `available_slots` is
    greater than zero are processed in ascending `created_at` order."
    PRD §3.3: "An event with no eligible candidate is simply skipped: that is not an
    error, and the checkpoint carries on."
    PRD §3.9: "First, the edition's `ops_epoch` is incremented by one, stamping the
    run."
    PRD §3.9: "Sixth, and only now that heads and stays have settled,
    `provisional_impact_cents` is recomputed."
    PRD §3.9: "Its head count, reported as `registered_heads`, is the number of athletes
    in the edition whose `registration_status` is `PENDING_PAYMENT`, `REGISTERED` or
    `CHECKED_IN` — everyone who has entered and not fallen away."

    The second route to cardinality zero is a full event, which the waterfall does
    not even visit.  A third checkpoint therefore changes no entry, yet the epoch
    still advances to three and the projection is still recomputed — unchanged,
    because promotion moves no heads.

    Design: Difficulty/boundary_precision_check/waitlist_promotion_empty_candidate_set_boundary_is_a_silent_noop
    """
    ctx = _two_seat_event_with_one_ineligible_waitlister()
    ops_run(ctx["edition_id"])
    pay_fees(ctx["bruno"]["id"], 15500)
    screen_athlete(ctx["bruno"]["id"], systolic_bp=120, resting_hr=68)
    ops_run(ctx["edition_id"])

    ops_run(ctx["edition_id"])

    assert get_entry(ctx["ada_entry"]["id"])["status"] == "ACCEPTED"
    assert get_entry(ctx["bruno_entry"]["id"])["status"] == "ACCEPTED"
    event = get_event(ctx["event_id"])
    assert event["accepted_entry_count"] == 2
    assert event["available_slots"] == 0
    edition = get_edition(ctx["edition_id"])
    assert edition["ops_epoch"] == 3
    assert edition["provisional_impact_cents"] == 600880
    assert edition["status"] == "REGISTRATION_OPEN"
