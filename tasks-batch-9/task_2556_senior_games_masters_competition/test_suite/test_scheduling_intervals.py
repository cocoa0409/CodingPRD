"""The four distinct occupancy models: venue area, personnel conflict, the daily
minutes ceiling and bed nights — plus the gates that guard slot placement."""
from test_helpers import (
    ApiErrorId,
    api_client,
    TEST_USERS,
    create_accommodation_block,
    create_athlete,
    create_personnel,
    create_session_slot,
    create_venue,
    close_venue,
    create_sport,
    create_sport_event,
    get_block,
    get_person,
    get_slot,
    reserve_stay,
    session_slot_payload,
    setup_open_edition,
    village_stay_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["games_admin_headers"]


def _slot_response(venue_id, event_id, start, end, buffer_minutes=0):
    return api_client.create_session_slot(
        session_slot_payload(
            venue_id, event_id,
            start_utc=start, end_utc=end,
            teardown_buffer_minutes=buffer_minutes, required_official_count=1,
        ),
        ADMIN,
    )


def _single_area_venue_with_incumbent() -> dict:
    """A one-area venue holding a 09:00-10:00 slot whose fifteen-minute teardown
    buffer carries its occupied window out to 10:15."""
    ctx = setup_open_edition()
    venue = create_venue(
        ctx["edition"]["id"], name="Single Track Oval", competition_area_count=1,
        spectator_capacity=200,
    )
    incumbent = create_session_slot(
        venue["id"], ctx["event"]["id"],
        start_utc="2026-09-12T09:00:00Z", end_utc="2026-09-12T10:00:00Z",
        teardown_buffer_minutes=15, required_official_count=1,
    )
    assert incumbent["teardown_buffer_minutes"] == 15
    return {"event": ctx["event"], "sport": ctx["sport"], "edition": ctx["edition"],
            "venue": venue, "incumbent": incumbent}


def test_the_teardown_buffer_extends_the_occupied_window_past_the_end_instant():
    """PRD §2.11: "Venue-area occupancy treats a slot's footprint as half-open — the start
    instant is included, the buffered end instant is excluded — so two slots whose
    footprints merely touch do not collide, and it compares that footprint against an
    aggregate per-venue area count."
    PRD §3.5: "A slot's occupied window runs from its `start_utc`, included, to its
    `end_utc` advanced by its `teardown_buffer_minutes`, excluded — the buffer extends
    the end only and is never subtracted from the start."
    PRD §3.5: "If that count has already reached the venue's `competition_area_count`,
    there is no free area and the request is refused with
    `ERR_VENUE_AREA_CAPACITY_EXCEEDED`."

    A block's occupied window runs to its `end_utc` advanced by
    `teardown_buffer_minutes`.  A candidate starting at 10:10 therefore
    intersects an incumbent that ends at 10:00 but occupies through 10:15, and
    the one-area venue has nothing left to give.

    Design: Difficulty/resource_temporal_overlap/venue_area_half_open_end_buffer_with_aggregate_area_capacity
    """
    ctx = _single_area_venue_with_incumbent()

    response = _slot_response(
        ctx["venue"]["id"], ctx["event"]["id"],
        "2026-09-12T10:10:00Z", "2026-09-12T11:00:00Z",
    )

    validate_error(
        response, ApiErrorId.ERR_VENUE_AREA_CAPACITY_EXCEEDED.value, expected_status=409
    )


def test_a_block_starting_exactly_when_the_buffered_window_ends_is_accepted():
    """PRD §2.11: "Venue-area occupancy treats a slot's footprint as half-open — the start
    instant is included, the buffered end instant is excluded — so two slots whose
    footprints merely touch do not collide, and it compares that footprint against an
    aggregate per-venue area count."
    PRD §3.5: "A slot's occupied window runs from its `start_utc`, included, to its
    `end_utc` advanced by its `teardown_buffer_minutes`, excluded — the buffer extends
    the end only and is never subtracted from the start."
    PRD §3.5: "Two windows intersect when the first begins strictly before the second
    ends and the second begins strictly before the first ends, which means windows that
    merely touch at an endpoint do not intersect: a block ending at exactly the instant
    another begins is legal."

    Venue-area windows are half-open, so two footprints that merely touch at
    an endpoint do not intersect.  A candidate starting at exactly 10:15 — the
    instant the incumbent's buffered window ends — is placed.

    Design: Difficulty/resource_temporal_overlap/venue_area_half_open_end_buffer_with_aggregate_area_capacity
    """
    ctx = _single_area_venue_with_incumbent()

    placed = validate_success(
        _slot_response(
            ctx["venue"]["id"], ctx["event"]["id"],
            "2026-09-12T10:15:00Z", "2026-09-12T11:00:00Z",
        ),
        expected_status=201,
    )

    assert placed["status"] == "SCHEDULED"
    assert placed["teardown_buffer_minutes"] == 0


def test_the_teardown_buffer_is_never_subtracted_from_the_start_instant():
    """PRD §2.11: "Venue-area occupancy treats a slot's footprint as half-open — the start
    instant is included, the buffered end instant is excluded — so two slots whose
    footprints merely touch do not collide, and it compares that footprint against an
    aggregate per-venue area count."
    PRD §3.5: "A slot's occupied window runs from its `start_utc`, included, to its
    `end_utc` advanced by its `teardown_buffer_minutes`, excluded — the buffer extends
    the end only and is never subtracted from the start."
    PRD §3.5: "Two windows intersect when the first begins strictly before the second
    ends and the second begins strictly before the first ends, which means windows that
    merely touch at an endpoint do not intersect: a block ending at exactly the instant
    another begins is legal."

    The buffer extends the end only.  A candidate running 08:00-09:00 ends
    exactly where the incumbent's window begins and is accepted, which it could
    not be if the buffer also widened the incumbent's start.

    Design: Difficulty/resource_temporal_overlap/venue_area_half_open_end_buffer_with_aggregate_area_capacity
    """
    ctx = _single_area_venue_with_incumbent()

    placed = validate_success(
        _slot_response(
            ctx["venue"]["id"], ctx["event"]["id"],
            "2026-09-12T08:00:00Z", "2026-09-12T09:00:00Z",
        ),
        expected_status=201,
    )

    assert placed["status"] == "SCHEDULED"


def test_venue_area_capacity_is_an_aggregate_count_not_one_booking_per_venue():
    """PRD §2.11: "Venue-area occupancy treats a slot's footprint as half-open — the start
    instant is included, the buffered end instant is excluded — so two slots whose
    footprints merely touch do not collide, and it compares that footprint against an
    aggregate per-venue area count."
    PRD §3.5: "The service then counts the slots at the requested `venue_id` whose
    status is `SCHEDULED` or `IN_PROGRESS` and whose occupied window intersects the
    candidate window, excluding — on a reschedule — the slot being moved from its own
    comparison."
    PRD §3.5: "If that count has already reached the venue's `competition_area_count`,
    there is no free area and the request is refused with
    `ERR_VENUE_AREA_CAPACITY_EXCEEDED`."

    The gate compares the number of intersecting live blocks against the
    venue's `competition_area_count`.  At a two-area venue a second overlapping
    block is placed because the concurrent count of 1 is still below 2, while a
    third that intersects both of them is refused at a count of 2.

    Design: Difficulty/resource_temporal_overlap/venue_area_half_open_end_buffer_with_aggregate_area_capacity
    """
    ctx = setup_open_edition()
    venue = create_venue(
        ctx["edition"]["id"], name="Twin Field House", competition_area_count=2,
        spectator_capacity=600,
    )
    create_session_slot(
        venue["id"], ctx["event"]["id"],
        start_utc="2026-09-12T14:00:00Z", end_utc="2026-09-12T15:00:00Z",
        teardown_buffer_minutes=0, required_official_count=1,
    )

    second = validate_success(
        _slot_response(
            venue["id"], ctx["event"]["id"], "2026-09-12T14:30:00Z", "2026-09-12T15:30:00Z"
        ),
        expected_status=201,
    )
    third = _slot_response(
        venue["id"], ctx["event"]["id"], "2026-09-12T14:45:00Z", "2026-09-12T15:15:00Z"
    )

    assert second["status"] == "SCHEDULED"
    validate_error(
        third, ApiErrorId.ERR_VENUE_AREA_CAPACITY_EXCEEDED.value, expected_status=409
    )


def _personnel_schedule() -> dict:
    """One official badged for the event's sport, two four-area venues, the seven
    candidate blocks of the personnel-conflict scenario, and the official already
    holding the 09:00-10:00 block at the first venue.

    Returns {"official", "slots": {...}} where the slot keys read a1..a5, b1, b2.
    """
    ctx = setup_open_edition()
    venue_a = create_venue(
        ctx["edition"]["id"], name="North Oval", competition_area_count=4
    )
    venue_b = create_venue(
        ctx["edition"]["id"], name="South Annex", competition_area_count=4
    )
    official = create_personnel(
        ctx["edition"]["id"], full_name="Dana Reyes", personnel_type="OFFICIAL",
        certification_level=3, certified_sport_codes=[ctx["sport"]["sport_code"]],
    )
    windows = {
        "a1": (venue_a, "2026-09-12T09:00:00Z", "2026-09-12T10:00:00Z"),
        "a2": (venue_a, "2026-09-12T10:00:00Z", "2026-09-12T11:00:00Z"),
        "a3": (venue_a, "2026-09-12T10:01:00Z", "2026-09-12T11:00:00Z"),
        "b1": (venue_b, "2026-09-12T11:30:00Z", "2026-09-12T12:30:00Z"),
        "b2": (venue_b, "2026-09-12T11:46:00Z", "2026-09-12T12:46:00Z"),
        "a4": (venue_a, "2026-09-12T14:20:00Z", "2026-09-12T20:20:00Z"),
        "a5": (venue_a, "2026-09-13T14:20:00Z", "2026-09-13T20:20:00Z"),
    }
    slots = {
        key: create_session_slot(
            venue["id"], ctx["event"]["id"],
            start_utc=start, end_utc=end,
            teardown_buffer_minutes=0, required_official_count=1,
        )
        for key, (venue, start, end) in windows.items()
    }
    first = validate_success(
        api_client.create_personnel_assignment(
            {
                "personnel_id": official["id"],
                "session_slot_id": slots["a1"]["id"],
                "role_at_event": "CHIEF_JUDGE",
            },
            ADMIN,
        ),
        expected_status=201,
    )
    assert first["duration_minutes"] == 60
    return {"official": official, "slots": slots, "venue_a": venue_a, "venue_b": venue_b}


def _assign(official_id, slot_id, role="JUDGE"):
    return api_client.create_personnel_assignment(
        {"personnel_id": official_id, "session_slot_id": slot_id, "role_at_event": role},
        ADMIN,
    )


def test_personnel_intervals_are_closed_so_touching_blocks_do_collide():
    """PRD §2.11: "Personnel conflict treats a slot's footprint as closed on both ends,
    expands it symmetrically by a travel buffer whose size depends on whether the two
    slots share a venue, and has an implicit capacity of one because a person cannot be
    in two places; it additionally enforces a separate per-calendar-date minutes
    ceiling."
    PRD §3.6: "Expand that existing slot symmetrically — its low bound is its
    `start_utc` moved earlier by the buffer, its high bound is its `end_utc` moved later
    by the buffer — and then compare inclusively on both ends: there is a collision when
    the expanded low bound is at or before the candidate slot's `end_utc` and the
    candidate slot's `start_utc` is at or before the expanded high bound."
    PRD §3.6: "Because the comparison is inclusive, two same-venue blocks that merely
    touch — one ending exactly when the next begins — do collide here even though they
    were perfectly legal for the venue's own area count."
    PRD §3.6: "Any collision is refused with `ERR_PERSONNEL_DOUBLE_BOOKED`."

    The personnel comparison is inclusive on both ends, so a block beginning
    at exactly the instant the person's existing block ends is a collision — the
    opposite verdict the half-open venue-area rule gives on the very same pair of
    timestamps.

    Design: Difficulty/resource_temporal_overlap/personnel_closed_interval_with_venue_conditional_travel_buffer
    """
    ctx = _personnel_schedule()

    response = _assign(ctx["official"]["id"], ctx["slots"]["a2"]["id"])

    validate_error(response, ApiErrorId.ERR_PERSONNEL_DOUBLE_BOOKED.value, expected_status=409)


def test_no_travel_buffer_applies_within_a_single_venue():
    """PRD §2.11: "Personnel conflict treats a slot's footprint as closed on both ends,
    expands it symmetrically by a travel buffer whose size depends on whether the two
    slots share a venue, and has an implicit capacity of one because a person cannot be
    in two places; it additionally enforces a separate per-calendar-date minutes
    ceiling."
    PRD §3.6: "For each such existing slot, decide the travel buffer: it is zero minutes
    when that slot is at the same `venue_id` as the candidate slot, and three quarters
    of an hour when the two are at different venues."
    PRD §3.6: "Expand that existing slot symmetrically — its low bound is its
    `start_utc` moved earlier by the buffer, its high bound is its `end_utc` moved later
    by the buffer — and then compare inclusively on both ends: there is a collision when
    the expanded low bound is at or before the candidate slot's `end_utc` and the
    candidate slot's `start_utc` is at or before the expanded high bound."
    PRD §3.6: "The service derives `duration_minutes` from the slot's own interval — the
    whole minutes from the slot's `start_utc` to its `end_utc`, with the teardown buffer
    playing no part — and credits the person's `assigned_minutes_total` by that figure."

    The travel buffer is zero minutes when the two blocks sit at the same
    venue, so one minute of daylight is enough: a 10:01-11:00 block at the same
    venue as the 09:00-10:00 incumbent is accepted, and its `duration_minutes` is
    the fifty-nine whole minutes of its own interval.

    Design: Difficulty/resource_temporal_overlap/personnel_closed_interval_with_venue_conditional_travel_buffer
    """
    ctx = _personnel_schedule()

    assignment = validate_success(
        _assign(ctx["official"]["id"], ctx["slots"]["a3"]["id"]), expected_status=201
    )

    assert assignment["status"] == "ASSIGNED"
    assert assignment["duration_minutes"] == 59


def test_the_cross_venue_travel_buffer_widens_the_existing_block_by_forty_five_minutes():
    """PRD §2.11: "Personnel conflict treats a slot's footprint as closed on both ends,
    expands it symmetrically by a travel buffer whose size depends on whether the two
    slots share a venue, and has an implicit capacity of one because a person cannot be
    in two places; it additionally enforces a separate per-calendar-date minutes
    ceiling."
    PRD §3.6: "For each such existing slot, decide the travel buffer: it is zero minutes
    when that slot is at the same `venue_id` as the candidate slot, and three quarters
    of an hour when the two are at different venues."
    PRD §3.6: "Expand that existing slot symmetrically — its low bound is its
    `start_utc` moved earlier by the buffer, its high bound is its `end_utc` moved later
    by the buffer — and then compare inclusively on both ends: there is a collision when
    the expanded low bound is at or before the candidate slot's `end_utc` and the
    candidate slot's `start_utc` is at or before the expanded high bound."
    PRD §3.6: "Any collision is refused with `ERR_PERSONNEL_DOUBLE_BOOKED`."

    When the two blocks sit at different venues the existing block is expanded
    symmetrically by three quarters of an hour.  The 10:01-11:00 block at the
    first venue therefore reaches 11:45, and a candidate at the other venue
    starting 11:30 collides — as it would not have done at the same venue.

    Design: Difficulty/resource_temporal_overlap/personnel_closed_interval_with_venue_conditional_travel_buffer
    """
    ctx = _personnel_schedule()
    validate_success(_assign(ctx["official"]["id"], ctx["slots"]["a3"]["id"]), expected_status=201)

    response = _assign(ctx["official"]["id"], ctx["slots"]["b1"]["id"])

    validate_error(response, ApiErrorId.ERR_PERSONNEL_DOUBLE_BOOKED.value, expected_status=409)


def test_one_minute_past_the_buffered_edge_is_accepted_across_venues():
    """PRD §3.6: "For each such existing slot, decide the travel buffer: it is zero minutes
    when that slot is at the same `venue_id` as the candidate slot, and three quarters
    of an hour when the two are at different venues."
    PRD §3.6: "Expand that existing slot symmetrically — its low bound is its
    `start_utc` moved earlier by the buffer, its high bound is its `end_utc` moved later
    by the buffer — and then compare inclusively on both ends: there is a collision when
    the expanded low bound is at or before the candidate slot's `end_utc` and the
    candidate slot's `start_utc` is at or before the expanded high bound."
    PRD §3.6: "The service derives `duration_minutes` from the slot's own interval — the
    whole minutes from the slot's `start_utc` to its `end_utc`, with the teardown buffer
    playing no part — and credits the person's `assigned_minutes_total` by that figure."

    The buffered edge sits at exactly 11:45 and the comparison is inclusive, so
    a cross-venue block starting at 11:46 clears it and is accepted with sixty
    duration minutes.

    Design: Difficulty/resource_temporal_overlap/personnel_closed_interval_with_venue_conditional_travel_buffer
    """
    ctx = _personnel_schedule()
    validate_success(_assign(ctx["official"]["id"], ctx["slots"]["a3"]["id"]), expected_status=201)

    assignment = validate_success(
        _assign(ctx["official"]["id"], ctx["slots"]["b2"]["id"]), expected_status=201
    )

    assert assignment["status"] == "ASSIGNED"
    assert assignment["duration_minutes"] == 60


def test_the_daily_minutes_ceiling_is_a_second_gate_evaluated_per_calendar_date():
    """PRD §2.11: "Personnel conflict treats a slot's footprint as closed on both ends,
    expands it symmetrically by a travel buffer whose size depends on whether the two
    slots share a venue, and has an implicit capacity of one because a person cannot be
    in two places; it additionally enforces a separate per-calendar-date minutes
    ceiling."
    PRD §3.6: "Take the UTC calendar date on which the candidate slot's `start_utc`
    falls, sum the `duration_minutes` of that person's assignments whose status is
    `ASSIGNED` or `CONFIRMED` and whose slots start on that same UTC date, and add the
    candidate slot's own `duration_minutes`."
    PRD §3.6: "If the total exceeds the daily ceiling of eight hours of assigned time —
    four hundred and eighty minutes — the request is refused with
    `ERR_PERSONNEL_DAILY_LIMIT_EXCEEDED`."
    PRD §3.6: "Two ledgers accompany every person and both start at zero:
    `assigned_minutes_total`, the sum of the `duration_minutes` of that person's
    assignments whose status is `ASSIGNED`, `CONFIRMED` or `COMPLETED`; and
    `no_show_count`, the number of that person's assignments that ended in `NO_SHOW`."

    A separate aggregate ceiling of eight hours applies per UTC date on top of
    the pairwise check.  A 360-minute block on 12 September conflicts with nothing
    yet pushes that date to 539 minutes and is refused; the identical block on 13
    September, a date carrying no minutes yet, is accepted.  The person's ledger
    then reads 60 + 59 + 60 + 360 = 539, counting only the accepted assignments.

    Design: Difficulty/resource_temporal_overlap/personnel_closed_interval_with_venue_conditional_travel_buffer
    """
    ctx = _personnel_schedule()
    validate_success(_assign(ctx["official"]["id"], ctx["slots"]["a3"]["id"]), expected_status=201)
    validate_success(_assign(ctx["official"]["id"], ctx["slots"]["b2"]["id"]), expected_status=201)

    over_the_ceiling = _assign(ctx["official"]["id"], ctx["slots"]["a4"]["id"], role="MARSHAL")
    next_day = _assign(ctx["official"]["id"], ctx["slots"]["a5"]["id"], role="MARSHAL")

    validate_error(
        over_the_ceiling,
        ApiErrorId.ERR_PERSONNEL_DAILY_LIMIT_EXCEEDED.value,
        expected_status=422,
    )
    accepted = validate_success(next_day, expected_status=201)
    assert accepted["duration_minutes"] == 360
    assert get_person(ctx["official"]["id"])["assigned_minutes_total"] == 539


def _two_bed_block_with_a_congested_night() -> dict:
    """A two-bed block at 10000 cents a night, with the night of 11 September
    already filled twice over: a three-night stay running 09-10 -> 09-13 and a
    one-night stay running 09-11 -> 09-12.
    """
    ctx = setup_open_edition()
    block = create_accommodation_block(
        ctx["edition"]["id"], name="Cedar Court", bed_capacity=2, nightly_rate_cents=10000
    )
    ada = create_athlete(ctx["edition"]["id"], full_name="Ada Frost")
    ben = create_athlete(ctx["edition"]["id"], full_name="Ben Iqbal")
    reserve_stay(
        ada["id"], block["id"], check_in_date="2026-09-10", check_out_date="2026-09-13"
    )
    reserve_stay(
        ben["id"], block["id"], check_in_date="2026-09-11", check_out_date="2026-09-12"
    )
    return {"edition": ctx["edition"], "block": block}


def _reserve_response(athlete_id, block_id, check_in, check_out):
    block = get_block(block_id)
    return api_client.create_village_stay(
        village_stay_payload(
            athlete_id, block_id, block["version"],
            check_in_date=check_in, check_out_date=check_out,
        ),
        ADMIN,
    )


def test_one_congested_night_defeats_a_stay_whose_other_four_nights_are_empty():
    """PRD §2.11: "Bed-night occupancy works at date granularity, half-open on the
    departure date, and is evaluated night by night rather than against one merged
    window, so a long stay can fail on a single night in the middle while every other
    night has room."
    PRD §3.8: "Bed capacity is tested one night at a time rather than against a single
    merged window, which means a long booking can fail on a single congested night even
    though every other night is wide open."
    PRD §3.8: "For each such date, count the existing stays on the same
    `accommodation_block_id` whose status is `RESERVED`, `CHECKED_IN` or `COMPLETED` and
    whose own interval covers that date under the same rule, its check-in date at or
    before the date and its check-out date strictly after it."
    PRD §3.8: "If on any single one of the candidate's nights that count has already
    reached the block's `bed_capacity`, the reservation is refused with
    `ERR_BLOCK_NIGHT_FULL`."

    Bed capacity is tested one night at a time, not against a merged window.  A
    booking of 11 -> 16 September asks for five nights of which only the first is
    contested, and that single night is already at the two-bed capacity, so the
    whole reservation is refused.

    Design: Difficulty/resource_temporal_overlap/bed_night_half_open_date_interval_with_per_night_capacity
    """
    ctx = _two_bed_block_with_a_congested_night()
    cleo = create_athlete(ctx["edition"]["id"], full_name="Cleo Nardi")

    response = _reserve_response(cleo["id"], ctx["block"]["id"], "2026-09-11", "2026-09-16")

    validate_error(response, ApiErrorId.ERR_BLOCK_NIGHT_FULL.value)
    assert get_block(ctx["block"]["id"])["reserved_bed_nights"] == 4


def test_moving_the_check_in_one_day_later_clears_the_congested_night():
    """PRD §2.11: "Bed-night occupancy works at date granularity, half-open on the
    departure date, and is evaluated night by night rather than against one merged
    window, so a long stay can fail on a single night in the middle while every other
    night has room."
    PRD §3.8: "Enumerate the nights of the candidate stay: each calendar date from the
    `check_in_date`, included, up to but not including the `check_out_date` — so the
    night of departure is never occupied and a stay of one night touches exactly one
    date."
    PRD §3.8: "For each such date, count the existing stays on the same
    `accommodation_block_id` whose status is `RESERVED`, `CHECKED_IN` or `COMPLETED` and
    whose own interval covers that date under the same rule, its check-in date at or
    before the date and its check-out date strictly after it."
    PRD §3.8: "Where the booking is accepted, the service derives the rest: `nights` is
    the whole number of days from the `check_in_date` to the `check_out_date`,
    `total_charge_cents` is that night count multiplied by the block's
    `nightly_rate_cents` — snapshotted at reservation so a later change to the block's
    nightly rate never rewrites an existing stay's charge — and the block's
    `reserved_bed_nights` is increased by the same night count."

    Shifting the same booking to 12 -> 16 September drops the contested night
    and lands on nights carrying only the one three-night stay, so it is accepted
    with four nights and a charge of 4 x 10000.

    Design: Difficulty/resource_temporal_overlap/bed_night_half_open_date_interval_with_per_night_capacity
    """
    ctx = _two_bed_block_with_a_congested_night()
    cleo = create_athlete(ctx["edition"]["id"], full_name="Cleo Nardi")

    stay = validate_success(
        _reserve_response(cleo["id"], ctx["block"]["id"], "2026-09-12", "2026-09-16"),
        expected_status=201,
    )

    assert stay["status"] == "RESERVED"
    assert stay["nights"] == 4
    assert stay["total_charge_cents"] == 40000


def test_the_night_of_departure_is_never_occupied():
    """PRD §2.11: "Bed-night occupancy works at date granularity, half-open on the
    departure date, and is evaluated night by night rather than against one merged
    window, so a long stay can fail on a single night in the middle while every other
    night has room."
    PRD §3.8: "Enumerate the nights of the candidate stay: each calendar date from the
    `check_in_date`, included, up to but not including the `check_out_date` — so the
    night of departure is never occupied and a stay of one night touches exactly one
    date."
    PRD §3.8: "For each such date, count the existing stays on the same
    `accommodation_block_id` whose status is `RESERVED`, `CHECKED_IN` or `COMPLETED` and
    whose own interval covers that date under the same rule, its check-in date at or
    before the date and its check-out date strictly after it."
    PRD §3.8: "Where the booking is accepted, the service derives the rest: `nights` is
    the whole number of days from the `check_in_date` to the `check_out_date`,
    `total_charge_cents` is that night count multiplied by the block's
    `nightly_rate_cents` — snapshotted at reservation so a later change to the block's
    nightly rate never rewrites an existing stay's charge — and the block's
    `reserved_bed_nights` is increased by the same night count."

    A one-night booking on 13 September touches exactly that one date.  The
    three-night stay departing that morning does not hold it — its check-out date
    must be strictly after the night to count — so only the 12 -> 16 stay is
    resident and the single bed left is free.

    Design: Difficulty/resource_temporal_overlap/bed_night_half_open_date_interval_with_per_night_capacity
    """
    ctx = _two_bed_block_with_a_congested_night()
    cleo = create_athlete(ctx["edition"]["id"], full_name="Cleo Nardi")
    dov = create_athlete(ctx["edition"]["id"], full_name="Dov Alaimo")
    reserve_stay(
        cleo["id"], ctx["block"]["id"],
        check_in_date="2026-09-12", check_out_date="2026-09-16",
    )

    stay = validate_success(
        _reserve_response(dov["id"], ctx["block"]["id"], "2026-09-13", "2026-09-14"),
        expected_status=201,
    )

    assert stay["nights"] == 1
    assert stay["total_charge_cents"] == 10000
    assert get_block(ctx["block"]["id"])["reserved_bed_nights"] == 9


def _event_with_an_open_and_a_closed_venue() -> dict:
    """One sport event, one venue that has been closed and one that is still open."""
    ctx = setup_open_edition()
    closed = create_venue(ctx["edition"]["id"], name="Riverside Arena")
    open_venue = create_venue(ctx["edition"]["id"], name="Highland Field")
    close_venue(closed["id"], reason="Roof inspection failed.")
    return {"event": ctx["event"], "closed": closed, "open": open_venue}


def test_a_slot_cannot_be_placed_at_a_closed_venue():
    """PRD §2.10: "The venue named for a session slot is `OPEN` — otherwise
    `ERR_VENUE_CLOSED` (HTTP 409)."
    PRD §3.5: "Placing a slot runs four independent gates beyond the basic requirement
    that the named venue be `OPEN`."
    PRD §3.5: "Venues start `OPEN` with `closed_reason` null; `CLOSED` is terminal."

    Placement reads a dimension that lives on another row entirely: the venue's
    own open/closed state.  Nothing about the requested window is wrong, yet a
    closed venue refuses the placement outright.

    Design: Difficulty/cross_entity_state_dependency/session_slot_placement_requires_venue_open_dimension
    """
    ctx = _event_with_an_open_and_a_closed_venue()

    response = _slot_response(
        ctx["closed"]["id"], ctx["event"]["id"],
        "2026-09-12T09:00:00Z", "2026-09-12T10:00:00Z",
    )

    validate_error(response, ApiErrorId.ERR_VENUE_CLOSED.value, expected_status=409)
    rows, _meta = validate_paginated(api_client.list_session_slots(ADMIN, {"limit": 50}))
    assert rows == []


def test_the_identical_window_is_accepted_at_an_open_venue():
    """PRD §2.10: "The venue named for a session slot is `OPEN` — otherwise
    `ERR_VENUE_CLOSED` (HTTP 409)."
    PRD §3.5: "Placing a slot runs four independent gates beyond the basic requirement
    that the named venue be `OPEN`."
    PRD §3.5: "A new slot is `SCHEDULED` with `confirmed_official_count` at 0."

    The very same interval and the very same event succeed the instant the venue
    dimension is satisfied, which isolates the venue's state as the only cause of
    the refusal.

    Design: Difficulty/cross_entity_state_dependency/session_slot_placement_requires_venue_open_dimension
    """
    ctx = _event_with_an_open_and_a_closed_venue()

    slot = validate_success(
        _slot_response(
            ctx["open"]["id"], ctx["event"]["id"],
            "2026-09-12T09:00:00Z", "2026-09-12T10:00:00Z",
        ),
        expected_status=201,
    )

    assert slot["status"] == "SCHEDULED"
    assert slot["venue_id"] == ctx["open"]["id"]


def test_closing_the_second_venue_displaces_its_slot_and_shuts_the_gate_behind_it():
    """PRD §3.5: "A `GamesAdmin` closing a venue supplies a `reason`, which is stored as
    the venue's `closed_reason` as the venue moves `OPEN` → `CLOSED`, and three links
    then fire."
    PRD §3.5: "First, every slot at that venue whose status is `SCHEDULED` or
    `IN_PROGRESS` moves to `DISPLACED`."
    PRD §3.5: "Third, each displaced slot re-evaluates its sport event, and an event
    whose slot set no longer contains any `SCHEDULED` or `IN_PROGRESS` slot moves
    `SEEDED` → `SCHEDULE_HOLD`."
    PRD §2.10: "The venue named for a session slot is `OPEN` — otherwise
    `ERR_VENUE_CLOSED` (HTTP 409)."

    The dependency is live, not a snapshot taken at creation time.  Closing the
    second venue displaces the slot standing on it and the same endpoint that
    succeeded a moment ago now refuses.  The event, which holds no accepted entry
    and so was never seeded, stays `OPEN` through both closures.

    Design: Difficulty/cross_entity_state_dependency/session_slot_placement_requires_venue_open_dimension
    """
    ctx = _event_with_an_open_and_a_closed_venue()
    slot = validate_success(
        _slot_response(
            ctx["open"]["id"], ctx["event"]["id"],
            "2026-09-12T09:00:00Z", "2026-09-12T10:00:00Z",
        ),
        expected_status=201,
    )

    close_venue(ctx["open"]["id"], reason="Flood damage to the infield.")
    second_attempt = _slot_response(
        ctx["open"]["id"], ctx["event"]["id"],
        "2026-09-13T09:00:00Z", "2026-09-13T10:00:00Z",
    )

    validate_error(second_attempt, ApiErrorId.ERR_VENUE_CLOSED.value, expected_status=409)
    assert get_slot(slot["id"])["status"] == "DISPLACED"
    event = validate_success(api_client.get_sport_event(ctx["event"]["id"], ADMIN))
    assert event["status"] == "OPEN"


def _two_sport_slots_that_overlap() -> dict:
    """Two events of two different sports on one four-area venue, their blocks
    overlapping between 09:30 and 10:00: the first sport asks for certification
    level 2, the second for level 3.
    """
    ctx = setup_open_edition()
    second_sport = create_sport(name="Swimming", required_certification_level=3)
    second_event = create_sport_event(
        second_sport["id"], ctx["edition"]["id"], event_code="S050F", capacity=6
    )
    venue = create_venue(
        ctx["edition"]["id"], name="Central Complex", competition_area_count=4
    )
    first_slot = create_session_slot(
        venue["id"], ctx["event"]["id"],
        start_utc="2026-09-12T09:00:00Z", end_utc="2026-09-12T10:00:00Z",
        teardown_buffer_minutes=0,
    )
    second_slot = create_session_slot(
        venue["id"], second_event["id"],
        start_utc="2026-09-12T09:30:00Z", end_utc="2026-09-12T10:30:00Z",
        teardown_buffer_minutes=0,
    )
    return {
        "edition": ctx["edition"],
        "first_sport": ctx["sport"],
        "second_sport": second_sport,
        "first_slot": first_slot,
        "second_slot": second_slot,
    }


def test_an_unqualified_official_is_refused_on_certification_not_on_the_clash():
    """PRD §2.10: "An official's certification covers the slot's sport at the required
    level — otherwise `ERR_CERTIFICATION_INSUFFICIENT` (HTTP 422)."
    PRD §2.10: "The person is not already committed in a conflicting window — otherwise
    `ERR_PERSONNEL_DOUBLE_BOOKED` (HTTP 409)."
    PRD §3.6: "When the person's `personnel_type` is `OFFICIAL`, their
    `certification_level` must be at least the `required_certification_level` of the
    sport that owns the slot's event, and that sport's `sport_code` must appear in their
    `certified_sport_codes`; failing either half is refused with
    `ERR_CERTIFICATION_INSUFFICIENT`."

    The candidate fails two gates at once: they are not badged for the second
    sport and they are already committed for half of the block's window.  The
    certification gate is decided first, so the answer is the 422 and not the 409,
    and the person's minutes ledger is left holding only the first block.

    Design: Difficulty/priority_pair_validation_conflict/assignment_certification_beats_personnel_double_booking
    """
    ctx = _two_sport_slots_that_overlap()
    official = create_personnel(
        ctx["edition"]["id"], full_name="Dana Reyes", certification_level=2,
        certified_sport_codes=[ctx["first_sport"]["sport_code"]],
    )
    validate_success(_assign(official["id"], ctx["first_slot"]["id"]), expected_status=201)

    response = _assign(official["id"], ctx["second_slot"]["id"], role="TIMER")

    validate_error(
        response, ApiErrorId.ERR_CERTIFICATION_INSUFFICIENT.value, expected_status=422
    )
    assert get_person(official["id"])["assigned_minutes_total"] == 60


def test_the_masked_clash_surfaces_once_the_badge_is_in_order():
    """PRD §2.10: "An official's certification covers the slot's sport at the required
    level — otherwise `ERR_CERTIFICATION_INSUFFICIENT` (HTTP 422)."
    PRD §2.10: "The person is not already committed in a conflicting window — otherwise
    `ERR_PERSONNEL_DOUBLE_BOOKED` (HTTP 409)."
    PRD §3.6: "When the person's `personnel_type` is `OFFICIAL`, their
    `certification_level` must be at least the `required_certification_level` of the
    sport that owns the slot's event, and that sport's `sport_code` must appear in their
    `certified_sport_codes`; failing either half is refused with
    `ERR_CERTIFICATION_INSUFFICIENT`."
    PRD §3.6: "Any collision is refused with `ERR_PERSONNEL_DOUBLE_BOOKED`."

    Repeating the identical request with a person badged for both sports at the
    required level proves the overlap was genuinely there all along: the same pair
    of blocks now yields the double-booking conflict that certification had been
    hiding.

    Design: Difficulty/priority_pair_validation_conflict/assignment_certification_beats_personnel_double_booking
    """
    ctx = _two_sport_slots_that_overlap()
    official = create_personnel(
        ctx["edition"]["id"], full_name="Rio Vance", certification_level=3,
        certified_sport_codes=[
            ctx["first_sport"]["sport_code"], ctx["second_sport"]["sport_code"]
        ],
    )
    validate_success(_assign(official["id"], ctx["first_slot"]["id"]), expected_status=201)

    response = _assign(official["id"], ctx["second_slot"]["id"], role="TIMER")

    validate_error(
        response, ApiErrorId.ERR_PERSONNEL_DOUBLE_BOOKED.value, expected_status=409
    )
    assert get_person(official["id"])["assigned_minutes_total"] == 60


def test_a_badged_and_unencumbered_official_takes_the_second_block():
    """PRD §3.6: "When the person's `personnel_type` is `OFFICIAL`, their
    `certification_level` must be at least the `required_certification_level` of the
    sport that owns the slot's event, and that sport's `sport_code` must appear in their
    `certified_sport_codes`; failing either half is refused with
    `ERR_CERTIFICATION_INSUFFICIENT`."
    PRD §3.6: "The service derives `duration_minutes` from the slot's own interval — the
    whole minutes from the slot's `start_utc` to its `end_utc`, with the teardown buffer
    playing no part — and credits the person's `assigned_minutes_total` by that figure."

    With neither gate engaged the second block is staffed normally, crediting the
    sixty whole minutes of its own interval.

    Design: Difficulty/priority_pair_validation_conflict/assignment_certification_beats_personnel_double_booking
    """
    ctx = _two_sport_slots_that_overlap()
    official = create_personnel(
        ctx["edition"]["id"], full_name="Mira Osei", certification_level=3,
        certified_sport_codes=[ctx["second_sport"]["sport_code"]],
    )

    assignment = validate_success(
        _assign(official["id"], ctx["second_slot"]["id"], role="TIMER"), expected_status=201
    )

    assert assignment["status"] == "ASSIGNED"
    assert assignment["duration_minutes"] == 60
    assert get_person(official["id"])["assigned_minutes_total"] == 60
