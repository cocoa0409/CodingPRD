"""Endpoint behaviour: partial updates, action side effects, computed reads and links."""

from test_helpers import (
    CLEAN_DIRTY,
    COMPLIANCE_COMPLIANT,
    COMPLIANCE_HEADERS,
    DEFAULT_CLOCK,
    DIRECTOR_HEADERS,
    ITEM_LOGGED,
    ITEM_STORED,
    OCCUPANCY_DUE_OUT,
    OCCUPANCY_STAYOVER,
    PROGRAM_DAILY,
    SERVICE_CHECKOUT,
    WAIVER_DECISION_GRANT,
    WAIVER_GRANTED,
    WAIVER_NONE,
    ApiErrorId,
    assert_credits,
    assert_instant_equals,
    assert_is_null,
    build_lost_found,
    build_scenario,
    build_second_property,
    create_property,
    create_room,
    create_room_type,
    decide_waiver,
    lost_found_payload,
    read_item,
    read_room,
    read_roster,
    read_sample_plan,
    request_waiver,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    waiver_decision_payload,
)

ONE_DEPARTURE_DAY = {
    "forecast_occupied_rooms": 1,
    "forecast_arrivals": 0,
    "forecast_departures": 1,
    "planned_deep_clean_rooms": 0,
}


# --------------------------------------------------------------------------
# The room PATCH is a partial update
# --------------------------------------------------------------------------


def test_patching_one_room_field_leaves_the_others_alone(api):
    """Only the occupancy posture moves, and the version advances by exactly one.

    PRD 3.1: "A `HousekeepingDirector` or a `FrontDeskAgent` may subsequently
    update a room's posture, supplying any subset of `occupancy_state`,
    `service_program`, `cleanliness_status`, `last_serviced_business_date` and
    `last_deep_cleaned_business_date`."

    Design: Corner/endpoints/ep_room_patch_updates_only_the_supplied_fields
    """
    set_clock(api, DEFAULT_CLOCK)
    prop = create_property(api)
    room_type = create_room_type(api, prop["id"])
    created = create_room(
        api,
        prop["id"],
        room_type["id"],
        "101",
        floor=4,
        occupancy_state=OCCUPANCY_STAYOVER,
    )
    assert created["version"] == 1

    patched = validate_success(
        api.patch_room(
            created["id"], {"occupancy_state": OCCUPANCY_DUE_OUT}, DIRECTOR_HEADERS
        ),
        200,
    )

    assert patched["occupancy_state"] == OCCUPANCY_DUE_OUT
    assert patched["service_program"] == PROGRAM_DAILY, "an unsupplied field must not move"
    assert patched["cleanliness_status"] == CLEAN_DIRTY
    assert patched["floor"] == 4
    assert patched["version"] == 2, (
        f"the update increments the version by one, got {patched['version']}"
    )
    assert_instant_equals(patched["updated_at"], DEFAULT_CLOCK, "updated_at")
    reread = read_room(api, created["id"])
    assert reread["occupancy_state"] == OCCUPANCY_DUE_OUT
    assert reread["version"] == 2
    assert reread["floor"] == 4


# --------------------------------------------------------------------------
# The store action stamps the retention window
# --------------------------------------------------------------------------


def test_binning_the_item_is_what_starts_the_retention_clock(api):
    """A logged item carries no window; storing it stamps thirty whole days.

    PRD 3.9: "The store stamps `stored_at` from the logical clock, advances `LOGGED
    → STORED`, and computes the retention window from the category alone:
    `retention_days` is 90 for `HIGH_VALUE`, 60 for `ID_DOCUMENT`, 30 for
    `STANDARD` and 0 for `PERISHABLE`, and `retention_expires_at` is `stored_at`
    advanced by that many whole days."

    Design: Corner/endpoints/ep_lost_found_store_stamps_the_retention_window
    """
    context = build_lost_found(api)
    logged = context.item
    assert logged["status"] == ITEM_LOGGED
    assert_instant_equals(logged["logged_at"], DEFAULT_CLOCK, "logged_at")
    assert_is_null(logged["retention_days"], "retention_days")
    assert_is_null(logged["retention_expires_at"], "retention_expires_at")

    stored = context.store(storage_bin="BIN-A7")

    assert stored["status"] == ITEM_STORED
    assert stored["storage_bin"] == "BIN-A7"
    assert_instant_equals(stored["stored_at"], DEFAULT_CLOCK, "stored_at")
    assert stored["retention_days"] == 30
    assert_instant_equals(
        stored["retention_expires_at"],
        "2026-09-02T07:00:00.000Z",
        "retention_expires_at",
    )
    assert stored["claim_attempt_count"] == 0
    assert read_item(api, context.item_id)["status"] == ITEM_STORED


# --------------------------------------------------------------------------
# The computed sample-plan read
# --------------------------------------------------------------------------


def test_the_sample_plan_ranks_credits_ahead_of_the_room_number(api):
    """Two finished rooms owe one sample, and the richer suite is picked over room 102.

    PRD 3.6: "The pool is ranked by `credits` descending, then by the room's
    `room_number` ascending, then by `created_at` ascending; the `created_at`
    comparison is the final tie-break and the `id` field is never consulted."

    Design: Corner/endpoints/ep_sample_plan_computed_read_ranks_credits_before_room_number
    """
    scenario = build_scenario(
        api,
        room_type_codes=("KING", "SUITE"),
        room_type_overrides={"SUITE": {"square_feet": 900}},
        rooms=[
            {"number": "102", "occupancy_state": OCCUPANCY_DUE_OUT},
            {"number": "201", "type": "SUITE", "occupancy_state": OCCUPANCY_DUE_OUT},
        ],
        linen={"total_owned_sets": 40},
        forecast={
            "forecast_occupied_rooms": 2,
            "forecast_arrivals": 0,
            "forecast_departures": 2,
            "planned_deep_clean_rooms": 0,
        },
    )
    king = scenario.clean(
        "102",
        SERVICE_CHECKOUT,
        "2026-08-03T09:00:00.000Z",
        "2026-08-03T09:30:00.000Z",
    )
    suite = scenario.clean(
        "201",
        SERVICE_CHECKOUT,
        "2026-08-03T09:40:00.000Z",
        "2026-08-03T10:10:00.000Z",
    )
    assert_credits(king["credits"], 1.00, "KING credits")
    assert_credits(suite["credits"], 2.00, "SUITE credits")

    plan = read_sample_plan(api, scenario.roster_id)

    assert plan["completed_count"] == 2
    assert plan["sample_rate"] == 0.20
    assert plan["required_samples"] == 1
    assert plan["inspections_completed"] == 0
    assert plan["remaining_samples"] == 1
    assert plan["selected_assignment_ids"] == [suite["id"]], (
        "the 2.00-credit room outranks the lower-numbered 1.00-credit room, got "
        f"{plan['selected_assignment_ids']!r}"
    )


# --------------------------------------------------------------------------
# Cross-property links
# --------------------------------------------------------------------------


def test_logging_an_item_against_another_propertys_room_is_a_scope_mismatch(api):
    """Both rows exist, so the refusal is a scope conflict rather than a not-found.

    PRD 2.5: "A room whose `property_id` differs from the property of the roster's
    forecast day, a linen line belonging to another property, an attendant being
    rostered onto another property's forecast day, or a lost-and-found item whose
    room sits under a different property are all rejected with
    `ERR_PROPERTY_SCOPE_MISMATCH` (HTTP 409)."

    Design: Corner/endpoints/ep_lost_found_logged_against_a_foreign_property_room_is_rejected
    """
    scenario = build_scenario(
        api, rooms=["101"], with_day=False, with_roster=False
    )
    other = build_second_property(api, room_number="501", with_attendant=False)

    response = api.create_lost_found_item(
        lost_found_payload(
            scenario.property_id, other.room_id("501"), scenario.worker_id
        ),
        scenario.supervisor_headers(),
    )

    validate_error(response, ApiErrorId.PROPERTY_SCOPE_MISMATCH, 409)
    assert read_room(api, other.room_id("501"))["room_number"] == "501", (
        "the foreign room must still resolve, so this was never a 404"
    )
    _, meta = validate_paginated(
        api.list_lost_found_items(
            {"property_id": scenario.property_id}, DIRECTOR_HEADERS
        )
    )
    assert meta["total_count"] == 0, "the refused logging must leave no item"
    logged = validate_success(
        api.create_lost_found_item(
            lost_found_payload(
                scenario.property_id, scenario.room_id("101"), scenario.worker_id
            ),
            scenario.supervisor_headers(),
        ),
        201,
    )
    assert logged["status"] == ITEM_LOGGED
    rows, home_meta = validate_paginated(
        api.list_lost_found_items(
            {"room_id": scenario.room_id("101")}, DIRECTOR_HEADERS
        )
    )
    assert home_meta["total_count"] == 1
    assert rows[0]["id"] == logged["id"]


# --------------------------------------------------------------------------
# A conditional action endpoint
# --------------------------------------------------------------------------


def test_a_waiver_decision_with_nothing_filed_is_refused(api):
    """The decision endpoint has nothing to decide until a request has been filed.

    PRD 3.3: "The roster's `waiver_state` must be `REQUESTED` — a decision filed
    while it is still `NONE` is `ERR_WAIVER_NOT_REQUESTED`, and a decision filed
    after the waiver has already been decided is `ERR_WAIVER_ALREADY_DECIDED`."

    Design: Corner/endpoints/ep_waiver_decision_without_a_filed_request_is_rejected
    """
    scenario = build_scenario(
        api, rooms=["101"], forecast=ONE_DEPARTURE_DAY, clocked_in=False
    )
    before = read_roster(api, scenario.roster_id)
    assert before["waiver_state"] == WAIVER_NONE

    response = api.decide_waiver(
        scenario.roster_id,
        waiver_decision_payload(WAIVER_DECISION_GRANT),
        COMPLIANCE_HEADERS,
    )

    validate_error(response, ApiErrorId.WAIVER_NOT_REQUESTED, 409)
    roster = read_roster(api, scenario.roster_id)
    assert roster["waiver_state"] == WAIVER_NONE
    assert_is_null(roster["waiver_decided_by_user_id"], "waiver_decided_by_user_id")
    assert roster["compliance_state"] == COMPLIANCE_COMPLIANT
    assert roster["version"] == before["version"], (
        "a refused decision must not move the roster version"
    )
    request_waiver(api, scenario.roster_id, 16.00, scenario.inspector_id)
    decided = decide_waiver(api, scenario.roster_id, WAIVER_DECISION_GRANT)
    assert decided["waiver_state"] == WAIVER_GRANTED, (
        "once a request exists the same GRANT must succeed"
    )
