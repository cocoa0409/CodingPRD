"""Meeting spaces, cohort formation, the indirect-fee tier rule and the
room-occupation geometry."""

import pytest

from test_helpers import (
    IC,
    PD,
    ApiErrorId,
    UNUSED_UUIDS,
    api_client,
    assert_cohort,
    assert_meeting_space,
    create_cohort,
    create_cohort_payload,
    create_meeting_space,
    create_remembrance_event_payload,
    read_cohort,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_meeting_space_defaults_are_stored_when_the_optional_fields_are_omitted():
    """PRD 3.3: "A `ProgramDirector` registers one with a human-readable `name` and
    a `capacity` of at least one seated occupant. Two further attributes are
    optional: `turnover_buffer_minutes`, the cleaning and turnover time that must
    separate two occupations of the room, which defaults to 30 minutes and may be
    zero but never negative; and `accessibility_features`, a free-form array of
    tags that defaults to an empty array. A space is registered in status
    `AVAILABLE`."

    Design: Corner/entities/meeting_space_turnover_buffer_defaults_to_thirty_when_omitted
    """
    set_clock()
    data = validate_success(
        api_client.create_meeting_space({"name": "Quiet Room", "capacity": 12}, PD), 201)
    assert_meeting_space(data)
    assert data["turnover_buffer_minutes"] == 30, (
        f"Expected the declared default of 30, got {data['turnover_buffer_minutes']}")
    assert data["status"] == "AVAILABLE"
    assert data["accessibility_features"] == []


def test_cohort_formation_computes_series_end_date_and_opens_the_seat_pool():
    """PRD 3.3: "`series_end_date` is the date of the last session: it is
    `series_start_date` advanced by seven days for every session after the first,
    so a six-session series starting on a Tuesday ends on the Tuesday thirty-five
    days later."
    PRD 3.3: "A cohort is created in status `FORMING` with `seats_open` set to
    `seats_total` and both `seats_held` and `seats_filled` at zero."

    Design: Corner/entities/cohort_series_end_date_and_seat_counters_are_computed_at_creation
    """
    set_clock()
    space = create_meeting_space(name="Chapel Room", capacity=20,
                                 turnover_buffer_minutes=30)
    data = validate_success(
        api_client.create_cohort(
            create_cohort_payload(
                space["id"], name="Computed Fields Group", loss_type="PEDIATRIC",
                seats_total=6, min_viable_enrollment=2, weekday="TUE",
                start_minute_utc=600, duration_minutes=90,
                series_start_date="2026-09-08", sessions_total=8,
                direct_cost_cents=100_000),
            PD), 201)
    assert_cohort(data)
    assert data["series_end_date"] == "2026-10-27", (
        f"Expected 2026-10-27, got {data['series_end_date']}")
    assert data["seats_open"] == 6
    assert data["seats_held"] == 0
    assert data["seats_filled"] == 0
    assert data["admin_fee_cents"] == 12_000
    assert data["program_cost_total_cents"] == 112_000
    assert data["status"] == "FORMING"


def test_cohorts_can_be_filtered_by_meeting_space():
    """PRD 3.3: "Cohorts can be listed and filtered by `meeting_space_id`, by
    `status` or by `loss_type`."
    PRD 3.3: "Every cohort formation and every event planning request is therefore
    checked against the room's existing occupations, and a clash is refused with
    `ERR_SPACE_TIME_CONFLICT`."

    Design: Corner/entities/cohorts_filtered_list_by_meeting_space_id_returns_only_matching_rows
    """
    set_clock()
    space_a = create_meeting_space(name="Room A", capacity=20,
                                   turnover_buffer_minutes=30)
    space_b = create_meeting_space(name="Room B", capacity=20,
                                   turnover_buffer_minutes=30)
    cohort_a = create_cohort(space_a["id"], name="Group In A",
                             loss_type="ANTICIPATED_ILLNESS")
    # The identical weekday and minute block in a different room must not clash.
    cohort_b = validate_success(
        api_client.create_cohort(
            create_cohort_payload(space_b["id"], name="Group In B",
                                  loss_type="SUDDEN_DEATH"), PD), 201)
    assert cohort_b["meeting_space_id"] == space_b["id"]

    rows, meta = validate_paginated(
        api_client.list_cohorts(PD, params={"meeting_space_id": space_a["id"]}))
    assert meta["total_count"] == 1, (
        f"Expected 1 cohort in room A, got {meta['total_count']}")
    assert meta["has_more"] is False
    assert len(rows) == 1
    assert rows[0]["id"] == cohort_a["id"]


def test_cohort_naming_an_unknown_meeting_space_is_not_found():
    """PRD 2.5: "Every entity identifier named inside the request body resolves to
    an existing record — otherwise the corresponding not-found error (404). This
    rung guards enrollment creation, counselling-referral creation,
    counselling-referral assignment, companion-match creation, cohort creation,
    remembrance-event creation, invitation creation, funding-allocation creation
    and grant-report creation."

    Design: Corner/errors/cohort_create_with_unknown_meeting_space_returns_space_not_found
    """
    set_clock()
    validate_error(
        api_client.create_cohort(
            create_cohort_payload(UNUSED_UUIDS["space"], name="Orphan Group"), PD),
        ApiErrorId.ERR_SPACE_NOT_FOUND.value, 404)


def test_cohort_larger_than_the_room_is_refused():
    """PRD 3.3: "And the room must be big enough — a `seats_total` exceeding the
    room's `capacity` is refused with `ERR_SPACE_CAPACITY_EXCEEDED`."

    Design: Corner/validations/cohort_seats_total_above_space_capacity_returns_space_capacity_exceeded
    """
    set_clock()
    space = create_meeting_space(name="Small Room", capacity=5,
                                 turnover_buffer_minutes=30)
    validate_error(
        api_client.create_cohort(
            create_cohort_payload(space["id"], name="Too Big Group", seats_total=10,
                                  min_viable_enrollment=2), PD),
        ApiErrorId.ERR_SPACE_CAPACITY_EXCEEDED.value, 422)

    rows, meta = validate_paginated(
        api_client.list_cohorts(PD, params={"meeting_space_id": space["id"]}))
    assert meta["total_count"] == 0


def test_indirect_tier_is_selected_from_direct_cost_not_from_the_total():
    """PRD 3.3: "A direct cost below 250,000 cents — that is, below twenty-five
    hundred dollars — selects a rate of 1200 basis points; a direct cost of 250,000
    cents or more but below 750,000 cents selects 1000 basis points; a direct cost
    of 750,000 cents or more selects 800 basis points."
    PRD 3.3: "A direct cost of 240,000 cents therefore yields an admin fee of
    28,800 cents and a programme total of 268,800 cents; keying the tier off the
    total instead would drop the total into the second band and produce 26,880 and
    266,880, which is the wrong answer."

    Design: Difficulty/combinatorial_formula/program_cost_indirect_tier_keyed_on_direct_cost_not_on_total
    """
    set_clock()
    space = create_meeting_space(name="Chapel Room", capacity=20,
                                 turnover_buffer_minutes=30)
    cohort = validate_success(
        api_client.create_cohort(
            create_cohort_payload(
                space["id"], name="Tier Boundary Below",
                loss_type="ANTICIPATED_ILLNESS", weekday="TUE",
                series_start_date="2026-09-08", direct_cost_cents=240_000), PD), 201)

    assert cohort["admin_fee_cents"] == 28_800, (
        f"Expected 28800, got {cohort['admin_fee_cents']}")
    assert cohort["program_cost_total_cents"] == 268_800
    assert cohort["admin_fee_cents"] != 26_880, (
        "the band must not be keyed off the resulting programme total")
    assert cohort["program_cost_total_cents"] != 266_880
    assert cohort["series_end_date"] == "2026-10-27"


def test_direct_cost_at_the_band_boundary_sits_in_the_middle_band():
    """PRD 3.3: "Each band's lower boundary is inclusive and its upper boundary
    exclusive, so a direct cost of exactly 250,000 cents sits in the middle band at
    1000 basis points."
    PRD 3.3: "sets `program_cost_total_cents` to `direct_cost_cents` plus the
    `admin_fee_cents` computed in step two."

    Design: Difficulty/combinatorial_formula/program_cost_indirect_tier_keyed_on_direct_cost_not_on_total
    """
    set_clock()
    space = create_meeting_space(name="Chapel Room", capacity=20,
                                 turnover_buffer_minutes=30)
    cohort = validate_success(
        api_client.create_cohort(
            create_cohort_payload(
                space["id"], name="Tier Boundary At", loss_type="SUDDEN_DEATH",
                weekday="WED", series_start_date="2026-09-09",
                direct_cost_cents=250_000), PD), 201)

    assert cohort["admin_fee_cents"] == 25_000, (
        f"Expected 25000 at the inclusive band boundary, got {cohort['admin_fee_cents']}")
    assert cohort["program_cost_total_cents"] == 275_000


def test_a_gap_of_exactly_the_turnover_buffer_still_collides():
    """PRD 3.3: "Both comparisons are non-strict, which has a consequence worth
    stating plainly: a gap of *exactly* the buffer still counts as a collision, and
    the gap must be strictly greater than the buffer to be legal."
    PRD 3.3: "With a 30-minute buffer and an existing block running from minute 600
    to minute 690, an incoming occupation starting at minute 720 has an adjusted
    start of 690, which is not greater than 690, and therefore collides; the same
    occupation starting at minute 721 has an adjusted start of 691, which clears
    690, and is legal."

    Design: Difficulty/boundary_precision_check/space_turnover_gap_equal_to_buffer_collides_one_minute_later_does_not
    """
    set_clock()
    space = create_meeting_space(name="Chapel Room", capacity=20,
                                 turnover_buffer_minutes=30)
    create_cohort(space["id"], name="Tuesday Illness Group",
                  loss_type="ANTICIPATED_ILLNESS", weekday="TUE",
                  start_minute_utc=600, duration_minutes=90,
                  series_start_date="2026-09-08", sessions_total=8,
                  direct_cost_cents=240_000)

    validate_error(
        api_client.create_remembrance_event(
            create_remembrance_event_payload(
                space["id"], title="Exactly One Buffer Later",
                event_date="2026-10-06", start_minute_utc=720, duration_minutes=60,
                expected_attendance=15, direct_cost_cents=10_220), PD),
        ApiErrorId.ERR_SPACE_TIME_CONFLICT.value, 409)

    rows, meta = validate_paginated(
        api_client.list_remembrance_events(PD, params={"meeting_space_id": space["id"]}))
    assert meta["total_count"] == 0, "the colliding event must not be persisted"


def test_one_minute_past_the_turnover_buffer_is_accepted():
    """PRD 3.3: "With a 30-minute buffer and an existing block running from minute
    600 to minute 690, an incoming occupation starting at minute 720 has an
    adjusted start of 690, which is not greater than 690, and therefore collides;
    the same occupation starting at minute 721 has an adjusted start of 691, which
    clears 690, and is legal."
    PRD 3.7: "The identical three-step rule computes `admin_fee_cents` and
    `program_cost_total_cents` for a remembrance event from its own
    `direct_cost_cents`."

    Design: Difficulty/boundary_precision_check/space_turnover_gap_equal_to_buffer_collides_one_minute_later_does_not
    """
    set_clock()
    space = create_meeting_space(name="Chapel Room", capacity=20,
                                 turnover_buffer_minutes=30)
    create_cohort(space["id"], name="Tuesday Illness Group",
                  loss_type="ANTICIPATED_ILLNESS", weekday="TUE",
                  start_minute_utc=600, duration_minutes=90,
                  series_start_date="2026-09-08", sessions_total=8,
                  direct_cost_cents=240_000)

    event = validate_success(
        api_client.create_remembrance_event(
            create_remembrance_event_payload(
                space["id"], title="One Minute Past The Buffer",
                event_date="2026-10-06", start_minute_utc=721, duration_minutes=60,
                expected_attendance=15, direct_cost_cents=10_220), PD), 201)
    assert event["start_minute_utc"] == 721
    assert event["status"] == "PLANNED"
    assert event["program_cost_total_cents"] == 11_446

    rows, meta = validate_paginated(
        api_client.list_remembrance_events(PD, params={"meeting_space_id": space["id"]}))
    assert meta["total_count"] == 1


def test_two_cohort_series_on_the_same_weekday_with_overlapping_windows_collide():
    """PRD 3.3: "Two cohorts share dates when they run on the same `weekday` and
    their two date windows, each taken inclusively from series start to series end,
    overlap at all."
    PRD 3.3: "Both comparisons are non-strict, which has a consequence worth
    stating plainly: a gap of *exactly* the buffer still counts as a collision, and
    the gap must be strictly greater than the buffer to be legal."

    Design: Difficulty/resource_temporal_overlap/meeting_space_recurring_window_and_buffer_geometry_on_cohort_series
    """
    set_clock()
    space = create_meeting_space(name="Chapel Room", capacity=20,
                                 turnover_buffer_minutes=30)
    series_a = create_cohort(space["id"], name="Series A",
                             loss_type="ANTICIPATED_ILLNESS", weekday="TUE",
                             start_minute_utc=600, duration_minutes=90,
                             series_start_date="2026-09-08", sessions_total=8,
                             direct_cost_cents=240_000)
    assert series_a["series_end_date"] == "2026-10-27"

    validate_error(
        api_client.create_cohort(
            create_cohort_payload(
                space["id"], name="Series B Overlapping Window",
                loss_type="SUDDEN_DEATH", weekday="TUE", start_minute_utc=720,
                duration_minutes=60, series_start_date="2026-10-20",
                sessions_total=4, direct_cost_cents=100_000), PD),
        ApiErrorId.ERR_SPACE_TIME_CONFLICT.value, 409)


def test_a_disjoint_series_window_in_the_same_room_is_accepted():
    """PRD 3.3: "Two cohorts share dates when they run on the same `weekday` and
    their two date windows, each taken inclusively from series start to series end,
    overlap at all."
    PRD 3.3: "`series_end_date` is the date of the last session: it is
    `series_start_date` advanced by seven days for every session after the first,
    so a six-session series starting on a Tuesday ends on the Tuesday thirty-five
    days later."

    Design: Difficulty/resource_temporal_overlap/meeting_space_recurring_window_and_buffer_geometry_on_cohort_series
    """
    set_clock()
    space = create_meeting_space(name="Chapel Room", capacity=20,
                                 turnover_buffer_minutes=30)
    create_cohort(space["id"], name="Series A", loss_type="ANTICIPATED_ILLNESS",
                  weekday="TUE", start_minute_utc=600, duration_minutes=90,
                  series_start_date="2026-09-08", sessions_total=8,
                  direct_cost_cents=240_000)

    series_c = validate_success(
        api_client.create_cohort(
            create_cohort_payload(
                space["id"], name="Series C Disjoint Window",
                loss_type="SUDDEN_DEATH", weekday="TUE", start_minute_utc=720,
                duration_minutes=60, series_start_date="2026-11-03",
                sessions_total=4, direct_cost_cents=100_000), PD), 201)
    assert series_c["series_end_date"] == "2026-11-24"
    assert series_c["status"] == "FORMING"
    assert series_c["admin_fee_cents"] == 12_000
    assert series_c["program_cost_total_cents"] == 112_000

    rows, meta = validate_paginated(
        api_client.list_cohorts(PD, params={"meeting_space_id": space["id"]}))
    assert meta["total_count"] == 2


def test_space_time_conflict_is_reported_ahead_of_space_capacity_on_event_create():
    """PRD 2.5: "When a single request violates several rules at once, the response
    must carry the error of the *first* rule that fails, evaluated in the fixed
    order below."
    PRD 2.5: "The five temporal rules — `ERR_SPACE_TIME_CONFLICT` (409),
    `ERR_EVENT_DATE_IN_PAST` (422), `ERR_DECEASED_DATE_IN_FUTURE` (422),
    `ERR_OUTSIDE_GRANT_PERIOD` (422) and `ERR_RSVP_WINDOW_CLOSED` (409) — guard
    exactly six operations: cohort creation, remembrance-event creation, referral
    filing, funding-allocation creation, invitation sending and invitation
    responding."
    PRD 2.5: "The twelve constraint rules enumerated in §3.4, §3.5, §3.6, §3.7,
    §3.8 and §3.9. All of them report HTTP 409 except `ERR_SPACE_CAPACITY_EXCEEDED`
    and `ERR_ASSESSMENT_SEQUENCE_INVALID`, which report 422."

    Design: Difficulty/priority_pair_validation_conflict/temporal_error_wins_over_capacity_error_on_remembrance_event_create
    """
    set_clock()
    space = create_meeting_space(name="Chapel Room", capacity=20,
                                 turnover_buffer_minutes=30)
    cohort = create_cohort(space["id"], name="Tuesday Illness Group",
                           loss_type="ANTICIPATED_ILLNESS", weekday="TUE",
                           start_minute_utc=600, duration_minutes=90,
                           series_start_date="2026-09-08", sessions_total=8,
                           direct_cost_cents=240_000)
    assert cohort["series_end_date"] == "2026-10-27"

    # 50 seats in a 20-seat room AND a collision with the Tuesday block.
    error = validate_error(
        api_client.create_remembrance_event(
            create_remembrance_event_payload(
                space["id"], title="Overbooked Vigil", event_date="2026-10-06",
                start_minute_utc=720, duration_minutes=60, expected_attendance=50,
                direct_cost_cents=10_220), PD),
        ApiErrorId.ERR_SPACE_TIME_CONFLICT.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_SPACE_CAPACITY_EXCEEDED.value


def test_no_event_is_persisted_when_the_temporal_rule_rejects_the_create():
    """PRD 3.7: "The room must hold the crowd: an `expected_attendance` exceeding
    the room's `capacity` is refused with `ERR_SPACE_CAPACITY_EXCEEDED`."
    PRD 3.7: "And the block must be free: the event's date and minute interval are
    tested against every live occupation of the same room under the closed-interval
    buffer arithmetic of §3.3, and a clash is refused with
    `ERR_SPACE_TIME_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/temporal_error_wins_over_capacity_error_on_remembrance_event_create
    """
    set_clock()
    space = create_meeting_space(name="Chapel Room", capacity=20,
                                 turnover_buffer_minutes=30)
    create_cohort(space["id"], name="Tuesday Illness Group",
                  loss_type="ANTICIPATED_ILLNESS", weekday="TUE",
                  start_minute_utc=600, duration_minutes=90,
                  series_start_date="2026-09-08", sessions_total=8,
                  direct_cost_cents=240_000)

    validate_error(
        api_client.create_remembrance_event(
            create_remembrance_event_payload(
                space["id"], title="Overbooked Vigil", event_date="2026-10-06",
                start_minute_utc=720, duration_minutes=60, expected_attendance=50,
                direct_cost_cents=10_220), PD),
        ApiErrorId.ERR_SPACE_TIME_CONFLICT.value, 409)

    rows, meta = validate_paginated(
        api_client.list_remembrance_events(PD, params={"meeting_space_id": space["id"]}))
    assert meta["total_count"] == 0, (
        f"Expected no event on file, got {meta['total_count']}")
