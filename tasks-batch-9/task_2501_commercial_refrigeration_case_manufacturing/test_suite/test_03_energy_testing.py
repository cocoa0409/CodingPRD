"""Energy test scheduling, starting, completion and the two index variants.

PRD §3.3 pins the standard's coefficients and the design's display area at
scheduling time, then decides pass or fail from the laboratory variant alone
while still computing the field projection in full.
"""

import pytest

from test_helpers import *  # noqa: F401,F403

LOW_TEMP_STANDARD = {
    "standard_code": "DOE-2027-RSC-LT",
    "effective_date": "2026-01-01T00:00:00Z",
    "max_gwp": 1500,
    "limit_coefficient_a": 0.90,
    "limit_constant_b": 1.50,
    "temperature_class": "LT",
    "system_type_scope": "ANY",
}


class TestSchedulingPinsTheContract:
    """PRD §3.3 — creation copies the design and the standard exactly once."""

    def test_01_scheduling_pins_the_standard_coefficients_and_the_design_area(self, api):
        """The daily limit is frozen at 17.568 kWh alongside the pinned inputs.

        PRD §3.3: "It is the standard's `limit_coefficient_a` multiplied by the
        case model's `tda_sqft`, plus the standard's `limit_constant_b`, rounded
        half up to 3 decimal places, and stored as `limit_daily_kwh`."

        Design: Corner/calculations/energy_limit_daily_kwh_pins_standard_coefficients_at_scheduling
        """
        ctx = setup_submitted_case_model()

        data = validate_success(schedule_energy_test(ctx), expected_status=201)
        assert_energy_test(data)
        assert data["status"] == "SCHEDULED"
        assert data["limit_daily_kwh"] == pytest.approx(17.568, abs=0.0001)
        assert data["pinned_tda_sqft"] == pytest.approx(26.4, abs=0.0001)
        assert data["pinned_defrost_cycles_per_day"] == 4
        assert data["pinned_design_revision"] == 1
        assert data.get("measured_kwh_24h") is None
        assert data.get("lab_rated_index") is None

    def test_02_energy_test_creation_links_the_model_chamber_and_standard(self, api):
        """One create links three parents and each is independently filterable.

        PRD §3.3: "Test listings can be filtered by `case_model_id`,
        `test_chamber_id`, `energy_standard_id` or `status`."

        Design: Corner/endpoints/energy_test_create_links_model_chamber_and_standard
        """
        ctx = setup_submitted_case_model()

        created = validate_success(schedule_energy_test(ctx), expected_status=201)
        assert created["case_model_id"] == ctx["case_model"]["id"]
        assert created["test_chamber_id"] == ctx["test_chamber"]["id"]
        assert created["energy_standard_id"] == ctx["energy_standard"]["id"]
        assert created["status"] == "SCHEDULED"
        assert created["pinned_design_revision"] == 1

        by_chamber, chamber_meta = validate_paginated(
            api.list_energy_tests(
                TEST_USERS["test_lab_technician_headers"],
                params={"test_chamber_id": ctx["test_chamber"]["id"]},
            )
        )
        assert chamber_meta["total_count"] == 1
        assert by_chamber[0]["id"] == created["id"]

        by_standard, standard_meta = validate_paginated(
            api.list_energy_tests(
                TEST_USERS["test_lab_technician_headers"],
                params={"energy_standard_id": ctx["energy_standard"]["id"]},
            )
        )
        assert standard_meta["total_count"] == 1
        assert by_standard[0]["limit_daily_kwh"] == pytest.approx(17.568, abs=0.0001)

    def test_03_stale_case_model_version_is_rejected_on_energy_test_creation(self, api):
        """A token read before submit-for-test is refused at HTTP 412.

        PRD §2.7: "Scheduling an energy test requires
        `expected_case_model_version` as a non-optional field in the request
        body, carrying the client's last observed `version` of the case model
        named by `case_model_id`. If that value does not equal the case model's
        current `version`, the create is rejected with
        `ERR_STALE_CASE_MODEL_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_case_model_version_rejected_on_energy_test_create
        """
        ctx = setup_modeled_case_model()
        stale_token = ctx["case_model"]["version"]
        assert stale_token == 2

        ctx["case_model"] = validate_success(
            api.submit_case_model_for_test(
                ctx["case_model"]["id"], TEST_USERS["design_engineer_headers"]
            )
        )
        assert_version_is(ctx["case_model"], 3, "case model")
        ctx["case_model_version"] = ctx["case_model"]["version"]

        stale = schedule_energy_test(ctx, expected_case_model_version=stale_token)
        validate_error(stale, ApiErrorId.ERR_STALE_CASE_MODEL_VERSION.value)
        assert_version_is(
            refresh_case_model(ctx), 3, "case model after the rejected schedule"
        )

        created = validate_success(schedule_energy_test(ctx), expected_status=201)
        assert created["status"] == "SCHEDULED"
        assert created["pinned_design_revision"] == 1
        assert created["limit_daily_kwh"] == pytest.approx(17.568, abs=0.0001)
        assert_version_is(
            refresh_case_model(ctx), 4, "case model after the accepted schedule"
        )

    def test_04_energy_test_against_a_wrong_class_standard_is_rejected(self, api):
        """An LT standard cannot cover an MT design.

        PRD §3.3: "First at global rank 13, the standard must actually cover the
        case: the standard's `temperature_class` must equal the model's
        `temperature_class`, the standard's `system_type_scope` must be either
        `ANY` or exactly the model's `system_type`, and the requested
        `window_start` must fall at or after the standard's `effective_date`."

        Design: Corner/validations/energy_test_against_wrong_class_standard_rejected
        """
        ctx = setup_submitted_case_model(standard_overrides=LOW_TEMP_STANDARD)

        response = schedule_energy_test(ctx)
        validate_error(response, ApiErrorId.ERR_STANDARD_NOT_APPLICABLE.value)

        _rows, meta = validate_paginated(
            api.list_energy_tests(TEST_USERS["test_lab_technician_headers"])
        )
        assert meta["total_count"] == 0, "the rejected schedule must not have persisted"

    def test_05_energy_test_window_ending_at_its_start_is_rejected(self, api):
        """A zero-length occupation interval is invalid.

        PRD §2.10: "Either violation is rejected with `ERR_INVALID_INTERVAL`
        (HTTP 422) at global rank 29."

        Design: Corner/validations/energy_test_window_end_equal_to_start_rejected
        """
        ctx = setup_submitted_case_model()

        response = schedule_energy_test(
            ctx,
            window_start="2026-08-03T08:00:00Z",
            window_end="2026-08-03T08:00:00Z",
        )
        validate_error(response, ApiErrorId.ERR_INVALID_INTERVAL.value)


class TestEnergyTestLifecycle:
    """PRD §3.3 — start and complete are each admissible exactly once."""

    def test_06_energy_test_start_called_twice_is_rejected(self, api):
        """A RUNNING test cannot be started again.

        PRD §3.3: "Starting a scheduled test moves it `SCHEDULED → RUNNING`,
        takes no request body, and increments the test's `version` by 1."

        Design: Corner/state_machines/energy_test_start_called_twice_rejected
        """
        ctx = setup_running_energy_test()

        response = api.start_energy_test(
            ctx["energy_test"]["id"], TEST_USERS["test_lab_technician_headers"]
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)

        fetched = refresh_energy_test(ctx)
        assert fetched["status"] == "RUNNING"
        assert_version_is(fetched, 2, "energy test")

    def test_07_energy_test_completion_on_a_completed_test_is_rejected(self, api):
        """Completion is admissible only from RUNNING, so it cannot repeat.

        PRD §3.3: "Completion is admissible only from `RUNNING`, and it
        recomputes both index variants before deciding the outcome."

        Design: Corner/state_machines/energy_test_complete_on_completed_pass_rejected
        """
        ctx = setup_completed_energy_test()
        assert ctx["energy_test"]["status"] == "COMPLETED_PASS"

        response = api.complete_energy_test(
            ctx["energy_test"]["id"],
            complete_energy_test_payload(measured_kwh_24h=17.0, measured_defrost_cycles=2),
            TEST_USERS["test_lab_technician_headers"],
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)

        fetched = refresh_energy_test(ctx)
        assert fetched["status"] == "COMPLETED_PASS"
        assert fetched["measured_kwh_24h"] == pytest.approx(15.0, abs=0.0001)
        assert fetched["lab_rated_index"] == pytest.approx(0.568, abs=0.0001)
        assert_version_is(fetched, 3, "energy test")
        assert refresh_case_model(ctx)["status"] == "TESTED_PASS"

    def test_08_energy_test_start_is_rejected_while_the_design_is_still_modeled(
        self, api
    ):
        """A test scheduled against a MODELED design fails the state check first.

        PRD §2.7: "Both checks sit at global rank 8, after state admissibility
        and before every domain rule, so a request that is both in the wrong
        state and carrying a stale version reports
        `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/energy_test_start_rejected_while_case_model_still_modeled
        """
        ctx = setup_modeled_case_model()
        ctx["energy_test"] = validate_success(
            schedule_energy_test(ctx), expected_status=201
        )
        assert ctx["energy_test"]["pinned_design_revision"] == 1

        response = api.start_energy_test(
            ctx["energy_test"]["id"], TEST_USERS["test_lab_technician_headers"]
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)

        fetched = refresh_energy_test(ctx)
        assert fetched["status"] == "SCHEDULED"
        assert_version_is(fetched, 1, "energy test")


class TestEnergyIndexVariants:
    """PRD §3.3 — the laboratory variant judges, the field variant informs."""

    def test_09_lab_and_field_variants_diverge_when_the_store_runs_warmer(self, api):
        """A 7 °C warmer store lifts 17.0 kWh to a 21.725 kWh projection.

        PRD §3.3: "Then `field_projected_daily_kwh` is `measured_kwh_24h`
        multiplied by the ambient uplift, plus twenty-eight hundredths of a
        kilowatt-hour for each missed defrost cycle, with the whole expression
        rounded half up to 3 decimals exactly once at the end."

        Design: Difficulty/dual_variant_calc/energy_index_lab_variant_versus_field_variant_divergence
        """
        ctx = setup_running_energy_test(
            test_overrides={"test_ambient_c": 24.0, "store_ambient_c": 31.0}
        )
        assert ctx["energy_test"]["limit_daily_kwh"] == pytest.approx(17.568, abs=0.0001)

        data = validate_success(
            api.complete_energy_test(
                ctx["energy_test"]["id"],
                complete_energy_test_payload(
                    measured_kwh_24h=17.0, measured_defrost_cycles=2
                ),
                TEST_USERS["test_lab_technician_headers"],
            )
        )
        assert data["status"] == "COMPLETED_PASS", (
            "pass or fail is decided by the laboratory variant alone"
        )
        assert data["lab_rated_index"] == pytest.approx(0.644, abs=0.0001)
        assert data["field_projected_daily_kwh"] == pytest.approx(21.725, abs=0.0001)
        assert data["field_projected_index"] == pytest.approx(0.823, abs=0.0001)
        assert data["field_exceedance"] is True, (
            "the lab variant passed while the projection sits above the limit"
        )

        ctx["energy_test"] = data
        assert refresh_case_model(ctx)["status"] == "TESTED_PASS"

    def test_10_field_variant_floors_the_uplift_and_the_missed_defrost_credit(
        self, api
    ):
        """A cooler store and extra defrost cycles earn no correction at all.

        PRD §3.3: "The missed defrost count is `pinned_defrost_cycles_per_day`
        less `measured_defrost_cycles`, floored at zero, so a chamber that ran
        more cycles than the design calls for earns no credit."

        Design: Difficulty/dual_variant_calc/energy_index_lab_variant_versus_field_variant_divergence
        """
        ctx = setup_running_energy_test(
            test_overrides={"test_ambient_c": 24.0, "store_ambient_c": 20.0}
        )

        data = validate_success(
            api.complete_energy_test(
                ctx["energy_test"]["id"],
                complete_energy_test_payload(
                    measured_kwh_24h=15.0, measured_defrost_cycles=6
                ),
                TEST_USERS["test_lab_technician_headers"],
            )
        )
        assert data["status"] == "COMPLETED_PASS"
        assert data["lab_rated_index"] == pytest.approx(0.568, abs=0.0001)
        assert data["field_projected_daily_kwh"] == pytest.approx(15.000, abs=0.0001), (
            "a store cooler than the chamber floors the uplift excess at zero"
        )
        assert data["field_projected_index"] == pytest.approx(0.568, abs=0.0001)
        assert data["field_exceedance"] is False

    def test_11_measurement_exactly_equal_to_the_daily_limit_passes(self, api):
        """17.568 kWh against a 17.568 kWh limit is a pass, not a fail.

        PRD §3.3: "A measurement exactly equal to the limit therefore passes."

        Design: Difficulty/boundary_precision_check/measured_energy_exactly_equal_to_daily_limit_passes
        """
        ctx = setup_running_energy_test(
            test_overrides={"test_ambient_c": 24.0, "store_ambient_c": 24.0}
        )
        assert ctx["energy_test"]["limit_daily_kwh"] == pytest.approx(17.568, abs=0.0001)

        data = validate_success(
            api.complete_energy_test(
                ctx["energy_test"]["id"],
                complete_energy_test_payload(
                    measured_kwh_24h=17.568, measured_defrost_cycles=4
                ),
                TEST_USERS["test_lab_technician_headers"],
            )
        )
        assert data["status"] == "COMPLETED_PASS"
        assert data["lab_rated_index"] == pytest.approx(0.665, abs=0.0001)
        assert data["field_projected_daily_kwh"] == pytest.approx(17.568, abs=0.0001)
        assert data["field_projected_index"] == pytest.approx(0.665, abs=0.0001)
        assert data["field_exceedance"] is False, (
            "the projection is not strictly above the limit, so nothing is flagged"
        )

        ctx["energy_test"] = data
        assert refresh_case_model(ctx)["status"] == "TESTED_PASS"

    def test_12_measurement_one_thousandth_above_the_daily_limit_fails(self, api):
        """17.569 kWh is strictly above the limit and fails the standard.

        PRD §3.3: "the test moves `RUNNING → COMPLETED_PASS` when
        `measured_kwh_24h` is at or below `limit_daily_kwh`, and `RUNNING →
        COMPLETED_FAIL` when it is strictly above."

        Design: Difficulty/boundary_precision_check/measured_energy_exactly_equal_to_daily_limit_passes
        """
        ctx = setup_running_energy_test(
            test_overrides={"test_ambient_c": 24.0, "store_ambient_c": 24.0}
        )

        data = validate_success(
            api.complete_energy_test(
                ctx["energy_test"]["id"],
                complete_energy_test_payload(
                    measured_kwh_24h=17.569, measured_defrost_cycles=4
                ),
                TEST_USERS["test_lab_technician_headers"],
            )
        )
        assert data["status"] == "COMPLETED_FAIL"
        assert data["field_exceedance"] is False, (
            "field_exceedance requires the lab variant to have passed"
        )

        ctx["energy_test"] = data
        assert refresh_case_model(ctx)["status"] == "TESTED_FAIL"


class TestDesignRevisionPinning:
    """PRD §2.7 and §3.5 — a test keeps its chamber slot but not its validity."""

    def test_13_pinned_design_revision_survives_an_engineering_change(self, api):
        """The engineering change moves the model, never the pinned copies.

        PRD §3.3: "Every later index computation divides by the pinned display
        area and reasons about the pinned defrost count, never about the live
        model fields — this is what makes a completed test reproducible after
        the design has moved on."

        Design: Corner/entities/energy_test_pinned_design_revision_immutable_after_engineering_change
        """
        ctx = setup_scheduled_energy_test()

        validate_success(
            open_engineering_change(
                ctx,
                refrigerant_id=ctx["refrigerant"]["id"],
                charge_grams=1200,
                line_set_length_ft=100,
                change_note="Lower-GWP retrofit trial",
            )
        )

        test_row = refresh_energy_test(ctx)
        assert test_row["pinned_design_revision"] == 1
        assert test_row["pinned_tda_sqft"] == pytest.approx(26.4, abs=0.0001)
        assert test_row["pinned_defrost_cycles_per_day"] == 4
        assert test_row["limit_daily_kwh"] == pytest.approx(17.568, abs=0.0001)
        assert test_row["status"] == "SCHEDULED", (
            "a SCHEDULED test keeps its chamber slot through an engineering change"
        )

        model = refresh_case_model(ctx)
        assert model["design_revision"] == 2
        assert model["status"] == "DRAFT"

    def test_14_energy_test_start_is_blocked_by_a_bumped_design_revision(self, api):
        """A test whose pinned revision has fallen behind is caught at the door.

        PRD §3.3: "Beyond admissibility from `SCHEDULED`, it requires the case
        model to still be in `SUBMITTED_FOR_TEST` and the test's
        `pinned_design_revision` to still equal the model's live
        `design_revision`; a revision mismatch is the rank-14 rejection
        `ERR_CASE_MODEL_REVISION_STALE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/energy_test_start_blocked_by_case_model_design_revision
        """
        ctx = setup_scheduled_energy_test()
        low_gwp = seed_low_gwp_refrigerant(max_charge_grams=4000)

        validate_success(
            open_engineering_change(
                ctx,
                refrigerant_id=low_gwp["id"],
                charge_grams=1200,
                line_set_length_ft=100,
                change_note="R-454C transition before the lab slot opened",
            )
        )
        remodelled = validate_success(
            api.run_airflow_model(
                ctx["case_model"]["id"], TEST_USERS["design_engineer_headers"]
            )
        )
        assert remodelled["installed_charge_grams"] == 3800
        validate_success(
            api.submit_case_model_for_test(
                ctx["case_model"]["id"], TEST_USERS["design_engineer_headers"]
            )
        )

        response = api.start_energy_test(
            ctx["energy_test"]["id"], TEST_USERS["test_lab_technician_headers"]
        )
        validate_error(response, ApiErrorId.ERR_CASE_MODEL_REVISION_STALE.value)

        test_row = refresh_energy_test(ctx)
        assert test_row["status"] == "SCHEDULED"
        assert test_row["pinned_design_revision"] == 1

        model = refresh_case_model(ctx)
        assert model["design_revision"] == 2
        assert model["status"] == "SUBMITTED_FOR_TEST"
        assert model["installed_charge_grams"] == 3800

    def test_15_a_test_scheduled_at_the_new_revision_starts_while_the_old_one_cannot(
        self, api
    ):
        """Only the test pinned to the live revision may occupy the chamber.

        PRD §2.7: "Whenever the service later acts on such a document, it
        compares the pinned copy against the live `design_revision` on the
        model, and a mismatch is rejected with `ERR_CASE_MODEL_REVISION_STALE`
        (HTTP 409) at global rank 14."

        Design: Difficulty/cross_entity_state_dependency/energy_test_start_blocked_by_case_model_design_revision
        """
        ctx = setup_scheduled_energy_test()
        stranded_test_id = ctx["energy_test"]["id"]
        low_gwp = seed_low_gwp_refrigerant(max_charge_grams=4000)

        validate_success(
            open_engineering_change(
                ctx,
                refrigerant_id=low_gwp["id"],
                charge_grams=1200,
                line_set_length_ft=100,
                change_note="R-454C transition before the lab slot opened",
            )
        )
        validate_success(
            api.run_airflow_model(
                ctx["case_model"]["id"], TEST_USERS["design_engineer_headers"]
            )
        )
        validate_success(
            api.submit_case_model_for_test(
                ctx["case_model"]["id"], TEST_USERS["design_engineer_headers"]
            )
        )
        refresh_case_model(ctx)

        # The blocked interval around the stranded slot ends at 2026-08-04T20:00Z,
        # and a candidate that merely touches it is accepted (PRD §3.3).
        fresh = validate_success(
            schedule_energy_test(
                ctx,
                window_start="2026-08-04T20:00:00Z",
                window_end="2026-08-05T20:00:00Z",
            ),
            expected_status=201,
        )
        assert fresh["pinned_design_revision"] == 2

        started = validate_success(
            api.start_energy_test(fresh["id"], TEST_USERS["test_lab_technician_headers"])
        )
        assert started["status"] == "RUNNING"

        stale = api.start_energy_test(
            stranded_test_id, TEST_USERS["test_lab_technician_headers"]
        )
        validate_error(stale, ApiErrorId.ERR_CASE_MODEL_REVISION_STALE.value)
