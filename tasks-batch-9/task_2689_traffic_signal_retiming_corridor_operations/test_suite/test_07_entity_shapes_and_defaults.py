"""Entity payload shapes: declared inputs, documented defaults, computed fields, envelopes."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_append_only_fields,
    assert_common_fields,
    assert_instant_equals,
    assert_intersection,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import CLOCK_START, NEVER_RETIMED_AGE_DAYS
from test_helpers.fixtures import (
    ADMIN,
    ENGINEER,
    TECHNICIAN,
    corridor_members,
    create_corridor,
    create_intersection,
    enrol_member,
    intersection_counts,
    intersection_memberships,
    open_project,
    project_plans,
    project_version,
    record_run,
    read_corridor,
    screen_corridor,
    set_clock,
    setup_project_in_plan_development,
    setup_selected_corridor,
)

FULL_INTERSECTION = {
    "location_name": "Main St @ 1st Ave",
    "controller_type": "ATC_CABINET",
    "detection_status": "FULL",
    "comm_status": "ONLINE",
    "aps_installed": True,
    "walking_speed_standard": "EXTENDED_3_0_FPS",
    "pedestrian_recall": True,
    "max_cycle_length_sec": 180,
}


def test_registering_an_intersection_echoes_every_declared_input_and_derives_the_rest():
    """All eight inputs come back alongside the derived posture, age and budget fields.

    PRD §3.1: "Registering a signalized intersection requires a `location_name` —
    a human-readable cross-street label of 1 to 120 characters that may not be
    blank — and a `controller_type` naming the cabinet family installed in the
    field, one of `TS2_CABINET`, `ATC_CABINET` or `LEGACY_170`." PRD §3.1: "while
    `last_retimed_at` is still null — meaning no timing plan for this
    intersection has ever reached `DEPLOYED` — the age reads exactly 3650 days".
    PRD §3.1: "`deployed_coordinated_cycle_sec` ... is null while no plan of this
    intersection is `DEPLOYED`" and "All three start at 0 for a freshly
    registered intersection, because it has no deployed cycle yet."

    Design: Corner/entities/intersection_created_with_every_declared_input_field
    """
    created = validate_success(
        api_client.create_intersection(FULL_INTERSECTION, ADMIN), 201
    )
    assert_common_fields(created)
    assert created["version"] == 1
    for field, expected in FULL_INTERSECTION.items():
        assert created[field] == expected, field

    assert created["operational_posture"] == "READY"
    assert created["timing_plan_age_days"] == NEVER_RETIMED_AGE_DAYS
    assert created["last_retimed_at"] is None
    assert created["deployed_coordinated_cycle_sec"] is None
    assert created["priority_budget_sec"] == 0
    assert created["granted_priority_extension_total_sec"] == 0
    assert created["unallocated_priority_budget_sec"] == 0
    assert_intersection(created)


def test_omitting_every_optional_input_yields_the_documented_defaults():
    """Only the two required inputs still produce a fully populated healthy row.

    PRD §3.1: "`detection_status` records vehicle-detection health as last
    field-verified and defaults to `FULL`" and "`comm_status` records
    connectivity back to the central signal system and defaults to `ONLINE`" and
    "`max_cycle_length_sec` is the locally adopted ceiling on cycle length at
    this intersection; it defaults to 150 seconds". PRD §3.1: "`aps_installed` is
    true when an Accessible Pedestrian Signal ... is present, and defaults to
    false. `walking_speed_standard` names the walking speed used to size
    pedestrian clearance and defaults to `STD_3_5_FPS` ... `pedestrian_recall` is
    true when the pedestrian phase is served on recall every cycle, whether or
    not anybody pushed the button, and defaults to false."

    Design: Corner/entities/intersection_defaults_applied_when_optional_inputs_are_omitted
    """
    created = validate_success(
        api_client.create_intersection(
            {"location_name": "Elm St @ 4th Ave", "controller_type": "LEGACY_170"}, ADMIN
        ),
        201,
    )
    assert created["detection_status"] == "FULL"
    assert created["comm_status"] == "ONLINE"
    assert created["aps_installed"] is False
    assert created["walking_speed_standard"] == "STD_3_5_FPS"
    assert created["pedestrian_recall"] is False
    assert created["max_cycle_length_sec"] == 150
    # The defaults compose to the healthy end of the posture ladder.
    assert created["operational_posture"] == "READY"


def test_reading_a_screened_corridor_returns_exactly_what_the_screen_reported():
    """The read path derives nothing extra and loses nothing the screen computed.

    PRD §3.2: "Then `avg_plan_age_days` and `priority_score` are recomputed under
    the screening variant, `priority_score_variant` is set to `SCREENING`,
    `screened_at` is stamped with the logical clock's current value, and the
    corridor's `version` is incremented." PRD §2.4: "`version`, an integer that
    starts at 1 when the row is created and increases by exactly 1 on every
    mutation."

    Design: Corner/entities/corridor_retrieval_returns_stored_and_derived_fields
    """
    intersection = create_intersection()
    corridor = create_corridor(jurisdiction_class="ARTERIAL", annual_volume_change_pct=20.0)
    enrol_member(corridor["id"], intersection["id"], 1)

    screened = screen_corridor(corridor["id"])
    assert float(screened["priority_score"]) == 91.25
    assert float(screened["avg_plan_age_days"]) == 3650.00
    assert screened["member_count"] == 1
    assert_instant_equals(screened["screened_at"], CLOCK_START, "screened_at")

    read = read_corridor(corridor["id"])
    assert float(read["priority_score"]) == float(screened["priority_score"])
    assert float(read["avg_plan_age_days"]) == float(screened["avg_plan_age_days"])
    assert read["member_count"] == screened["member_count"]
    assert read["screened_at"] == screened["screened_at"]
    assert read["selection_status"] == "SCREENED"
    assert read["priority_score_variant"] == "SCREENING"
    # A GET is not a mutation.
    assert read["version"] == screened["version"]


def test_the_inventory_listing_pages_and_filters_over_the_same_collection():
    """Two pages cover three rows without duplication, and the posture filter narrows to one.

    PRD §2.3: "Every list response reports `limit`, `offset`, `total_count` and
    `has_more` inside `meta`, where `total_count` is the number of rows matching
    the request's filters before the pagination window is applied, and `has_more`
    is true exactly when rows matching the filters remain beyond the current
    window." PRD §3.1: "The inventory listing accepts four filters —
    `controller_type`, `comm_status`, `detection_status` and
    `operational_posture` — alongside the usual pagination."

    Design: Corner/entities/intersections_list_returns_pagination_envelope_and_honours_filters
    """
    first = create_intersection(location_name="Main St @ 1st Ave")
    second = create_intersection(location_name="Main St @ 2nd Ave")
    dark = create_intersection(location_name="Main St @ 3rd Ave",
                               controller_type="LEGACY_170", comm_status="OFFLINE")
    assert dark["operational_posture"] == "BLOCKED"

    page1, meta1 = validate_paginated(
        api_client.list_intersections(ADMIN, {"limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2
    assert meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api_client.list_intersections(ADMIN, {"limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    assert meta2["offset"] == 2

    seen = [row["id"] for row in page1] + [row["id"] for row in page2]
    assert sorted(seen) == sorted([first["id"], second["id"], dark["id"]])

    blocked, meta3 = validate_paginated(
        api_client.list_intersections(ADMIN, {"operational_posture": "BLOCKED"})
    )
    assert meta3["total_count"] == 1
    assert [row["id"] for row in blocked] == [dark["id"]]
    assert blocked[0]["operational_posture"] == "BLOCKED"


def test_an_unknown_corridor_id_is_a_typed_not_found():
    """A well-formed but unknown id is 404 on the corridor's own code, not a blank 200.

    PRD §2.6: "Identifiers embedded in a path are resolved strictly **left to
    right**, and the first identifier that resolves to nothing decides the
    response: a missing corridor yields `ERR_CORRIDOR_NOT_FOUND` ... All eleven
    are HTTP 404."

    Design: Corner/entities/get_corridor_with_unknown_id_returns_corridor_not_found
    """
    error = validate_error(
        api_client.get_corridor(NON_EXISTENT_UUID, ADMIN),
        ApiErrorId.ERR_CORRIDOR_NOT_FOUND.value,
        404,
    )
    assert isinstance(error["message"], str) and error["message"]


def test_a_corridor_without_a_jurisdiction_class_is_refused_and_creates_nothing():
    """The one input with no default is mandatory; the one with a default is optional.

    PRD §3.2: "Creating one requires a `name` of 1 to 120 non-blank characters,
    unique across corridors, and a `jurisdiction_class` — `ARTERIAL`,
    `COLLECTOR` or `LOCAL` — which is the functional classification that later
    multiplies the corridor's score. `annual_volume_change_pct` is the signed
    year-over-year traffic volume change in percent; it defaults to 0". PRD §2.7
    rung 8: "Request-body shape: required fields present, declared types
    honoured, numeric ranges respected, enum values inside their declared sets —
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/corridor_create_missing_jurisdiction_class_returns_invalid_request
    """
    validate_error(
        api_client.create_corridor({"name": "Main St 1st-3rd"}, ADMIN),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )
    _rows, meta = validate_paginated(api_client.list_corridors(ADMIN))
    assert meta["total_count"] == 0

    created = validate_success(
        api_client.create_corridor(
            {"name": "Main St 1st-3rd", "jurisdiction_class": "COLLECTOR"}, ADMIN
        ),
        201,
    )
    assert created["jurisdiction_class"] == "COLLECTOR"
    assert float(created["annual_volume_change_pct"]) == 0


def test_a_count_derives_its_two_numbers_and_ignores_what_the_body_claims():
    """Smuggled values for the derived fields are discarded and the row is append-only.

    PRD §3.4: "Its `critical_flow_ratio_sum` is the sum of all its phase volumes
    divided by a saturation flow of 1800 vehicles per hour per lane; ... the value
    persisted on the count is that quotient rounded half up to 4 decimal places."
    PRD §3.4: "the total lost time is the number of phase entries multiplied by
    4.0 seconds of lost time per phase; the raw cycle is one and a half times that
    total lost time, plus 5.0, all divided by one minus the critical flow ratio
    sum; that raw cycle is then raised to the next whole multiple of 5 seconds".
    PRD §2.4: "Three record types are deliberately append-only and therefore carry
    **only** `id` and `created_at`, with both `updated_at` and `version` absent
    from their payloads entirely: corridor membership rows, turning movement
    counts and travel time runs."

    Design: Corner/entities/turning_movement_count_computed_fields_ignore_client_supplied_values
    """
    ctx = setup_project_in_plan_development()
    intersection_id = ctx["intersections"][0]["id"]
    project_id = ctx["project"]["id"]

    smuggled = validate_success(
        api_client.create_turning_movement_count(
            intersection_id,
            {
                "project_id": project_id,
                "study_role": "BEFORE",
                "count_date": "2026-07-16T00:00:00Z",
                "period": "MID_DAY",
                "phase_volumes": {"1": 350, "2": 500, "4": 250, "6": 180},
                # Neither of these is an input of the endpoint.
                "critical_flow_ratio_sum": 0.1000,
                "recommended_cycle_sec": 60,
                "id": "11111111-1111-4111-8111-111111111111",
            },
            TECHNICIAN,
        ),
        201,
    )

    assert float(smuggled["critical_flow_ratio_sum"]) == 0.7111
    assert smuggled["recommended_cycle_sec"] == 105
    # PRD §2.4: "Clients never supply an `id`; a client-supplied value is ignored."
    assert smuggled["id"] != "11111111-1111-4111-8111-111111111111"
    assert_append_only_fields(smuggled)

    stored = [c for c in intersection_counts(intersection_id) if c["id"] == smuggled["id"]]
    assert len(stored) == 1
    assert float(stored[0]["critical_flow_ratio_sum"]) == 0.7111
    assert stored[0]["recommended_cycle_sec"] == 105


def test_two_runs_either_side_of_a_clock_move_carry_different_recorded_stamps():
    """`recorded_at` follows the logical clock while `started_at` stays where the body put it.

    PRD §3.4: "the `started_at` instant the probe vehicle entered the corridor ...
    The server stamps `recorded_at` with the logical clock's current value; that
    stamp, not `started_at`, is what the certified performance variant later
    filters on." PRD §2.5: "On startup that clock stands at exactly
    `2026-08-01T00:00:00Z`, and it stays there until an administrator moves it."

    Design: Corner/entities/travel_time_run_recorded_at_is_system_assigned_from_the_logical_clock
    """
    ctx = setup_selected_corridor()
    project_id = open_project(ctx["corridor"]["id"])["id"]

    first = record_run(project_id, study_role="BEFORE", direction="NB",
                       started_at="2026-07-15T09:00:00Z", duration_sec=320,
                       stops_count=5, arrivals_on_green_count=4, total_arrivals=12)
    assert_instant_equals(first["recorded_at"], CLOCK_START, "recorded_at")
    assert_instant_equals(first["started_at"], "2026-07-15T09:00:00Z", "started_at")

    set_clock("2026-08-03T00:00:00Z")

    second = record_run(project_id, study_role="BEFORE", direction="SB",
                        started_at="2026-07-15T09:00:00Z", duration_sec=340,
                        stops_count=7, arrivals_on_green_count=3, total_arrivals=18)
    assert_instant_equals(second["recorded_at"], "2026-08-03T00:00:00Z", "recorded_at")
    assert_instant_equals(second["started_at"], "2026-07-15T09:00:00Z", "started_at")

    assert first["recorded_at"] != second["recorded_at"]
    assert_append_only_fields(second)


def test_three_shape_violations_on_the_plan_endpoint_write_nothing_and_burn_no_version():
    """A bad enum, an inverted window and a sub-floor cycle all fail the same way.

    PRD §3.5: "a `tod_period` label from `AM_PEAK`, `MID_DAY`, `PM_PEAK` and
    `OFF_PEAK` ... Windows never wrap around midnight, so `tod_end_min` must be
    strictly greater than `tod_start_min`; a body that violates this is an invalid
    request and never reaches any business rule. The drafted `cycle_length_sec`
    must lie between 60 and 240 seconds". PRD §2.7 rung 8: "Request-body shape:
    required fields present, declared types honoured, numeric ranges respected,
    enum values inside their declared sets — `ERR_INVALID_REQUEST`."

    Design: Corner/entities/timing_plan_type_constraints_reject_bad_enum_and_inverted_tod_window
    """
    ctx = setup_project_in_plan_development()
    project_id = ctx["project"]["id"]
    intersection_id = ctx["intersections"][0]["id"]
    version = project_version(project_id)

    def body(**overrides):
        payload = {
            "project_id": project_id,
            "intersection_id": intersection_id,
            "tod_period": "AM_PEAK",
            "tod_start_min": 360,
            "tod_end_min": 540,
            "cycle_length_sec": 90,
            "expected_project_version": version,
        }
        payload.update(overrides)
        return payload

    for overrides in (
        {"tod_period": "NIGHT_OWL"},
        {"tod_start_min": 540, "tod_end_min": 540},
        {"cycle_length_sec": 50},
    ):
        validate_error(
            api_client.create_timing_plan(body(**overrides), ENGINEER),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            422,
        )

    assert project_plans(project_id) == []
    # Three refusals mutated nothing, so the very same guard still matches.
    assert project_version(project_id) == version

    drafted = validate_success(api_client.create_timing_plan(body(), ENGINEER), 201)
    assert drafted["status"] == "DRAFT"
    assert drafted["cycle_length_sec"] == 90
    assert drafted["drafted_cycle_length_sec"] == 90
    assert len(project_plans(project_id)) == 1


def test_a_membership_row_is_append_only_with_no_mutation_surface():
    """Members carry neither version nor updated_at and list in sequence order.

    PRD §2.4: "Three record types are deliberately append-only and therefore carry
    **only** `id` and `created_at`, with both `updated_at` and `version` absent
    from their payloads entirely: corridor membership rows, turning movement counts
    and travel time runs. Nothing in this system mutates a membership row, a count
    or a run after creation, so neither field would ever change and neither is
    exposed." PRD §3.2: "the supplied `sequence_index` must equal the corridor's
    current `member_count` plus 1" and "The first member of a corridor has nothing
    before it, so a `distance_from_prev_ft` other than exactly 0 at
    `sequence_index` 1 is an invalid request."

    Design: Corner/entities/corridor_member_is_immutable_with_no_version_and_no_update_endpoint
    """
    first = create_intersection(location_name="Main St @ 1st Ave")
    second = create_intersection(location_name="Main St @ 3rd Ave")
    corridor = create_corridor()
    enrol_member(corridor["id"], first["id"], 1, distance_from_prev_ft=0)
    enrol_member(corridor["id"], second["id"], 2, distance_from_prev_ft=2640)

    rows = corridor_members(corridor["id"])
    assert len(rows) == 2
    assert [row["sequence_index"] for row in rows] == [1, 2]
    assert [row["distance_from_prev_ft"] for row in rows] == [0, 2640]
    assert [row["intersection_id"] for row in rows] == [first["id"], second["id"]]
    for row in rows:
        assert_append_only_fields(row)

    # Correcting the corridor means appending the next position, never editing.
    third = create_intersection(location_name="Main St @ 5th Ave")
    appended = enrol_member(corridor["id"], third["id"], 3, distance_from_prev_ft=1320)
    assert appended["sequence_index"] == 3
    assert read_corridor(corridor["id"])["member_count"] == 3
    assert [row["sequence_index"] for row in corridor_members(corridor["id"])] == [1, 2, 3]


def test_a_split_against_an_unknown_plan_is_a_not_found_even_with_a_bad_body():
    """Path resolution outranks body shape, so the plan's 404 wins over the range error.

    PRD §2.6: "Identifiers embedded in a path are resolved strictly **left to
    right**, and the first identifier that resolves to nothing decides the
    response: ... a missing timing plan `ERR_TIMING_PLAN_NOT_FOUND`". PRD §2.7
    pins the order: rung 6 is "Path identifiers resolve, left to right — the eleven
    404 codes of §2.6." and rung 8 is "Request-body shape: required fields
    present, declared types honoured, numeric ranges respected, enum values inside
    their declared sets — `ERR_INVALID_REQUEST`."

    Design: Corner/entities/phase_split_create_against_unknown_timing_plan_returns_not_found
    """
    validate_error(
        api_client.create_phase_split(
            NON_EXISTENT_UUID,
            {
                "phase_number": 99,
                "split_sec": 21,
                "min_green_sec": 10,
                "yellow_sec": 3.0,
                "red_clearance_sec": 1.0,
            },
            ENGINEER,
        ),
        ApiErrorId.ERR_TIMING_PLAN_NOT_FOUND.value,
        404,
    )


def test_one_intersection_holds_a_different_position_in_each_of_two_corridors():
    """The junction rows are per-pairing, so the shared intersection is 1 here and 2 there.

    PRD §3.2: "An intersection already enrolled in that corridor is refused with
    `ERR_DUPLICATE_CORRIDOR_MEMBER`; the uniqueness is on the pairing of corridor
    and intersection, so the same intersection may legitimately belong to several
    corridors." PRD §3.1: "Because an intersection sits at the centre of the
    reference graph rather than at the top of a tree, five reverse-reachability
    listings hang off it: the corridor membership rows that enrol it in
    corridors". PRD
    §3.2: "Each accepted enrolment recomputes `member_count` as the number of
    membership rows pointing at the corridor".

    Design: Corner/entities/one_intersection_participates_in_two_corridors_through_the_junction_entity
    """
    shared = create_intersection(location_name="Shared Junction @ Main")
    other = create_intersection(location_name="B St @ 1st Ave")
    corridor_a = create_corridor(name="A Street Corridor", jurisdiction_class="ARTERIAL",
                                 annual_volume_change_pct=10.0)
    corridor_b = create_corridor(name="B Street Corridor", jurisdiction_class="COLLECTOR",
                                 annual_volume_change_pct=5.0)
    enrol_member(corridor_a["id"], shared["id"], 1, distance_from_prev_ft=0)
    enrol_member(corridor_b["id"], other["id"], 1, distance_from_prev_ft=0)
    enrol_member(corridor_b["id"], shared["id"], 2, distance_from_prev_ft=1320)

    memberships = intersection_memberships(shared["id"])
    assert len(memberships) == 2
    assert {row["corridor_id"] for row in memberships} == {corridor_a["id"], corridor_b["id"]}
    positions = {row["corridor_id"]: row["sequence_index"] for row in memberships}
    assert positions[corridor_a["id"]] == 1
    assert positions[corridor_b["id"]] == 2

    a_members = corridor_members(corridor_a["id"])
    assert len(a_members) == 1
    assert a_members[0]["intersection_id"] == shared["id"]

    assert read_corridor(corridor_a["id"])["member_count"] == 1
    assert read_corridor(corridor_b["id"])["member_count"] == 2
