"""Entity shapes: initial values, declared defaults, computed fields and reference integrity."""
from test_helpers import (
    CLINICAL_STAFF,
    DINING_MANAGER,
    KITCHEN_LEAD,
    PROGRAM_ADMIN,
    ApiErrorId,
    create_community,
    create_diet_order,
    create_resident,
    create_venue,
    resident_version,
    set_clock,
    setup_dining_program,
    validate_error,
    validate_paginated,
    validate_success,
    venue_version,
)

UNKNOWN_RESIDENT_ID = "11111111-1111-4111-8111-111111111111"
UNKNOWN_BODY_RESIDENT_ID = "22222222-2222-4222-8222-222222222222"


def test_community_create_returns_every_declared_field_at_its_initial_value(api):
    """The two required fields are enough: the response carries `version` 1, the two policy dials
    at their defaults, the two roll-ups at their initial values, and timestamps taken from the
    startup logical clock rather than wall-clock time.

    PRD: "The service never reads wall-clock time. It reads a logical clock that, before any call to
    the clock-setting endpoint, reads exactly `2026-08-01T00:00:00Z`; there is no fallback to real
    time under any circumstance."

    Design: Corner/entities/community_create_with_all_required_fields
    """
    response = api.create_community(
        {
            "name": "Brookdale Aldergate",
            "care_levels_offered": ["ASSISTED_LIVING", "MEMORY_CARE"],
        },
        PROGRAM_ADMIN,
    )
    community = validate_success(response, 201)

    assert isinstance(community["id"], str) and community["id"]
    assert community["version"] == 1
    assert community["pending_dietitian_review_count"] == 0
    assert community["active_menu_cycle_id"] is None
    assert community["guest_meal_sponsor_cap_cents"] == 20000
    assert community["variance_tolerance_cents"] == 5000
    assert community["created_at"] == community["updated_at"]
    assert community["created_at"].startswith("2026-08-01T00:00:00")
    assert response.json()["response_type"] == "object"
    assert response.json()["meta"]["api_request_id"]


def test_venue_read_echoes_stored_fields_and_the_three_initialised_ones(api):
    """The read returns the stored parent, kind and capacity alongside the three fields creation
    initialises rather than accepts, with `version` still 1.

    PRD: "A new venue opens with `temp_compliance_posture` at `COMPLIANT`,
    `consecutive_temp_violation_count` at 0, and `status` at `OPEN`."

    Design: Corner/entities/venue_get_returns_stored_and_initialised_fields
    """
    community = create_community("Brookdale Aldergate", ["MEMORY_CARE"])
    venue = create_venue(
        community["id"],
        name="Aldergate Satellite",
        venue_kind="SATELLITE",
        seat_capacity=4,
        care_levels_served=["MEMORY_CARE"],
    )

    fetched = validate_success(api.get_venue(venue["id"], KITCHEN_LEAD))

    assert fetched["community_id"] == community["id"]
    assert fetched["venue_kind"] == "SATELLITE"
    assert fetched["seat_capacity"] == 4
    assert fetched["status"] == "OPEN"
    assert fetched["temp_compliance_posture"] == "COMPLIANT"
    assert fetched["consecutive_temp_violation_count"] == 0
    assert fetched["version"] == 1


def test_resident_listing_reports_total_count_over_the_whole_set(api):
    """Two windows over three residents: `total_count` stays 3 on both pages, `has_more` flips on
    the last one, and the rows come back in creation order.

    PRD: "The `meta` block of a list response carries `limit`, `offset`, `total_count` (the number
    of rows matching the filters before the window is applied) and `has_more` (true when rows remain
    beyond the current window)."

    Design: Corner/entities/community_residents_list_paginates_with_total_count
    """
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])
    first = create_resident(
        community["id"], full_name="Resident One", baseline_weight_kg=70.0
    )
    create_resident(community["id"], full_name="Resident Two", baseline_weight_kg=71.0)
    third = create_resident(
        community["id"], full_name="Resident Three", baseline_weight_kg=72.0
    )

    page_one, meta_one = validate_paginated(
        api.list_community_residents(
            community["id"], PROGRAM_ADMIN, params={"limit": 2, "offset": 0}
        )
    )
    page_two, meta_two = validate_paginated(
        api.list_community_residents(
            community["id"], PROGRAM_ADMIN, params={"limit": 2, "offset": 2}
        )
    )

    assert len(page_one) == 2
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0

    assert len(page_two) == 1
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False
    assert meta_two["offset"] == 2

    assert page_one[0]["id"] == first["id"]
    assert page_two[0]["id"] == third["id"]


def test_unknown_resident_id_in_the_path_returns_the_entity_specific_not_found(api):
    """A well-formed but unknown id resolves to nothing, and the path-existence tier names the
    entity that was missing.

    PRD: "**Path existence** — every id embedded in the URL resolves, checked strictly left to right
    in path order, so that a nested read of a cycle's items reports the missing cycle before it
    looks at anything else."

    Design: Corner/entities/resident_get_unknown_id_not_found
    """
    create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])

    response = api.get_resident(UNKNOWN_RESIDENT_ID, CLINICAL_STAFF)
    error = validate_error(response, ApiErrorId.ERR_RESIDENT_NOT_FOUND, 404)

    assert isinstance(error["message"], str) and error["message"]
    assert response.json()["response_type"] == "error"


def test_venue_create_without_seat_capacity_is_a_shape_error(api):
    """`seat_capacity` is a required input with no default, so omitting it is refused by the shape
    tier and no venue row is written.

    PRD: "**Request shape** — required fields present, JSON types correct, enum values inside their
    declared sets, integers and numbers inside their declared ranges, dates in `YYYY-MM-DD` form,
    datetimes RFC 3339 UTC, `service_date` equal to the UTC date of `seat_start_utc`,
    `period_end_date` not before `period_start_date`, `effective_end_date` not before
    `effective_start_date`, and decimal fields at their declared precision: `ERR_INVALID_REQUEST`
    (400)."

    Design: Corner/entities/venue_create_missing_required_seat_capacity_returns_invalid_request
    """
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])

    response = api.create_venue(
        {
            "community_id": community["id"],
            "name": "Aldergate Main Dining",
            "venue_kind": "MAIN_DINING",
            "care_levels_served": ["ASSISTED_LIVING"],
        },
        PROGRAM_ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    _, meta = validate_paginated(
        api.list_community_venues(community["id"], PROGRAM_ADMIN)
    )
    assert meta["total_count"] == 0


def test_omitted_scheduling_dials_take_their_declared_defaults(api):
    """Left out, the two dials read 60 and 20 — the numbers the interval arithmetic then uses — and
    supplied values are stored as given.

    PRD: "Two scheduling dials may be supplied: `seating_turn_minutes`, the length of one seating
    turn, defaults to 60 and must be at least 15; and `turnover_buffer_minutes`, the table-reset
    tail appended to an incumbent reservation's occupation interval, defaults to 20 and may be 0."

    Design: Corner/entities/venue_create_omitted_optional_fields_apply_declared_defaults
    """
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])

    defaulted = create_venue(
        community["id"],
        name="Aldergate Default Dining",
        venue_kind="MAIN_DINING",
        seat_capacity=6,
        care_levels_served=["ASSISTED_LIVING"],
    )
    explicit = create_venue(
        community["id"],
        name="Aldergate Fast Turn Bistro",
        venue_kind="BISTRO",
        seat_capacity=6,
        care_levels_served=["ASSISTED_LIVING"],
        seating_turn_minutes=45,
        turnover_buffer_minutes=5,
    )

    assert defaulted["seating_turn_minutes"] == 60
    assert defaulted["turnover_buffer_minutes"] == 20
    assert explicit["seating_turn_minutes"] == 45
    assert explicit["turnover_buffer_minutes"] == 5


def test_client_supplied_ticket_amount_and_status_are_not_inputs(api):
    """The rate table decides the amount and the lifecycle decides the status, so a payload that
    also carries an amount of 1 and a status of `BILLED` still yields 650 and `ISSUED`.

    PRD: "A `RESIDENT` meal is 400 cents at `BREAKFAST`, 650 at `LUNCH` and 800 at `DINNER`."

    Design: Corner/entities/ticket_billed_amount_client_supplied_value_input_ignored
    """
    program = setup_dining_program(
        clock="2026-08-10T09:00:00Z",
        community_name="Brookdale Aldergate",
        care_levels=["ASSISTED_LIVING"],
        venue_name="Aldergate Main Dining",
        seat_capacity=6,
        resident_name="Ada Whitlock",
        baseline_weight_kg=68.0,
    )

    response = api.create_meal_ticket(
        {
            "venue_id": program["venue"]["id"],
            "ticket_type": "RESIDENT",
            "service_date": "2026-08-10",
            "meal_period": "LUNCH",
            "resident_id": program["resident"]["id"],
            "billed_amount_cents": 1,
            "status": "BILLED",
        },
        DINING_MANAGER,
    )
    ticket = validate_success(response, 201)

    assert ticket["billed_amount_cents"] == 650
    assert ticket["status"] == "ISSUED"
    assert ticket["voided_amount_cents"] == 0


def test_menu_cycle_system_fields_are_stamped_from_the_logical_clock(api):
    """Creation stamps `created_at` and `updated_at` from the clock, starts `version` at 1, and
    leaves the cycle in its initial refresh posture.

    PRD: "Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp with three
    fractional digits refreshed on every mutation of that row, and `version`, an integer that starts
    at 1 on creation and increments by exactly 1 on every mutation of that row."

    Design: Corner/entities/menu_cycle_system_fields_stamped_on_create
    """
    set_clock("2026-08-05T07:30:00Z")
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])

    response = api.create_menu_cycle(
        {
            "community_id": community["id"],
            "cycle_number": 1,
            "week_count": 2,
            "effective_start_date": "2026-08-10",
            "effective_end_date": "2026-08-23",
        },
        DINING_MANAGER,
    )
    cycle = validate_success(response, 201)

    assert cycle["created_at"] == cycle["updated_at"]
    assert cycle["created_at"].startswith("2026-08-05T07:30:00")
    assert cycle["version"] == 1
    assert cycle["status"] == "DRAFT"
    assert cycle["refresh_round"] == 0
    assert float(cycle["refresh_index"]) == 0.00
    assert cycle["refresh_tier"] == "ADVISORY"


def test_undeclared_texture_value_is_refused_before_the_stale_version_guard(api):
    """A plausible but undeclared texture is rejected by the shape tier even though the same payload
    also carries a resident version the first order has already bumped past.

    PRD: "Because most write endpoints are guarded by several checks at once, the order in which
    those checks run is part of the contract: the first failing check determines the error the
    caller sees, and later checks never mask an earlier one."

    Design: Corner/entities/diet_order_create_invalid_enum_texture_returns_invalid_request
    """
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])
    resident = create_resident(
        community["id"], full_name="Bram Halvorsen", baseline_weight_kg=75.0
    )
    stale_version = resident["version"]
    first_order = create_diet_order(
        resident["id"], texture_level="BITE_SIZED", liquid_consistency="THIN"
    )
    assert stale_version == 1
    assert resident_version(resident["id"]) == 2

    response = api.create_diet_order(
        {
            "resident_id": resident["id"],
            "texture_level": "SOFT",
            "liquid_consistency": "THIN",
            "expected_resident_version": stale_version,
        },
        CLINICAL_STAFF,
    )
    error = validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)
    assert error["error_id"] != ApiErrorId.ERR_STALE_VERSION.value

    rows, meta = validate_paginated(
        api.list_diet_orders(CLINICAL_STAFF, params={"resident_id": resident["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first_order["id"]


def test_intake_observations_are_append_only_and_carry_no_version(api):
    """The observation response carries `id` and `created_at` but neither `version` nor
    `updated_at`, and the row reads back through the resident's stream unchanged.

    PRD: "Three record types are append-only observations and carry **only** `id` and `created_at` —
    they have no `updated_at` and no `version` field at all, and neither field should appear in their
    responses: `IntakeObservation`, `TemperatureLog` and `CommitteeFeedback`."

    Design: Corner/entities/intake_observation_immutable_has_no_version_field
    """
    set_clock("2026-08-10T09:00:00Z")
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])
    resident = create_resident(
        community["id"], full_name="Cleo Barrington", baseline_weight_kg=64.0
    )

    response = api.create_intake_observation(
        resident["id"],
        {"observation_date": "2026-08-10", "meal_period": "BREAKFAST", "intake_pct": 90},
        CLINICAL_STAFF,
    )
    observation = validate_success(response, 201)

    assert observation["created_at"].startswith("2026-08-10T09:00:00")
    assert observation["recorded_by_user_id"] == CLINICAL_STAFF["X-User-ID"]
    assert "version" not in observation
    assert "updated_at" not in observation

    rows, _ = validate_paginated(
        api.list_intake_observations(
            resident["id"], CLINICAL_STAFF, params={"meal_period": "BREAKFAST"}
        )
    )
    assert rows[0]["id"] == observation["id"]
    assert rows[0]["intake_pct"] == 90


def test_unknown_body_reference_is_a_not_found_rather_than_a_version_conflict(api):
    """A `resident_id` that resolves to no row fails the body-reference tier, which runs before the
    optimistic-concurrency comparison it could never have passed.

    PRD: "**Body reference existence** — every foreign key supplied in the payload resolves, checked
    in the order the fields are declared on the owning entity."

    Design: Corner/entities/diet_order_create_unknown_resident_not_found
    """
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])
    real_resident = create_resident(
        community["id"], full_name="Vera Lindholm", baseline_weight_kg=63.0
    )

    response = api.create_diet_order(
        {
            "resident_id": UNKNOWN_BODY_RESIDENT_ID,
            "texture_level": "PUREED",
            "liquid_consistency": "MILDLY_THICK",
            "expected_resident_version": real_resident["version"],
        },
        CLINICAL_STAFF,
    )
    error = validate_error(response, ApiErrorId.ERR_RESIDENT_NOT_FOUND, 404)
    assert error["error_id"] != ApiErrorId.ERR_STALE_VERSION.value

    _, meta = validate_paginated(api.list_diet_orders(CLINICAL_STAFF))
    assert meta["total_count"] == 0


def test_booking_a_resident_into_another_communitys_venue_is_refused(api):
    """The two references on a reservation must agree on the community, and that boundary check runs
    before the verified-order gate the same request would also fail.

    PRD: "6. **Community boundary** — `ERR_CROSS_COMMUNITY_REFERENCE` (422), described in section
    2.7."

    Design: Corner/entities/reservation_venue_from_another_community_returns_422
    """
    set_clock("2026-08-10T09:00:00Z")
    community_a = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])
    community_b = create_community("Brookdale Belmont", ["ASSISTED_LIVING"])
    venue_b = create_venue(
        community_b["id"],
        name="Belmont Main Dining",
        venue_kind="MAIN_DINING",
        seat_capacity=10,
        care_levels_served=["ASSISTED_LIVING"],
    )
    resident_a = create_resident(
        community_a["id"], full_name="Dara Winslow", baseline_weight_kg=66.0
    )

    response = api.create_reservation(
        {
            "resident_id": resident_a["id"],
            "venue_id": venue_b["id"],
            "service_date": "2026-08-11",
            "meal_period": "LUNCH",
            "seat_start_utc": "2026-08-11T12:00:00Z",
            "party_size": 1,
            "expected_venue_version": venue_b["version"],
        },
        DINING_MANAGER,
    )
    error = validate_error(response, ApiErrorId.ERR_CROSS_COMMUNITY_REFERENCE, 422)
    assert error["error_id"] != ApiErrorId.ERR_DIET_ORDER_NOT_VERIFIED.value

    assert venue_version(venue_b["id"]) == venue_b["version"]
