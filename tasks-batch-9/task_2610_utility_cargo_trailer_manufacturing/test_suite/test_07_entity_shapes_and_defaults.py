"""Entity shapes: opening values, declared defaults, derived totals and channels.

Each test reads a row straight back and pins the fields PRD 3.1, 3.2, 3.5, 3.8
and 2.5 declare it carries, including the audit discipline that separates the
versioned entities from the append-only frame inspection.
"""

import test_helpers as H
from test_helpers import (
    ASSEMBLY_TECH,
    PLANT_ENGINEER,
    SALES_ADMIN,
    WELD_SUPERVISOR,
    validate_paginated,
    validate_success,
)


class TestModelCreationShape:
    def test_a_freshly_registered_model_returns_every_declared_field(self, api):
        """The 201 body echoes the fourteen inputs and opens every derived field.

        PRD 3.1: "A freshly registered model opens in `certification_status`
        `DRAFT`, with `revision_round` at 0 and `active_unit_count` at 0. Neither
        rating is populated yet: `provisional_gvwr_lbs` and `certified_gvwr_lbs`
        both stay null until the model enters review, and `certified_by_user_id`
        and `certified_at` stay null until an officer actually signs it."

        Design: Corner/entities/entity_trailer_model_creation_returns_every_declared_field
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)

        response = api.create_model(H.model_payload(), headers=PLANT_ENGINEER)

        model = validate_success(response, expected_status=201)
        assert model["model_code"] == H.MODEL_TA["model_code"]
        assert model["description"] == H.MODEL_TA["description"]
        assert model["axle_count"] == 2
        assert model["axle_rating_lbs"] == 3500
        assert model["design_braked_axle_count"] == 1
        assert model["tire_load_rating_lbs"] == 1820
        assert model["frame_design_code"] == "TA"
        assert model["frame_design_rated_lbs"] == 7200
        assert model["coupler_rating_lbs"] == 7500
        H.assert_one_decimal(model["overall_width_in"], 78.5)
        assert model["nominal_length_mm"] == H.TA_NOMINAL_LENGTH_MM
        assert model["nominal_width_mm"] == H.TA_NOMINAL_WIDTH_MM
        assert model["base_curb_weight_lbs"] == H.TA_BASE_CURB_WEIGHT_LBS
        H.assert_money(model["base_dealer_price_cents"], H.TA_BASE_DEALER_PRICE_CENTS)
        assert model["certification_status"] == H.CertificationStatus.DRAFT
        assert model["revision_round"] == 0
        assert model["active_unit_count"] == 0
        assert model["provisional_gvwr_lbs"] is None
        assert model["certified_gvwr_lbs"] is None
        assert model["certified_by_user_id"] is None
        assert model["certified_at"] is None
        assert model["version"] == 1
        H.assert_full_audit_fields(model)
        H.assert_timestamp_with_millis(model["created_at"])


class TestDealerBalancesArePersisted:
    def test_reading_a_newly_enrolled_dealer_returns_its_derived_balances(self, api):
        """The derived money and counter fields live on the row, not in a response.

        PRD 3.8: "A newly enrolled dealer opens with `status` `ACTIVE`,
        `floor_plan_outstanding_cents` at 0, `floor_plan_available_cents` equal to
        its `floor_plan_limit_cents`, and `allocations_current_month_count`,
        `allocations_ytd_count` and `warranty_receivable_cents` all at 0."

        Design: Corner/entities/entity_dealer_get_returns_stored_and_derived_balances
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        enrolled = H.enroll_dealer(api)

        dealer = validate_success(api.get_dealer(enrolled["id"], headers=SALES_ADMIN))

        assert dealer["dealer_code"] == H.DEALER_001["dealer_code"]
        H.assert_money(dealer["labor_rate_cents_per_hour"], H.DEALER_LABOR_RATE_CENTS_PER_HOUR)
        H.assert_money(dealer["floor_plan_limit_cents"], H.DEALER_FLOOR_PLAN_LIMIT_CENTS)
        H.assert_floor_plan_conserved(dealer, 0)
        H.assert_money(dealer["floor_plan_available_cents"], H.DEALER_FLOOR_PLAN_LIMIT_CENTS)
        assert dealer["allocation_quota_per_month"] == 5
        assert dealer["allocations_current_month_count"] == 0
        assert dealer["allocations_ytd_count"] == 0
        H.assert_money(dealer["warranty_receivable_cents"], 0)
        assert dealer["status"] == H.DealerStatus.ACTIVE
        assert dealer["version"] == 1


class TestAssetDefaults:
    def test_omitting_the_buffer_and_the_capacity_materialises_both_defaults(self, api):
        """A jig omitting its buffer gets 45 and a lane omitting capacity gets 2.

        PRD 3.2: "when the buffer is omitted it defaults to 45 minutes, and it may
        not be negative."
        PRD 3.6: "a `max_concurrent_tests` capacity of at least 1 that defaults to
        2 when omitted."

        Design: Corner/entities/entity_weld_jig_and_test_lane_defaults_applied_when_fields_omitted
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)

        jig = validate_success(
            api.create_jig({"jig_code": "JIG-TA-02", "frame_design_code": "TA"}, headers=PLANT_ENGINEER),
            expected_status=201,
        )
        lane = validate_success(
            api.create_lane({"lane_code": "LANE-02", "surface_type": "GRAVEL"}, headers=PLANT_ENGINEER),
            expected_status=201,
        )

        assert jig["changeover_buffer_min"] == H.DEFAULT_CHANGEOVER_BUFFER_MIN
        assert jig["reserved_minutes_total"] == 0
        assert jig["version"] == 1
        assert lane["max_concurrent_tests"] == H.DEFAULT_LANE_CAPACITY
        assert lane["surface_type"] == "GRAVEL"
        assert lane["version"] == 1


class TestTrailerListFilterAndWindow:
    def test_the_trailer_list_filters_by_build_status_and_windows_the_result(self, api):
        """Three trailers of one model read three ways: two filters and one window.

        PRD 3.2: "Trailers can be listed filtered by `model_id`, by owning
        `dealer_order_id` and by `build_status`, windowed by `limit` and `offset`
        with `total_count` and `has_more` riding in the envelope."

        Design: Corner/entities/entity_trailer_unit_list_filters_by_build_status_with_limit_and_offset
        """
        plant = H.setup_plant(api)
        model_id = plant["model"]["id"]
        first = H.open_unit(api, model_id, "SN-000101")
        H.open_unit(api, model_id, "SN-000102")
        H.open_unit(api, model_id, "SN-000103")
        H.reserve_jig_window(api, plant["jig"]["id"], first["id"])
        reserved_version = H.read_unit(api, first["id"])["version"]

        planned, _planned_meta = validate_paginated(
            api.list_units(
                params={"model_id": model_id, "build_status": H.BuildStatus.PLANNED},
                headers=WELD_SUPERVISOR,
            )
        )
        on_the_jig, _jig_meta = validate_paginated(
            api.list_units(
                params={"model_id": model_id, "build_status": H.BuildStatus.JIG_RESERVED},
                headers=WELD_SUPERVISOR,
            )
        )
        window, window_meta = validate_paginated(
            api.list_units(
                params={"model_id": model_id, "limit": 2, "offset": 0}, headers=WELD_SUPERVISOR
            )
        )

        assert sorted(row["serial_number"] for row in planned) == ["SN-000102", "SN-000103"]
        assert [row["serial_number"] for row in on_the_jig] == ["SN-000101"]
        assert len(window) == 2
        H.assert_pagination_meta(window_meta, limit=2, offset=0, total_count=3, has_more=True)
        for row in planned + on_the_jig + window:
            assert row["model_id"] == model_id
        assert H.read_unit(api, first["id"])["version"] == reserved_version


class TestOptionInstallExtendedTotals:
    def test_a_quantity_of_three_extends_both_totals_and_re_derives_the_budget(self, api):
        """The client supplies per-unit values; the server extends and re-derives.

        PRD 3.5: "Each install line opens with `status` `PENDING` and two extended
        amounts:
        `total_weight_lbs` is the `quantity` multiplied by `unit_weight_lbs`, and
        `total_price_cents` is the `quantity` multiplied by `unit_price_cents`."

        Design: Corner/entities/entity_option_install_totals_are_computed_from_quantity
        """
        plant = H.setup_plant(api)
        staged = H.unit_at_systems_installed(plant, api)

        response = api.create_option_install(
            staged["unit"]["id"],
            H.option_payload(
                option_code="E_TRACK_KIT",
                quantity=3,
                unit_weight_lbs=20,
                unit_price_cents=6650,
                labor_hours=0.75,
            ),
            headers=ASSEMBLY_TECH,
        )

        line = validate_success(response, expected_status=201)
        assert line["quantity"] == 3
        assert line["unit_weight_lbs"] == 20
        H.assert_money(line["unit_price_cents"], 6650)
        assert line["total_weight_lbs"] == 60
        H.assert_money(line["total_price_cents"], 19950)
        assert line["status"] == H.OptionStatus.PENDING
        H.assert_one_decimal(line["labor_hours"], 0.75)
        unit = H.read_unit(api, staged["unit"]["id"])
        assert unit["curb_weight_lbs"] == 2040
        assert unit["payload_capacity_lbs"] == 4260
        assert unit["gvwr_lbs"] == H.TA_CERTIFIED_GVWR_LBS
        H.assert_weight_budget_balances(unit)


class TestFrameInspectionsAreAppendOnly:
    def test_a_corrected_measurement_appends_a_second_row_and_leaves_the_first(self, api):
        """The failed reading stays on the record after the rework passes.

        PRD 2.5: "`FrameInspection` is the deliberate exception. A dimensional
        inspection is an immutable regulatory record: it carries only `id` and
        `created_at`. It has no `updated_at` and no `version`, and there is no
        endpoint that updates or deletes one."

        Design: Corner/entities/entity_frame_inspection_rows_are_immutable_and_append_only
        """
        plant = H.setup_plant(api)
        staged = H.unit_at_jig_reserved(plant, api)
        unit_id = staged["unit"]["id"]
        H.inspect_frame(api, unit_id, measured_length_mm=H.TA_NOMINAL_LENGTH_MM + 4)
        H.inspect_frame(api, unit_id, measured_length_mm=H.TA_NOMINAL_LENGTH_MM)

        rows, _meta = validate_paginated(
            api.list_frame_inspections(unit_id, headers=WELD_SUPERVISOR)
        )

        assert [row["inspection_seq"] for row in rows] == [1, 2]
        assert rows[0]["result"] == H.InspectionResult.FAIL
        H.assert_one_decimal(rows[0]["max_deviation_mm"], 4)
        assert rows[0]["failure_reasons"] == [H.FRAME_FAILURE_MAX_DEVIATION]
        assert rows[1]["result"] == H.InspectionResult.PASS
        H.assert_one_decimal(rows[1]["max_deviation_mm"], 0)
        assert rows[1]["failure_reasons"] == []
        for row in rows:
            H.assert_append_only_audit_fields(row)
            H.assert_timestamp_with_millis(row["created_at"])
        unit = H.read_unit(api, unit_id)
        assert unit["frame_fail_count"] == 1
        assert unit["build_status"] == H.BuildStatus.FRAME_WELDED


class TestReservationIsReachableFromBothParents:
    def test_the_reservation_surfaces_on_the_jig_channel_and_the_trailer_channel(self, api):
        """One row, two reverse-lookup lists, both foreign keys populated.

        PRD 3.2: "An accepted reservation is created against that jig with
        `jig_id` set, `status` `RESERVED`, and two computed quantities:
        `duration_minutes`, the whole minutes between `window_start_at` and
        `window_end_at` with the changeover buffer **excluded**, and
        `occupancy_end_at` as described above."

        Design: Corner/entities/entity_jig_reservation_resolves_both_of_its_foreign_keys
        """
        plant = H.setup_plant(api)
        staged = H.unit_at_jig_reserved(plant, api, window=H.JIG_WINDOW_1)
        reservation_id = staged["reservation"]["id"]

        from_the_jig, _jig_meta = validate_paginated(
            api.list_jig_reservations(
                plant["jig"]["id"],
                params={"status": H.ReservationStatus.RESERVED},
                headers=WELD_SUPERVISOR,
            )
        )
        from_the_trailer, _unit_meta = validate_paginated(
            api.list_unit_jig_reservations(staged["unit"]["id"], headers=WELD_SUPERVISOR)
        )

        assert [row["id"] for row in from_the_jig] == [reservation_id]
        assert [row["id"] for row in from_the_trailer] == [reservation_id]
        for row in (from_the_jig[0], from_the_trailer[0]):
            assert row["jig_id"] == plant["jig"]["id"]
            assert row["unit_id"] == staged["unit"]["id"]
            assert row["status"] == H.ReservationStatus.RESERVED
            assert row["duration_minutes"] == 120
            H.assert_instant(row["window_start_at"], H.JIG_WINDOW_1[0])
            H.assert_instant(row["occupancy_end_at"], H.JIG_WINDOW_1_OCCUPANCY_END)
