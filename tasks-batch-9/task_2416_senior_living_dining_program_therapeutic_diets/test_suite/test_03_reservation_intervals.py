"""The reservation book: interval geometry, precedence pairs and seat conservation."""
from test_helpers import (
    BILLING_SPECIALIST,
    DINING_MANAGER,
    ApiErrorId,
    add_verified_resident,
    approve_diet_order,
    create_diet_order,
    create_reservation,
    create_resident,
    create_venue,
    list_resident_reservations,
    read_reservation,
    read_seat_availability,
    read_tray_card,
    seat_reservation,
    setup_dining_program,
    setup_published_menu_cycle,
    tickets_for_reservation,
    validate_error,
    validate_success,
    venue_version,
)


def _cedar_point_waitlisted_pair():
    """A two-seat venue holding a seated party of two and a waitlisted party of two."""
    program = setup_dining_program(
        clock="2026-08-10T09:00:00Z",
        community_name="Brookdale Cedar Point",
        care_levels=["ASSISTED_LIVING"],
        venue_name="Cedar Point Main Dining",
        seat_capacity=2,
        seating_turn_minutes=60,
        turnover_buffer_minutes=20,
        resident_name="Gil Abara",
        baseline_weight_kg=74.0,
    )
    setup_published_menu_cycle(
        program["community"]["id"],
        effective_start_date="2026-08-10",
        effective_end_date="2026-08-16",
        items=[{"item_code": "REG-BAKED-COD", "name": "Baked Cod"}],
    )
    resident_b = add_verified_resident(
        program["community"], "Hana Brill", baseline_weight_kg=61.0
    )
    reservation_a = create_reservation(
        program["resident"]["id"],
        program["venue"]["id"],
        "2026-08-10",
        "LUNCH",
        "2026-08-10T12:00:00Z",
        party_size=2,
    )
    reservation_b = create_reservation(
        resident_b["id"],
        program["venue"]["id"],
        "2026-08-10",
        "LUNCH",
        "2026-08-10T12:00:00Z",
        party_size=2,
        allow_waitlist=True,
    )
    seat_reservation(reservation_a["id"])
    program["resident_b"] = resident_b
    program["reservation_a"] = reservation_a
    program["reservation_b"] = reservation_b
    program["ticket"] = tickets_for_reservation(reservation_a["id"])[0]
    return program


def test_voiding_the_seated_party_ticket_releases_its_reservation(api):
    """The void moves the charge into `voided_amount_cents`, and the linked `SEATED` reservation
    follows it to `RELEASED`.

    PRD: "The void then cascades: a linked reservation in `SEATED` or `COMPLETED` status moves to
    `RELEASED`, and that release in turn runs the waitlist promotion selector for the freed venue,
    `service_date` and `meal_period` combination."

    Design: Difficulty/transitive_cascade/ticket_void_three_hop_waitlist_chain
    """
    program = _cedar_point_waitlisted_pair()
    assert program["reservation_b"]["status"] == "WAITLISTED"
    assert program["ticket"]["billed_amount_cents"] == 650

    response = api.void_meal_ticket(
        program["ticket"]["id"],
        {"void_reason": "resident left before service"},
        BILLING_SPECIALIST,
    )
    voided = validate_success(response)

    assert voided["status"] == "VOIDED"
    assert voided["billed_amount_cents"] == 0
    assert voided["voided_amount_cents"] == 650
    assert read_reservation(program["reservation_a"]["id"])["status"] == "RELEASED"


def test_the_freed_seats_promote_the_waitlisted_party(api):
    """The release fires the promotion selector, so the waitlisted party of two becomes
    `RESERVED` without any suspension hold and re-occupies both seats.

    PRD: "Promotion moves one `WAITLISTED` row to `RESERVED`, and it happens only when three
    conditions hold: the venue's `temp_compliance_posture` is `COMPLIANT` — a `WATCH` posture is
    not good enough for promotion — the committed seats after the release plus the candidate row's
    `party_size` is at most the venue's `seat_capacity`, and the candidate is the selector winner."

    Design: Difficulty/transitive_cascade/ticket_void_three_hop_waitlist_chain
    """
    program = _cedar_point_waitlisted_pair()

    api.void_meal_ticket(
        program["ticket"]["id"],
        {"void_reason": "resident left before service"},
        BILLING_SPECIALIST,
    )

    promoted = read_reservation(program["reservation_b"]["id"])
    assert promoted["status"] == "RESERVED"
    assert promoted["suspension_hold"] is False

    availability = read_seat_availability(program["venue"]["id"], "2026-08-10", "LUNCH")
    assert availability["committed_seats"] == 2
    assert availability["open_seats"] == 0


def _quarry_hill_blocked_waitlist():
    """A single-seat bistro serving peanuts, with the allergic resident stuck on the waitlist."""
    program = setup_dining_program(
        clock="2026-08-10T09:00:00Z",
        community_name="Brookdale Quarry Hill",
        care_levels=["ASSISTED_LIVING"],
        venue_name="Quarry Hill Bistro",
        venue_kind="BISTRO",
        seat_capacity=1,
        resident_name="Ida Cortez",
        baseline_weight_kg=66.0,
    )
    setup_published_menu_cycle(
        program["community"]["id"],
        effective_start_date="2026-08-10",
        effective_end_date="2026-08-16",
        items=[
            {
                "item_code": "PB-NOODLE",
                "name": "Peanut Noodle Bowl",
                "allergen_tags": ["PEANUT"],
            }
        ],
    )
    allergic = create_resident(
        program["community"]["id"],
        full_name="Jonas Reyes",
        baseline_weight_kg=71.0,
        allergens=["PEANUT"],
    )
    approve_diet_order(create_diet_order(allergic["id"])["id"])
    create_reservation(
        program["resident"]["id"],
        program["venue"]["id"],
        "2026-08-10",
        "LUNCH",
        "2026-08-10T12:00:00Z",
        party_size=1,
    )
    waitlisted = create_reservation(
        allergic["id"],
        program["venue"]["id"],
        "2026-08-10",
        "LUNCH",
        "2026-08-10T12:00:00Z",
        party_size=1,
        allow_waitlist=True,
    )
    program["allergic_resident"] = allergic
    program["waitlisted"] = waitlisted
    return program


def test_illegal_seating_state_is_reported_before_the_unsafe_tray(api):
    """Seating a `WAITLISTED` row whose tray card is genuinely `BLOCKED` reports the state
    failure, because the state tier runs ahead of the tray-safety tier.

    PRD: "9. **State legality** — the addressed row is in a state from which the requested
    transition exists, and every row-shape precondition that transition declares holds:
    `ERR_INVALID_STATE` (409)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_on_seat
    """
    program = _quarry_hill_blocked_waitlist()
    assert program["waitlisted"]["status"] == "WAITLISTED"
    assert (
        read_tray_card(program["allergic_resident"]["id"], "2026-08-10", "LUNCH")[
            "tray_status"
        ]
        == "BLOCKED"
    )

    response = api.seat_reservation(program["waitlisted"]["id"], DINING_MANAGER)
    error = validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)
    assert error["error_id"] != ApiErrorId.ERR_UNSAFE_TRAY_NO_SUBSTITUTION.value


def test_the_refused_seating_leaves_the_row_waitlisted_with_no_ticket(api):
    """Nothing is written by the refused seating: the row is still `WAITLISTED` and the seating
    cascade never minted a ticket for it.

    PRD: "If any gate anywhere in the chain fails, nothing is written at all."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_on_seat
    """
    program = _quarry_hill_blocked_waitlist()

    api.seat_reservation(program["waitlisted"]["id"], DINING_MANAGER)

    assert read_reservation(program["waitlisted"]["id"])["status"] == "WAITLISTED"
    assert tickets_for_reservation(program["waitlisted"]["id"]) == []


def _stonebriar_single_seat_lunch():
    """A one-seat venue where the incumbent lunch booking blocks both spacing and capacity."""
    program = setup_dining_program(
        clock="2026-08-10T09:00:00Z",
        community_name="Brookdale Stonebriar",
        care_levels=["ASSISTED_LIVING"],
        venue_name="Stonebriar Main Dining",
        seat_capacity=1,
        seating_turn_minutes=60,
        turnover_buffer_minutes=20,
        resident_name="Karla Nunez",
        baseline_weight_kg=69.0,
    )
    setup_published_menu_cycle(
        program["community"]["id"],
        effective_start_date="2026-08-10",
        effective_end_date="2026-08-16",
        items=[
            {"item_code": "REG-COD-L", "name": "Baked Cod", "meal_period": "LUNCH"},
            {"item_code": "REG-BEEF-D", "name": "Braised Beef", "meal_period": "DINNER"},
        ],
    )
    program["incumbent"] = create_reservation(
        program["resident"]["id"],
        program["venue"]["id"],
        "2026-08-10",
        "LUNCH",
        "2026-08-10T12:00:00Z",
        party_size=1,
    )
    program["venue_version"] = venue_version(program["venue"]["id"])
    return program


def test_resident_meal_spacing_is_reported_ahead_of_venue_capacity(api):
    """A candidate 72 minutes after the incumbent violates the 90-minute resident gap and the
    single-seat capacity at once, and the spacing conflict is what the caller sees.

    PRD: "Note in particular that tier 12's suspension check precedes tier 16's verified-order
    check, so a suspended venue reports the suspension rather than a missing order; and that tier
    27's capacity check comes after tier 21's spacing check, so a candidate seating that violates
    both reports the resident-side spacing conflict."

    Design: Difficulty/priority_pair_validation_conflict/business_temporal_beats_business_fiscal_on_reserve
    """
    program = _stonebriar_single_seat_lunch()

    response = api.create_reservation(
        {
            "resident_id": program["resident"]["id"],
            "venue_id": program["venue"]["id"],
            "service_date": "2026-08-10",
            "meal_period": "DINNER",
            "seat_start_utc": "2026-08-10T13:12:00Z",
            "party_size": 1,
            "expected_venue_version": program["venue_version"],
        },
        DINING_MANAGER,
    )
    error = validate_error(response, ApiErrorId.ERR_RESIDENT_MEAL_SPACING, 409)
    assert error["error_id"] != ApiErrorId.ERR_VENUE_CAPACITY_EXCEEDED.value


def test_the_refused_booking_writes_no_row_and_leaves_the_venue_version_alone(api):
    """A refused reservation create neither persists a row nor bumps the venue's `version`.

    PRD: "Both reservation creation and reservation release increment the venue's `version`, so
    any client that observed the venue before either of those events must re-read it."

    Design: Difficulty/priority_pair_validation_conflict/business_temporal_beats_business_fiscal_on_reserve
    """
    program = _stonebriar_single_seat_lunch()

    api.create_reservation(
        {
            "resident_id": program["resident"]["id"],
            "venue_id": program["venue"]["id"],
            "service_date": "2026-08-10",
            "meal_period": "DINNER",
            "seat_start_utc": "2026-08-10T13:12:00Z",
            "party_size": 1,
            "expected_venue_version": program["venue_version"],
        },
        DINING_MANAGER,
    )

    rows = list_resident_reservations(program["resident"]["id"])
    assert [row["id"] for row in rows] == [program["incumbent"]["id"]]
    assert venue_version(program["venue"]["id"]) == program["venue_version"]


def _millbrook_two_seat_venue():
    """A two-seat venue whose incumbent party of two occupies noon to 13:00 plus the buffer."""
    program = setup_dining_program(
        clock="2026-08-10T09:00:00Z",
        community_name="Brookdale Millbrook",
        care_levels=["ASSISTED_LIVING"],
        venue_name="Millbrook Main Dining",
        seat_capacity=2,
        seating_turn_minutes=60,
        turnover_buffer_minutes=20,
        resident_name="Quinn Ashby",
        baseline_weight_kg=70.0,
    )
    program["resident_b"] = add_verified_resident(
        program["community"], "Rosa Lindqvist", baseline_weight_kg=62.0
    )
    program["incumbent"] = create_reservation(
        program["resident"]["id"],
        program["venue"]["id"],
        "2026-08-10",
        "LUNCH",
        "2026-08-10T12:00:00Z",
        party_size=2,
    )
    program["venue_version"] = venue_version(program["venue"]["id"])
    return program


def test_a_candidate_inside_the_buffered_tail_exceeds_venue_capacity(api):
    """The incumbent's seat interval ends at 13:00 and its buffered occupation runs to 13:20, so
    a 13:10 candidate falls inside it and pushes committed seats past capacity.

    PRD: "Each incumbent reservation of the same venue on the same `service_date` whose `status`
    is `RESERVED` or `SEATED` occupies the **half-open** interval from its `seat_start_utc` up to
    but not including its `seat_end_utc` advanced by the venue's `turnover_buffer_minutes` — the
    buffer is appended only to the incumbent's tail, never to the candidate's."

    Design: Difficulty/resource_temporal_overlap/venue_half_open_interval_with_tail_buffer
    """
    program = _millbrook_two_seat_venue()
    assert program["incumbent"]["seat_end_utc"].startswith("2026-08-10T13:00:00")

    response = api.create_reservation(
        {
            "resident_id": program["resident_b"]["id"],
            "venue_id": program["venue"]["id"],
            "service_date": "2026-08-10",
            "meal_period": "LUNCH",
            "seat_start_utc": "2026-08-10T13:10:00Z",
            "party_size": 1,
            "expected_venue_version": program["venue_version"],
        },
        DINING_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_VENUE_CAPACITY_EXCEEDED, 409)


def test_a_candidate_at_the_exclusive_buffered_end_is_accepted(api):
    """Starting exactly at 13:20 does not intersect the half-open occupation, so the booking is
    accepted and the meal-period roll-up legitimately reports three committed seats.

    PRD: "Because the intervals are half-open, a candidate starting exactly at an incumbent's
    buffered end instant does not conflict at all."

    Design: Difficulty/resource_temporal_overlap/venue_half_open_interval_with_tail_buffer
    """
    program = _millbrook_two_seat_venue()

    response = api.create_reservation(
        {
            "resident_id": program["resident_b"]["id"],
            "venue_id": program["venue"]["id"],
            "service_date": "2026-08-10",
            "meal_period": "LUNCH",
            "seat_start_utc": "2026-08-10T13:20:00Z",
            "party_size": 1,
            "expected_venue_version": program["venue_version"],
        },
        DINING_MANAGER,
    )
    accepted = validate_success(response, 201)
    assert accepted["status"] == "RESERVED"

    availability = read_seat_availability(program["venue"]["id"], "2026-08-10", "LUNCH")
    assert availability["committed_seats"] == 3
    assert availability["open_seats"] == 0


def _fernbank_two_venues():
    """One resident, two venues, and an incumbent lunch booking at the first venue."""
    program = setup_dining_program(
        clock="2026-08-10T09:00:00Z",
        community_name="Brookdale Fernbank",
        care_levels=["ASSISTED_LIVING"],
        venue_name="Fernbank Main Dining",
        seat_capacity=10,
        resident_name="Sylvia Marchetti",
        baseline_weight_kg=67.0,
    )
    bistro = create_venue(
        program["community"]["id"],
        name="Fernbank Bistro",
        venue_kind="BISTRO",
        seat_capacity=10,
        care_levels_served=["ASSISTED_LIVING"],
    )
    program["incumbent"] = create_reservation(
        program["resident"]["id"],
        program["venue"]["id"],
        "2026-08-10",
        "LUNCH",
        "2026-08-10T12:00:00Z",
        party_size=1,
    )
    program["bistro"] = bistro
    program["bistro_version"] = venue_version(bistro["id"])
    return program


def test_touching_the_widened_spacing_endpoint_conflicts_across_venues(api):
    """The incumbent's noon-to-13:00 sitting widens to a closed window ending at 14:30, so a
    14:30 candidate at a different venue still conflicts.

    PRD: "Because both intervals are closed, merely touching endpoints do intersect: a candidate
    that starts exactly 90 minutes after an incumbent's `seat_end_utc` conflicts, and it must
    start at least one minute later than that to be accepted."

    Design: Difficulty/resource_temporal_overlap/resident_closed_interval_symmetric_meal_gap
    """
    program = _fernbank_two_venues()

    response = api.create_reservation(
        {
            "resident_id": program["resident"]["id"],
            "venue_id": program["bistro"]["id"],
            "service_date": "2026-08-10",
            "meal_period": "DINNER",
            "seat_start_utc": "2026-08-10T14:30:00Z",
            "party_size": 1,
            "expected_venue_version": program["bistro_version"],
        },
        DINING_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_RESIDENT_MEAL_SPACING, 409)


def test_one_minute_of_clearance_accepts_the_second_sitting(api):
    """A 14:31 candidate clears the widened window and is accepted at the second venue, leaving
    the resident with exactly two reservation rows.

    PRD: "Every other reservation of the same resident — at any venue, in any community — whose
    `status` is `RESERVED`, `SEATED` or `COMPLETED` occupies the **closed** interval running from
    90 minutes before its `seat_start_utc` to 90 minutes after its `seat_end_utc`."

    Design: Difficulty/resource_temporal_overlap/resident_closed_interval_symmetric_meal_gap
    """
    program = _fernbank_two_venues()

    api.create_reservation(
        {
            "resident_id": program["resident"]["id"],
            "venue_id": program["bistro"]["id"],
            "service_date": "2026-08-10",
            "meal_period": "DINNER",
            "seat_start_utc": "2026-08-10T14:30:00Z",
            "party_size": 1,
            "expected_venue_version": program["bistro_version"],
        },
        DINING_MANAGER,
    )

    response = api.create_reservation(
        {
            "resident_id": program["resident"]["id"],
            "venue_id": program["bistro"]["id"],
            "service_date": "2026-08-10",
            "meal_period": "DINNER",
            "seat_start_utc": "2026-08-10T14:31:00Z",
            "party_size": 1,
            "expected_venue_version": program["bistro_version"],
        },
        DINING_MANAGER,
    )
    accepted = validate_success(response, 201)
    assert accepted["status"] == "RESERVED"
    assert accepted["venue_id"] == program["bistro"]["id"]

    rows = list_resident_reservations(program["resident"]["id"])
    assert sorted(row["id"] for row in rows) == sorted(
        [program["incumbent"]["id"], accepted["id"]]
    )


def _rosewood_open_venue():
    """A ten-seat venue with nothing yet booked for 2026-08-12 lunch."""
    return setup_dining_program(
        clock="2026-08-10T09:00:00Z",
        community_name="Brookdale Rosewood",
        care_levels=["ASSISTED_LIVING"],
        venue_name="Rosewood Main Dining",
        seat_capacity=10,
        resident_name="Tomas Iverson",
        baseline_weight_kg=81.0,
    )


def test_reserving_a_party_of_three_consumes_exactly_three_seats(api):
    """Committed seats move from 0 to 3 and open seats from 10 to 7 on the reserve.

    PRD: "For one venue, one `service_date` and one `meal_period` it rolls up the sum of
    `party_size` over every reservation of that venue, date and meal period whose `status` is
    `RESERVED` or `SEATED`, and reports `venue_id`, `service_date`, `meal_period`,
    `seat_capacity`, `committed_seats`, `open_seats` — the venue's `seat_capacity` minus committed
    seats, floored at 0 — and `blocking_reservation_ids`, the ids of the rows that were summed, in
    ascending `created_at` order."

    Design: Difficulty/compensating_invariant/venue_committed_seats_reserve_then_release
    """
    program = _rosewood_open_venue()
    before = read_seat_availability(program["venue"]["id"], "2026-08-12", "LUNCH")
    assert before["committed_seats"] == 0
    assert before["open_seats"] == 10

    reservation = create_reservation(
        program["resident"]["id"],
        program["venue"]["id"],
        "2026-08-12",
        "LUNCH",
        "2026-08-12T12:00:00Z",
        party_size=3,
    )
    assert reservation["status"] == "RESERVED"

    during = read_seat_availability(program["venue"]["id"], "2026-08-12", "LUNCH")
    assert during["committed_seats"] == 3
    assert during["open_seats"] == 7


def test_releasing_the_party_restores_the_seat_count_without_deleting_the_row(api):
    """The release is a true inverse: the counts return to 0 and 10, the conflict set empties,
    and the released row is still retrievable.

    PRD: "Releasing a reservation is a `DiningServicesManager` action with an optional `reason`,
    accepted from `RESERVED`, `WAITLISTED` or `SEATED`, and it moves the row to `RELEASED` and
    increments the venue's `version` by 1."

    Design: Difficulty/compensating_invariant/venue_committed_seats_reserve_then_release
    """
    program = _rosewood_open_venue()
    reservation = create_reservation(
        program["resident"]["id"],
        program["venue"]["id"],
        "2026-08-12",
        "LUNCH",
        "2026-08-12T12:00:00Z",
        party_size=3,
    )

    response = api.release_reservation(
        reservation["id"], {"reason": "family took the resident out"}, DINING_MANAGER
    )
    released = validate_success(response)
    assert released["status"] == "RELEASED"

    after = read_seat_availability(program["venue"]["id"], "2026-08-12", "LUNCH")
    assert after["committed_seats"] == 0
    assert after["open_seats"] == 10
    assert after["blocking_reservation_ids"] == []
    assert read_reservation(reservation["id"])["status"] == "RELEASED"
