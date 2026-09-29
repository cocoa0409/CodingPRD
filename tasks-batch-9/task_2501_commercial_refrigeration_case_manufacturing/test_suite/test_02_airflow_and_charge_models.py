"""The airflow load model and the refrigerant charge basis (PRD §3.2).

One request computes eight thermal fields and three charge fields over the
design row and its blend, with every component rounded at its own precision
before the combination described in PRD §2.6.
"""

import pytest

from test_helpers import *  # noqa: F401,F403

LOW_TEMP_SELF_CONTAINED = {
    "model_code": "MDL-LT-6",
    "application": "FROZEN_REACH_IN",
    "temperature_class": "LT",
    "system_type": "SELF_CONTAINED",
    "nominal_length_ft": 6,
    "tda_sqft": 18.0,
    "charge_grams": 1800,
    "line_set_length_ft": 0,
    "door_type": "GLASS_DOOR",
    "glass_door_count": 3,
    "curtain_layers": 3,
    "discharge_velocity_mps": 0.60,
    "case_air_temp_c": -24.0,
    "ambient_dew_point_c": 12.0,
    "lighting_w_per_ft": 14.0,
    "fan_w_per_ft": 11.0,
    "defrost_cycles_per_day": 6,
}


class TestAirflowLoadModel:
    """PRD §3.2 — five rounded components, then the architecture branch."""

    def test_01_airflow_model_computes_every_component_for_a_medium_temp_remote_case(
        self, api
    ):
        """An 8 ft MT remote case totals 442.91 W with a zero rejection term.

        PRD §3.2: "The five components above are each rounded **first** and then
        added to form the load subtotal. A `SELF_CONTAINED` case then adds a
        condenser-heat rejection term, because its condenser dumps heat back
        into the space: eight hundredths of the already-rounded subtotal, itself
        rounded half up to 2 decimals. A `REMOTE` case's rejection term is
        exactly zero."

        Design: Difficulty/combinatorial_formula/airflow_design_load_nonlinear_branching_formula
        """
        ctx = setup_draft_case_model()

        data = validate_success(
            api.run_airflow_model(
                ctx["case_model"]["id"], TEST_USERS["design_engineer_headers"]
            )
        )
        assert data["status"] == "MODELED"
        assert data["curtain_factor"] == pytest.approx(0.88, abs=1e-9), (
            "a two-layer curtain reduces 1 by twelve hundredths exactly once"
        )
        assert data["infiltration_load_w"] == pytest.approx(255.51, abs=0.001)
        assert data["lighting_load_w"] == pytest.approx(96.00, abs=0.001)
        assert data["fan_load_w"] == pytest.approx(76.00, abs=0.001)
        assert data["defrost_load_w"] == pytest.approx(15.40, abs=0.001)
        assert data["anti_sweat_load_w"] == pytest.approx(0.00, abs=0.001), (
            "an MT case with no glass doors carries no anti-sweat load"
        )
        assert data["total_design_load_w"] == pytest.approx(442.91, abs=0.001)

    def test_02_airflow_model_adds_condenser_rejection_for_a_self_contained_case(
        self, api
    ):
        """A 6 ft LT self-contained glass-door case totals 910.80 W.

        PRD §3.2: "The **anti-sweat component** `anti_sweat_load_w` is a
        per-door anti-sweat wattage for the temperature class, multiplied by
        `glass_door_count`, rounded half up to 2 decimals."

        Design: Difficulty/combinatorial_formula/airflow_design_load_nonlinear_branching_formula
        """
        ctx = setup_draft_case_model(model_overrides=LOW_TEMP_SELF_CONTAINED)

        data = validate_success(
            api.run_airflow_model(
                ctx["case_model"]["id"], TEST_USERS["design_engineer_headers"]
            )
        )
        assert data["status"] == "MODELED"
        assert data["curtain_factor"] == pytest.approx(0.76, abs=1e-9), (
            "three curtain layers reduce 1 by twelve hundredths twice"
        )
        assert data["infiltration_load_w"] == pytest.approx(551.58, abs=0.001)
        assert data["anti_sweat_load_w"] == pytest.approx(126.00, abs=0.001), (
            "42 W per door for an LT case, times three glass doors"
        )
        assert data["total_design_load_w"] == pytest.approx(910.80, abs=0.001)

    def test_03_curtain_factor_is_clamped_at_its_minimum_for_six_layers(self, api):
        """Six curtain layers compute to 0.40 but are held at the 0.55 floor.

        PRD §3.2: "The **curtain factor** rewards additional curtain layers: it
        is one, reduced by twelve hundredths for each layer beyond the first,
        and then floored at fifty-five hundredths."

        Design: Corner/calculations/airflow_curtain_factor_clamped_at_minimum_for_six_layers
        """
        ctx = setup_draft_case_model(
            model_overrides={"model_code": "MDL-MT-8C", "curtain_layers": 6}
        )

        data = validate_success(
            api.run_airflow_model(
                ctx["case_model"]["id"], TEST_USERS["design_engineer_headers"]
            )
        )
        assert data["curtain_factor"] == pytest.approx(0.55, abs=1e-9)
        assert data["infiltration_load_w"] == pytest.approx(159.69, abs=0.001)
        assert data["lighting_load_w"] == pytest.approx(96.00, abs=0.001)
        assert data["fan_load_w"] == pytest.approx(76.00, abs=0.001)
        assert data["defrost_load_w"] == pytest.approx(15.40, abs=0.001)
        assert data["anti_sweat_load_w"] == pytest.approx(0.00, abs=0.001)
        assert data["total_design_load_w"] == pytest.approx(347.09, abs=0.001)
        assert data["status"] == "MODELED"

    def test_04_airflow_model_exposes_computed_loads_in_the_same_response(self, api):
        """The write response already carries the loads a later read repeats.

        PRD §3.2: "Both computations, together with all eight airflow fields,
        are written in the single airflow-model request, which also increments
        the case model's `version` by 1."

        Design: Corner/consistency_model/airflow_model_exposes_computed_loads_in_same_response
        """
        ctx = setup_draft_case_model()
        assert_case_model_load_fields_absent(ctx["case_model"])

        written = validate_success(
            api.run_airflow_model(
                ctx["case_model"]["id"], TEST_USERS["design_engineer_headers"]
            )
        )
        assert written["status"] == "MODELED"
        assert written["total_design_load_w"] == pytest.approx(442.91, abs=0.001)
        assert written["installed_charge_grams"] == 7320
        assert_version_is(written, 2, "case model")

        read_back = validate_success(
            api.get_case_model(
                ctx["case_model"]["id"], TEST_USERS["design_engineer_headers"]
            )
        )
        for field in (
            "curtain_factor",
            "velocity_factor",
            "infiltration_load_w",
            "lighting_load_w",
            "fan_load_w",
            "defrost_load_w",
            "anti_sweat_load_w",
            "total_design_load_w",
            "installed_charge_grams",
            "nameplate_co2e_kg",
            "installed_co2e_kg",
        ):
            assert read_back[field] == pytest.approx(written[field], abs=1e-9), (
                f"{field} must read back exactly as the write response returned it"
            )


class TestRefrigerantChargeBasis:
    """PRD §3.2 — the nameplate basis and the installed basis are distinct."""

    def test_05_charge_basis_separates_the_nameplate_mass_from_the_installed_mass(
        self, api
    ):
        """120 ft of line set adds 3120 g on the installed basis only.

        PRD §3.2: "The `installed_charge_grams` is the nameplate `charge_grams`
        plus 26 grams for every foot of `line_set_length_ft`, and it is an exact
        integer with no rounding."

        Design: Difficulty/dual_variant_calc/refrigerant_charge_nameplate_basis_versus_installed_basis
        """
        ctx = setup_draft_case_model()

        data = validate_success(
            api.run_airflow_model(
                ctx["case_model"]["id"], TEST_USERS["design_engineer_headers"]
            )
        )
        assert data["status"] == "MODELED"
        assert data["charge_grams"] == 4200, "the nameplate charge is untouched"
        assert data["installed_charge_grams"] == 7320
        assert data["nameplate_co2e_kg"] == pytest.approx(5825.4, abs=0.01)
        assert data["installed_co2e_kg"] == pytest.approx(10152.8, abs=0.01), (
            "the installed basis converts 7320 g at the blend's GWP of 1387"
        )
        assert data["installed_co2e_kg"] > data["nameplate_co2e_kg"], (
            "a remote case with a long line set must read higher on the installed basis"
        )

    def test_06_the_two_charge_bases_coincide_for_a_self_contained_case(self, api):
        """With zero line-set feet the nameplate and installed masses are equal.

        PRD §3.2: "Because a self-contained circuit is required to declare zero
        line-set feet, the two bases coincide exactly for `SELF_CONTAINED`
        cases."

        Design: Difficulty/dual_variant_calc/refrigerant_charge_nameplate_basis_versus_installed_basis
        """
        ctx = setup_draft_case_model(
            model_overrides={
                "model_code": "MDL-SC-8",
                "system_type": "SELF_CONTAINED",
                "line_set_length_ft": 0,
            }
        )

        data = validate_success(
            api.run_airflow_model(
                ctx["case_model"]["id"], TEST_USERS["design_engineer_headers"]
            )
        )
        assert data["installed_charge_grams"] == 4200, (
            "zero line-set feet contribute zero additional grams"
        )
        assert data["nameplate_co2e_kg"] == pytest.approx(5825.4, abs=0.01)
        assert data["installed_co2e_kg"] == pytest.approx(5825.4, abs=0.01)


class TestAirflowModelPreconditions:
    """PRD §3.2 — the model runs once, and only for a compatible architecture."""

    def test_07_airflow_model_run_twice_is_rejected(self, api):
        """A MODELED design cannot run the airflow model a second time.

        PRD §3.2: "Running the **airflow model** moves the design `DRAFT →
        MODELED` and takes no request body at all: everything it needs is
        already on the row. It is admissible only from `DRAFT`."

        Design: Corner/state_machines/case_model_airflow_model_run_twice_rejected
        """
        ctx = setup_modeled_case_model()

        response = api.run_airflow_model(
            ctx["case_model"]["id"], TEST_USERS["design_engineer_headers"]
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)

        fetched = refresh_case_model(ctx)
        assert fetched["status"] == "MODELED"
        assert fetched["total_design_load_w"] == pytest.approx(442.91, abs=0.001)
        assert_version_is(fetched, 2, "case model")

    def test_08_airflow_model_with_an_incompatible_refrigerant_is_rejected(self, api):
        """A REMOTE design charged with a self-contained-only blend is refused.

        PRD §3.2: "The design's `system_type` must be a member of the
        `allowed_system_types` of the blend named by `refrigerant_id`, and a
        mismatch is rejected with `ERR_REFRIGERANT_SYSTEM_TYPE_INCOMPATIBLE`
        (HTTP 422) at global rank 10"

        Design: Corner/validations/airflow_model_with_incompatible_refrigerant_rejected
        """
        ctx = setup_draft_case_model(
            refrigerant_overrides={
                "refrigerant_code": "R-290",
                "trade_name": "Propane",
                "gwp_100yr": 3,
                "safety_class": "A3",
                "max_charge_grams": 300,
                "allowed_system_types": ["SELF_CONTAINED"],
            },
            model_overrides={
                "model_code": "MDL-MT-8R",
                "system_type": "REMOTE",
                "charge_grams": 280,
                "line_set_length_ft": 120,
            },
        )

        response = api.run_airflow_model(
            ctx["case_model"]["id"], TEST_USERS["design_engineer_headers"]
        )
        validate_error(
            response, ApiErrorId.ERR_REFRIGERANT_SYSTEM_TYPE_INCOMPATIBLE.value
        )

        fetched = refresh_case_model(ctx)
        assert fetched["status"] == "DRAFT"
        assert fetched.get("total_design_load_w") is None
        assert_version_is(fetched, 1, "case model")

    def test_09_submit_for_test_records_the_submitter_and_bumps_the_version(self, api):
        """Submission stamps `submitted_by_user_id` and moves version 2 to 3.

        PRD §3.2: "Submission also increments the case model's `version` by 1."

        Design: Corner/endpoints/submit_for_test_action_records_submitter_and_bumps_version
        """
        ctx = setup_modeled_case_model()
        assert ctx["case_model"]["version"] == 2
        assert ctx["case_model"].get("submitted_by_user_id") is None

        data = validate_success(
            api.submit_case_model_for_test(
                ctx["case_model"]["id"], TEST_USERS["design_engineer_headers"]
            )
        )
        assert data["status"] == "SUBMITTED_FOR_TEST"
        assert data["submitted_by_user_id"] == DESIGN_ENGINEER_USER_ID
        assert_version_is(data, 3, "case model")
        assert data["design_revision"] == 1
