"""Entity surface: creation, retrieval, listing, defaults and computed fields."""

from test_helpers import (
    CLEAN_DIRTY,
    COMPLIANCE_HEADERS,
    DEFAULT_CLOCK,
    DIRECTOR_HEADERS,
    FRONT_DESK_HEADERS,
    INSPECTION_PASS,
    NON_EXISTENT_UUID,
    OCCUPANCY_DUE_OUT,
    OCCUPANCY_VACANT,
    ORDINANCE_SQFT_CAP_2200,
    PROGRAM_DAILY,
    SERVICE_CHECKOUT,
    ApiErrorId,
    assert_credits,
    assert_instant_equals,
    assert_is_null,
    assert_score_pct,
    build_scenario,
    create_property,
    create_room,
    create_room_type,
    is_valid_uuid,
    property_payload,
    read_property,
    room_payload,
    room_type_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_property_creation_returns_the_full_declared_field_set(api):
    """A property arrives with both computed counters seeded and its version at one.

    PRD 3.1: "`outstanding_incentive_points` is the sum of `points_accrued` across
    every service enrolment whose room belongs to the property and whose `status`
    is still `ACTIVE`, and likewise starts at 0."

    Design: Corner/entities/entity_property_creation_returns_every_declared_field
    """
    set_clock(api, DEFAULT_CLOCK)

    prop = validate_success(
        api.create_property(property_payload(), DIRECTOR_HEADERS), 201
    )

    assert prop["name"] == "Harborview Hotel"
    assert prop["ordinance_profile"] == ORDINANCE_SQFT_CAP_2200
    assert prop["credit_minute_value"] == 30
    assert_credits(prop["max_daily_credits"], 16.00, "max_daily_credits")
    assert prop["total_rooms"] == 0
    assert prop["outstanding_incentive_points"] == 0
    assert prop["version"] == 1


def test_room_retrieval_echoes_the_stored_room(api):
    """The stored room reads back with its seeded posture and a DIRTY condition.

    PRD 3.1: "`cleanliness_status` is the housekeeping condition and is one of
    `CLEAN`, `DIRTY`, `IN_SERVICE`, `INSPECTED_PASS`, `RECLEAN_REQUIRED` or
    `OUT_OF_ORDER`; it starts at `DIRTY` on creation and is thereafter driven by
    the system rather than commanded, except through the explicit operator
    correction described below."

    Design: Corner/entities/entity_room_retrieval_returns_the_stored_room
    """
    set_clock(api, DEFAULT_CLOCK)
    prop = create_property(api)
    room_type = create_room_type(api, prop["id"])
    created = create_room(
        api, prop["id"], room_type["id"], "101", occupancy_state=OCCUPANCY_DUE_OUT
    )

    room = validate_success(api.get_room(created["id"], FRONT_DESK_HEADERS), 200)

    assert room["room_number"] == "101"
    assert room["floor"] == 1
    assert room["room_type_id"] == room_type["id"]
    assert room["property_id"] == prop["id"]
    assert room["occupancy_state"] == OCCUPANCY_DUE_OUT
    assert room["cleanliness_status"] == CLEAN_DIRTY


def test_room_listing_filtered_by_room_type_returns_only_the_matching_room(api):
    """Filtering on the suite type returns the suite alone, and the count follows.

    PRD 2.3: "Filters are combined with logical conjunction — a request naming two
    filters returns only rows matching both — and are applied before pagination, so
    `total_count` reflects the filtered set rather than the whole collection."

    Design: Corner/entities/entity_room_listing_filtered_by_room_type_returns_only_matches
    """
    scenario = build_scenario(
        api,
        room_type_codes=("KING", "SUITE"),
        rooms=["101", "102", ("201", "SUITE")],
        with_worker=False,
        with_inspector=False,
        with_day=False,
        with_roster=False,
    )
    suite_type_id = scenario.room_types["SUITE"]["id"]

    rows, meta = validate_paginated(
        api.list_rooms({"room_type_id": suite_type_id}, COMPLIANCE_HEADERS)
    )

    assert meta["total_count"] == 1, (
        f"only the suite should match, got {meta['total_count']}"
    )
    assert [row["room_number"] for row in rows] == ["201"]
    assert rows[0]["id"] == scenario.room_id("201")
    _, all_meta = validate_paginated(
        api.list_rooms({"property_id": scenario.property_id}, COMPLIANCE_HEADERS)
    )
    assert all_meta["total_count"] == 3


def test_room_get_with_an_unknown_identifier_is_a_not_found(api):
    """An unresolvable room identifier is a 404 with its own error, not an empty read.

    PRD 2.5: "The first identifier that does not resolve determines the 404:
    `ERR_PROPERTY_NOT_FOUND`, `ERR_ROOM_TYPE_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`,
    `ERR_ATTENDANT_NOT_FOUND`, `ERR_FORECAST_DAY_NOT_FOUND`,
    `ERR_ROSTER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
    `ERR_INSPECTION_NOT_FOUND`, `ERR_LINEN_ITEM_NOT_FOUND`,
    `ERR_LAUNDRY_CYCLE_NOT_FOUND`, `ERR_LOST_FOUND_ITEM_NOT_FOUND` or
    `ERR_ENROLLMENT_NOT_FOUND` as appropriate to the entity that failed to
    resolve."

    Design: Corner/entities/entity_room_get_with_unknown_id_returns_not_found
    """
    set_clock(api, DEFAULT_CLOCK)

    response = api.get_room(NON_EXISTENT_UUID, COMPLIANCE_HEADERS)

    error = validate_error(response, ApiErrorId.ROOM_NOT_FOUND, 404)
    assert error["message"], "the error envelope must carry a human-readable message"


def test_room_creation_without_a_room_number_is_rejected(api):
    """The one input with no default is missing, so the body shape fails first.

    PRD 2.10: "**Fourth**, request-body shape on every write operation: every
    required input field present, every JSON type correct, every enum value inside
    its declared set, counts and minute totals non-negative, inspection point
    fields inside 0 through 10, and the `expected_roster_version` or
    `expected_linen_item_version` field present on the two operations that declare
    it — any failure is `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/entity_room_creation_missing_required_room_number_is_rejected
    """
    set_clock(api, DEFAULT_CLOCK)
    prop = create_property(api)
    room_type = create_room_type(api, prop["id"])

    response = api.create_room(
        {
            "property_id": prop["id"],
            "room_type_id": room_type["id"],
            "floor": 1,
            "occupancy_state": OCCUPANCY_DUE_OUT,
        },
        DIRECTOR_HEADERS,
    )

    validate_error(response, ApiErrorId.INVALID_REQUEST, 400)
    _, meta = validate_paginated(
        api.list_rooms({"property_id": prop["id"]}, DIRECTOR_HEADERS)
    )
    assert meta["total_count"] == 0, "the refused create must leave no room behind"
    assert read_property(api, prop["id"])["total_rooms"] == 0


def test_room_defaults_are_applied_when_the_optional_inputs_are_omitted(api):
    """The omitted postures take their declared defaults rather than nulls.

    PRD 3.1: "`service_program` is the guest service programme in force and is one
    of `DAILY` (serviced every day), `EVERY_OTHER_DAY` (stayover service permitted
    only when the room was last serviced two or more business dates ago) or
    `OPT_OUT` (stayover service declined by the guest), defaulting to `DAILY`."

    Design: Corner/entities/entity_room_defaults_applied_when_optional_inputs_are_omitted
    """
    set_clock(api, DEFAULT_CLOCK)
    prop = create_property(api)
    room_type = create_room_type(api, prop["id"])

    room = validate_success(
        api.create_room(
            {
                "property_id": prop["id"],
                "room_type_id": room_type["id"],
                "room_number": "110",
                "floor": 1,
            },
            DIRECTOR_HEADERS,
        ),
        201,
    )

    assert room["service_program"] == PROGRAM_DAILY
    assert room["occupancy_state"] == OCCUPANCY_VACANT
    assert room["cleanliness_status"] == CLEAN_DIRTY
    assert_is_null(room["last_serviced_business_date"], "last_serviced_business_date")
    assert_is_null(
        room["last_deep_cleaned_business_date"], "last_deep_cleaned_business_date"
    )
    assert read_property(api, prop["id"])["total_rooms"] == 1
    types, _ = validate_paginated(
        api.list_room_types({"property_id": prop["id"]}, DIRECTOR_HEADERS)
    )
    assert types[0]["room_count"] == 1


def test_assignment_credits_and_square_feet_are_snapshotted_from_the_room_type(api):
    """Neither figure is an input, yet both arrive on the created assignment.

    PRD 3.4: "Creation also snapshots the room type's `square_feet` into the
    assignment's own `square_feet_snapshot`."

    Design: Corner/entities/entity_assignment_credits_and_square_feet_are_computed_from_the_room_type
    """
    scenario = build_scenario(
        api,
        rooms=[{"number": "101", "occupancy_state": OCCUPANCY_DUE_OUT}],
        linen={"total_owned_sets": 20},
    )

    assignment = validate_success(
        scenario.assign_raw(
            "101", SERVICE_CHECKOUT, headers=scenario.supervisor_headers()
        ),
        201,
    )

    assert_credits(assignment["credits"], 1.00, "credits")
    assert assignment["square_feet_snapshot"] == 420
    assert assignment["reclean_generation"] == 0
    assert assignment["linen_sets_debited"] == 0
    assert_is_null(assignment["actual_minutes"], "actual_minutes")
    assert_is_null(assignment["supersedes_assignment_id"], "supersedes_assignment_id")


def test_system_fields_are_minted_by_the_server_from_the_logical_clock(api):
    """The identifier, both timestamps and the version are all server-side.

    PRD 2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC
    timestamp in the same format refreshed on every mutation, and `version`, an
    integer that starts at 1 on creation and increments by one on every mutation of
    that resource."

    Design: Corner/entities/entity_system_fields_are_server_generated_from_the_logical_clock
    """
    set_clock(api, DEFAULT_CLOCK)
    prop = create_property(api)
    room_type = create_room_type(api, prop["id"])

    room = validate_success(
        api.create_room(
            room_payload(prop["id"], room_type["id"], "120"), DIRECTOR_HEADERS
        ),
        201,
    )

    assert is_valid_uuid(room["id"]), (
        f"the room id should be a server-minted UUID, got {room['id']!r}"
    )
    assert_instant_equals(room["created_at"], DEFAULT_CLOCK, "created_at")
    assert_instant_equals(room["updated_at"], DEFAULT_CLOCK, "updated_at")
    assert room["version"] == 1


def test_room_type_square_feet_below_the_permitted_range_is_rejected(api):
    """Forty square feet sits under the declared floor of fifty and is refused.

    PRD 3.1: "A room type belongs to a property, carries a `code` (1 to 24
    uppercase characters, unique within the property — a collision is
    `ERR_ROOM_TYPE_CODE_DUPLICATE`), a `square_feet` figure for one room of that
    type between 50 and 5000, and the three credit columns that make the credit
    standard concrete: `checkout_credits` for a departure clean,
    `stayover_credits` for an occupied-room service, and `deep_clean_credits` for a
    rotational deep clean."

    Design: Corner/entities/entity_room_type_square_feet_out_of_range_is_rejected
    """
    set_clock(api, DEFAULT_CLOCK)
    prop = create_property(api)

    response = api.create_room_type(
        room_type_payload(prop["id"], code="CLOSET", square_feet=40), DIRECTOR_HEADERS
    )

    validate_error(response, ApiErrorId.INVALID_REQUEST, 400)
    _, meta = validate_paginated(
        api.list_room_types({"property_id": prop["id"]}, DIRECTOR_HEADERS)
    )
    assert meta["total_count"] == 0, "the refused create must leave no room type behind"


def test_room_creation_naming_an_unknown_room_type_is_a_not_found(api):
    """The body's foreign key resolves to nothing, which is a 404 of its own.

    PRD 2.5: "Foreign keys inside a request body are resolved after the path and
    after the body's shape has been checked, and they are resolved in the order in
    which the endpoint declares its input fields."

    Design: Corner/entities/entity_room_creation_with_unknown_room_type_returns_not_found
    """
    set_clock(api, DEFAULT_CLOCK)
    prop = create_property(api)

    response = api.create_room(
        room_payload(prop["id"], NON_EXISTENT_UUID, "101"), DIRECTOR_HEADERS
    )

    validate_error(response, ApiErrorId.ROOM_TYPE_NOT_FOUND, 404)
    assert read_property(api, prop["id"])["total_rooms"] == 0


def test_the_room_to_assignment_edge_is_navigable_in_reverse(api):
    """The assignment is discovered from the room by filtering the flat collection.

    PRD 2.5: "This is the only discovery channel for system-generated re-clean
    assignments, which no client ever creates directly; they are found by listing
    room assignments filtered by `supersedes_assignment_id`."

    Design: Corner/entities/entity_assignment_room_fk_is_reverse_reachable_by_filtered_list
    """
    scenario = build_scenario(
        api,
        rooms=[
            {"number": "101", "occupancy_state": OCCUPANCY_DUE_OUT},
            {"number": "102", "occupancy_state": OCCUPANCY_DUE_OUT},
        ],
        linen={"total_owned_sets": 20},
    )
    assignment = scenario.assign("101", SERVICE_CHECKOUT)

    rows, meta = validate_paginated(
        api.list_room_assignments(
            {"room_id": scenario.room_id("101")}, COMPLIANCE_HEADERS
        )
    )

    assert meta["total_count"] == 1
    assert rows[0]["id"] == assignment["id"]
    _, empty_meta = validate_paginated(
        api.list_room_assignments(
            {"room_id": scenario.room_id("102")}, COMPLIANCE_HEADERS
        )
    )
    assert empty_meta["total_count"] == 0
    by_roster, _ = validate_paginated(
        api.list_room_assignments(
            {"roster_id": scenario.roster_id}, COMPLIANCE_HEADERS
        )
    )
    assert [row["id"] for row in by_roster] == [assignment["id"]]


def test_an_inspection_carries_no_version_and_re_reads_identically(api):
    """The filed inspection exposes only an identifier and a creation instant.

    PRD 2.4: "It has no `updated_at` field and no `version` field, and neither
    appears in its response payload."

    Design: Corner/entities/entity_inspection_is_immutable_with_no_update_surface
    """
    scenario = build_scenario(
        api,
        rooms=[{"number": "101", "occupancy_state": OCCUPANCY_DUE_OUT}],
        linen={"total_owned_sets": 20},
    )
    cleaned = scenario.clean(
        "101",
        SERVICE_CHECKOUT,
        "2026-08-03T09:00:00.000Z",
        "2026-08-03T09:30:00.000Z",
    )
    filed = scenario.inspect(
        cleaned["id"],
        bathroom_points=9,
        linen_points=9,
        dust_points=9,
        amenity_points=9,
        floor_points=9,
    )

    reread = validate_success(api.get_inspection(filed["id"], COMPLIANCE_HEADERS), 200)

    assert_score_pct(reread["score_pct"], 90.0)
    assert reread["result"] == INSPECTION_PASS
    assert reread["inspector_attendant_id"] == scenario.inspector_id
    assert_is_null(
        reread["generated_reclean_assignment_id"], "generated_reclean_assignment_id"
    )
    assert "version" not in reread, "an inspection payload carries no version field"
    assert "updated_at" not in reread, "an inspection payload carries no updated_at"
    rows, meta = validate_paginated(
        api.list_inspections({"assignment_id": cleaned["id"]}, COMPLIANCE_HEADERS)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == filed["id"]
