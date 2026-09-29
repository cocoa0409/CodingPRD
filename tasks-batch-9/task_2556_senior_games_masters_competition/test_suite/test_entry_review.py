"""Entry review: the bounded revision loop and the cross-row gates on acceptance."""
from test_helpers import (
    ApiErrorId,
    api_client,
    TEST_USERS,
    REGISTRATION_OFFICER_USER_ID,
    create_athlete,
    create_entry,
    get_athlete,
    get_entry,
    get_event,
    make_athlete_headers,
    make_registration_officer_headers,
    pay_fees,
    review_entry,
    screen_athlete,
    setup_open_edition,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["games_admin_headers"]
OFFICER = make_registration_officer_headers(REGISTRATION_OFFICER_USER_ID)


def _submitted_entry() -> dict:
    """One athlete with one `SUBMITTED` organizer-invite entry on an open event.

    Returns {"edition", "event", "athlete", "entry"}.
    """
    ctx = setup_open_edition()
    athlete = create_athlete(ctx["edition"]["id"])
    entry = create_entry(athlete["id"], ctx["event"]["id"])
    return {
        "edition": ctx["edition"],
        "event": ctx["event"],
        "athlete": athlete,
        "entry": entry,
    }


def _revise_once(entry_id: str, athlete_id: str, note: str) -> dict:
    """One full turn of the loop: `SUBMITTED` → `UNDER_REVIEW` →
    `REVISION_REQUESTED` → `SUBMITTED`."""
    review_entry(entry_id, "TAKE_UP")
    review_entry(entry_id, "REQUEST_REVISION", review_note=note)
    return validate_success(
        api_client.resubmit_sport_entry(
            entry_id,
            {"qualification_source": "ORGANIZER_INVITE"},
            make_athlete_headers(athlete_id),
        )
    )


def test_the_revision_loop_counts_its_first_turn_on_the_entry():
    """PRD §3.3: "Entries begin `SUBMITTED` with `revision_round` at 0 and `review_note`
    null, and two fields are derived on the spot."
    PRD §3.3: "`TAKE_UP` moves the entry `SUBMITTED` → `UNDER_REVIEW` and requires the
    target event to be `OPEN` or `UNDERSUBSCRIBED`."
    PRD §3.3: "`REQUEST_REVISION` moves it `UNDER_REVIEW` → `REVISION_REQUESTED` and
    stores the `review_note`, but only while the entry's `revision_round` is still below
    the two-round revision budget; a third request is refused with
    `ERR_REVISION_LIMIT_REACHED`."
    PRD §3.3: "An `Athlete` answering a revision request resubmits with a corrected
    `qualification_source` and, where the new source demands it, a
    `qualifying_result_id`; the entry moves `REVISION_REQUESTED` → `SUBMITTED`, the two
    supplied fields overwrite what was there, `qualification_priority` and
    `qualifying_mark` are recomputed from the new source and citation, and
    `revision_round` is incremented by one."

    The cycle `SUBMITTED` → `UNDER_REVIEW` → `REVISION_REQUESTED` →
    `SUBMITTED` closes on the athlete's resubmission, which returns the entry to
    `SUBMITTED` and increments `revision_round` to 1.

    Design: Difficulty/non_linear_state_machine/sport_entry_revision_cycle_allows_two_loops_then_blocks
    """
    ctx = _submitted_entry()

    resubmitted = _revise_once(
        ctx["entry"]["id"], ctx["athlete"]["id"], "Attach a sanctioned qualifying mark."
    )

    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_round"] == 1


def test_the_revision_loop_may_be_travelled_a_second_time():
    """PRD §3.3: "An `Athlete` answering a revision request resubmits with a corrected
    `qualification_source` and, where the new source demands it, a
    `qualifying_result_id`; the entry moves `REVISION_REQUESTED` → `SUBMITTED`, the two
    supplied fields overwrite what was there, `qualification_priority` and
    `qualifying_mark` are recomputed from the new source and citation, and
    `revision_round` is incremented by one."
    PRD §3.3: "Resubmission requires `revision_round` still below the budget of two — a
    third resubmission is likewise refused with `ERR_REVISION_LIMIT_REACHED` — and
    requires the logical clock strictly before `registration_deadline_utc`."
    PRD §3.3: "The whole loop `SUBMITTED` → `UNDER_REVIEW` → `REVISION_REQUESTED` →
    `SUBMITTED` may therefore run at most twice before the entry has to be decided on
    its merits."

    The budget is two rounds, so a second full turn is admissible and carries
    `revision_round` to 2 with the entry back at `SUBMITTED`.

    Design: Difficulty/non_linear_state_machine/sport_entry_revision_cycle_allows_two_loops_then_blocks
    """
    ctx = _submitted_entry()
    _revise_once(ctx["entry"]["id"], ctx["athlete"]["id"], "Attach a sanctioned mark.")

    resubmitted = _revise_once(
        ctx["entry"]["id"], ctx["athlete"]["id"], "Second pass: gender division mismatch."
    )

    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_round"] == 2


def test_a_third_revision_request_is_refused_and_applies_no_transition():
    """PRD §3.3: "`TAKE_UP` moves the entry `SUBMITTED` → `UNDER_REVIEW` and requires the
    target event to be `OPEN` or `UNDERSUBSCRIBED`."
    PRD §3.3: "`REQUEST_REVISION` moves it `UNDER_REVIEW` → `REVISION_REQUESTED` and
    stores the `review_note`, but only while the entry's `revision_round` is still below
    the two-round revision budget; a third request is refused with
    `ERR_REVISION_LIMIT_REACHED`."
    PRD §3.3: "The whole loop `SUBMITTED` → `UNDER_REVIEW` → `REVISION_REQUESTED` →
    `SUBMITTED` may therefore run at most twice before the entry has to be decided on
    its merits."
    PRD §2.10: "The entry's revision budget is not exhausted — otherwise
    `ERR_REVISION_LIMIT_REACHED` (HTTP 422)."

    With `revision_round` already at the budget of 2, a third
    `REQUEST_REVISION` is refused.  The entry is left in the `UNDER_REVIEW` it
    reached on the way in, and the counter does not move.

    Design: Difficulty/non_linear_state_machine/sport_entry_revision_cycle_allows_two_loops_then_blocks
    """
    ctx = _submitted_entry()
    _revise_once(ctx["entry"]["id"], ctx["athlete"]["id"], "First pass.")
    _revise_once(ctx["entry"]["id"], ctx["athlete"]["id"], "Second pass.")
    review_entry(ctx["entry"]["id"], "TAKE_UP")

    response = api_client.review_sport_entry(
        ctx["entry"]["id"],
        {"decision": "REQUEST_REVISION", "review_note": "Third pass attempt."},
        OFFICER,
    )

    validate_error(response, ApiErrorId.ERR_REVISION_LIMIT_REACHED.value, expected_status=422)
    entry = get_entry(ctx["entry"]["id"])
    assert entry["status"] == "UNDER_REVIEW"
    assert entry["revision_round"] == 2


def _entry_under_review_for_an_unpaid_athlete() -> dict:
    """An `UNDER_REVIEW` entry on an event with all eight slots free, whose
    athlete is cleared medically but has not yet paid."""
    ctx = _submitted_entry()
    screen_athlete(ctx["athlete"]["id"])
    review_entry(ctx["entry"]["id"], "TAKE_UP")
    assert get_athlete(ctx["athlete"]["id"])["medical_status"] == "SCREENED_CLEARED"
    return ctx


def test_acceptance_is_refused_while_the_athlete_row_is_still_unpaid():
    """PRD §3.3: "`ACCEPT` moves it `UNDER_REVIEW` → `ACCEPTED`, and is the transition that
    consumes capacity: it requires the athlete's `registration_status` to be
    `REGISTERED` — otherwise `ERR_ATHLETE_NOT_REGISTERED` — the athlete's
    `medical_status` to be one of `SCREENED_CLEARED`, `SCREENED_RESTRICTED` or
    `CLEARED_BY_APPEAL`, the event's `available_slots` to be greater than zero —
    otherwise `ERR_EVENT_CAPACITY_FULL` — and the athlete's already-scheduled
    competition blocks to still satisfy the recovery-gap rule described in §3.5."
    PRD §2.10: "The entering athlete's `registration_status` is `REGISTERED` when an
    entry is accepted — otherwise `ERR_ATHLETE_NOT_REGISTERED` (HTTP 409)."

    Acceptance reads the other row's dimension: the entry's own
    `UNDER_REVIEW` is a legal origin state and the event has free capacity, yet
    `ACCEPT` is refused because the athlete's `registration_status` is still
    `PENDING_PAYMENT`.  No capacity is consumed and the entry does not move.

    Design: Difficulty/cross_entity_state_dependency/entry_acceptance_requires_athlete_registration_dimension
    """
    ctx = _entry_under_review_for_an_unpaid_athlete()

    response = api_client.review_sport_entry(ctx["entry"]["id"], {"decision": "ACCEPT"}, OFFICER)

    validate_error(response, ApiErrorId.ERR_ATHLETE_NOT_REGISTERED.value, expected_status=409)
    assert get_entry(ctx["entry"]["id"])["status"] == "UNDER_REVIEW"
    event = get_event(ctx["event"]["id"])
    assert event["accepted_entry_count"] == 0
    assert event["available_slots"] == 8


def test_settling_the_fee_touches_only_the_athlete_row():
    """PRD §3.2: "**Step three** adds the base registration fee — ninety-five dollars, that
    is 9500 cents — to `event_fees_cents` to give `subtotal_cents`."
    PRD §3.2: "**Step four** picks the multi-event `discount_pct` from `entry_count`:
    zero for a single entry or none at all, five percent for two or three entries,
    twelve percent for four or five entries, and twenty percent for six or more;
    `discount_cents` is the subtotal multiplied by that percentage and rounded half up
    to whole cents, and this is the only rounding step in the whole settlement;
    `discounted_cents` is the subtotal less the discount."
    PRD §3.2: "On success the recomputed `fee_total_cents` and `fee_breakdown` are
    stored, `fee_paid_cents` is set equal to `fee_total_cents`, and the registration
    dimension advances `PENDING_PAYMENT` → `REGISTERED`."

    The remedy is applied to the athlete, not to the entry: paying the settled
    15500 cents flips `registration_status` to `REGISTERED` and leaves the entry
    exactly where it was.

    Design: Difficulty/cross_entity_state_dependency/entry_acceptance_requires_athlete_registration_dimension
    """
    ctx = _entry_under_review_for_an_unpaid_athlete()

    pay_fees(ctx["athlete"]["id"], 15500)

    athlete = get_athlete(ctx["athlete"]["id"])
    assert athlete["registration_status"] == "REGISTERED"
    assert athlete["fee_total_cents"] == 15500
    assert get_entry(ctx["entry"]["id"])["status"] == "UNDER_REVIEW"


def test_the_identical_acceptance_succeeds_once_the_athlete_is_registered():
    """PRD §3.3: "`ACCEPT` moves it `UNDER_REVIEW` → `ACCEPTED`, and is the transition that
    consumes capacity: it requires the athlete's `registration_status` to be
    `REGISTERED` — otherwise `ERR_ATHLETE_NOT_REGISTERED` — the athlete's
    `medical_status` to be one of `SCREENED_CLEARED`, `SCREENED_RESTRICTED` or
    `CLEARED_BY_APPEAL`, the event's `available_slots` to be greater than zero —
    otherwise `ERR_EVENT_CAPACITY_FULL` — and the athlete's already-scheduled
    competition blocks to still satisfy the recovery-gap rule described in §3.5."
    PRD §3.3: "On success it stores the `review_note`, increments the event's
    `accepted_entry_count` by one, decrements the event's `available_slots` by one, and
    lifts the event `UNDERSUBSCRIBED` → `OPEN` when the acceptance brings
    `accepted_entry_count` up to `min_entries_to_stage`."
    PRD §3.4: "A `CLEARED` recommendation moves the athlete `NOT_SCREENED` →
    `SCREENED_CLEARED` and touches nothing else; the athlete's entries stand as they
    are."

    With nothing changed but the other row's dimension, the same `ACCEPT`
    succeeds: the entry moves to `ACCEPTED`, `accepted_entry_count` rises to 1
    and `available_slots` falls to 7.

    Design: Difficulty/cross_entity_state_dependency/entry_acceptance_requires_athlete_registration_dimension
    """
    ctx = _entry_under_review_for_an_unpaid_athlete()
    pay_fees(ctx["athlete"]["id"], 15500)

    accepted = validate_success(
        api_client.review_sport_entry(ctx["entry"]["id"], {"decision": "ACCEPT"}, OFFICER)
    )

    assert accepted["status"] == "ACCEPTED"
    event = get_event(ctx["event"]["id"])
    assert event["accepted_entry_count"] == 1
    assert event["available_slots"] == 7
    assert get_athlete(ctx["athlete"]["id"])["medical_status"] == "SCREENED_CLEARED"
