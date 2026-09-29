"""Entity shape: what a create returns, what a retrieval returns, which fields
the server owns, which listings filter and page, and how a row resolves its
parents."""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    create_drying_schedule_payload,
    create_grade_bundle_payload,
    create_green_receipt_payload,
    create_species_profile_payload,
    create_flooring_lot_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    CLERK,
    INSPECTOR,
    OPERATOR,
    SUPERVISOR,
    create_product_line,
    create_receipt,
    create_species,
    refetch_charge,
    refetch_core_stock,
    set_logical_clock,
    setup_draft_grade_run,
    setup_planned_lot,
    setup_released_charge,
)

MAPLE = {
    "species_code": "HARD_MAPLE",
    "common_name": "Hard Maple",
    "density_class": "MEDIUM",
    "tangential_shrinkage_coefficient": 0.158,
}
ENGINEERED_LINE = {
    "line_code": "ENG-RO-500",
    "construction_type": "ENGINEERED",
    "nominal_width_in": 5.000,
    "nominal_thickness_in": 0.500,
    "material_value_cents_per_sf": 640,
}
BIRCH_CORE = {
    "core_material": "BIRCH_PLY",
    "lot_reference": "BP-2026-04",
    "available_square_feet": 4000.00,
}


class TestSpeciesProfileRows:
    """The species profile is the root of the configuration graph, and its
    shrink percentage is the server's own."""

    def test_registering_a_dense_species_returns_every_declared_field(self, api):
        """PRD 3.1: "A `MillAdmin` registers a species by supplying its
        `species_code` (the mill's own identifier, such as `RED_OAK`), a
        human-readable `common_name`, a `density_class` of `DENSE`, `MEDIUM` or
        `SOFT`, the `tangential_shrinkage_coefficient` expressing dimensional change
        per one percentage point of moisture change as a fraction of board width, the
        `target_moisture_pct` the kilns aim for, and the `max_moisture_gradient_pp`
        that caps the acceptable shell-to-core spread in percentage points."

        PRD 3.1: "From the density class the server derives
        `green_to_dry_shrink_pct`, the board-foot shrink from green to kiln-dry: 7.5
        percent for `DENSE`, 6.0 percent for `MEDIUM` and 5.0 percent for `SOFT`."

        PRD 2.2: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources."

        Design: Corner/entities/species_profile_creation_returns_full_row_with_derived_shrink
        """
        set_logical_clock(api)

        response = api.create_species_profile(create_species_profile_payload(), ADMIN)
        species = validate_success(response, expected_status=201)

        assert species["species_code"] == "RED_OAK"
        assert species["common_name"] == "Red Oak"
        assert species["density_class"] == "DENSE"
        assert species["tangential_shrinkage_coefficient"] == pytest.approx(
            0.145, abs=0.0001
        )
        assert species["target_moisture_pct"] == pytest.approx(7.0, abs=0.01)
        assert species["max_moisture_gradient_pp"] == pytest.approx(2.0, abs=0.01)
        assert species["green_to_dry_shrink_pct"] == pytest.approx(7.5, abs=0.01)

        envelope = response.json()
        assert envelope["response_type"] == "object"
        assert envelope["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(envelope["meta"]["api_request_timestamp"])

    def test_fetching_the_profile_back_returns_the_same_stored_row(self, api):
        """PRD 3.1: "From the density class the server derives
        `green_to_dry_shrink_pct`, the board-foot shrink from green to kiln-dry: 7.5
        percent for `DENSE`, 6.0 percent for `MEDIUM` and 5.0 percent for `SOFT`."

        PRD 2.4: "Most resources additionally carry an `updated_at` timestamp in the
        same format and an integer `version` that starts at 1 on creation and
        increases by exactly 1 on every mutation of that resource — including
        mutations reached as a cascade from an operation aimed at some other
        resource."

        Design: Corner/entities/species_profile_retrieval_returns_stored_row
        """
        set_logical_clock(api)
        created = create_species(api, **MAPLE)

        fetched = validate_success(
            api.get_species_profile(created["id"], OPERATOR), expected_status=200
        )

        assert fetched["id"] == created["id"]
        assert fetched["species_code"] == "HARD_MAPLE"
        assert fetched["density_class"] == "MEDIUM"
        assert fetched["green_to_dry_shrink_pct"] == pytest.approx(6.0, abs=0.01)
        assert fetched["version"] == 1

    def test_the_identity_fields_are_minted_by_the_server(self, api):
        """PRD 2.4: "Each stored resource carries a server-minted `id` in canonical
        UUID form with no type prefix of any kind, and a `created_at` timestamp in ISO
        8601 UTC with three fractional digits."

        PRD 2.4: "Most resources additionally carry an `updated_at` timestamp in the
        same format and an integer `version` that starts at 1 on creation and
        increases by exactly 1 on every mutation of that resource — including
        mutations reached as a cascade from an operation aimed at some other
        resource."

        Design: Corner/entities/species_profile_system_fields_are_server_generated
        """
        set_logical_clock(api)
        payload = create_species_profile_payload(
            species_code="WHITE_OAK",
            common_name="White Oak",
            tangential_shrinkage_coefficient=0.137,
        )
        assert "id" not in payload and "version" not in payload

        species = validate_success(
            api.create_species_profile(payload, ADMIN), expected_status=201
        )

        assert is_valid_uuid(species["id"])
        assert is_iso8601_timestamp(species["created_at"])
        assert is_iso8601_timestamp(species["updated_at"])
        assert species["version"] == 1


class TestGreenReceiptRows:
    """The receiving deck's row: five required inputs, three server-owned
    defaults, and a filterable collection."""

    def test_a_new_receipt_opens_with_its_declared_defaults(self, api):
        """PRD 3.2: "A new receipt opens in `RECEIVED` status with
        `accepted_board_feet` at 0, a null `kiln_charge_id` and a null
        `rejection_reason`."

        PRD 3.2: "A `ProcurementClerk` (or a `MillAdmin` acting as backstop) records
        each inbound delivery of logs or green lumber with the `species_profile_id`
        delivered, the `supplier_name` of record, the gross `received_board_feet` as
        delivered, a `receipt_grade` of `FAS`, `SELECT`, `NO1_COMMON` or `NO2_COMMON`
        assigned at the deck, and the measured `moisture_pct_at_receipt`."

        Design: Corner/entities/green_receipt_defaults_applied_on_create
        """
        set_logical_clock(api)
        species = create_species(api)

        receipt = validate_success(
            api.create_green_receipt(
                create_green_receipt_payload(species["id"]), CLERK
            ),
            expected_status=201,
        )

        assert receipt["status"] == "RECEIVED"
        assert receipt["accepted_board_feet"] == 0
        assert receipt["kiln_charge_id"] is None
        assert receipt["rejection_reason"] is None
        assert receipt["received_board_feet"] == 6000

    def test_omitting_the_moisture_reading_persists_nothing(self, api):
        """PRD 2.7: "Schema — required fields present, types well formed, enum values
        within their declared sets, decimals non-negative where applicable, and
        pagination `limit` within 1 through 100 with `offset` at least 0. Rejected with
        `ERR_INVALID_REQUEST` (400). Applies to every endpoint."

        PRD 3.2: "A `ProcurementClerk` (or a `MillAdmin` acting as backstop) records
        each inbound delivery of logs or green lumber with the `species_profile_id`
        delivered, the `supplier_name` of record, the gross `received_board_feet` as
        delivered, a `receipt_grade` of `FAS`, `SELECT`, `NO1_COMMON` or `NO2_COMMON`
        assigned at the deck, and the measured `moisture_pct_at_receipt`."

        Design: Corner/entities/green_receipt_missing_required_moisture_rejected
        """
        set_logical_clock(api)
        species = create_species(api)
        payload = create_green_receipt_payload(species["id"])
        payload.pop("moisture_pct_at_receipt")

        response = api.create_green_receipt(payload, CLERK)
        validate_error(response, "ERR_INVALID_REQUEST", expected_status=400)

        _rows, meta = validate_paginated(api.list_green_receipts(ADMIN))
        assert meta["total_count"] == 0

    def test_a_grade_outside_the_declared_enum_is_not_stored_as_free_text(self, api):
        """PRD 2.7: "Schema — required fields present, types well formed, enum values
        within their declared sets, decimals non-negative where applicable, and
        pagination `limit` within 1 through 100 with `offset` at least 0. Rejected with
        `ERR_INVALID_REQUEST` (400). Applies to every endpoint."

        PRD 3.2: "A `ProcurementClerk` (or a `MillAdmin` acting as backstop) records
        each inbound delivery of logs or green lumber with the `species_profile_id`
        delivered, the `supplier_name` of record, the gross `received_board_feet` as
        delivered, a `receipt_grade` of `FAS`, `SELECT`, `NO1_COMMON` or `NO2_COMMON`
        assigned at the deck, and the measured `moisture_pct_at_receipt`."

        Design: Corner/entities/green_receipt_invalid_enum_grade_rejected
        """
        set_logical_clock(api)
        species = create_species(api)

        response = api.create_green_receipt(
            create_green_receipt_payload(species["id"], receipt_grade="PREMIUM"), CLERK
        )
        validate_error(response, "ERR_INVALID_REQUEST", expected_status=400)

        _rows, meta = validate_paginated(api.list_green_receipts(ADMIN))
        assert meta["total_count"] == 0

    def test_the_deck_collection_pages_by_created_at_and_narrows_by_species(self, api):
        """PRD 2.3: "The `meta` block of a list response carries `limit` and `offset`
        as applied, `total_count` as the number of rows matching the filters before
        paging, and `has_more` as a boolean indicating whether rows remain beyond the
        current page."

        PRD 2.3: "A `limit` outside 1 through 100, or a negative `offset`, is a schema
        failure and is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        PRD 3.2: "Receipts may be listed filtered by `species_profile_id`,
        `kiln_charge_id` or `status`."

        Design: Corner/entities/green_receipt_listing_paginates_and_filters
        """
        set_logical_clock(api)
        oak = create_species(api)
        maple = create_species(api, **MAPLE)
        first = create_receipt(api, oak)
        second = create_receipt(
            api, oak, received_board_feet=4000, receipt_grade="SELECT",
            moisture_pct_at_receipt=44.0,
        )
        third = create_receipt(
            api,
            maple,
            supplier_name="Northern Hardwoods",
            received_board_feet=5200,
            receipt_grade="NO1_COMMON",
            moisture_pct_at_receipt=40.0,
        )

        page_one, meta_one = validate_paginated(
            api.list_green_receipts(SUPERVISOR, params={"limit": 2, "offset": 0})
        )
        assert len(page_one) == 2
        assert meta_one["total_count"] == 3
        assert meta_one["has_more"] is True
        assert meta_one["limit"] == 2
        assert meta_one["offset"] == 0

        page_two, meta_two = validate_paginated(
            api.list_green_receipts(SUPERVISOR, params={"limit": 2, "offset": 2})
        )
        assert len(page_two) == 1
        assert meta_two["total_count"] == 3
        assert meta_two["has_more"] is False

        seen = [row["id"] for row in page_one] + [row["id"] for row in page_two]
        assert sorted(seen) == sorted([first["id"], second["id"], third["id"]])

        filtered, meta_filtered = validate_paginated(
            api.list_green_receipts(
                SUPERVISOR, params={"species_profile_id": maple["id"]}
            )
        )
        assert meta_filtered["total_count"] == 1
        assert filtered[0]["species_profile_id"] == maple["id"]

        response = api.list_green_receipts(SUPERVISOR, params={"limit": 0})
        validate_error(response, "ERR_INVALID_REQUEST", expected_status=400)


class TestDryingScheduleRows:
    """The schedule's duration is computed, never accepted from the caller."""

    def test_a_caller_supplied_duration_is_replaced_by_the_computed_one(self, api):
        """PRD 3.1: "The schedule's `planned_dry_hours` is computed at creation and is
        the mill's single estimate of how long the load will occupy a chamber."

        PRD 3.1: "A dense one-inch schedule taking stock from 45.0 percent down to
        7.0 percent with 24 conditioning hours and 12 stress relief hours therefore
        plans 265.0 hours."

        PRD 2.5: "A successful create increments `SpeciesProfile.version`, so a caller
        that holds a pre-write version is refused on its next attempt until it re-reads
        the profile."

        Design: Corner/entities/drying_schedule_planned_hours_client_input_ignored
        """
        set_logical_clock(api)
        species = create_species(api)

        schedule = validate_success(
            api.create_drying_schedule(
                create_drying_schedule_payload(
                    species["id"], species["version"], planned_dry_hours=99.9
                ),
                ADMIN,
            ),
            expected_status=201,
        )

        assert schedule["planned_dry_hours"] == pytest.approx(265.0, abs=0.01)
        assert schedule["planned_dry_hours"] != pytest.approx(99.9, abs=0.01)

        reread = validate_success(
            api.get_species_profile(species["id"], ADMIN), expected_status=200
        )
        assert reread["version"] == 2


class TestGradeBundleRows:
    """The one entity in the system with no revision counter."""

    def test_a_bundle_carries_only_an_id_and_a_created_at(self, api):
        """PRD 2.4: "`GradeBundle` is the single exception. A graded bundle is an
        immutable tally line: once written it is never edited, so it carries only `id`
        and `created_at`. It has no `updated_at` field and no `version` field at all,
        and neither appears in its representation."

        PRD 3.7: "Its `length_factor` is selected by average length: 0.83 for bundles
        averaging under 24 inches, 1.00 for bundles averaging at least 24 but under 48
        inches, and 1.07 for bundles averaging 48 inches or more."

        PRD 3.7: "Its `tally_value_cents` is the bundle's board feet multiplied by the
        per-board-foot price of its grade class — 640 cents for `CLEAR`, 520 for
        `SELECT`, 395 for `NO1_COMMON`, 280 for `NO2_COMMON`, 240 for `CHARACTER` and
        150 for `CABIN` — multiplied by the length factor, and rounded half up to whole
        cents."

        Design: Corner/entities/grade_bundle_is_immutable_and_carries_no_version
        """
        ctx = setup_draft_grade_run(api, bundles=[])

        bundle = validate_success(
            api.create_grade_bundle(
                ctx["grade_run"]["id"],
                create_grade_bundle_payload(
                    grade_class="CLEAR", bundle_board_feet=1187.25, average_length_in=50
                ),
                INSPECTOR,
            ),
            expected_status=201,
        )

        assert is_valid_uuid(bundle["id"])
        assert is_iso8601_timestamp(bundle["created_at"])
        assert "version" not in bundle
        assert "updated_at" not in bundle
        assert bundle["length_factor"] == pytest.approx(1.07, abs=0.001)
        assert bundle["credit_factor"] == pytest.approx(1.00, abs=0.001)
        assert bundle["tally_value_cents"] == 813029

        rows, meta = validate_paginated(
            api.list_grade_run_bundles(ctx["grade_run"]["id"], ADMIN)
        )
        assert meta["total_count"] == 1
        assert rows[0]["tally_value_cents"] == 813029
        assert "version" not in rows[0]

    def test_bundles_are_readable_within_their_run_and_by_grade_class(self, api):
        """PRD 3.7: "Bundles are immutable tally lines: they carry no revision counter
        and are never edited or deleted. They may be read individually and listed either
        within their run or across runs, filtered by `grade_run_id` or `grade_class`."

        PRD 3.7: "Its `credit_factor` is selected by grade class: 1.00 for `CLEAR`,
        0.95 for `SELECT`, 0.85 for `NO1_COMMON`, 0.70 for `NO2_COMMON`, 0.60 for
        `CHARACTER` and 0.40 for `CABIN`."

        PRD 3.7: "Its `tally_value_cents` is the bundle's board feet multiplied by the
        per-board-foot price of its grade class — 640 cents for `CLEAR`, 520 for
        `SELECT`, 395 for `NO1_COMMON`, 280 for `NO2_COMMON`, 240 for `CHARACTER` and
        150 for `CABIN` — multiplied by the length factor, and rounded half up to whole
        cents."

        Design: Corner/entities/grade_bundle_listing_filters_by_grade_class
        """
        ctx = setup_draft_grade_run(
            api,
            bundles=[
                {"grade_class": "CLEAR", "bundle_board_feet": 1000.00, "average_length_in": 50},
                {"grade_class": "CHARACTER", "bundle_board_feet": 400.00, "average_length_in": 20},
                {"grade_class": "CHARACTER", "bundle_board_feet": 300.00, "average_length_in": 20},
            ],
        )
        run_id = ctx["grade_run"]["id"]

        _rows, meta = validate_paginated(api.list_grade_run_bundles(run_id, SUPERVISOR))
        assert meta["total_count"] == 3
        assert meta["has_more"] is False

        character, character_meta = validate_paginated(
            api.list_grade_bundles(
                SUPERVISOR, params={"grade_run_id": run_id, "grade_class": "CHARACTER"}
            )
        )
        assert character_meta["total_count"] == 2
        assert all(row["grade_class"] == "CHARACTER" for row in character)
        assert all(
            row["credit_factor"] == pytest.approx(0.60, abs=0.001) for row in character
        )

        by_id = {row["bundle_board_feet"]: row for row in character}
        assert by_id[400.00]["tally_value_cents"] == 79680

        clear, _clear_meta = validate_paginated(
            api.list_grade_bundles(
                SUPERVISOR, params={"grade_run_id": run_id, "grade_class": "CLEAR"}
            )
        )
        assert clear[0]["tally_value_cents"] == 684800


class TestFlooringLotParents:
    """A lot resolves up to three parents, and a missing configuration parent
    decides the response before any pairing rule runs."""

    def test_an_unknown_core_stock_is_a_configuration_failure(self, api):
        """PRD 2.7: "Configuration existence — a referenced `SpeciesProfile`,
        `DryingSchedule`, `KilnChamber`, `ProductLine`, `CoreStock` or `PrefinishLine`
        must exist, whether it is named in the path or in the body. Rejected with
        `ERR_CONFIG_NOT_FOUND` (404)."

        PRD 2.7: "Core stock forbidden — `ERR_CORE_STOCK_NOT_ALLOWED` (422), on `POST
        /mill/flooring-lots`."

        PRD 3.5: "A charge holding 9700 green board feet of a `DENSE` species yields
        8972.50 kiln-dry board feet."

        Design: Corner/entities/flooring_lot_unknown_core_stock_returns_config_not_found
        """
        ctx = setup_released_charge(api)
        product_line = create_product_line(api, ctx["species"])

        response = api.create_flooring_lot(
            create_flooring_lot_payload(
                product_line["id"],
                ctx["charge"]["id"],
                6000,
                core_stock_id=NON_EXISTENT_UUID,
            ),
            SUPERVISOR,
        )
        validate_error(response, "ERR_CONFIG_NOT_FOUND", expected_status=404)

        _rows, meta = validate_paginated(
            api.list_flooring_lots(ADMIN, params={"kiln_charge_id": ctx["charge"]["id"]})
        )
        assert meta["total_count"] == 0

        charge = refetch_charge(api, ctx["charge"]["id"])
        assert charge["remaining_dry_bf"] == pytest.approx(8972.50, abs=0.01)

    def test_an_engineered_lot_resolves_line_charge_and_core_stock_together(self, api):
        """PRD 3.6: "The lot snapshots the line's `construction_type` and
        `nominal_width_in` so that later configuration changes cannot rewrite history,
        and opens in `PLANNED` status."

        PRD 3.6: "For an engineered lot the server computes `reserved_core_sf` as the
        drawn `input_dry_bf` multiplied by 1.10 square feet of core per board foot,
        rounded half up to two decimal places — a draw of 2900 board feet reserves
        3190.00 square feet — and adds it to the core stock's `reserved_square_feet`,
        which is at all times the total `reserved_core_sf` of the non-voided lots on
        that stock."

        PRD 3.6: "Planning a lot draws down the charge: the charge's `remaining_dry_bf`
        is reduced by `input_dry_bf`, and it is always `dry_bf_out` less the total
        `input_dry_bf` of the non-voided lots drawn from that charge."

        PRD 3.6: "Lots may be listed filtered by `product_line_id`, `kiln_charge_id`,
        `core_stock_id`, `final_grade_run_id` or `status`."

        Design: Corner/entities/engineered_lot_joins_product_line_charge_and_core_stock
        """
        ctx = setup_planned_lot(
            api,
            input_dry_bf=2900,
            line_overrides=dict(ENGINEERED_LINE),
            with_core_stock=True,
            core_stock_overrides=dict(BIRCH_CORE),
        )
        lot = ctx["lot"]

        assert lot["status"] == "PLANNED"
        assert lot["construction_type"] == "ENGINEERED"
        assert lot["nominal_width_in"] == pytest.approx(5.000, abs=0.0001)
        assert lot["reserved_core_sf"] == pytest.approx(3190.00, abs=0.01)
        assert lot["dimensional_growth_allowance_in"] == pytest.approx(
            0.0015, abs=0.00001
        )
        assert lot["planned_finished_width_in"] == pytest.approx(4.939, abs=0.0001)

        core = refetch_core_stock(api, ctx["core_stock"]["id"])
        assert core["reserved_square_feet"] == pytest.approx(3190.00, abs=0.01)

        charge = refetch_charge(api, ctx["charge"]["id"])
        assert charge["status"] == "RELEASED"
        assert charge["remaining_dry_bf"] == pytest.approx(6072.50, abs=0.01)

        for key, value in (
            ("product_line_id", ctx["product_line"]["id"]),
            ("kiln_charge_id", ctx["charge"]["id"]),
            ("core_stock_id", ctx["core_stock"]["id"]),
        ):
            rows, meta = validate_paginated(
                api.list_flooring_lots(ADMIN, params={key: value})
            )
            assert meta["total_count"] == 1, f"filter on {key} must reach the lot"
            assert rows[0]["id"] == lot["id"]


class TestKilnChargeLookup:
    """An unknown charge id resolves to the charge's own not-found code."""

    def test_an_unknown_charge_id_reports_the_charge_specific_code(self, api):
        """PRD 2.7: "Kiln charge existence — `ERR_CHARGE_NOT_FOUND` (404), on kiln
        charge paths and on flooring lot creation."

        PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies
        the specific error."

        Design: Corner/entities/kiln_charge_unknown_id_returns_not_found
        """
        set_logical_clock(api)

        response = api.get_kiln_charge(NON_EXISTENT_UUID, OPERATOR)
        error = validate_error(response, "ERR_CHARGE_NOT_FOUND", expected_status=404)

        assert error["error_id"] != "ERR_CONFIG_NOT_FOUND"
        assert response.json()["response_type"] == "error"
