"""Reserving a slot: pricing, the guards that run before it, and confirmation."""

from test_helpers import (
    ApiErrorId,
    create_active_participant,
    create_event,
    create_participant,
    create_registration,
    create_registration_payload,
    make_participant_headers,
    set_clock,
    setup_full_event_with_reservation,
    setup_participant_at_credit,
    setup_participant_at_credit_with_match,
    setup_published_campaign,
    setup_two_published_campaigns,
    validate_error,
    validate_success,
)


def test_early_bird_discount_does_not_apply_at_the_exact_cutoff_instant(api):
    """PRD §3.3: "If the current logical-clock instant is **strictly earlier** than
    the event's `early_bird_ends_at`, the fundraiser earns the early-bird discount of
    20 percent: the discount is the event's `registration_fee_cents` multiplied by 20
    percent, rounded half up to whole cents, and `fee_charged_cents` is
    `registration_fee_cents` reduced by that rounded discount."
    PRD §3.3: "At exactly the `early_bird_ends_at` instant the discount does **not**
    apply."

    Design: Corner/calculations/early_bird_discount_not_applied_at_exact_cutoff_instant
    """
    ctx = setup_published_campaign(api=api, fundraising_minimum_cents=0)
    event = create_event(ctx["campaign_id"], ctx["cm_headers"], api=api)
    participant = create_active_participant(ctx["campaign_id"], api=api)
    headers = make_participant_headers(participant["id"])
    set_clock("2026-08-01T00:00:00Z", api=api)

    response = api.create_registration(
        create_registration_payload(participant["id"], event["id"]), headers
    )

    registration = validate_success(response, expected_status=201)
    assert registration["fee_charged_cents"] == 4000, "Undiscounted at the cutoff"
    assert registration["status"] == "RESERVED"


def test_a_second_registration_for_the_same_event_is_rejected(api, anonymous_headers):
    """PRD §3.3: "Next, a fundraiser may hold at most one registration in `RESERVED`,
    `CONFIRMED` or `CHECKED_IN` for the same event; a second attempt is rejected with
    `ERR_DUPLICATE_REGISTRATION`."

    Design: Corner/validations/duplicate_registration_for_same_event_rejected
    """
    ctx = setup_full_event_with_reservation(api=api, capacity=10)

    response = api.create_registration(
        create_registration_payload(ctx["participant_id"], ctx["event_id"]),
        ctx["participant_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_DUPLICATE_REGISTRATION.value, expected_status=409
    )
    event = validate_success(api.get_event(ctx["event_id"], anonymous_headers))
    assert event["registered_count"] == 1


def test_registration_beyond_capacity_is_rejected(api, anonymous_headers):
    """PRD §3.3: "Finally, the event's `registered_count` must be strictly below
    `capacity` at the moment of persistence, or `ERR_EVENT_AT_CAPACITY` applies."
    PRD §3.3: "the moment a registration is persisted that brings `registered_count`
    up to `capacity`, the event transitions `OPEN → FULL`, and further registration
    attempts are rejected with `ERR_EVENT_AT_CAPACITY`"

    Design: Corner/validations/event_at_capacity_rejects_second_registration
    """
    ctx = setup_full_event_with_reservation(api=api, capacity=1)
    second = create_active_participant(ctx["campaign_id"], api=api, display_name="Ben Ortiz")

    response = api.create_registration(
        create_registration_payload(second["id"], ctx["event_id"]),
        make_participant_headers(second["id"]),
    )

    validate_error(response, ApiErrorId.ERR_EVENT_AT_CAPACITY.value, expected_status=422)
    event = validate_success(api.get_event(ctx["event_id"], anonymous_headers))
    assert event["registered_count"] == 1
    assert event["status"] == "FULL"


def test_checking_in_before_the_event_starts_is_rejected(api, anonymous_headers):
    """PRD §3.3: "The registration must be `CONFIRMED`, the fundraiser's page must be
    `ACTIVE`, and the current logical-clock instant must be at or after the event's
    `starts_at` — checking in before the gun is not permitted."
    PRD §2.8: "**State admissibility** — the target is in a state that admits the
    requested transition, otherwise `ERR_INVALID_STATE` (HTTP 409), except on the
    refund path where the dedicated code `ERR_DONATION_NOT_REFUNDABLE` (HTTP 409) is
    returned instead."

    Design: Corner/state_machines/registration_check_in_before_event_start_rejected
    """
    ctx = setup_full_event_with_reservation(api=api, capacity=10)
    validate_success(
        api.confirm_registration(ctx["registration_id"], ctx["participant_headers"])
    )

    response = api.check_in_registration(ctx["registration_id"], ctx["cm_headers"])

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
    registration = validate_success(
        api.get_registration(ctx["registration_id"], anonymous_headers)
    )
    assert registration["status"] == "CONFIRMED"


def test_confirming_while_the_page_is_still_pending_is_rejected(api, anonymous_headers):
    """PRD §3.3: "It requires the registration to be `RESERVED`, the fundraiser's page
    to be `ACTIVE` (otherwise `ERR_PARTICIPANT_NOT_ACTIVE`), the event to be `OPEN` or
    `FULL` — a full event still admits confirmations of slots already reserved — and
    the fundraising gate to pass."

    Design: Corner/validations/confirm_while_participant_pending_rejected
    """
    ctx = setup_published_campaign(api=api, fundraising_minimum_cents=0)
    event = create_event(ctx["campaign_id"], ctx["cm_headers"], api=api)
    participant = create_participant(ctx["campaign_id"], api=api)
    headers = make_participant_headers(participant["id"])
    registration = create_registration(participant["id"], event["id"], headers, api=api)

    response = api.confirm_registration(registration["id"], headers)

    validate_error(
        response, ApiErrorId.ERR_PARTICIPANT_NOT_ACTIVE.value, expected_status=409
    )
    unchanged = validate_success(
        api.get_registration(registration["id"], anonymous_headers)
    )
    assert unchanged["status"] == "RESERVED"


def test_a_waived_minimum_confirms_a_fundraiser_with_no_credit(api, anonymous_headers):
    """PRD §3.3: "That gate is satisfied when the registration's `minimum_waived` is
    true, **or** when the fundraiser's `credited_cents` is greater than or equal to
    the campaign's `fundraising_minimum_cents`; exactly meeting the minimum passes."

    Design: Corner/validations/minimum_waived_registration_confirms_without_credit
    """
    ctx = setup_published_campaign(api=api, fundraising_minimum_cents=15000)
    event = create_event(ctx["campaign_id"], ctx["cm_headers"], api=api)
    participant = create_active_participant(ctx["campaign_id"], api=api)
    registration = create_registration(
        participant["id"], event["id"], ctx["cm_headers"], api=api, minimum_waived=True
    )

    confirmed = validate_success(
        api.confirm_registration(registration["id"], ctx["cm_headers"])
    )

    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["minimum_waived"] is True
    assert confirmed["fee_charged_cents"] == 3200, "4000 less a 20 percent early bird"
    page = validate_success(api.get_participant(participant["id"], anonymous_headers))
    assert page["credited_cents"] == 0


def test_credit_one_cent_short_of_the_minimum_blocks_confirmation(api, anonymous_headers):
    """PRD §3.3: "A confirmation that fails the gate is rejected with
    `ERR_FUNDRAISING_MINIMUM_NOT_MET`."
    PRD §3.6: "Alongside it, `minimum_met` is true exactly when `credited_cents` is
    greater than or equal to the campaign's `fundraising_minimum_cents`, and false
    otherwise."

    Design: Corner/validations/fundraising_minimum_one_cent_short_rejected
    """
    ctx = setup_participant_at_credit(
        14999, api=api, fundraising_minimum_cents=15000, with_event=True
    )
    registration = create_registration(
        ctx["participant_id"], ctx["event_id"], ctx["participant_headers"], api=api
    )

    response = api.confirm_registration(registration["id"], ctx["participant_headers"])

    validate_error(
        response, ApiErrorId.ERR_FUNDRAISING_MINIMUM_NOT_MET.value, expected_status=422
    )
    page = validate_success(api.get_participant(ctx["participant_id"], anonymous_headers))
    assert page["credited_cents"] == 14999
    assert page["minimum_met"] is False
    unchanged = validate_success(
        api.get_registration(registration["id"], anonymous_headers)
    )
    assert unchanged["status"] == "RESERVED"


def test_credit_exactly_at_the_minimum_marks_the_page_as_meeting_it(api, anonymous_headers):
    """PRD §3.6: "Alongside it, `minimum_met` is true exactly when `credited_cents` is
    greater than or equal to the campaign's `fundraising_minimum_cents`, and false
    otherwise."
    PRD §3.6: "A fundraiser's `credited_cents` is the sum, across gifts whose
    `designation_type` is `PARTICIPANT`, whose `designation_id` names that fundraiser,
    and whose payment dimension reads `SETTLED`, of the gift's `amount_cents` added to
    its `matched_amount_cents`."

    Design: Difficulty/boundary_precision_check/fundraising_minimum_exactly_met_confirms_registration
    """
    ctx = setup_participant_at_credit_with_match(api=api, fundraising_minimum_cents=15000)

    page = validate_success(api.get_participant(ctx["participant_id"], anonymous_headers))

    assert page["credited_cents"] == 15000, "10000 gift plus a 5000 sponsor match"
    assert page["minimum_met"] is True


def test_credit_exactly_at_the_minimum_admits_confirmation(api):
    """PRD §3.3: "That gate is satisfied when the registration's `minimum_waived` is
    true, **or** when the fundraiser's `credited_cents` is greater than or equal to
    the campaign's `fundraising_minimum_cents`; exactly meeting the minimum passes."
    PRD §3.3: "Success stamps `confirmed_at` with the current logical-clock instant."

    Design: Difficulty/boundary_precision_check/fundraising_minimum_exactly_met_confirms_registration
    """
    ctx = setup_participant_at_credit_with_match(api=api, fundraising_minimum_cents=15000)
    registration = create_registration(
        ctx["participant_id"], ctx["event_id"], ctx["participant_headers"], api=api
    )

    confirmed = validate_success(
        api.confirm_registration(registration["id"], ctx["participant_headers"])
    )

    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["fee_charged_cents"] == 3200
    assert confirmed["confirmed_at"] is not None


def test_buffered_windows_that_merely_touch_are_a_conflict(api):
    """PRD §3.3: "the system widens that registration's event window by 90 minutes on
    each side — from 90 minutes before `starts_at` through 90 minutes after `ends_at`
    — and rejects the new reservation with `ERR_REGISTRATION_TIME_CONFLICT` if the new
    event's identically widened window intersects it."
    PRD §3.3: "Both ends of these buffered windows are inclusive, so two events whose
    buffered windows merely touch at a single instant are still a conflict."

    Design: Difficulty/resource_temporal_overlap/registration_buffered_closed_windows_touching_is_a_conflict
    """
    ctx = setup_published_campaign(api=api)
    event_a = create_event(
        ctx["campaign_id"], ctx["cm_headers"], api=api, name="Morning Walk",
        starts_at="2026-09-12T14:00:00Z", ends_at="2026-09-12T16:00:00Z",
    )
    event_b = create_event(
        ctx["campaign_id"], ctx["cm_headers"], api=api, name="Evening Run",
        starts_at="2026-09-12T19:00:00Z", ends_at="2026-09-12T21:00:00Z",
    )
    participant = create_active_participant(ctx["campaign_id"], api=api)
    headers = make_participant_headers(participant["id"])
    create_registration(participant["id"], event_a["id"], headers, api=api)

    response = api.create_registration(
        create_registration_payload(participant["id"], event_b["id"]), headers
    )

    validate_error(
        response, ApiErrorId.ERR_REGISTRATION_TIME_CONFLICT.value, expected_status=409
    )


def test_the_rejected_touching_registration_leaves_both_events_untouched(api, anonymous_headers):
    """PRD §3.3: "Both ends of these buffered windows are inclusive, so two events
    whose buffered windows merely touch at a single instant are still a conflict."
    PRD §2.11: "An event's `registered_count` is the number of that event's
    registrations sitting in `RESERVED`, `CONFIRMED` or `CHECKED_IN`, and the event's
    `status` flips between `OPEN` and `FULL` purely as a function of that count against
    `capacity`."

    Design: Difficulty/resource_temporal_overlap/registration_buffered_closed_windows_touching_is_a_conflict
    """
    ctx = setup_published_campaign(api=api)
    event_a = create_event(
        ctx["campaign_id"], ctx["cm_headers"], api=api, name="Morning Walk",
        starts_at="2026-09-12T14:00:00Z", ends_at="2026-09-12T16:00:00Z",
    )
    event_b = create_event(
        ctx["campaign_id"], ctx["cm_headers"], api=api, name="Evening Run",
        starts_at="2026-09-12T19:00:00Z", ends_at="2026-09-12T21:00:00Z",
    )
    participant = create_active_participant(ctx["campaign_id"], api=api)
    headers = make_participant_headers(participant["id"])
    registration_a = create_registration(participant["id"], event_a["id"], headers, api=api)

    rejected = api.create_registration(
        create_registration_payload(participant["id"], event_b["id"]), headers
    )
    validate_error(
        rejected, ApiErrorId.ERR_REGISTRATION_TIME_CONFLICT.value, expected_status=409
    )

    second_event = validate_success(api.get_event(event_b["id"], anonymous_headers))
    assert second_event["registered_count"] == 0
    first_registration = validate_success(
        api.get_registration(registration_a["id"], anonymous_headers)
    )
    assert first_registration["status"] == "RESERVED"


def test_cross_campaign_event_outranks_the_capacity_complaint(api):
    """PRD §2.8: "7. **Cross-aggregate referential integrity** — the
    campaign-containment checks of §2.7."
    PRD §2.8: "12. **Event capacity** — `ERR_EVENT_AT_CAPACITY`."
    PRD §3.3: "The event must belong to the same campaign as the fundraiser, or
    `ERR_EVENT_CAMPAIGN_MISMATCH` is returned."

    Design: Difficulty/priority_pair_validation_conflict/registration_campaign_mismatch_beats_capacity_priority_conflict
    """
    ctx = setup_two_published_campaigns(api=api)
    event_b = create_event(
        ctx["campaign_b_id"], ctx["cm_headers"], api=api, name="B 5K Run", capacity=1
    )
    occupant = create_active_participant(ctx["campaign_b_id"], api=api, display_name="Bea Bravo")
    create_registration(
        occupant["id"], event_b["id"], make_participant_headers(occupant["id"]), api=api
    )
    outsider = create_active_participant(ctx["campaign_a_id"], api=api)

    response = api.create_registration(
        create_registration_payload(outsider["id"], event_b["id"]),
        make_participant_headers(outsider["id"]),
    )

    validate_error(
        response, ApiErrorId.ERR_EVENT_CAMPAIGN_MISMATCH.value, expected_status=422
    )


def test_the_outranked_capacity_check_leaves_the_full_event_untouched(api, anonymous_headers):
    """PRD §2.8: "When several rules could reject the same request, they are evaluated
    in a fixed order so that clients see the most fundamental problem first."
    PRD §3.3: "The event must belong to the same campaign as the fundraiser, or
    `ERR_EVENT_CAMPAIGN_MISMATCH` is returned."

    Design: Difficulty/priority_pair_validation_conflict/registration_campaign_mismatch_beats_capacity_priority_conflict
    """
    ctx = setup_two_published_campaigns(api=api)
    event_b = create_event(
        ctx["campaign_b_id"], ctx["cm_headers"], api=api, name="B 5K Run", capacity=1
    )
    occupant = create_active_participant(ctx["campaign_b_id"], api=api, display_name="Bea Bravo")
    create_registration(
        occupant["id"], event_b["id"], make_participant_headers(occupant["id"]), api=api
    )
    outsider = create_active_participant(ctx["campaign_a_id"], api=api)

    rejected = api.create_registration(
        create_registration_payload(outsider["id"], event_b["id"]),
        make_participant_headers(outsider["id"]),
    )
    validate_error(
        rejected, ApiErrorId.ERR_EVENT_CAMPAIGN_MISMATCH.value, expected_status=422
    )

    event = validate_success(api.get_event(event_b["id"], anonymous_headers))
    assert event["registered_count"] == 1, "The rejected request must not consume a slot"
