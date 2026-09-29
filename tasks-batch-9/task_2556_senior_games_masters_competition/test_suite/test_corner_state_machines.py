"""Lifecycle breadth: declared origins, opening states, preconditions in their
declared order, terminal lockdown, non-idempotent actions and bubbled-up moves."""
from test_helpers import (
    ApiErrorId,
    CLOCK_EPOCH_UTC,
    TEST_USERS,
    api_client,
    advance_slot,
    create_accommodation_block,
    create_assignment,
    create_athlete,
    create_edition,
    create_entry,
    create_personnel,
    create_session_slot,
    create_sponsorship_commitment,
    create_sport,
    create_sport_event,
    create_venue,
    get_assignment,
    get_edition,
    get_entry,
    get_event,
    get_person,
    get_slot,
    make_athlete_headers,
    make_registration_officer_headers,
    open_registration,
    reserve_stay,
    seed_event,
    set_clock,
    setup_accepted_entry,
    setup_open_edition,
    setup_seeded_event_with_staffed_slot,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    REGISTRATION_OFFICER_USER_ID,
)

ADMIN = TEST_USERS["games_admin_headers"]
OFFICER = make_registration_officer_headers(REGISTRATION_OFFICER_USER_ID)


def test_seeding_stamps_the_logical_clock_and_leaves_the_capacity_ledger_alone():
    """PRD §3.1: "Once entries have accumulated, a `RegistrationOfficer` seeds an event,
    advancing it `OPEN` → `SEEDED` and stamping `seeded_at_utc` with the current logical
    clock."
    PRD §2.4: "On process startup that clock reads exactly `2026-08-01T00:00:00Z`, and
    until a harness moves it, that is the instant every rule sees; falling back to real
    time is a defect."
    PRD §2.5: "`version` is an integer that starts at 1 on creation and increments by
    one on every mutation of that row, including mutations the server performs on its
    own initiative as part of a cascade, and including mutations that only touch a
    derived counter such as `accepted_entry_count`, `confirmed_official_count`,
    `assigned_minutes_total`, `reserved_bed_nights` or `sponsorship_recognized_cents`."
    PRD §2.8: "`accepted_entry_count` and `available_slots` on a sport event always sum
    to `capacity`, and `available_slots` is never negative."

    The seed moves the event out of its open state, stamps the seeding instant from
    the server's logical clock rather than from wall time, and bumps the row's
    version — while the accepted count, the free seats and the entry itself are all
    untouched by the seeding.

    Design: Corner/state_machines/corner_state_machine_valid_transition_seed_open_to_seeded
    """
    ctx = setup_open_edition(event={"capacity": 8, "min_entries_to_stage": 1})
    pair = setup_accepted_entry(ctx["edition"]["id"], ctx["event"])
    before = get_event(ctx["event"]["id"])

    seeded = seed_event(ctx["event"]["id"])

    assert seeded["status"] == "SEEDED"
    assert seeded["seeded_at_utc"].startswith(CLOCK_EPOCH_UTC[:19])
    assert seeded["version"] == before["version"] + 1
    assert seeded["accepted_entry_count"] == 1
    assert seeded["available_slots"] == 7
    assert get_entry(pair["entry"]["id"])["status"] == "ACCEPTED"


def test_an_empty_candidate_set_is_reported_ahead_of_the_staging_shortfall():
    """PRD §3.1: "Seeding demands both that the event's `accepted_entry_count` has reached
    its `min_entries_to_stage` — a shortfall is refused with `ERR_MIN_ENTRIES_NOT_MET` —
    and that the set of entries on the event currently `ACCEPTED` is not empty, an empty
    set being refused with `ERR_NO_ELIGIBLE_ENTRIES`."
    PRD §2.10: "Seeding has at least one accepted entry to work from — otherwise
    `ERR_NO_ELIGIBLE_ENTRIES` (HTTP 422)."
    PRD §2.10: "Seeding meets the event's staging floor — otherwise
    `ERR_MIN_ENTRIES_NOT_MET` (HTTP 422)."
    PRD §2.10: "When a request violates several rules at once, exactly one error is
    returned, and which one is fully determined."

    An event whose only entry is still submitted breaks both seeding
    preconditions at once.  The emptiness of the accepted set is the earlier rule,
    so that is the answer, and the refused transition writes nothing at all.

    Design: Corner/state_machines/corner_state_machine_precondition_seed_with_no_accepted_entries_rejected
    """
    ctx = setup_open_edition(event={"capacity": 8, "min_entries_to_stage": 1})
    athlete = create_athlete(ctx["edition"]["id"], full_name="Ada Fenn")
    entry = create_entry(athlete["id"], ctx["event"]["id"])
    before = get_event(ctx["event"]["id"])

    response = api_client.seed_sport_event(ctx["event"]["id"], OFFICER)

    validate_error(
        response, ApiErrorId.ERR_NO_ELIGIBLE_ENTRIES.value, expected_status=422
    )
    after = get_event(ctx["event"]["id"])
    assert after["status"] == "OPEN"
    assert after["seeded_at_utc"] is None
    assert after["version"] == before["version"]
    assert get_entry(entry["id"])["status"] == "SUBMITTED"


def test_a_non_empty_but_short_candidate_set_reports_the_staging_shortfall_instead():
    """PRD §2.10: "Seeding meets the event's staging floor — otherwise
    `ERR_MIN_ENTRIES_NOT_MET` (HTTP 422)."
    PRD §2.10: "Seeding has at least one accepted entry to work from — otherwise
    `ERR_NO_ELIGIBLE_ENTRIES` (HTTP 422)."
    PRD §3.1: "Seeding demands both that the event's `accepted_entry_count` has reached
    its `min_entries_to_stage` — a shortfall is refused with `ERR_MIN_ENTRIES_NOT_MET` —
    and that the set of entries on the event currently `ACCEPTED` is not empty, an empty
    set being refused with `ERR_NO_ELIGIBLE_ENTRIES`."
    PRD §3.1: "Whenever an accepted entry leaves the `ACCEPTED` state and the resulting
    `accepted_entry_count` falls below `min_entries_to_stage`, the event moves to
    `UNDERSUBSCRIBED` — from `OPEN` as `OPEN` → `UNDERSUBSCRIBED`, and from `SEEDED` as
    `SEEDED` → `UNDERSUBSCRIBED`."

    With one accepted entry against a floor of three the earlier rule is satisfied,
    so the later one fires: the two preconditions are separately observable rather
    than collapsed into a single error.  A refused seed never drives the event
    undersubscribed, because that state is only reachable by losing an acceptance.

    Design: Corner/state_machines/corner_state_machine_precondition_seed_below_min_entries_rejected
    """
    ctx = setup_open_edition(event={"capacity": 8, "min_entries_to_stage": 3})
    setup_accepted_entry(ctx["edition"]["id"], ctx["event"])

    response = api_client.seed_sport_event(ctx["event"]["id"], OFFICER)

    validate_error(
        response, ApiErrorId.ERR_MIN_ENTRIES_NOT_MET.value, expected_status=422
    )
    event = get_event(ctx["event"]["id"])
    assert event["accepted_entry_count"] == 1
    assert event["min_entries_to_stage"] == 3
    assert event["status"] == "OPEN"


def test_every_stateful_resource_opens_in_its_declared_state():
    """PRD §2.5: "Every resource that has a lifecycle also exposes a `status` field naming
    the state it currently occupies, and the corresponding list read may be narrowed by
    a `status` filter; the athlete is the one exception, splitting its lifecycle across
    two separately named dimensions instead of a single `status`."
    PRD §3.1: "A newly created edition is `DRAFT`, its `ops_epoch` counter reads 0, both
    `sponsorship_recognized_cents` and `provisional_impact_cents` read 0, and
    `final_impact_cents` is null."
    PRD §3.1: "A fresh event is `OPEN`, with `accepted_entry_count` at 0,
    `available_slots` equal to its `capacity`, `current_record_id` null and
    `seeded_at_utc` null."
    PRD §3.5: "Venues start `OPEN` with `closed_reason` null; `CLOSED` is terminal."
    PRD §3.5: "A new slot is `SCHEDULED` with `confirmed_official_count` at 0."
    PRD §3.2: "`registration_status` tracks the commercial and attendance dimension and
    starts at `PENDING_PAYMENT`, with `REGISTERED`, `CHECKED_IN`, `WITHDRAWN` and
    `EXPIRED` as its other values and the last two terminal."
    PRD §3.2: "`medical_status` tracks the clinical dimension and starts at
    `NOT_SCREENED`, with `SCREENED_CLEARED`, `SCREENED_RESTRICTED`, `SCREENED_HOLD` and
    `CLEARED_BY_APPEAL` as its other values and none of them terminal."
    PRD §3.3: "Entries begin `SUBMITTED` with `revision_round` at 0 and `review_note`
    null, and two fields are derived on the spot."
    PRD §3.9: "It opens `PLEDGED` with `recognized_cents` at zero and an empty
    `allocation_map`."

    One pass over the whole catalogue, including the athlete's two independent
    dimensions, which are both set at creation: the commercial dimension awaiting
    payment and the clinical one unscreened, neither derived from the other.

    Design: Corner/state_machines/corner_state_machine_initial_state_every_entity_starts_in_its_declared_state
    """
    edition = create_edition()
    sport = create_sport()
    event = create_sport_event(sport["id"], edition["id"], min_entries_to_stage=1)
    venue = create_venue(edition["id"], competition_area_count=4)
    slot = create_session_slot(
        venue["id"], event["id"], teardown_buffer_minutes=0, required_official_count=1
    )
    person = create_personnel(
        edition["id"], certification_level=3, certified_sport_codes=[sport["sport_code"]]
    )
    assignment = create_assignment(person["id"], slot["id"])
    open_registration(edition["id"])
    athlete = create_athlete(edition["id"], full_name="Ada Fenn")
    entry = create_entry(athlete["id"], event["id"])
    block = create_accommodation_block(edition["id"], bed_capacity=4)
    stay = reserve_stay(
        athlete["id"], block["id"],
        check_in_date="2026-09-09", check_out_date="2026-09-14",
    )
    commitment = create_sponsorship_commitment(
        edition["id"], sponsor_name="Prairie Mutual", tier="BRONZE", pledged_cents=120000
    )

    assert edition["status"] == "DRAFT"
    assert event["status"] == "OPEN"
    assert venue["status"] == "OPEN"
    assert slot["status"] == "SCHEDULED"
    assert assignment["status"] == "ASSIGNED"
    assert athlete["registration_status"] == "PENDING_PAYMENT"
    assert athlete["medical_status"] == "NOT_SCREENED"
    assert entry["status"] == "SUBMITTED"
    assert stay["status"] == "RESERVED"
    assert commitment["status"] == "PLEDGED"


def test_a_withdrawn_entry_refuses_resubmission_review_and_a_second_withdrawal():
    """PRD §2.10: "The target row is not already sitting in a terminal state of its own
    machine — otherwise `ERR_ALREADY_TERMINAL` (HTTP 409)."
    PRD §2.10: "The terminal states for this purpose are `REJECTED` and `WITHDRAWN` on a
    sport entry, `VOIDED` on a competition result, `REJECTED` and `SUPERSEDED` on an
    age-group record, `COMPLETED` and `CANCELLED` on a village stay, `WITHDRAWN` and
    `EXPIRED` on an athlete's registration dimension, and `WITHDRAWN` on a sponsorship
    commitment."
    PRD §2.10: "The target row's own current status is a declared origin state of the
    requested transition — otherwise `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."
    PRD §3.3: "From the four states that hold no capacity the move to `WITHDRAWN` is
    bookkeeping only."
    PRD §2.8: "`accepted_entry_count` and `available_slots` on a sport event always sum
    to `capacity`, and `available_slots` is never negative."

    Withdrawal is terminal for an entry: all three follow-up commands are refused
    with a conflict, none of them writes, and the event's capacity ledger was
    never involved because the entry had held no seat.  The PRD names the
    terminal-state check one rung below the origin-state check, so either conflict
    is an admissible reading of the refusal; what is pinned is that every one of
    the three is refused and that nothing moves.

    Design: Corner/state_machines/corner_state_machine_terminal_withdrawn_entry_cannot_resubmit
    """
    ctx = setup_open_edition(event={"capacity": 8, "min_entries_to_stage": 1})
    athlete = create_athlete(ctx["edition"]["id"], full_name="Ada Fenn")
    entry = create_entry(athlete["id"], ctx["event"]["id"])
    withdrawn = validate_success(
        api_client.withdraw_sport_entry(entry["id"], OFFICER, {"reason": "travel plans changed"})
    )

    resubmit = api_client.resubmit_sport_entry(
        entry["id"], {"qualification_source": "ORGANIZER_INVITE"},
        make_athlete_headers(athlete["id"]),
    )
    review = api_client.review_sport_entry(entry["id"], {"decision": "TAKE_UP"}, OFFICER)
    second_withdraw = api_client.withdraw_sport_entry(
        entry["id"], OFFICER, {"reason": "second attempt"}
    )

    for response in (resubmit, review, second_withdraw):
        assert response.status_code == 409
        validate_error_is_one_of(
            response,
            [
                ApiErrorId.ERR_ALREADY_TERMINAL.value,
                ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
            ],
        )
    after = get_entry(entry["id"])
    assert after["status"] == "WITHDRAWN"
    assert after["version"] == withdrawn["version"]
    event = get_event(ctx["event"]["id"])
    assert event["accepted_entry_count"] == 0
    assert event["available_slots"] == 8


def test_opening_registration_twice_is_refused_rather_than_silently_repeated():
    """PRD §3.1: "With at least one `OPEN` event in place, a `GamesAdmin` may open
    registration, moving the edition `DRAFT` → `REGISTRATION_OPEN`."
    PRD §3.1: "The transition requires all three of: the edition currently `DRAFT`, at
    least one sport event belonging to that edition currently `OPEN`, and a logical
    clock strictly before `registration_deadline_utc` — a clock already at or past the
    deadline is refused with `ERR_REGISTRATION_DEADLINE_PASSED`."
    PRD §2.10: "The target row's own current status is a declared origin state of the
    requested transition — otherwise `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."
    PRD §3.9: "`DRAFT` is never advanced by a checkpoint run at all — only the explicit
    act of opening registration moves an edition out of `DRAFT`."
    PRD §2.5: "`version` is an integer that starts at 1 on creation and increments by
    one on every mutation of that row, including mutations the server performs on its
    own initiative as part of a cascade, and including mutations that only touch a
    derived counter such as `accepted_entry_count`, `confirmed_official_count`,
    `assigned_minutes_total`, `reserved_bed_nights` or `sponsorship_recognized_cents`."

    The action is not idempotent: the first call advances the edition and bumps its
    version, and the second is refused on its origin state without bumping anything,
    so a duplicated request cannot re-run the transition.  Nor does opening
    registration touch the checkpoint epoch, which is a different mechanism.

    Design: Corner/state_machines/corner_state_machine_idempotency_second_open_registration_rejected
    """
    edition = create_edition()
    sport = create_sport()
    create_sport_event(sport["id"], edition["id"], min_entries_to_stage=1)

    first = validate_success(api_client.open_registration(edition["id"], ADMIN))
    second = api_client.open_registration(edition["id"], ADMIN)

    assert first["status"] == "REGISTRATION_OPEN"
    assert first["version"] == edition["version"] + 1
    validate_error(
        second, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409
    )
    after = get_edition(edition["id"])
    assert after["version"] == first["version"]
    assert after["ops_epoch"] == 0


def test_cancellation_is_reachable_only_from_the_undersubscribed_state():
    """PRD §3.1: "Cancellation is available only from the undersubscribed state."
    PRD §3.1: "A `GamesAdmin` supplying a `reason` moves the event `UNDERSUBSCRIBED` →
    `CANCELLED`, which withdraws every entry on that event still sitting in `SUBMITTED`,
    `UNDER_REVIEW`, `REVISION_REQUESTED`, `ACCEPTED`, `WAITLISTED` or `MEDICAL_HOLD`,
    and resets the event's capacity accounting outright — `accepted_entry_count` back to
    0 and `available_slots` back to the full `capacity`."
    PRD §2.10: "The target row's own current status is a declared origin state of the
    requested transition — otherwise `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."
    PRD §2.10: "This applies to every action endpoint, that is, every operation that
    opens registration, runs the operations checkpoint, seeds, cancels, closes,
    reschedules, advances, pays fees, checks in, withdraws, hears a medical appeal,
    reviews, resubmits, confirms, releases, verifies, publishes, protests, resolves a
    protest, ratifies, allocates or finalizes impact."

    Neither an open event nor a seeded one may be scrapped directly, so an
    organiser cannot skip the undersubscription path.  Both refusals leave the
    events where they stood, the accepted entry in place and the seeded event's
    capacity accounting unreset.

    Design: Corner/state_machines/corner_state_machine_invalid_transition_cancel_open_event_rejected
    """
    ctx = setup_open_edition(event={"capacity": 8, "min_entries_to_stage": 1})
    open_event = ctx["event"]
    seeded_event = create_sport_event(
        ctx["sport"]["id"], ctx["edition"]["id"], event_code="T200M", capacity=8,
        min_entries_to_stage=1,
    )
    pair = setup_accepted_entry(ctx["edition"]["id"], seeded_event)
    seed_event(seeded_event["id"])

    cancel_open = api_client.cancel_sport_event(
        open_event["id"], {"reason": "no entries received"}, ADMIN
    )
    cancel_seeded = api_client.cancel_sport_event(
        seeded_event["id"], {"reason": "venue lost"}, ADMIN
    )

    for response in (cancel_open, cancel_seeded):
        validate_error(
            response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409
        )
    assert get_event(open_event["id"])["status"] == "OPEN"
    after = get_event(seeded_event["id"])
    assert after["status"] == "SEEDED"
    assert after["accepted_entry_count"] == 1
    assert after["available_slots"] == 7
    assert get_entry(pair["entry"]["id"])["status"] == "ACCEPTED"


def test_advancing_the_only_block_of_an_event_bubbles_two_levels_up_each_time():
    """PRD §3.5: "Starting a block moves it `SCHEDULED` → `IN_PROGRESS` and requires the
    slot's venue to be `OPEN`, the slot's sport event to be `SEEDED` or `IN_PROGRESS`,
    the slot's `confirmed_official_count` to have reached its `required_official_count`,
    and the logical clock to be at or past the slot's `start_utc`."
    PRD §3.5: "On success the slot's event follows it `SEEDED` → `IN_PROGRESS` if it was
    still merely seeded."
    PRD §3.5: "Closing a block moves it `IN_PROGRESS` → `COMPLETED` and settles that
    block's staffing: every personnel assignment on the slot that was `CONFIRMED` moves
    `CONFIRMED` → `COMPLETED`, and every assignment that was still merely `ASSIGNED`
    moves `ASSIGNED` → `NO_SHOW`, each no-show incrementing that person's
    `no_show_count` by one and decrementing their `assigned_minutes_total` by the
    assignment's `duration_minutes`."
    PRD §3.5: "Closing the block also closes its event `IN_PROGRESS` → `COMPLETED` when
    no sibling slot of that event remains `SCHEDULED`, `IN_PROGRESS` or `DISPLACED`."
    PRD §3.6: "When a block closes normally, a `CONFIRMED` assignment moves to
    `COMPLETED` and the person's `assigned_minutes_total` is deliberately left alone,
    because completed service still counts as minutes served; an assignment still
    sitting at `ASSIGNED` when the block closes moves to `NO_SHOW`, which raises
    `no_show_count` by one and debits `assigned_minutes_total` by that assignment's
    `duration_minutes`, since minutes that were never worked should not appear on the
    ledger."

    Starting the block drags its event out of the seeded state in the same request;
    closing the block drags the event to its terminal state, because no sibling
    block remains live, and carries the confirmed assignment to completed by
    cascade.  Completed service keeps its minutes on the ledger — unlike a release
    or a no-show — and the seeding stamp survives both moves.

    Design: Corner/state_machines/corner_state_machine_bubble_up_slot_completion_drives_event_and_assignment
    """
    ctx = setup_seeded_event_with_staffed_slot(
        event_overrides={"capacity": 8, "min_entries_to_stage": 1},
        venue_overrides={"competition_area_count": 4},
        slot_overrides={"teardown_buffer_minutes": 0, "required_official_count": 1},
    )
    assignment = get_assignment(ctx["assignment"]["id"])
    assert assignment["duration_minutes"] == 60
    assert assignment["status"] == "CONFIRMED"
    assert get_slot(ctx["slot"]["id"])["confirmed_official_count"] == 1
    set_clock("2026-09-12T09:00:00Z")

    started = advance_slot(ctx["slot"]["id"], "IN_PROGRESS")
    event_running = get_event(ctx["event"]["id"])
    finished = advance_slot(ctx["slot"]["id"], "COMPLETED")
    event_closed = get_event(ctx["event"]["id"])

    assert started["status"] == "IN_PROGRESS"
    assert event_running["status"] == "IN_PROGRESS"
    assert finished["status"] == "COMPLETED"
    assert event_closed["status"] == "COMPLETED"
    assert get_assignment(ctx["assignment"]["id"])["status"] == "COMPLETED"
    person = get_person(ctx["official"]["id"])
    assert person["assigned_minutes_total"] == 60
    assert person["no_show_count"] == 0
    assert event_closed["accepted_entry_count"] == 1
    assert event_closed["seeded_at_utc"] is not None
