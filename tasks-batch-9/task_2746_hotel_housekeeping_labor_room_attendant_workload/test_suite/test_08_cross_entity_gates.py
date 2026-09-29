"""Operations gated on the state of a neighbouring entity rather than their own."""

from test_helpers import (
    ASSIGN_ASSIGNED,
    ASSIGN_IN_PROGRESS,
    CLEAN_DIRTY,
    CLEAN_IN_SERVICE,
    COMPLIANCE_COMPLIANT,
    DIRECTOR_HEADERS,
    FORECAST_DRAFT,
    FORECAST_PUBLISHED,
    ROSTER_PLANNED,
    SERVICE_CHECKOUT,
    SERVICE_DEEP_CLEAN,
    SHORTAGE_SHORTAGE,
    WAIVER_NONE,
    ApiErrorId,
    assert_coverage_ratio,
    assert_credits,
    assert_instant_equals,
    assert_is_null,
    assert_linen_buckets,
    assert_roster_dimensions,
    build_scenario,
    clock_in,
    publish_day,
    read_assignment,
    read_day,
    read_linen_item,
    read_room,
    read_roster,
    shift_roster_payload,
    start_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------
# A room may not be started against a shift nobody has begun
# --------------------------------------------------------------------------


def _planned_roster_with_one_room(api):
    """A departure clean allocated against a roster still in PLANNED."""
    scenario = build_scenario(
        api,
        rooms=[{"number": "101", "occupancy_state": "DUE_OUT"}],
        linen={"total_owned_sets": 20},
        clocked_in=False,
    )
    return scenario, scenario.assign("101", SERVICE_CHECKOUT)


def test_start_is_refused_while_the_parent_roster_is_still_planned(api):
    """The assignment is startable in itself, yet its roster has not begun.

    PRD 3.5: "The parent roster must be `CLOCKED_IN`, or
    `ERR_ROSTER_NOT_CLOCKED_IN` — this is the cross-entity gate that stops work
    being recorded against a shift nobody has started."

    Design: Difficulty/cross_entity_state_dependency/assignment_start_gated_on_parent_roster_being_clocked_in
    """
    scenario, assignment = _planned_roster_with_one_room(api)
    assert read_roster(api, scenario.roster_id)["status"] == ROSTER_PLANNED
    assert assignment["status"] == ASSIGN_ASSIGNED

    response = api.start_assignment(
        assignment["id"],
        start_payload("2026-08-03T10:00:00.000Z"),
        scenario.attendant_headers(),
    )

    validate_error(response, ApiErrorId.ROSTER_NOT_CLOCKED_IN, 409)
    refused = read_assignment(api, assignment["id"])
    assert refused["status"] == ASSIGN_ASSIGNED
    assert_is_null(refused["started_at"], "started_at")
    assert read_room(api, scenario.room_id("101"))["cleanliness_status"] == CLEAN_DIRTY


def test_the_same_start_is_accepted_once_the_roster_has_clocked_in(api):
    """Nothing about the assignment changed; only the roster's own state did.

    PRD 3.3: "Assignments may be created against a roster while it is still
    `PLANNED`, but no assignment may be **started** until the roster is
    `CLOCKED_IN`."

    Design: Difficulty/cross_entity_state_dependency/assignment_start_gated_on_parent_roster_being_clocked_in
    """
    scenario, assignment = _planned_roster_with_one_room(api)

    clock_in(api, scenario.roster_id, scenario.worker_id)
    started = scenario.start(assignment["id"], "2026-08-03T10:00:00.000Z")

    assert started["status"] == ASSIGN_IN_PROGRESS
    assert_instant_equals(
        started["started_at"], "2026-08-03T10:00:00.000Z", "started_at"
    )
    assert read_room(api, scenario.room_id("101"))["cleanliness_status"] == (
        CLEAN_IN_SERVICE
    )


# --------------------------------------------------------------------------
# A roster may not be built against an unpublished day
# --------------------------------------------------------------------------


def _drafted_day_with_an_active_attendant(api):
    """A forecast day left in DRAFT, with an ACTIVE attendant ready to be rostered."""
    return build_scenario(
        api,
        rooms=["101"],
        linen={"total_owned_sets": 20},
        publish=False,
        with_roster=False,
    )


def test_roster_creation_is_refused_while_its_forecast_day_is_still_draft(api):
    """The attendant is employable, but the staffing plan has not been released.

    PRD 3.3: "Two cross-entity gates guard the create: the forecast day's
    `status` must be `PUBLISHED`, or the request is refused with
    `ERR_FORECAST_NOT_PUBLISHED`, and the attendant's `status` must be `ACTIVE`,
    or the request is refused with `ERR_ATTENDANT_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/roster_creation_gated_on_forecast_day_being_published
    """
    scenario = _drafted_day_with_an_active_attendant(api)
    assert read_day(api, scenario.day_id)["status"] == FORECAST_DRAFT

    response = api.create_shift_roster(
        shift_roster_payload(scenario.day_id, scenario.worker_id), DIRECTOR_HEADERS
    )

    validate_error(response, ApiErrorId.FORECAST_NOT_PUBLISHED, 409)
    rows, meta = validate_paginated(
        api.list_shift_rosters({"forecast_day_id": scenario.day_id}, DIRECTOR_HEADERS)
    )
    assert meta["total_count"] == 0, (
        f"no roster should exist on the drafted day, found {meta['total_count']}"
    )
    assert rows == []


def test_the_same_roster_creation_is_accepted_once_the_day_is_published(api):
    """Publishing the day is the only thing that changes, and it opens the create.

    PRD 3.2: "Rosters may only be built against a `PUBLISHED` day."

    Design: Difficulty/cross_entity_state_dependency/roster_creation_gated_on_forecast_day_being_published
    """
    scenario = _drafted_day_with_an_active_attendant(api)

    published = publish_day(api, scenario.day_id)
    roster = validate_success(
        api.create_shift_roster(
            shift_roster_payload(scenario.day_id, scenario.worker_id), DIRECTOR_HEADERS
        ),
        201,
    )

    assert published["status"] == FORECAST_PUBLISHED
    assert roster["forecast_day_id"] == scenario.day_id
    assert roster["attendant_id"] == scenario.worker_id
    assert_roster_dimensions(
        roster, ROSTER_PLANNED, COMPLIANCE_COMPLIANT, WAIVER_NONE
    )
    assert_credits(roster["assigned_credits"], 0.00, "assigned_credits")


# --------------------------------------------------------------------------
# Rotational deep cleaning is gated on the linen line's health
# --------------------------------------------------------------------------


def _property_short_of_linen(api):
    """One of four owned sets is soiled, leaving the line at 0.7500 coverage."""
    scenario = build_scenario(
        api,
        rooms=[{"number": "101", "occupancy_state": "DUE_OUT"}, "103"],
        linen={"total_owned_sets": 4, "initial_soiled_sets": 1},
    )
    line = read_linen_item(api, scenario.linen_id)
    assert_linen_buckets(line, 3, 0, 1)
    assert_coverage_ratio(line["coverage_ratio"], 0.7500)
    assert line["shortage_status"] == SHORTAGE_SHORTAGE
    return scenario


def test_deep_clean_creation_is_refused_while_a_linen_line_reports_shortage(api):
    """A vacant room otherwise ready for rotation is held back by the linen supply.

    PRD 3.4: "A `DEEP_CLEAN` assignment may not be created while any linen line of
    the property has a `shortage_status` of `SHORTAGE` or `ESCALATED`; the refusal
    is `ERR_LINEN_SHORTAGE_BLOCK` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/deep_clean_creation_gated_on_property_linen_shortage_status
    """
    scenario = _property_short_of_linen(api)

    response = scenario.assign_raw(
        "103", SERVICE_DEEP_CLEAN, headers=scenario.supervisor_headers()
    )

    validate_error(response, ApiErrorId.LINEN_SHORTAGE_BLOCK, 409)
    assert_credits(
        read_roster(api, scenario.roster_id)["assigned_credits"],
        0.00,
        "assigned_credits",
    )
    assert read_room(api, scenario.room_id("103"))["cleanliness_status"] == CLEAN_DIRTY


def test_departure_cleaning_is_unaffected_by_the_linen_shortage(api):
    """The same shortage that defers rotation leaves the departure clean untouched.

    PRD 3.4: "`CHECKOUT`, `STAYOVER` and `LINEN_REFRESH` work is unaffected — only
    rotational deep cleaning is deferred until the linen supply recovers."

    Design: Difficulty/cross_entity_state_dependency/deep_clean_creation_gated_on_property_linen_shortage_status
    """
    scenario = _property_short_of_linen(api)

    assignment = validate_success(
        scenario.assign_raw(
            "101", SERVICE_CHECKOUT, headers=scenario.supervisor_headers()
        ),
        201,
    )

    assert assignment["status"] == ASSIGN_ASSIGNED
    assert assignment["service_type"] == SERVICE_CHECKOUT
    assert_credits(assignment["credits"], 1.00, "assignment credits")
    assert_credits(
        read_roster(api, scenario.roster_id)["assigned_credits"],
        1.00,
        "assigned_credits",
    )
