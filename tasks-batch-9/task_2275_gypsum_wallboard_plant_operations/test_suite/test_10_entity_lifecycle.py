"""Creation shapes, computed defaults, reads and the reference-integrity bands:
what each entity looks like the moment it exists and which error a bad reference
earns.
"""

from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiClient,
    ApiErrorId,
    BatchStatus,
    LotSourceType,
    LotStatus,
    ProductionPosture,
    QualityState,
    RateZone,
    RunStatus,
    SaleableGrade,
    assert_append_only,
    assert_calciner_batch,
    assert_error_body,
    assert_gypsum_lot,
    assert_market,
    assert_plant,
    assert_stucco_test,
    factories,
    fixtures,
    is_iso8601_timestamp,
    is_valid_uuid,
    test_users,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPlantAndMarketCreation:
    """The two configuration entities whose creation derives fields the client never
    supplies."""

    def test_registering_a_plant_echoes_its_inputs_and_zeroes_the_silo(
        self, api: ApiClient
    ) -> None:
        """Every account starts at 0.000, which is why a new plant opens RESTRICTED.

        PRD: "On registration the silo accounts and the held-run counter are all set as described in §2.8, and the posture is derived at once — which, for an empty silo, means the plant opens for business `RESTRICTED`."

        Design: Corner/entities/plant_create_returns_all_fields_and_computed_defaults
        """
        plant = validate_success(
            api.create_plant(
                factories.plant_payload(
                    code="GYP-2",
                    name="Platte Valley Wallboard",
                    calciner_capacity_tph=45,
                    stucco_silo_capacity_tons=900,
                    natural_gypsum_purity_floor_pct=90.0,
                    synthetic_free_moisture_ceiling_pct=11.0,
                    energy_price_per_mmbtu=3.8,
                    contribution_margin_per_msf=41.25,
                ),
                test_users.PLANT_ADMIN,
            ),
            201,
        )

        assert_plant(plant)
        assert plant["code"] == "GYP-2"
        assert plant["name"] == "Platte Valley Wallboard"
        assert plant["calciner_capacity_tph"] == 45
        assert plant["stucco_silo_capacity_tons"] == 900
        assert plant["natural_gypsum_purity_floor_pct"] == pytest.approx(90.0, abs=0.005)
        assert plant["synthetic_free_moisture_ceiling_pct"] == pytest.approx(11.0, abs=0.005)
        assert plant["energy_price_per_mmbtu"] == pytest.approx(3.80, abs=0.005)
        assert plant["contribution_margin_per_msf"] == pytest.approx(41.25, abs=0.005)
        assert plant["stucco_on_hand_tons"] == pytest.approx(0.000, abs=0.0005)
        assert plant["stucco_committed_tons"] == pytest.approx(0.000, abs=0.0005)
        assert plant["stucco_available_tons"] == pytest.approx(0.000, abs=0.0005)
        assert plant["held_run_count"] == 0
        assert plant["production_posture"] == ProductionPosture.RESTRICTED.value, (
            "an empty silo is below the 40.0-ton availability floor"
        )
        assert plant["version"] == 1
        assert is_valid_uuid(plant["id"]), "the id is server-minted"
        assert is_iso8601_timestamp(plant["created_at"])
        assert is_iso8601_timestamp(plant["updated_at"])

    def test_a_market_registered_without_a_backhaul_credit_stores_zero(
        self, api: ApiClient
    ) -> None:
        """The one optional market input defaults to 0.00 rather than to null.

        PRD: "A market carries a `name`, a one-way haul `distance_miles` greater than zero, a `fuel_surcharge_pct` between 0.0 and 60.0, a `min_charge_usd` of zero or more that acts as a freight floor per load, and an optional `backhaul_credit_usd` that also defaults to `0.00` and may not be negative."

        Design: Corner/entities/market_backhaul_credit_defaults_to_zero
        """
        market = validate_success(
            api.create_market(
                factories.omitting(
                    factories.market_payload(
                        name="Cheyenne",
                        distance_miles=100,
                        fuel_surcharge_pct=12.0,
                        min_charge_usd=250.0,
                    ),
                    "backhaul_credit_usd",
                ),
                test_users.PLANT_ADMIN,
            ),
            201,
        )

        assert_market(market)
        assert market["backhaul_credit_usd"] == pytest.approx(0.00, abs=0.005)
        assert market["rate_zone"] == RateZone.ZONE_1.value
        assert market["base_rate_per_msf"] == pytest.approx(8.50, abs=0.005)
        assert market["version"] == 1

    def test_four_hauls_land_in_the_four_rate_zones(self, api: ApiClient) -> None:
        """100, 200, 500 and 640 miles derive ZONE_1 to ZONE_4 with their base rates.

        PRD: "From `distance_miles` the system immediately derives the market's `rate_zone` and its `base_rate_per_msf`: a haul under 150 miles is `ZONE_1` at 8.50 dollars per MSF, a haul of at least 150 but under 350 miles is `ZONE_2` at 12.75, a haul of at least 350 but under 600 miles is `ZONE_3` at 17.40, and anything from 600 miles upward is `ZONE_4` at 23.10."

        Design: Corner/entities/market_rate_zone_and_base_rate_are_computed_from_distance
        """
        expected = (
            ("Local", 100, RateZone.ZONE_1.value, 8.50),
            ("Regional", 200, RateZone.ZONE_2.value, 12.75),
            ("Interstate", 500, RateZone.ZONE_3.value, 17.40),
            ("Denver Metro", 640, RateZone.ZONE_4.value, 23.10),
        )
        for name, miles, zone, rate in expected:
            market = fixtures.create_market(
                api, name=name, distance_miles=miles, min_charge_usd=250.0
            )
            assert market["rate_zone"] == zone, f"{miles} miles must fall in {zone}"
            assert market["base_rate_per_msf"] == pytest.approx(rate, abs=0.005), (
                f"{zone} bills {rate} dollars a MSF"
            )


class TestReadsAndListings:
    """Detail reads return stored values without recomputing them, and collection reads
    page and filter one collection."""

    def test_reading_an_assayed_lot_returns_the_stored_laboratory_values(
        self, api: ApiClient
    ) -> None:
        """The read reports the assay snapshot and the disposition it decided earlier.

        PRD: "The controller submits a `free_moisture_pct`, a `purity_pct` and an integer `chloride_ppm`, all measured in the laboratory; these overwrite whatever was there before, `assayed_at` is stamped from the logical clock, and `assay_count` increases by 1."

        Design: Corner/entities/gypsum_lot_get_returns_stored_assay_values
        """
        plant = fixtures.create_plant(api)
        assayed = fixtures.synthetic_lot(api, plant["id"])

        lot = validate_success(
            api.get_gypsum_lot(assayed["id"], test_users.PRODUCTION_SCHEDULER)
        )

        assert_gypsum_lot(lot)
        assert lot["source_type"] == LotSourceType.SYNTHETIC.value
        assert lot["supplier_name"] == "Comanche FGD"
        assert lot["free_moisture_pct"] == pytest.approx(9.40, abs=0.005)
        assert lot["purity_pct"] == pytest.approx(94.0, abs=0.005)
        assert lot["chloride_ppm"] == 120
        assert lot["declared_free_moisture_pct"] == pytest.approx(9.50, abs=0.005), (
            "the declared values are kept alongside the laboratory ones"
        )
        assert lot["declared_purity_pct"] == pytest.approx(94.0, abs=0.005)
        assert lot["status"] == LotStatus.APPROVED.value
        assert lot["quarantine_reason"] is None
        assert lot["assay_count"] == 1
        assert lot["received_tons"] == pytest.approx(300.000, abs=0.0005)
        assert lot["consumed_tons"] == pytest.approx(0.000, abs=0.0005)
        assert lot["remaining_tons"] == pytest.approx(300.000, abs=0.0005)
        assert lot["assayed_at"].startswith("2026-08-01T00:00:00"), (
            "the stamp comes from the untouched logical clock"
        )
        assert lot["version"] == 2, "receipt then assay is two writes"

    def test_the_run_listing_pages_and_filters_one_collection(self, api: ApiClient) -> None:
        """Three drafts page two-then-one and the SCHEDULED filter finds none of them.

        PRD: "List responses populate `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` counts the rows matching the filter before the page window is applied."

        Design: Corner/entities/production_run_list_paginates_with_total_count_and_has_more
        """
        world = fixtures.baseline(api)
        world.batch = fixtures.create_batch(api, world.plant_id)
        windows = (
            ("2026-08-03T06:00:00Z", "2026-08-03T10:00:00Z"),
            ("2026-08-03T10:00:00Z", "2026-08-03T14:00:00Z"),
            ("2026-08-03T14:00:00Z", "2026-08-03T18:00:00Z"),
        )
        for start, end in windows:
            fixtures.draft_run(api, world, window_start=start, window_end=end)

        first_page, first_meta = validate_paginated(
            api.list_production_runs(
                test_users.PRODUCTION_SCHEDULER,
                params={"plant_id": world.plant_id, "limit": 2, "offset": 0},
            )
        )
        assert len(first_page) == 2, "the page window caps the rows returned"
        assert first_meta["total_count"] == 3, "the count ignores the page window"
        assert first_meta["has_more"] is True

        second_page, second_meta = validate_paginated(
            api.list_production_runs(
                test_users.PRODUCTION_SCHEDULER,
                params={"plant_id": world.plant_id, "limit": 2, "offset": 2},
            )
        )
        assert len(second_page) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False

        scheduled, scheduled_meta = validate_paginated(
            api.list_production_runs(
                test_users.PRODUCTION_SCHEDULER, params={"status": RunStatus.SCHEDULED.value}
            )
        )
        assert scheduled == [], "none of the three drafts has been scheduled"
        assert scheduled_meta["total_count"] == 0
        assert scheduled_meta["has_more"] is False

        for run in first_page + second_page:
            assert run["status"] == RunStatus.DRAFT.value
            assert run["quality_state"] == QualityState.UNTESTED.value
            assert run["saleable_grade"] == SaleableGrade.UNGRADED.value


class TestAppendOnlyMeasurementRows:
    """`StuccoTest` rows are measurements: stamped from the acting user and the logical
    clock, and never versioned."""

    @staticmethod
    def _calcining_batch_at_half_past_nine(api: ApiClient):
        world = fixtures.compact_batch_world(api)
        fixtures.set_clock(api, "2026-08-02T09:30:00Z")
        return world

    def test_a_stucco_sample_stamps_the_acting_user_and_the_logical_clock(
        self, api: ApiClient
    ) -> None:
        """Neither field is client-supplied: one comes from the header, one from the clock.

        PRD: "Each sample stamps `recorded_by_user_id` from the acting `X-User-ID` and `tested_at` from the logical clock."

        Design: Corner/entities/stucco_test_stamps_recording_user_and_logical_clock
        """
        world = self._calcining_batch_at_half_past_nine(api)

        sample = fixtures.record_stucco_test(api, world.batch_id)

        assert_stucco_test(sample)
        assert sample["recorded_by_user_id"] == test_users.USER_INSPECTOR_1
        assert sample["tested_at"].startswith("2026-08-02T09:30:00"), (
            "nothing in this system reads wall-clock time"
        )
        assert sample["result"] == "PASS"
        assert sample["batch_id"] == world.batch_id

        batch = world.read_batch()
        assert_calciner_batch(batch)
        assert batch["status"] == BatchStatus.COMPLETED.value
        assert batch["stucco_yield_actual_tons"] == pytest.approx(77.340, abs=0.0005), (
            "90.000 dry tons at 90 percent purity converts to 77.340"
        )
        assert world.read_plant()["stucco_on_hand_tons"] == pytest.approx(77.340, abs=0.0005)

    def test_a_stucco_test_row_carries_no_version_and_cannot_reuse_its_sequence(
        self, api: ApiClient
    ) -> None:
        """The row exposes only id and created_at, and a repeated sample_seq is rejected.

        PRD: "For those three, both `updated_at` and `version` are absent from the response entirely."

        Design: Corner/entities/stucco_test_is_append_only_without_version_field
        """
        world = self._calcining_batch_at_half_past_nine(api)
        recorded = fixtures.record_stucco_test(api, world.batch_id)

        detail = validate_success(
            api.get_stucco_test(recorded["id"], test_users.QUALITY_MANAGER)
        )
        assert_append_only(detail, "StuccoTest")
        assert "version" not in detail
        assert "updated_at" not in detail
        assert detail["sample_seq"] == 1

        rows, meta = validate_paginated(
            api.list_stucco_tests(
                test_users.QUALITY_MANAGER, params={"batch_id": world.batch_id}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["result"] == "PASS"

        validate_error(
            api.create_stucco_test(
                world.batch_id,
                factories.stucco_test_payload(sample_seq=1),
                test_users.QUALITY_INSPECTOR,
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )


class TestReferenceIntegrityBands:
    """Which error a bad identifier earns depends on where it was named: a path
    segment, a body foreign key, or the wrong plant entirely."""

    def test_each_unknown_path_id_returns_its_own_not_found_code(self, api: ApiClient) -> None:
        """One unknown UUID, six collections, six distinct 404 codes.

        PRD: "Identifiers embedded in the URL are resolved in the order they appear, and the first one that does not exist decides the error: `{plantId}` yields `ERR_PLANT_NOT_FOUND`, `{lotId}` yields `ERR_LOT_NOT_FOUND`, `{batchId}` yields `ERR_BATCH_NOT_FOUND`, `{runId}` yields `ERR_RUN_NOT_FOUND`, `{outageId}` yields `ERR_OUTAGE_NOT_FOUND`, `{loadOrderId}` yields `ERR_LOAD_ORDER_NOT_FOUND`, and the read-only addresses `{lineId}`, `{specId}`, `{feedId}`, `{stuccoTestId}`, `{boardTestId}` and `{marketId}` resolve their own collections."

        Design: Corner/entities/unknown_ids_return_entity_specific_not_found_codes
        """
        probes = (
            (api.get_plant(NON_EXISTENT_UUID, test_users.PLANT_ADMIN), ApiErrorId.PLANT_NOT_FOUND),
            (
                api.get_gypsum_lot(NON_EXISTENT_UUID, test_users.MATERIALS_CONTROLLER),
                ApiErrorId.LOT_NOT_FOUND,
            ),
            (
                api.get_calciner_batch(NON_EXISTENT_UUID, test_users.MATERIALS_CONTROLLER),
                ApiErrorId.BATCH_NOT_FOUND,
            ),
            (
                api.get_production_run(NON_EXISTENT_UUID, test_users.PRODUCTION_SCHEDULER),
                ApiErrorId.RUN_NOT_FOUND,
            ),
            (
                api.get_outage(NON_EXISTENT_UUID, test_users.MAINTENANCE_PLANNER),
                ApiErrorId.OUTAGE_NOT_FOUND,
            ),
            (
                api.get_load_order(NON_EXISTENT_UUID, test_users.PRODUCTION_SCHEDULER),
                ApiErrorId.LOAD_ORDER_NOT_FOUND,
            ),
        )
        for response, expected in probes:
            body = validate_error(response, expected.value, 404)
            assert_error_body(body)

    def test_a_spec_created_under_an_unknown_plant_reports_the_plant_miss(
        self, api: ApiClient
    ) -> None:
        """The path segment resolves before the body, so this is not a reference miss.

        PRD: "Because resolution is strictly left to right, a request for a board line under a non-existent plant reports the plant miss, never the line miss."

        Design: Corner/entities/create_product_spec_under_unknown_plant_returns_plant_not_found
        """
        body = validate_error(
            api.create_product_spec(
                NON_EXISTENT_UUID, factories.regular_spec_payload(), test_users.PLANT_ADMIN
            ),
            ApiErrorId.PLANT_NOT_FOUND.value,
            404,
        )
        assert body["error_id"] != ApiErrorId.REFERENCE_NOT_FOUND.value, (
            "the reference code is reserved for body-supplied foreign keys"
        )

    def test_a_feed_naming_another_plants_lot_is_refused_as_a_scope_mismatch(
        self, api: ApiClient
    ) -> None:
        """Both rows exist and the lot is APPROVED, but they belong to different plants.

        PRD: "Cross-referenced entities must belong to the same plant: a feed's source lot must belong to the batch's plant, and a run's line, product specification and calciner batch must all belong to the run's plant."

        Design: Corner/entities/feed_naming_a_lot_from_another_plant_returns_plant_scope_mismatch
        """
        world = fixtures.baseline(api)
        batch = fixtures.create_batch(api, world.plant_id)
        other_plant = fixtures.create_plant(api, code="GYP-2", name="Platte Valley Wallboard")
        foreign_lot = fixtures.synthetic_lot(api, other_plant["id"], received_tons=100.0)

        validate_error(
            api.create_batch_feed(
                batch["id"],
                factories.batch_feed_payload(
                    foreign_lot["id"], 50.0, 10.0, foreign_lot["version"]
                ),
                test_users.MATERIALS_CONTROLLER,
            ),
            ApiErrorId.PLANT_SCOPE_MISMATCH.value,
            409,
        )

        after_batch = fixtures.read_batch(api, batch["id"])
        assert after_batch["status"] == BatchStatus.PLANNED.value
        assert after_batch["feed_tons_total"] == pytest.approx(0.000, abs=0.0005)

        after_lot = fixtures.read_lot(api, foreign_lot["id"])
        assert after_lot["status"] == LotStatus.APPROVED.value
        assert after_lot["consumed_tons"] == pytest.approx(0.000, abs=0.0005)
        assert after_lot["remaining_tons"] == pytest.approx(100.000, abs=0.0005)

        _, meta = validate_paginated(
            api.list_batch_feeds(
                test_users.MATERIALS_CONTROLLER, params={"batch_id": batch["id"]}
            )
        )
        assert meta["total_count"] == 0, "the refused feed wrote no row"


class TestRequestShapeBand:
    """Band four answers before any derivation runs: a missing required field, a value
    outside its enum, and a duplicate identifier are all the same 400."""

    def test_a_draft_missing_the_kiln_dwell_is_rejected_before_any_derivation(
        self, api: ApiClient
    ) -> None:
        """`kiln_dwell_minutes` has no default, so its absence stops the request at 400.

        PRD: "On every write endpoint: the body parses, required fields are present, enum values are members of their declared sets, numbers fall inside their declared ranges, and the uniqueness rules hold — `code` unique across all plants, `sku_code` unique within a plant, `designation` unique within a plant, `sample_seq` unique within a batch, `specimen_seq` unique within a run."

        Design: Corner/entities/create_production_run_missing_kiln_dwell_returns_invalid_request
        """
        world = fixtures.baseline(api)
        batch = fixtures.create_batch(api, world.plant_id)

        validate_error(
            api.create_production_run(
                factories.omitting(
                    factories.run_draft_payload(
                        world.plant_id,
                        world.line_id,
                        world.spec_reg_id,
                        batch["id"],
                        requested_planned_msf=100.0,
                    ),
                    "kiln_dwell_minutes",
                ),
                test_users.PRODUCTION_SCHEDULER,
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

        _, meta = validate_paginated(
            api.list_production_runs(
                test_users.PRODUCTION_SCHEDULER, params={"plant_id": world.plant_id}
            )
        )
        assert meta["total_count"] == 0, "no run row was created"

    def test_an_undeclared_lot_source_type_is_rejected(self, api: ApiClient) -> None:
        """The source_type enum is closed at two members even though only two branch.

        PRD: "A `MaterialsController` receives each inbound lot against a bill of lading, naming the destination plant, the `source_type` — either `NATURAL` for quarried rock or `SYNTHETIC` for FGD byproduct — the `supplier_name`, and the as-received `received_tons`, which must be greater than zero and is carried to 3 decimals."

        Design: Corner/entities/create_lot_with_invalid_source_type_returns_invalid_request
        """
        plant = fixtures.create_plant(api)

        validate_error(
            api.create_gypsum_lot(
                factories.synthetic_lot_payload(
                    plant["id"],
                    source_type="RECYCLED",
                    supplier_name="Unknown",
                    received_tons=50.0,
                    declared_free_moisture_pct=5.0,
                    declared_purity_pct=92.0,
                ),
                test_users.MATERIALS_CONTROLLER,
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

        _, meta = validate_paginated(
            api.list_gypsum_lots(
                test_users.MATERIALS_CONTROLLER, params={"plant_id": plant["id"]}
            )
        )
        assert meta["total_count"] == 0, "no lot row was created"

    def test_a_duplicate_plant_code_and_a_duplicate_sku_code_are_both_rejected(
        self, api: ApiClient
    ) -> None:
        """Replaying either creation is a shape failure, not a conflict code.

        PRD: "A `PlantAdmin` begins by registering the plant itself, supplying a short `code` of between 1 and 16 characters that must be unique across every plant in the system (a duplicate is an `ERR_INVALID_REQUEST`), a display `name`, and the physical and commercial parameters that the rest of the system reads."

        Design: Corner/entities/duplicate_plant_code_and_sku_code_return_invalid_request
        """
        plant = fixtures.create_plant(api)
        fixtures.create_regular_spec(api, plant["id"])

        validate_error(
            api.create_plant(
                factories.plant_payload(code="GYP-1", name="Duplicate Plant"),
                test_users.PLANT_ADMIN,
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )
        validate_error(
            api.create_product_spec(
                plant["id"], factories.regular_spec_payload(), test_users.PLANT_ADMIN
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

        _, plant_meta = validate_paginated(api.list_plants(test_users.PLANT_ADMIN))
        assert plant_meta["total_count"] == 1, "the duplicate plant was not written"

        _, spec_meta = validate_paginated(
            api.list_product_specs(test_users.PLANT_ADMIN, params={"plant_id": plant["id"]})
        )
        assert spec_meta["total_count"] == 1, "the duplicate SKU was not written"
