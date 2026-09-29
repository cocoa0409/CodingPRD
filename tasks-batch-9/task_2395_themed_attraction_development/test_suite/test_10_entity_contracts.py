"""Each record's own shape: what it echoes, what it derives, what it refuses."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    add_scene,
    assert_append_only_record,
    assert_newly_opened_project,
    assert_ride_capacity_variants,
    assert_ride_system,
    create_design_package_payload,
    create_effect_cue_payload,
    create_ledger_entry_payload,
    create_project_payload,
    create_queue_segment_payload,
    create_ride_system_payload,
    open_project,
    post_change_order,
    project_version,
    read_capacity_summary,
    read_ledger,
    read_project,
    register_ride_system,
    setup_program_at_concept,
    validate_error,
    validate_paginated,
    validate_success,
)

OWNER = TEST_USERS["owner_rep_headers"]
DESIGNER = TEST_USERS["creative_director_headers"]
ENGINEER = TEST_USERS["ride_engineer_headers"]
PROGRAMMER = TEST_USERS["show_programmer_headers"]


def test_opening_a_programme_returns_the_whole_row_with_its_capacity_target(api):
    """`required_hourly_capacity_guests` is the product of `design_day_attendance` and `peak_hour_share`, computed as an exact decimal and then rounded up to a whole number of guests.

    The new programme is written with `design_phase` at `BLUE_SKY`,
    `readiness_posture` at `OPEN`, `selected_ride_system_id` null,
    `committed_cost_cents` and `forecast_cost_cents` at 0,
    `open_critical_finding_count` and `open_major_finding_count` at 0,
    `queue_capacity_total_guests` at 0, `show_quality_score` at 0.00,
    `soft_open_validated` false, `handover_accepted_at` null, and
    `ledger_sequence_high_water` at 0.

    The `response_type` is either "object" for a single resource or "array" for a
    list of resources.

    A design day of 7501 guests at a peak-hour share of 0.1234 wants 925.6234
    guests an hour, so the yardstick rounds up to 926, and every other field of
    the returned row stands at its opening value.

    Design: Corner/entities/attraction_project_creation_returns_the_full_row_with_computed_capacity
    """
    payload = create_project_payload(project_code="TAD-EN1A", name="Cavern of Echoes",
                                     design_day_attendance=7501, peak_hour_share=0.1234,
                                     budget_ceiling_cents=3600000000)

    response = api.create_project(payload, OWNER)

    project = validate_success(response, 201)
    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert_newly_opened_project(project)
    assert project["project_code"] == "TAD-EN1A"
    assert project["name"] == "Cavern of Echoes"
    assert project["design_day_attendance"] == 7501
    assert float(project["peak_hour_share"]) == 0.1234
    assert project["budget_ceiling_cents"] == 3600000000
    assert project["required_hourly_capacity_guests"] == 926
    assert project["version"] == 1


def test_reading_a_candidate_ride_system_echoes_its_inputs_and_its_two_capacities(api):
    """A `RideEngineer` registers each vendor offer as a candidate ride system against a programme, supplying `project_id`, the manufacturer's `vendor_name` (1 to 120 characters), the `system_type` — one of `DARK_RIDE_TRACKLESS`, `OMNIMOVER`, `LAUNCH_COASTER`, `BOAT_FLUME` or `MOTION_BASE_THEATER` — and seven engineering parameters: `vehicle_count` (at least 1), `riders_per_vehicle` (at least 1), `block_zone_count` (at least 2), `cycle_time_seconds` (at least 1), `availability_pct` and `load_efficiency_pct` (each greater than 0 and at most 100, two decimal places), and `show_stops_per_hour` (at least 0, two decimal places). The offer lands with `status` `CANDIDATE`.

    Second, `dispatch_interval_seconds` is the `cycle_time_seconds` divided by that
    in-service vehicle count and rounded up to a whole second, but never below the
    control system's twenty-second minimum dispatch interval — whichever of the two
    is larger wins.

    It requires the posture not to be `FROZEN` and the programme to be in
    `SCHEMATIC`, `DESIGN_DEVELOPMENT` or `PRODUCTION`, and it records the declared
    design standard `safety_standard` — either `ASTM_F2291` or `EN_13814` — together
    with `control_system_spec_ref`, the control-system specification document
    reference, 1 to 64 characters when present.

    Twelve vehicles inside fourteen block zones dispatch every twenty seconds for a
    theoretical 1440 guests an hour and a derated 1179, and the standard the ride
    will be engineered to is not yet declared.

    Design: Corner/entities/ride_system_retrieval_returns_stored_inputs_and_derived_capacity
    """
    project = open_project(project_code="TAD-EN2A")
    registered = register_ride_system(project["id"])

    ride = validate_success(api.get_ride_system(registered["id"], ENGINEER))

    assert_ride_system(ride)
    assert_ride_capacity_variants(ride, dispatch=20, theoretical=1440, operational=1179)
    assert ride["project_id"] == project["id"]
    assert ride["vendor_name"] == "Vekoma Rides"
    assert ride["system_type"] == "DARK_RIDE_TRACKLESS"
    assert ride["vehicle_count"] == 12
    assert ride["riders_per_vehicle"] == 8
    assert ride["block_zone_count"] == 14
    assert ride["cycle_time_seconds"] == 240
    assert ride["status"] == "CANDIDATE"
    assert ride["safety_standard"] is None
    assert ride["version"] == 1


def test_the_programme_list_pages_its_window_and_filters_on_the_design_phase(api):
    """Every list endpoint accepts two query parameters. `limit` caps the number of items returned; when it is absent it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100. `offset` is the number of items to skip; when it is absent it defaults to 0, and its minimum accepted value is 0.

    List responses carry `limit`, `offset`, `total_count`, and `has_more` inside the
    `meta` object of the envelope. `total_count` counts the rows matching the filter
    before pagination is applied; `has_more` is true when rows remain beyond the
    returned window.

    The two flat collection reads take richer filters: programmes may be filtered by
    `design_phase` and `readiness_posture`; scenes by `project_id`,
    `follows_scene_id`, `validating_rehearsal_run_id` and `status`; packages by
    `project_id`, `ride_system_id` and `status`.

    Three programmes stand, only the middle one has left blue sky: a two-row window
    still counts all three and reports more to come, the window past it returns the
    last row alone, and the phase filter narrows the count to the single programme at
    concept.

    Design: Corner/entities/attraction_project_listing_paginates_and_filters_by_design_phase
    """
    open_project(project_code="TAD-EN3A")
    concept = setup_program_at_concept(project_overrides={"project_code": "TAD-EN3B"})
    open_project(project_code="TAD-EN3C")

    first_page, first_meta = validate_paginated(
        api.list_projects(OWNER, params={"limit": 2, "offset": 0}))
    second_page, second_meta = validate_paginated(
        api.list_projects(OWNER, params={"limit": 2, "offset": 2}))
    filtered, filtered_meta = validate_paginated(
        api.list_projects(OWNER, params={"design_phase": "CONCEPT"}))

    assert len(first_page) == 2
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert len(second_page) == 1
    assert second_meta["offset"] == 2
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert len(filtered) == 1
    assert filtered_meta["total_count"] == 1
    assert filtered[0]["project_code"] == "TAD-EN3B"
    assert filtered[0]["id"] == concept["project"]["id"]
    assert filtered[0]["design_phase"] == "CONCEPT"


def test_reading_a_scene_that_does_not_exist_reports_the_scene_not_found(api):
    """A path `{id}` that resolves to nothing yields the 404 belonging to the resource the path addresses — `ERR_PROJECT_NOT_FOUND` for the eleven programme-addressed endpoints (single-programme read, programme patch, phase advance, the capacity summary, the budget position, and the six reverse lookups for ride systems, queue segments, value-engineering items, rehearsal runs, ledger entries and maintenance items), `ERR_RIDE_SYSTEM_NOT_FOUND`, `ERR_QUEUE_SEGMENT_NOT_FOUND`, `ERR_SCENE_NOT_FOUND`, `ERR_CUE_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`, `ERR_VE_ITEM_NOT_FOUND`, `ERR_REHEARSAL_RUN_NOT_FOUND`, `ERR_MAINTENANCE_ITEM_NOT_FOUND` and `ERR_LEDGER_ENTRY_NOT_FOUND` for the others.

    A well-formed identifier that addresses no scene is answered by the scene's own
    404, not by a generic one.

    Design: Corner/entities/show_scene_read_with_unknown_id_not_found
    """
    response = api.get_show_scene(NON_EXISTENT_UUID, DESIGNER)

    validate_error(response, ApiErrorId.ERR_SCENE_NOT_FOUND.value, 404)


def test_a_ride_system_registered_without_a_cycle_time_is_refused(api):
    """Request-body schema: every required field present, no unknown field, every enum value a declared member, every number inside its declared range and decimal-place limit, every datetime a valid ISO 8601 UTC instant, and `window_end_utc` strictly after `window_start_utc` — `ERR_INVALID_REQUEST` (400).

    The cycle time is one of the seven engineering parameters the vendor offer
    cannot be sized without, so an offer that omits it is refused on schema and the
    programme is left with no candidate at all.

    Design: Corner/entities/ride_system_create_missing_required_cycle_time_returns_invalid_request
    """
    project = open_project(project_code="TAD-EN5A")
    payload = create_ride_system_payload(project["id"])
    payload.pop("cycle_time_seconds")

    response = api.create_ride_system(payload, ENGINEER)

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
    systems, meta = validate_paginated(
        api.list_project_ride_systems(project["id"], ENGINEER))
    assert systems == []
    assert meta["total_count"] == 0


def test_an_omitted_virtual_queue_share_is_stored_as_zero(api):
    """The optional value is `virtual_queue_share_pct`, the percent of accepted queue capacity released through the virtual queue, which defaults to 0 and whose schema range is 0 through 100 inclusive with at most two decimal places.

    `virtual_queue_allocation_guests` is the total capacity multiplied by
    `virtual_queue_share_pct` divided by one hundred, rounded down to a whole guest.

    A programme opened without the field releases nothing through the virtual queue,
    while one that declares a quarter keeps that quarter on the record.

    Design: Corner/entities/virtual_queue_share_pct_defaults_to_zero_when_omitted
    """
    defaulted = open_project(project_code="TAD-EN6A")
    declared = open_project(project_code="TAD-EN6B", virtual_queue_share_pct=25)

    assert float(defaulted["virtual_queue_share_pct"]) == 0
    assert float(declared["virtual_queue_share_pct"]) == 25
    assert float(read_project(defaulted["id"])["virtual_queue_share_pct"]) == 0
    summary = read_capacity_summary(defaulted["id"])
    assert summary["queue_capacity_total_guests"] == 0
    assert summary["virtual_queue_allocation_guests"] == 0


def test_a_client_supplied_queue_capacity_is_not_a_declared_input(api):
    """A segment's `capacity_guests` is its `length_meters` multiplied by its `width_meters`, divided by the per-guest area for its routing class, and rounded down to a whole guest; the area is carried as an exact decimal.

    Request-body schema: every required field present, no unknown field, every enum
    value a declared member, every number inside its declared range and decimal-place
    limit, every datetime a valid ISO 8601 UTC instant, and `window_end_utc` strictly
    after `window_start_utc` — `ERR_INVALID_REQUEST` (400).

    Segments are created `PROPOSED` and their capacity is not yet part of any
    programme total.

    A run offered with its own capacity figure of 9999 is refused because that field
    is not part of the create body, and the same geometry offered without it is sized
    by the server at 443 guests while contributing nothing to the programme yet.

    Design: Corner/entities/queue_segment_capacity_guests_is_computed_and_client_input_ignored
    """
    project = open_project(project_code="TAD-EN7A")
    smuggled = create_queue_segment_payload(project["id"], length_meters=120,
                                            width_meters=2.4)
    smuggled["capacity_guests"] = 9999

    response = api.create_queue_segment(smuggled, DESIGNER)

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
    segments, meta = validate_paginated(
        api.list_project_queue_segments(project["id"], DESIGNER))
    assert segments == []
    assert meta["total_count"] == 0

    honest = validate_success(
        api.create_queue_segment(
            create_queue_segment_payload(project["id"], length_meters=120,
                                         width_meters=2.4),
            DESIGNER,
        ),
        201,
    )
    assert honest["capacity_guests"] == 443
    assert honest["status"] == "PROPOSED"
    assert read_project(project["id"])["queue_capacity_total_guests"] == 0


def test_a_client_supplied_ledger_sequence_number_is_not_a_declared_input(api):
    """Every entry, however it was minted, receives a `sequence_no`: a per-programme ordinal starting at 1 and taken as one greater than the programme's `ledger_sequence_high_water`, which then advances to that value. The `sequence_no` is never accepted from a request body.

    Request-body schema: every required field present, no unknown field, every enum
    value a declared member, every number inside its declared range and decimal-place
    limit, every datetime a valid ISO 8601 UTC instant, and `window_end_utc` strictly
    after `window_start_utc` — `ERR_INVALID_REQUEST` (400).

    Non-reversal entries carry `reversed` false and `reversal_of_sequence_no` null.

    An entry that tries to name its own ordinal 99 is refused outright, and the first
    entry the programme actually accepts is minted as ordinal 1 off a high-water mark
    that was still zero.

    Design: Corner/entities/budget_ledger_sequence_no_is_system_assigned_and_client_input_ignored
    """
    project = open_project(project_code="TAD-EN8A")
    smuggled = create_ledger_entry_payload(project["id"], project["version"])
    smuggled["sequence_no"] = 99

    response = api.create_ledger_entry(smuggled, OWNER)

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
    rows, meta = read_ledger(project["id"])
    assert rows == []
    assert meta["total_count"] == 0

    entry = post_change_order(project["id"], 1000)
    programme = read_project(project["id"])
    assert entry["sequence_no"] == 1
    assert entry["amount_cents"] == 1000
    assert entry["reversed"] is False
    assert entry["reversal_of_sequence_no"] is None
    assert programme["ledger_sequence_high_water"] == 1
    assert programme["committed_cost_cents"] == 1000


def test_an_undeclared_system_type_and_a_single_block_zone_are_both_refused(api):
    """Request-body schema: every required field present, no unknown field, every enum value a declared member, every number inside its declared range and decimal-place limit, every datetime a valid ISO 8601 UTC instant, and `window_end_utc` strictly after `window_start_utc` — `ERR_INVALID_REQUEST` (400).

    First, the control system limits how many vehicles can actually run: the number
    in service is the smaller of `vehicle_count` and one less than
    `block_zone_count`, because one block zone must always stay empty ahead of the
    leading vehicle.

    A suspended monorail is not one of the five declared system types, and a single
    block zone would leave no zone at all for a vehicle to run in; both offers are
    refused on schema and neither is stored.

    Design: Corner/entities/ride_system_unknown_system_type_enum_returns_invalid_request
    """
    project = open_project(project_code="TAD-EN9A")

    unknown_type = api.create_ride_system(
        create_ride_system_payload(project["id"], system_type="SUSPENDED_MONORAIL"),
        ENGINEER,
    )
    single_zone = api.create_ride_system(
        create_ride_system_payload(project["id"], block_zone_count=1), ENGINEER)

    validate_error(unknown_type, ApiErrorId.ERR_INVALID_REQUEST.value)
    validate_error(single_zone, ApiErrorId.ERR_INVALID_REQUEST.value)
    systems, meta = validate_paginated(
        api.list_project_ride_systems(project["id"], ENGINEER))
    assert systems == []
    assert meta["total_count"] == 0


def test_a_ledger_entry_carries_no_revision_counter_at_all(api):
    """Ledger entries and ballots are the two record types that carry only `id` and `created_at`, with no `updated_at` and no `version`.

    Two resources are append-only records of an event rather than living objects,
    and they are deliberately leaner: a **VEBallot** and a **BudgetLedgerEntry** each
    carry only `id` and `created_at`.

    The posted entry reads back exactly as it was minted — ordinal 1, a thousand
    cents, not reversed — and it offers no revision counter to pin an update
    against, because it is a record of something that happened.

    Design: Corner/entities/budget_ledger_entry_is_immutable_and_carries_no_version_field
    """
    project = open_project(project_code="TAD-EN10A")
    posted = post_change_order(project["id"], 1000)

    entry = validate_success(api.get_ledger_entry(posted["id"], OWNER))

    assert_append_only_record(entry)
    assert entry["id"] == posted["id"]
    assert entry["project_id"] == project["id"]
    assert entry["entry_kind"] == "CHANGE_ORDER"
    assert entry["amount_cents"] == 1000
    assert entry["sequence_no"] == 1
    assert entry["reversed"] is False
    assert "version" not in entry
    assert "updated_at" not in entry


def test_a_cue_placed_against_an_unknown_scene_reports_the_scene_not_found(api):
    """Only once the path resolves does the server look up body references: an unresolvable `project_id` yields `ERR_PROJECT_NOT_FOUND`, an unresolvable `ride_system_id` yields `ERR_RIDE_SYSTEM_NOT_FOUND`, an unresolvable `scene_id` or `follows_scene_id` yields `ERR_SCENE_NOT_FOUND`, an unresolvable `design_package_id` yields `ERR_PACKAGE_NOT_FOUND`, an unresolvable `safety_review_id` yields `ERR_REVIEW_NOT_FOUND`, an unresolvable `value_engineering_item_id` yields `ERR_VE_ITEM_NOT_FOUND`, and an unresolvable `rehearsal_run_id` yields `ERR_REHEARSAL_RUN_NOT_FOUND`.

    A cue whose parent scene cannot be resolved is refused with the scene's own 404,
    and the real scene standing beside it keeps an empty timeline.

    Design: Corner/entities/effect_cue_create_with_unknown_parent_scene_not_found
    """
    project = open_project(project_code="TAD-EN11A")
    scene = add_scene(project["id"])

    response = api.create_effect_cue(
        create_effect_cue_payload(NON_EXISTENT_UUID), PROGRAMMER)

    validate_error(response, ApiErrorId.ERR_SCENE_NOT_FOUND.value, 404)
    cues, meta = validate_paginated(
        api.list_scene_effect_cues(scene["id"], PROGRAMMER))
    assert cues == []
    assert meta["total_count"] == 0


def test_a_package_may_not_cite_another_programmes_ride_system(api):
    """The named ride system must belong to the same programme as the named `project_id`; a cross-programme reference is refused with `ERR_RIDE_SYSTEM_PROJECT_MISMATCH`.

    A successful create advances the programme's `version` by one, which is exactly
    why a client creating a second package must re-read the programme first.

    The drawing set is priced against a vehicle that belongs to the neighbouring
    programme, so the create is refused, no package is filed against the citing
    programme, and that programme's revision counter has not moved.

    Design: Corner/entities/design_package_citing_a_ride_system_of_another_project_is_rejected
    """
    citing = open_project(project_code="TAD-EN12A")
    other = open_project(project_code="TAD-EN12B")
    foreign_ride = register_ride_system(other["id"])

    response = api.create_design_package(
        create_design_package_payload(citing["id"], foreign_ride["id"],
                                      project_version(citing["id"])),
        DESIGNER,
    )

    validate_error(response, ApiErrorId.ERR_RIDE_SYSTEM_PROJECT_MISMATCH.value)
    packages, meta = validate_paginated(
        api.list_design_packages(DESIGNER, params={"project_id": citing["id"]}))
    assert packages == []
    assert meta["total_count"] == 0
    assert read_project(citing["id"])["version"] == 1
