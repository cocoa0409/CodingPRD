"""Record shapes: seeded ledgers, declared defaults, server-minted system fields."""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.assertions import (
    assert_append_only_row,
    assert_classification,
    assert_demand_ledger,
    assert_density,
    assert_empty_ledger,
    assert_flow,
    assert_identity_fields,
    assert_money,
    assert_posture,
    assert_pressure,
    assert_versioned_row,
)
from test_helpers.factories import (
    build_auxiliary_system_payload,
    build_flow_test_payload,
    build_hazard_area_payload,
    build_hydraulic_calculation_payload,
    build_project_payload,
)
from test_helpers.fixtures import (
    ADMIN_HEADERS,
    CONTRACTOR_HEADERS,
    build_directory,
    build_project_stage,
    create_auxiliary_system,
    create_calculation,
    create_engineer,
    create_flow_test,
    create_hazard_area,
    create_project,
    create_reviewer,
    read_auxiliary_system,
    read_hazard_area,
    read_project,
)
from test_helpers.test_users import make_design_engineer_headers

FP2601 = dict(
    project_number="FP-2601",
    building_name="Rio Grande Distribution Center",
    jurisdiction_code="TX-AUS",
    jurisdiction_state="TX",
    occupancy_type="STORAGE",
    building_height_ft=42.0,
    underground_lead_in_loss_psi=5.0,
)

# Rack bay HA-1: CLASS_IV stored 18 ft high escalates ORDINARY_2 to EXTRA_1.
RACK_BAY_A = dict(
    label="Rack Storage Bay A",
    hazard_class="ORDINARY_2",
    commodity_class="CLASS_IV",
    storage_height_ft=18.0,
    ceiling_height_ft=36.0,
    area_sqft=24000.0,
    sprinkler_system_type="WET",
    ceiling_slope_pct=4.0,
    room_area_sqft=None,
    enclosure_rating_hours=None,
    room_has_unprotected_opening=None,
)


class TestProjectRecordSeed:
    def test_01_a_new_project_seeds_the_whole_ledger_and_every_counter_at_zero(
        self, client
    ):
        """A newly opened project starts at `status` `DESIGN` with `design_posture` `OPEN`.
        Its ledger starts empty: `governing_hydraulic_calculation_id` is null and
        `governing_demand_gpm`, `auxiliary_demand_gpm` and `total_system_demand_gpm` are
        all 0.0.

        Design: Corner/entities/project_creation_seeds_the_whole_demand_ledger_at_zero
        """
        engineer = create_engineer(client, license_status="ACTIVE")
        reviewer = create_reviewer(client)
        payload = build_project_payload(
            lead_engineer_id=engineer["id"],
            ahj_reviewer_id=reviewer["id"],
            **FP2601,
        )
        project = validate_success(
            client.create_project(payload, ADMIN_HEADERS), expected_status=201
        )

        assert project["status"] == "DESIGN"
        assert_posture(project, "OPEN")
        assert_demand_ledger(project, None, 0.0, 0.0, 0.0)
        assert_empty_ledger(project)
        assert project["sealed_calculation_count"] == 0
        assert project["open_major_comment_count"] == 0
        assert project["submittal_cycle_count"] == 0
        assert_money(project["review_fee_balance_usd"], 0.00)
        assert project["pump_required_flag"] is False
        assert_pressure(project["underground_lead_in_loss_psi"], 5.0)
        assert project["lead_engineer_id"] == engineer["id"]
        assert project["ahj_reviewer_id"] == reviewer["id"]
        assert_versioned_row(project, expected_version=1)

    def test_02_the_seeded_figures_survive_a_read_back(self, client):
        """Its counters start at zero — `sealed_calculation_count`,
        `open_major_comment_count` and `submittal_cycle_count` — its
        `review_fee_balance_usd` starts at 0.00, and `pump_required_flag`, the derived
        marker that this design cannot be supplied without a fire pump, starts false.

        Design: Corner/entities/project_creation_seeds_the_whole_demand_ledger_at_zero
        """
        ctx = build_project_stage(client, **FP2601)
        project = read_project(client, ctx["project_id"])
        assert project["project_number"] == "FP-2601"
        assert project["building_name"] == "Rio Grande Distribution Center"
        assert project["occupancy_type"] == "STORAGE"
        assert project["building_height_ft"] == 42.0
        assert_demand_ledger(project, None, 0.0, 0.0, 0.0)
        assert project["pump_required_flag"] is False
        assert_money(project["review_fee_balance_usd"], 0.00)
        assert_versioned_row(project, expected_version=1)


class TestHazardAreaRead:
    def test_03_the_area_read_carries_both_the_stored_inputs_and_the_derived_figures(
        self, client
    ):
        """Declaring the area immediately derives its classification, in three ordered
        steps, and the outputs are `effective_hazard_class`, `design_density`,
        `design_area_sqft` and `hose_allowance_gpm`.

        Design: Corner/entities/hazard_area_read_returns_the_stored_inputs_and_the_derived_classification
        """
        ctx = build_project_stage(client, **FP2601)
        created = create_hazard_area(
            client, ctx["project_id"], ctx["lead_id"], **RACK_BAY_A
        )
        area = read_hazard_area(client, created["id"])

        # Stored inputs come back exactly as declared.
        assert area["project_id"] == ctx["project_id"]
        assert area["label"] == "Rack Storage Bay A"
        assert area["hazard_class"] == "ORDINARY_2"
        assert area["commodity_class"] == "CLASS_IV"
        assert area["storage_height_ft"] == 18.0
        assert area["ceiling_height_ft"] == 36.0
        assert area["area_sqft"] == 24000.0
        assert area["sprinkler_system_type"] == "WET"
        assert area["ceiling_slope_pct"] == 4.0
        assert area["room_area_sqft"] is None

        # CLASS_IV above 15 ft escalates one position, and the 36 ft ceiling earns one
        # whole 5 ft density step above 30 ft.
        assert_classification(area, "EXTRA_1", 0.320, 2500, 500.0)
        assert area["reclassification_count"] == 0
        assert_versioned_row(area, expected_version=1)

    def test_04_the_declared_class_is_kept_alongside_the_escalated_one(self, client):
        """The classification also initialises `reclassification_count` to 0.

        Design: Corner/entities/hazard_area_read_returns_the_stored_inputs_and_the_derived_classification
        """
        ctx = build_project_stage(client, **FP2601)
        created = create_hazard_area(
            client, ctx["project_id"], ctx["lead_id"], **RACK_BAY_A
        )
        area = read_hazard_area(client, created["id"])
        assert area["hazard_class"] == "ORDINARY_2"
        assert area["effective_hazard_class"] == "EXTRA_1"
        assert area["hazard_class"] != area["effective_hazard_class"]
        assert_density(area["design_density"], 0.320)
        assert area["reclassification_count"] == 0


CLASS_I_RISERS = dict(
    system_type="STANDPIPE_CLASS_I", label="Stair Standpipe Risers", riser_count=2
)
HOOD = dict(
    system_type="COOKING",
    label="Cafeteria Hood",
    appliance_count=4,
    water_wash_enabled=True,
    agent_type="WET_CHEMICAL",
)
HOSE_STATION = dict(
    system_type="STANDPIPE_CLASS_II", label="Office Hose Station", riser_count=1
)


def _three_auxiliaries(client):
    """One Class I standpipe, one hood and one Class II hose station on FP-2601."""
    ctx = build_project_stage(client, **FP2601)
    ctx["systems"] = [
        create_auxiliary_system(client, ctx["project_id"], ctx["lead_id"], **spec)
        for spec in (CLASS_I_RISERS, HOOD, HOSE_STATION)
    ]
    return ctx


class TestAuxiliarySystemListing:
    def test_05_the_first_page_reports_the_unpaginated_total_and_more_to_come(
        self, client
    ):
        """`total_count` counts every row matching the filters before pagination is applied
        and `has_more` is true when rows remain beyond the current page.

        Design: Corner/entities/auxiliary_system_listing_paginates_with_total_count_and_has_more
        """
        ctx = _three_auxiliaries(client)
        headers = make_design_engineer_headers(ctx["lead_id"])
        rows, meta = validate_paginated(
            client.list_auxiliary_systems(
                headers,
                params={"project_id": ctx["project_id"], "limit": 2, "offset": 0},
            )
        )
        assert len(rows) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0

    def test_06_the_last_page_returns_the_remainder_with_has_more_false(self, client):
        """Systems can be listed by `project_id`, `hazard_area_id`, `system_type` or
        `status`.

        Design: Corner/entities/auxiliary_system_listing_paginates_with_total_count_and_has_more
        """
        ctx = _three_auxiliaries(client)
        headers = make_design_engineer_headers(ctx["lead_id"])
        first, _ = validate_paginated(
            client.list_auxiliary_systems(
                headers,
                params={"project_id": ctx["project_id"], "limit": 2, "offset": 0},
            )
        )
        last, meta = validate_paginated(
            client.list_auxiliary_systems(
                headers,
                params={"project_id": ctx["project_id"], "limit": 2, "offset": 2},
            )
        )
        assert len(last) == 1
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert meta["offset"] == 2

        paged_ids = [row["id"] for row in first] + [row["id"] for row in last]
        assert sorted(paged_ids) == sorted(row["id"] for row in ctx["systems"])

        by_type = {row["system_type"]: row for row in ctx["systems"]}
        assert_flow(by_type["STANDPIPE_CLASS_I"]["demand_gpm"], 750.0)
        assert_flow(by_type["COOKING"]["demand_gpm"], 160.0)
        assert_flow(by_type["STANDPIPE_CLASS_II"]["demand_gpm"], 100.0)
        assert_demand_ledger(
            read_project(client, ctx["project_id"]), None, 0.0, 1010.0, 1010.0
        )


class TestUnknownIdentifierReads:
    def test_07_reading_a_fire_pump_that_was_never_sized_is_a_not_found(self, client):
        """Every `{id}` path parameter resolves to an existing row, validated left to right
        along the path — the matching one of ... `ERR_FIRE_PUMP_NOT_FOUND` ... (404).

        Design: Corner/entities/fire_pump_read_with_an_unknown_id_returns_not_found
        """
        build_project_stage(client, **FP2601)
        refused = client.get_fire_pump(NON_EXISTENT_UUID, ADMIN_HEADERS)
        validate_error(refused, "ERR_FIRE_PUMP_NOT_FOUND", expected_status=404)

    def test_08_an_empty_pump_catalogue_still_answers_the_read_with_not_found(
        self, client
    ):
        """Every resource is addressed by an `id` that is a server-minted UUID with no
        type prefix.

        Design: Corner/entities/fire_pump_read_with_an_unknown_id_returns_not_found
        """
        ctx = build_project_stage(client, **FP2601)
        rows, meta = validate_paginated(
            client.list_fire_pumps(ADMIN_HEADERS, params={"project_id": ctx["project_id"]})
        )
        assert rows == []
        assert meta["total_count"] == 0
        validate_error(
            client.get_fire_pump(NON_EXISTENT_UUID, ADMIN_HEADERS),
            "ERR_FIRE_PUMP_NOT_FOUND",
            expected_status=404,
        )


class TestFlowTestRequiredFields:
    def test_09_a_flow_test_without_a_tested_at_stamp_is_an_invalid_request(self, client):
        """The body conforms to the endpoint's input schema: required fields present, types
        correct, enum members recognised, numeric ranges satisfied ... — `ERR_INVALID_REQUEST`
        (422).

        Design: Corner/entities/flow_test_creation_missing_required_tested_at_is_invalid_request
        """
        ctx = build_project_stage(client, **FP2601)
        payload = build_flow_test_payload(
            project_id=ctx["project_id"],
            hydrant_tag="H-14",
            static_psi=80.0,
            residual_psi=64.0,
            flow_gpm=2250.0,
        )
        del payload["tested_at"]
        refused = client.create_flow_test(payload, CONTRACTOR_HEADERS)
        validate_error(refused, "ERR_INVALID_REQUEST", expected_status=422)

    def test_10_the_refused_flow_test_leaves_the_project_list_empty(self, client):
        """A flow test is immutable once recorded, and every test taken for a project can be
        listed from the project.

        Design: Corner/entities/flow_test_creation_missing_required_tested_at_is_invalid_request
        """
        ctx = build_project_stage(client, **FP2601)
        payload = build_flow_test_payload(project_id=ctx["project_id"])
        del payload["tested_at"]
        validate_error(client.create_flow_test(payload, CONTRACTOR_HEADERS), "ERR_INVALID_REQUEST")

        rows, meta = validate_paginated(
            client.list_project_flow_tests(ctx["project_id"], ADMIN_HEADERS)
        )
        assert rows == []
        assert meta["total_count"] == 0


class TestDeclaredDefaults:
    def test_11_the_two_directory_records_take_their_declared_defaults(self, client):
        """Two further attributes may be supplied and otherwise take defaults:
        `license_status`, one of `ACTIVE`, `EXPIRED` or `SUSPENDED`, defaulting to
        `ACTIVE`; and `discipline`, one of `FIRE_PROTECTION`, `MECHANICAL` or
        `ELECTRICAL`, defaulting to `FIRE_PROTECTION`.

        Design: Corner/entities/omitted_optional_inputs_fall_back_to_their_declared_defaults
        """
        engineer = create_engineer(
            client,
            full_name="Owen Petrov",
            license_state="TX",
            license_number="PE-91004",
        )
        assert engineer["license_status"] == "ACTIVE"
        assert engineer["discipline"] == "FIRE_PROTECTION"
        assert_identity_fields(engineer)

        reviewer = create_reviewer(
            client, full_name="Nadia Frost", jurisdiction_code="TX-AUS"
        )
        assert reviewer["discipline"] == "FIRE"

    def test_12_an_omitted_lead_in_allowance_defaults_to_no_pressure_adder(self, client):
        """An optional `underground_lead_in_loss_psi`, which must not be negative and
        defaults to 0.0, records the fixed friction allowance for the underground lead-in
        between the city main and the base of riser.

        Design: Corner/entities/omitted_optional_inputs_fall_back_to_their_declared_defaults
        """
        engineer = create_engineer(
            client, full_name="Owen Petrov", license_number="PE-91004"
        )
        reviewer = create_reviewer(client, full_name="Nadia Frost")
        project = create_project(
            client,
            engineer["id"],
            reviewer["id"],
            project_number="FP-2604",
            building_name="Default Fixture Building",
            occupancy_type="MERCANTILE",
            building_height_ft=20.0,
            underground_lead_in_loss_psi=None,
        )
        assert_pressure(project["underground_lead_in_loss_psi"], 0.0)

    def test_13_an_omitted_slope_and_opening_flag_leave_the_base_classification(
        self, client
    ):
        """Four further inputs are optional: `ceiling_slope_pct`, the ceiling slope as a
        percentage, which must not be negative and defaults to 0.0; ... and
        `room_has_unprotected_opening`, a flag defaulting to false.

        Design: Corner/entities/omitted_optional_inputs_fall_back_to_their_declared_defaults
        """
        engineer = create_engineer(
            client, full_name="Owen Petrov", license_number="PE-91004"
        )
        reviewer = create_reviewer(client, full_name="Nadia Frost")
        project = create_project(
            client,
            engineer["id"],
            reviewer["id"],
            project_number="FP-2604",
            building_name="Default Fixture Building",
            occupancy_type="MERCANTILE",
            building_height_ft=20.0,
            underground_lead_in_loss_psi=None,
        )
        payload = build_hazard_area_payload(
            project_id=project["id"],
            label="Sales Floor",
            hazard_class="ORDINARY_1",
            commodity_class="CLASS_III",
            storage_height_ft=8.0,
            ceiling_height_ft=12.0,
            area_sqft=1800.0,
            sprinkler_system_type="WET",
            ceiling_slope_pct=None,
            room_area_sqft=None,
            enclosure_rating_hours=None,
            room_has_unprotected_opening=None,
        )
        area = validate_success(
            client.create_hazard_area(
                payload, make_design_engineer_headers(engineer["id"])
            ),
            expected_status=201,
        )
        assert_pressure(area["ceiling_slope_pct"], 0.0)
        assert area["room_has_unprotected_opening"] is False
        assert area["room_area_sqft"] is None
        assert area["enclosure_rating_hours"] is None
        # No escalation, no multiplier and no ceiling bump: the base pair stands.
        assert_classification(area, "ORDINARY_1", 0.150, 1500, 250.0)


class TestCalculationDemandSnapshot:
    def test_14_every_demand_figure_on_a_new_calculation_is_derived_not_supplied(
        self, client
    ):
        """The engineer opens one by naming the `project_id`, the `hazard_area_id` of the
        most demanding area it demonstrates, the `method` by which the demand is computed —
        either `AREA_DENSITY` or `ROOM_DESIGN` — and the `k_factor`.

        Design: Corner/entities/hydraulic_calculation_demand_snapshot_is_computed_not_supplied
        """
        ctx = build_project_stage(client, **FP2601)
        area = create_hazard_area(client, ctx["project_id"], ctx["lead_id"], **RACK_BAY_A)
        payload = build_hydraulic_calculation_payload(
            project_id=ctx["project_id"],
            hazard_area_id=area["id"],
            method="AREA_DENSITY",
            k_factor=25.2,
        )
        assert sorted(payload) == [
            "hazard_area_id",
            "k_factor",
            "method",
            "project_id",
        ], "the endpoint accepts no demand figures at all"

        calculation = validate_success(
            client.create_hydraulic_calculation(
                payload, make_design_engineer_headers(ctx["lead_id"])
            ),
            expected_status=201,
        )
        # 0.320 gpm/sqft over 2500 sqft at the 1.10 overdischarge factor.
        assert_flow(calculation["design_flow_gpm"], 880.0)
        assert_flow(calculation["hose_allowance_gpm"], 500.0)
        assert_flow(calculation["room_design_penalty_gpm"], 0.0)
        assert_flow(calculation["hazard_total_demand_gpm"], 1380.0)

    def test_15_the_author_is_taken_from_the_acting_identity_and_the_chain_starts_empty(
        self, client
    ):
        """The server records `authored_by_engineer_id` from the acting engineer's
        identifier; the client never supplies it. A new calculation opens in state `DRAFT`
        with `chain_start_index` 1, `iteration_count` 0, `end_head_psi` 0.0 and
        `required_psi_at_base_of_riser` 0.0.

        Design: Corner/entities/hydraulic_calculation_demand_snapshot_is_computed_not_supplied
        """
        ctx = build_project_stage(client, **FP2601)
        area = create_hazard_area(client, ctx["project_id"], ctx["lead_id"], **RACK_BAY_A)
        calculation = create_calculation(
            client, ctx["project_id"], area["id"], ctx["lead_id"], k_factor=25.2
        )
        assert calculation["authored_by_engineer_id"] == ctx["lead_id"]
        assert calculation["state"] == "DRAFT"
        assert calculation["chain_start_index"] == 1
        assert calculation["iteration_count"] == 0
        assert_pressure(calculation["end_head_psi"], 0.0)
        assert_pressure(calculation["required_psi_at_base_of_riser"], 0.0)

        # A DRAFT calculation is not eligible, so the ledger stays empty.
        assert_empty_ledger(read_project(client, ctx["project_id"]))


class TestProjectSystemFields:
    def test_16_the_identity_and_version_fields_are_minted_by_the_server(self, client):
        """Most resources additionally carry `updated_at`, in the same format, and `version`,
        an integer that starts at 1 on creation and increases by exactly 1 on every mutation
        of that row.

        Design: Corner/entities/project_system_fields_are_server_minted_and_version_moves_on_every_write
        """
        directory = build_directory(client)
        payload = build_project_payload(
            lead_engineer_id=directory["lead_engineer"]["id"],
            ahj_reviewer_id=directory["reviewer"]["id"],
            **FP2601,
        )
        assert "id" not in payload
        assert "version" not in payload
        assert "created_at" not in payload

        project = validate_success(
            client.create_project(payload, ADMIN_HEADERS), expected_status=201
        )
        assert_versioned_row(project, expected_version=1)

    def test_17_one_auxiliary_write_moves_the_project_version_by_exactly_one(
        self, client
    ):
        """Whenever a write changes a row — whether the client addressed that row directly or
        the row moved as a downstream consequence of some other write — both `updated_at` and
        `version` advance on it.

        Design: Corner/entities/project_system_fields_are_server_minted_and_version_moves_on_every_write
        """
        ctx = build_project_stage(client, **FP2601)
        before = read_project(client, ctx["project_id"])
        assert_versioned_row(before, expected_version=1)

        create_auxiliary_system(
            client, ctx["project_id"], ctx["lead_id"], **CLASS_I_RISERS
        )
        after = read_project(client, ctx["project_id"])
        assert after["version"] == before["version"] + 1
        assert after["id"] == before["id"]
        assert after["created_at"] == before["created_at"]
        assert_flow(after["auxiliary_demand_gpm"], 750.0)
        assert_flow(after["total_system_demand_gpm"], 750.0)


class TestSchemaViolations:
    def test_18_an_unrecognised_enum_member_is_refused_on_both_writes(self, client):
        """The body conforms to the endpoint's input schema: required fields present, types
        correct, enum members recognised, numeric ranges satisfied ... — `ERR_INVALID_REQUEST`
        (422).

        Design: Corner/entities/enum_and_numeric_range_violations_are_rejected_as_invalid_request
        """
        directory = build_directory(client)
        bad_occupancy = build_project_payload(
            lead_engineer_id=directory["lead_engineer"]["id"],
            ahj_reviewer_id=directory["reviewer"]["id"],
            **dict(FP2601, occupancy_type="WAREHOUSE"),
        )
        validate_error(
            client.create_project(bad_occupancy, ADMIN_HEADERS),
            "ERR_INVALID_REQUEST",
            expected_status=422,
        )

        ctx = build_project_stage(client, **FP2601)
        area = create_hazard_area(client, ctx["project_id"], ctx["lead_id"], **RACK_BAY_A)
        bad_method = build_hydraulic_calculation_payload(
            project_id=ctx["project_id"],
            hazard_area_id=area["id"],
            method="PIPE_SCHEDULE",
            k_factor=25.2,
        )
        validate_error(
            client.create_hydraulic_calculation(
                bad_method, make_design_engineer_headers(ctx["lead_id"])
            ),
            "ERR_INVALID_REQUEST",
            expected_status=422,
        )

    def test_19_a_bound_violation_is_refused_on_the_reading_and_the_riser_count(
        self, client
    ):
        """... `included_calculation_ids` non-empty and free of duplicates, and
        `residual_psi` strictly below `static_psi` — `ERR_INVALID_REQUEST` (422).

        Design: Corner/entities/enum_and_numeric_range_violations_are_rejected_as_invalid_request
        """
        ctx = build_project_stage(client, **FP2601)
        flat_reading = build_flow_test_payload(
            project_id=ctx["project_id"], static_psi=80.0, residual_psi=80.0
        )
        validate_error(
            client.create_flow_test(flat_reading, CONTRACTOR_HEADERS),
            "ERR_INVALID_REQUEST",
            expected_status=422,
        )

        # Both standpipe classes require riser_count, which must be at least 1.
        no_risers = build_auxiliary_system_payload(
            project_id=ctx["project_id"],
            system_type="STANDPIPE_CLASS_I",
            label="Stair Standpipe Risers",
            riser_count=0,
        )
        validate_error(
            client.create_auxiliary_system(
                no_risers, make_design_engineer_headers(ctx["lead_id"])
            ),
            "ERR_INVALID_REQUEST",
            expected_status=422,
        )
        assert_demand_ledger(read_project(client, ctx["project_id"]), None, 0.0, 0.0, 0.0)


FIELD_TESTED_AT = "2026-05-14T15:00:00.000Z"
H14 = dict(
    hydrant_tag="H-14",
    static_psi=80.0,
    residual_psi=64.0,
    flow_gpm=2250.0,
    tested_at=FIELD_TESTED_AT,
)


class TestAppendOnlyRows:
    def test_20_the_three_reference_only_rows_expose_neither_version_nor_updated_at(
        self, client
    ):
        """Four record types are deliberately append-only or reference-only and therefore
        carry **only** `id` and `created_at`, with both `updated_at` and `version` absent
        from their representations.

        Design: Corner/entities/immutable_rows_carry_no_version_and_no_mutating_endpoint
        """
        ctx = build_project_stage(client, **FP2601)
        flow_test = create_flow_test(client, ctx["project_id"], ctx["lead_id"], **H14)

        assert_append_only_row(flow_test)
        assert_append_only_row(ctx["lead_engineer"])
        assert_append_only_row(ctx["reviewer"])
        assert flow_test["tested_at"].startswith("2026-05-14T15:00:00")

    def test_21_the_recorded_test_survives_two_later_project_writes_unchanged(self, client):
        """A flow test, once witnessed and recorded, is never edited; an iteration, once
        appended, is never edited.

        Design: Corner/entities/immutable_rows_carry_no_version_and_no_mutating_endpoint
        """
        ctx = build_project_stage(client, **FP2601)
        flow_test = create_flow_test(client, ctx["project_id"], ctx["lead_id"], **H14)

        before = read_project(client, ctx["project_id"])["version"]
        create_auxiliary_system(
            client, ctx["project_id"], ctx["lead_id"], **CLASS_I_RISERS
        )
        create_auxiliary_system(client, ctx["project_id"], ctx["lead_id"], **HOSE_STATION)
        assert read_project(client, ctx["project_id"])["version"] == before + 2

        rows, meta = validate_paginated(
            client.list_project_flow_tests(ctx["project_id"], ADMIN_HEADERS)
        )
        assert meta["total_count"] == 1
        # The field record is not touched by any downstream write.
        for field in ("id", "created_at", "hydrant_tag", "static_psi", "residual_psi", "flow_gpm"):
            assert rows[0][field] == flow_test[field]
        assert rows[0]["tested_at"] == flow_test["tested_at"]
        assert_append_only_row(rows[0])


class TestBodyForeignKeyOrder:
    def test_22_two_unknown_parents_surface_the_first_declared_field(self, client):
        """Every foreign key supplied in the request body resolves to an existing row of its
        declared parent type, validated in the order the fields are listed for that endpoint.

        Design: Corner/entities/body_foreign_keys_are_resolved_in_the_declared_field_order
        """
        ctx = build_project_stage(client, **FP2601)
        create_flow_test(client, ctx["project_id"], ctx["lead_id"], **H14)

        both_unknown = {
            "project_id": NON_EXISTENT_UUID,
            "flow_test_id": NON_EXISTENT_UUID,
            "governing_hydraulic_calculation_id": NON_EXISTENT_UUID,
            "evaluation_basis": "RAW_TEST",
        }
        refused = client.create_water_supply_evaluation(
            both_unknown, make_design_engineer_headers(ctx["lead_id"])
        )
        validate_error(refused, "ERR_PROJECT_NOT_FOUND", expected_status=404)

    def test_23_a_resolved_project_lets_the_unknown_flow_test_surface_next(self, client):
        """This applies to project creation, hazard area creation, flow test creation, water
        supply evaluation creation, hydraulic calculation creation, fire pump creation,
        auxiliary system creation, shop drawing creation, submittal creation, resubmittal, and
        comment creation.

        Design: Corner/entities/body_foreign_keys_are_resolved_in_the_declared_field_order
        """
        ctx = build_project_stage(client, **FP2601)
        create_flow_test(client, ctx["project_id"], ctx["lead_id"], **H14)
        headers = make_design_engineer_headers(ctx["lead_id"])

        known_project = {
            "project_id": ctx["project_id"],
            "flow_test_id": NON_EXISTENT_UUID,
            "governing_hydraulic_calculation_id": NON_EXISTENT_UUID,
            "evaluation_basis": "RAW_TEST",
        }
        refused = client.create_water_supply_evaluation(known_project, headers)
        validate_error(refused, "ERR_FLOW_TEST_NOT_FOUND", expected_status=404)

        rows, meta = validate_paginated(
            client.list_water_supply_evaluations(
                headers, params={"project_id": ctx["project_id"]}
            )
        )
        assert rows == []
        assert meta["total_count"] == 0


BACKSTOCK_SHELF = dict(
    label="Backstock Shelf",
    hazard_class="ORDINARY_1",
    commodity_class="CLASS_II",
    storage_height_ft=8.0,
    ceiling_height_ft=14.0,
    area_sqft=4000.0,
    sprinkler_system_type="WET",
    ceiling_slope_pct=None,
    room_area_sqft=None,
    enclosure_rating_hours=None,
    room_has_unprotected_opening=None,
)


class TestInRackCommodityQualification:
    def test_24_ten_heads_over_a_class_four_rack_are_accepted_at_thirty_gpm_each(
        self, client
    ):
        """An in-rack system takes 30.0 per assumed operating head, then is raised to a floor
        of 150.0 if it falls below that, and capped at 480.0.

        Design: Corner/entities/in_rack_auxiliary_cross_reference_integrity_rejects_a_class_ii_commodity
        """
        ctx = build_project_stage(client, **FP2601)
        rack = create_hazard_area(client, ctx["project_id"], ctx["lead_id"], **RACK_BAY_A)
        assert rack["commodity_class"] == "CLASS_IV"

        system = create_auxiliary_system(
            client,
            ctx["project_id"],
            ctx["lead_id"],
            system_type="IN_RACK",
            label="Rack Zone A In-Rack Heads",
            in_rack_head_count=10,
            hazard_area_id=rack["id"],
        )
        assert_flow(system["demand_gpm"], 300.0)
        assert system["interlock_required"] is False
        assert system["status"] == "PROPOSED"
        assert system["hazard_area_id"] == rack["id"]
        assert read_auxiliary_system(client, system["id"])["agent_type"] == "NONE"

    def test_25_the_same_heads_over_a_class_two_shelf_are_a_hazard_mismatch(self, client):
        """that referenced area must store a qualifying commodity, meaning its
        `commodity_class` is either `CLASS_IV` or `GROUP_A_PLASTIC`, and anything else is
        refused with `ERR_IN_RACK_HAZARD_MISMATCH`.

        Design: Corner/entities/in_rack_auxiliary_cross_reference_integrity_rejects_a_class_ii_commodity
        """
        ctx = build_project_stage(client, **FP2601)
        rack = create_hazard_area(client, ctx["project_id"], ctx["lead_id"], **RACK_BAY_A)
        shelf = create_hazard_area(
            client, ctx["project_id"], ctx["lead_id"], **BACKSTOCK_SHELF
        )
        qualifying = create_auxiliary_system(
            client,
            ctx["project_id"],
            ctx["lead_id"],
            system_type="IN_RACK",
            label="Rack Zone A In-Rack Heads",
            in_rack_head_count=10,
            hazard_area_id=rack["id"],
        )
        assert_flow(qualifying["demand_gpm"], 300.0)

        mismatched = build_auxiliary_system_payload(
            project_id=ctx["project_id"],
            system_type="IN_RACK",
            label="Backstock In-Rack Heads",
            in_rack_head_count=10,
            hazard_area_id=shelf["id"],
        )
        validate_error(
            client.create_auxiliary_system(
                mismatched, make_design_engineer_headers(ctx["lead_id"])
            ),
            "ERR_IN_RACK_HAZARD_MISMATCH",
            expected_status=422,
        )
        assert_demand_ledger(
            read_project(client, ctx["project_id"]), None, 0.0, 300.0, 300.0
        )
