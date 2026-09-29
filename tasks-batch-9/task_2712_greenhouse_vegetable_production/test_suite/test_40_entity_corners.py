"""Resource-level corners: creation defaults, single fetches, listing, and payload hygiene.

Every test builds its own compartments, cultivars, cycles and workers from scratch,
because the service starts each test against an empty database with the logical
clock reading 2026-08-01T00:00:00Z.
"""

from test_helpers import (
    CLOCK_EPOCH,
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_four_decimal_places,
    assert_immutable_common_fields,
    assert_money,
    assert_zone,
    create_crop_cycle,
    create_crop_cycle_payload,
    create_scout_worker,
    create_variety,
    create_variety_payload,
    create_worker,
    create_worker_payload,
    create_zone,
    create_zone_payload,
    file_observation,
    read_zone,
    set_clock,
    transition_crop_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)

GM = TEST_USERS["grower_manager_headers"]
IT = TEST_USERS["irrigation_tech_headers"]


def test_new_compartment_reads_every_derived_counter_and_posture_at_its_default(api):
    """PRD §3.1: "Newly registered compartments read `IDLE` for `status`, `NORMAL` for both `ipm_posture` and `irrigation_posture`, zero for `open_pest_alert_count`, `drain_alarm_count`, `hive_slots_used` and `climate_plan_revision`, `0.00` for `labor_budget_committed_usd` with `labor_budget_remaining_usd` equal to the full `labor_budget_usd`, a null `reentry_clear_at`, and `version` 1."

    Design: Corner/entities/zone_create_returns_every_declared_field_with_postures_at_their_defaults
    """
    set_clock(CLOCK_EPOCH)

    response = api.create_zone(
        create_zone_payload(code="ZC-01", labor_budget_usd=20000.00), GM
    )
    zone = validate_success(response, 201)

    assert_zone(zone)
    assert zone["status"] == "IDLE", f"expected IDLE, got {zone['status']}"
    assert zone["ipm_posture"] == "NORMAL", f"expected NORMAL, got {zone['ipm_posture']}"
    assert zone["irrigation_posture"] == "NORMAL", (
        f"expected NORMAL, got {zone['irrigation_posture']}"
    )
    assert zone["open_pest_alert_count"] == 0
    assert zone["drain_alarm_count"] == 0
    assert zone["hive_slots_used"] == 0
    assert zone["climate_plan_revision"] == 0
    assert_money(zone["labor_budget_committed_usd"], 0.00, "labor_budget_committed_usd")
    assert_money(zone["labor_budget_remaining_usd"], 20000.00, "labor_budget_remaining_usd")
    assert zone["reentry_clear_at"] is None, "a new compartment has no re-entry interval"
    assert zone["version"] == 1, f"version starts at 1, got {zone['version']}"


def test_any_role_may_fetch_one_compartment_and_sees_the_stored_row(api):
    """PRD §2.1: "All six roles may read every collection and every single-resource fetch."

    Design: Corner/entities/zone_get_by_id_returns_the_stored_row_unchanged
    """
    set_clock(CLOCK_EPOCH)
    zone = create_zone(code="ZC-02", area_sqft=9450, labor_budget_usd=20000.00)

    response = api.get_zone(zone["id"], IT)
    fetched = validate_success(response, 200)

    assert response.json()["response_type"] == "object", (
        "a single-resource fetch carries response_type object"
    )
    assert fetched["id"] == zone["id"]
    assert fetched["code"] == "ZC-02", f"expected ZC-02, got {fetched['code']}"
    assert fetched["area_sqft"] == 9450
    assert_money(
        fetched["labor_budget_remaining_usd"], 20000.00, "labor_budget_remaining_usd"
    )


def test_worker_list_meta_counts_the_filtered_rows_not_the_page(api):
    """PRD §2.3: "`total_count` is the number of rows matching the filters before pagination is applied, and `has_more` is true exactly when rows remain beyond the current page."

    Design: Corner/entities/worker_list_is_paginated_with_total_count_and_has_more
    """
    set_clock(CLOCK_EPOCH)
    create_worker()
    create_worker(full_name="Petra Lund", productivity_index=1.00)
    create_scout_worker()

    first_page, first_meta = validate_paginated(
        api.list_workers(GM, params={"skill": "HARVEST", "limit": 1, "offset": 0})
    )
    second_page, second_meta = validate_paginated(
        api.list_workers(GM, params={"skill": "HARVEST", "limit": 1, "offset": 1})
    )

    assert first_meta["total_count"] == 2, (
        f"two HARVEST workers match the filter, meta says {first_meta['total_count']}"
    )
    assert first_meta["limit"] == 1 and first_meta["offset"] == 0
    assert first_meta["has_more"] is True, "a second HARVEST row remains beyond page one"
    assert len(first_page) == 1

    assert second_meta["total_count"] == 2
    assert second_meta["limit"] == 1 and second_meta["offset"] == 1
    assert second_meta["has_more"] is False, "no HARVEST row remains beyond page two"
    assert len(second_page) == 1


def test_worker_list_pages_walk_the_filtered_rows_in_creation_order(api):
    """PRD §2.3: "Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending."

    Design: Corner/entities/worker_list_is_paginated_with_total_count_and_has_more
    """
    set_clock(CLOCK_EPOCH)
    first_harvest_worker = create_worker()
    second_harvest_worker = create_worker(full_name="Petra Lund", productivity_index=1.00)
    scout_worker = create_scout_worker()

    page_one, _ = validate_paginated(
        api.list_workers(GM, params={"skill": "HARVEST", "limit": 1, "offset": 0})
    )
    page_two, _ = validate_paginated(
        api.list_workers(GM, params={"skill": "HARVEST", "limit": 1, "offset": 1})
    )

    assert page_one[0]["id"] == first_harvest_worker["id"], (
        "the oldest HARVEST worker heads the first page"
    )
    assert page_two[0]["id"] == second_harvest_worker["id"], (
        "the next HARVEST worker by creation order heads the second page"
    )
    listed_ids = {row["id"] for row in page_one + page_two}
    assert scout_worker["id"] not in listed_ids, (
        "the SCOUT worker is excluded by the skill filter"
    )


def test_fetching_a_crop_cycle_that_was_never_planned_is_a_not_found(api):
    """PRD §2.11: "Where a path does carry an identifier, or carries an identifier followed by a sub-path segment, identifiers are resolved strictly left to right and the first one that does not exist determines the 404."

    Design: Corner/entities/crop_cycle_get_with_an_unknown_id_returns_not_found
    """
    set_clock(CLOCK_EPOCH)

    response = api.get_crop_cycle(NON_EXISTENT_UUID, GM)

    validate_error(response, ApiErrorId.ERR_CROP_CYCLE_NOT_FOUND.value)
    assert response.json()["response_type"] == "error"


def test_registering_a_cultivar_without_its_ec_target_is_rejected(api):
    """PRD §2.10: "Every field the operation declares as required is present and of the declared type — `ERR_VALIDATION`, 422."

    Design: Corner/entities/variety_create_missing_a_required_field_is_rejected
    """
    set_clock(CLOCK_EPOCH)
    payload = create_variety_payload()
    payload.pop("ec_target_ms")

    response = api.create_variety(payload, GM)

    validate_error(response, ApiErrorId.ERR_VALIDATION.value)

    _, meta = validate_paginated(api.list_varieties(GM))
    assert meta["total_count"] == 0, "the rejected create must not write a cultivar"


def test_worker_registration_defaults_the_productivity_index_and_employment_status(api):
    """PRD §3.8: "Two fields are optional at registration: `productivity_index`, a multiplier applied to the productivity standard of any task this worker is given, which must be at least 0.5 and at most 2.0 and defaults to `1.00`; and `status`, either `ACTIVE` or `INACTIVE`, which defaults to `ACTIVE`."

    Design: Corner/entities/worker_create_omitting_optional_fields_applies_the_declared_defaults
    """
    set_clock(CLOCK_EPOCH)
    payload = create_worker_payload(full_name="Default Dana", hourly_rate_usd=19.50)
    payload.pop("productivity_index")
    payload.pop("status")

    worker = validate_success(api.create_worker(payload, GM), 201)

    assert worker["productivity_index"] == 1.00, (
        f"productivity_index defaults to 1.00, got {worker['productivity_index']}"
    )
    assert worker["status"] == "ACTIVE", (
        f"status defaults to ACTIVE, got {worker['status']}"
    )


def test_newly_registered_worker_carries_no_committed_hours(api):
    """PRD §3.8: "A newly registered worker has `committed_hours` of `0.00`."

    Design: Corner/entities/worker_create_omitting_optional_fields_applies_the_declared_defaults
    """
    set_clock(CLOCK_EPOCH)
    payload = create_worker_payload(full_name="Default Dana", hourly_rate_usd=19.50)
    payload.pop("productivity_index")
    payload.pop("status")

    worker = validate_success(api.create_worker(payload, GM), 201)

    assert_money(worker["committed_hours"], 0.00, "committed_hours")


def test_client_supplied_yield_figures_on_a_crop_cycle_are_discarded(api):
    """PRD §2.10: "Computed and system-managed fields that appear in a payload are silently ignored rather than rejected."

    Design: Corner/entities/crop_cycle_computed_density_factor_ignores_an_extra_field_in_the_payload
    """
    set_clock(CLOCK_EPOCH)
    zone = create_zone(code="ZC-03", area_sqft=9450)
    variety = create_variety()

    payload = create_crop_cycle_payload(
        zone["id"],
        variety["id"],
        transplant_date="2026-08-03",
        plants_transplanted=2157,
        density_factor=5.0,
        expected_total_yield_lbs=1.0,
    )
    cycle = validate_success(api.create_crop_cycle(payload, GM), 201)

    assert_four_decimal_places(cycle["density_factor"], 0.9511, "density_factor")
    assert_money(cycle["expected_total_yield_lbs"], 82688.64, "expected_total_yield_lbs")


def test_crop_cycle_dates_are_derived_from_the_cultivar_not_from_the_client(api):
    """PRD §3.2: "A cycle transplanted on 2026-08-03 under a 13-week cultivar whose first harvest week is 4 therefore has a `planned_end_date` of 2026-10-31 and a `first_harvest_allowed_date` of 2026-08-24."

    Design: Corner/entities/crop_cycle_computed_density_factor_ignores_an_extra_field_in_the_payload
    """
    set_clock(CLOCK_EPOCH)
    zone = create_zone(code="ZC-03", area_sqft=9450)
    variety = create_variety(cycle_length_weeks=13, first_harvest_week=4)

    cycle = create_crop_cycle(
        zone["id"], variety["id"], transplant_date="2026-08-03", plants_transplanted=2157
    )

    assert cycle["first_harvest_allowed_date"] == "2026-08-24", (
        "expected first_harvest_allowed_date 2026-08-24, got "
        f"{cycle['first_harvest_allowed_date']}"
    )


def test_client_supplied_identity_fields_on_a_compartment_are_discarded(api):
    """PRD §2.10: "Computed and system-managed fields that appear in a payload are silently ignored rather than rejected."

    Design: Corner/entities/zone_create_with_a_client_supplied_id_extra_field_ignored
    """
    set_clock(CLOCK_EPOCH)
    payload = create_zone_payload(
        code="ZC-04",
        id="11111111-1111-4111-8111-111111111111",
        version=99,
        created_at="2000-01-01T00:00:00Z",
    )

    zone = validate_success(api.create_zone(payload, GM), 201)

    assert zone["id"] != "11111111-1111-4111-8111-111111111111", (
        "the identifier is server-minted, not taken from the payload"
    )
    assert zone["version"] == 1, f"version starts at 1, got {zone['version']}"
    assert not zone["created_at"].startswith("2000-01-01"), (
        f"created_at is server-minted, got {zone['created_at']}"
    )


def test_registering_a_cultivar_with_an_undeclared_crop_type_is_rejected(api):
    """PRD §2.10: "Every enum-typed field carries a declared member of its enumeration — `ERR_INVALID_ENUM_VALUE`, 422."

    Design: Corner/entities/variety_create_with_an_invalid_enum_crop_type_is_rejected
    """
    set_clock(CLOCK_EPOCH)

    response = api.create_variety(
        create_variety_payload(name="Mystery Crop", crop_type="DURIAN"), GM
    )

    validate_error(response, ApiErrorId.ERR_INVALID_ENUM_VALUE.value)

    _, meta = validate_paginated(api.list_varieties(GM))
    assert meta["total_count"] == 0, "the rejected create must not write a cultivar"


def test_cultivar_and_observation_reads_carry_no_updated_at_and_no_version(api):
    """PRD §2.4: "Two resource kinds are immutable once written and therefore carry only `id` and `created_at` — they have no `updated_at` field and no `version` field at all."

    Design: Corner/entities/immutable_variety_and_observation_rows_carry_no_version_and_no_writer
    """
    set_clock("2026-08-06T00:00:00Z")
    zone = create_zone(code="ZC-05")
    variety = create_variety()
    cycle = create_crop_cycle(zone["id"], variety["id"])
    transition_crop_cycle(cycle["id"], "TRANSPLANTED")
    scout = create_scout_worker()
    observation = file_observation(
        zone["id"],
        cycle["id"],
        scout["id"],
        observed_at="2026-08-06T08:00:00Z",
        pest_code="WHITEFLY",
        pest_count_per_plant=0.400,
    )

    fetched_variety = validate_success(api.get_variety(variety["id"], GM), 200)
    fetched_observation = validate_success(
        api.get_scouting_observation(observation["id"], GM), 200
    )

    assert fetched_variety["id"] == variety["id"]
    assert fetched_observation["id"] == observation["id"]
    assert_immutable_common_fields(fetched_variety)
    assert_immutable_common_fields(fetched_observation)


def test_a_below_threshold_round_leaves_the_compartment_posture_untouched(api):
    """PRD §3.6: "A below-threshold observation is filed normally, sets `release_required` false, and leaves the compartment's posture entirely untouched."

    Design: Corner/entities/immutable_variety_and_observation_rows_carry_no_version_and_no_writer
    """
    set_clock("2026-08-06T00:00:00Z")
    zone = create_zone(code="ZC-05")
    variety = create_variety()
    cycle = create_crop_cycle(zone["id"], variety["id"])
    transition_crop_cycle(cycle["id"], "TRANSPLANTED")
    scout = create_scout_worker()

    observation = file_observation(
        zone["id"],
        cycle["id"],
        scout["id"],
        observed_at="2026-08-06T08:00:00Z",
        pest_code="WHITEFLY",
        pest_count_per_plant=0.400,
    )

    assert observation["threshold_status"] == "BELOW", (
        f"0.400 is below the whitefly threshold, got {observation['threshold_status']}"
    )
    assert observation["release_required"] is False
    after = read_zone(zone["id"])
    assert after["open_pest_alert_count"] == 0, (
        "a below-threshold round opens no pest alert"
    )
    assert after["ipm_posture"] == "NORMAL", (
        f"the pest gate stays NORMAL, got {after['ipm_posture']}"
    )


def test_planning_a_cycle_against_an_unknown_cultivar_is_a_not_found(api):
    """PRD §2.11: "The same codes serve for body foreign keys: an unknown `variety_id` yields `ERR_VARIETY_NOT_FOUND`, an unknown `worker_id` yields `ERR_WORKER_NOT_FOUND`, an unknown `observation_id` yields `ERR_SCOUTING_OBSERVATION_NOT_FOUND`, an unknown `program_id` yields `ERR_RETAIL_PROGRAM_NOT_FOUND`, and an unknown `labor_task_id` yields `ERR_LABOR_TASK_NOT_FOUND`."

    Design: Corner/entities/crop_cycle_create_with_an_unknown_variety_id_returns_not_found
    """
    set_clock(CLOCK_EPOCH)
    zone = create_zone(code="ZC-06")

    response = api.create_crop_cycle(
        create_crop_cycle_payload(zone["id"], NON_EXISTENT_UUID), GM
    )

    validate_error(response, ApiErrorId.ERR_VARIETY_NOT_FOUND.value)

    _, meta = validate_paginated(api.list_crop_cycles(GM))
    assert meta["total_count"] == 0, "the rejected plan must not write a crop cycle"
    assert read_zone(zone["id"])["status"] == "IDLE", (
        "an unoccupied compartment stays IDLE"
    )
