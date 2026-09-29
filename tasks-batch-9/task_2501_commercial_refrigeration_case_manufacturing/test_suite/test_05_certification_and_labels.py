"""Label issuance, its preconditions, and supersession by an engineering change.

PRD §3.4 pins the printed record on the label and certifies the design in the
same request; PRD §3.5 hop 2 supersedes that label when the design moves on.
"""

import pytest

from test_helpers import *  # noqa: F401,F403

A2L_TRANSITION_BLEND = {
    "refrigerant_code": "R-454C",
    "trade_name": "Opteon XL20",
    "gwp_100yr": 148,
    "safety_class": "A2L",
    "max_charge_grams": 4000,
    "allowed_system_types": ["REMOTE", "SELF_CONTAINED"],
}


class TestLabelIssuance:
    """PRD §3.4 — the gate where the most preconditions converge."""

    def test_01_label_issuance_pins_the_printed_record_and_certifies_the_design(
        self, api
    ):
        """One request pins three values and moves TESTED_PASS to CERTIFIED.

        PRD §3.4: "Three values are pinned at issuance: `pinned_design_revision`
        takes the model's current `design_revision`, `pinned_lab_rated_index`
        takes the source test's `lab_rated_index`, and `pinned_standard_code`
        takes the `standard_code` of the energy standard that test was run
        against."

        Design: Corner/state_machines/compliance_label_issue_pins_index_and_certifies_model
        """
        ctx = setup_completed_energy_test()
        assert ctx["case_model"]["status"] == "TESTED_PASS"
        assert ctx["energy_test"]["lab_rated_index"] == pytest.approx(0.568, abs=0.0001)

        data = validate_success(
            api.create_compliance_label(
                create_compliance_label_payload(
                    ctx["case_model"]["id"], ctx["energy_test"]["id"]
                ),
                TEST_USERS["compliance_officer_headers"],
            ),
            expected_status=201,
        )
        assert_compliance_label(data)
        assert data["label_status"] == "ISSUED"
        assert data["pinned_design_revision"] == 1
        assert data["pinned_lab_rated_index"] == pytest.approx(0.568, abs=0.0001)
        assert data["pinned_standard_code"] == "DOE-2027-RSC-MT"
        assert data["issued_by_user_id"] == COMPLIANCE_OFFICER_USER_ID
        assert data.get("revocation_reason") is None

        assert refresh_case_model(ctx)["status"] == "CERTIFIED"

    def test_02_label_issuance_above_the_standard_gwp_ceiling_is_rejected(self, api):
        """A blend at 1387 GWP cannot be labelled against a 150 GWP ceiling.

        PRD §3.4: "And the refrigerant's `gwp_100yr` must be at or below the
        `max_gwp` of the energy standard the test was run against, else
        `ERR_GWP_EXCEEDS_STANDARD` (HTTP 422) at global rank 12."

        Design: Corner/validations/label_issue_with_gwp_above_standard_ceiling_rejected
        """
        ctx = setup_completed_energy_test(
            standard_overrides={
                "standard_code": "DOE-2028-LOWGWP-MT",
                "max_gwp": 150,
            }
        )
        assert ctx["refrigerant"]["gwp_100yr"] == 1387
        version_before = ctx["case_model"]["version"]

        response = api.create_compliance_label(
            create_compliance_label_payload(
                ctx["case_model"]["id"], ctx["energy_test"]["id"]
            ),
            TEST_USERS["compliance_officer_headers"],
        )
        validate_error(response, ApiErrorId.ERR_GWP_EXCEEDS_STANDARD.value)

        model = refresh_case_model(ctx)
        assert model["status"] == "TESTED_PASS"
        assert_version_is(model, version_before, "case model after the rejected label")

        _rows, meta = validate_paginated(
            api.list_compliance_labels(TEST_USERS["compliance_officer_headers"])
        )
        assert meta["total_count"] == 0

    def test_03_label_issued_by_the_submitting_user_id_is_rejected(self, api):
        """The officer whose id submitted the design may not certify it.

        PRD §3.4: "The acting officer's `X-User-ID` must differ from the model's
        `submitted_by_user_id`, else the rank-9 `ERR_SEGREGATION_OF_DUTIES` (HTTP
        403) applies."

        Design: Corner/validations/label_issued_by_submitting_engineer_id_rejected
        """
        ctx = setup_modeled_case_model()
        ctx["case_model"] = validate_success(
            api.submit_case_model_for_test(
                ctx["case_model"]["id"],
                make_design_engineer_headers(COMPLIANCE_OFFICER_USER_ID),
            )
        )
        ctx["case_model_version"] = ctx["case_model"]["version"]
        assert ctx["case_model"]["submitted_by_user_id"] == COMPLIANCE_OFFICER_USER_ID

        ctx["energy_test"] = validate_success(
            schedule_energy_test(ctx), expected_status=201
        )
        validate_success(
            api.start_energy_test(
                ctx["energy_test"]["id"], TEST_USERS["test_lab_technician_headers"]
            )
        )
        ctx["energy_test"] = validate_success(
            api.complete_energy_test(
                ctx["energy_test"]["id"],
                complete_energy_test_payload(),
                TEST_USERS["test_lab_technician_headers"],
            )
        )

        payload = create_compliance_label_payload(
            ctx["case_model"]["id"], ctx["energy_test"]["id"]
        )
        conflicted = api.create_compliance_label(
            payload, TEST_USERS["compliance_officer_headers"]
        )
        validate_error(conflicted, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

        accepted = validate_success(
            api.create_compliance_label(
                payload, TEST_USERS["compliance_officer_alt_headers"]
            ),
            expected_status=201,
        )
        assert accepted["label_status"] == "ISSUED"
        assert accepted["issued_by_user_id"] == COMPLIANCE_OFFICER_ALT_USER_ID


class TestLabelSupersession:
    """PRD §3.5 — the design may move; the printed record may not."""

    def test_04_the_pinned_index_survives_supersession_by_an_engineering_change(
        self, api
    ):
        """The label goes SUPERSEDED while all three pinned values stand still.

        PRD §3.5: "Because `design_revision` now exceeds the
        `pinned_design_revision` of any label written against the previous
        revision, every compliance label of this model whose `label_status` is
        `ISSUED` moves `ISSUED → SUPERSEDED`."

        Design: Corner/cross_cutting_complexity_layers/label_pinned_index_survives_supersession_by_engineering_change
        """
        ctx = setup_certified_case_model()
        low_gwp = seed_low_gwp_refrigerant()

        changed = validate_success(
            open_engineering_change(
                ctx,
                refrigerant_id=low_gwp["id"],
                charge_grams=3900,
                line_set_length_ft=120,
                change_note="Transition to R-454C",
            )
        )
        assert changed["status"] == "DRAFT"
        assert changed["design_revision"] == 2
        assert changed["refrigerant_id"] == low_gwp["id"]
        assert changed.get("total_design_load_w") is None
        assert changed.get("installed_charge_grams") is None

        label = refresh_compliance_label(ctx)
        assert label["label_status"] == "SUPERSEDED"
        assert label["pinned_lab_rated_index"] == pytest.approx(0.568, abs=0.0001)
        assert label["pinned_design_revision"] == 1
        assert label["pinned_standard_code"] == "DOE-2027-RSC-MT"

    def test_05_a_certified_design_cycles_back_to_draft_on_a_refrigerant_transition(
        self, api
    ):
        """CERTIFIED → DRAFT clears every computed field and the submitter.

        PRD §3.5: "The model's `design_revision` is incremented by exactly 1,
        `submitted_by_user_id` is cleared to absent, `status` becomes `DRAFT`, and
        every computed airflow and charge field is cleared to absent"

        Design: Difficulty/non_linear_state_machine/case_model_certified_cycles_back_to_draft_on_refrigerant_transition
        """
        ctx = setup_certified_case_model()
        assert ctx["case_model"]["status"] == "CERTIFIED"
        a2l = seed_refrigerant(**A2L_TRANSITION_BLEND)

        changed = validate_success(
            open_engineering_change(
                ctx,
                refrigerant_id=a2l["id"],
                charge_grams=3600,
                line_set_length_ft=120,
                change_note="R-454C transition for the 2027 GWP step-down",
            )
        )
        assert changed["status"] == "DRAFT"
        assert changed["design_revision"] == 2
        assert changed["refrigerant_id"] == a2l["id"]
        assert changed["charge_grams"] == 3600
        assert changed.get("submitted_by_user_id") is None
        assert_case_model_load_fields_absent(changed)

        label = refresh_compliance_label(ctx)
        assert label["label_status"] == "SUPERSEDED"
        assert label["pinned_design_revision"] == 1

        assert refresh_energy_test(ctx)["status"] == "COMPLETED_PASS", (
            "the passing test is stranded by the change, never voided"
        )

    def test_06_the_cycled_design_re_runs_the_airflow_model_on_the_new_blend(self, api):
        """Back in DRAFT the airflow model is admissible again at revision 2.

        PRD §3.5: "Because the airflow fields are gone, the engineer must run the
        airflow model again before the design can be re-submitted."

        Design: Difficulty/non_linear_state_machine/case_model_certified_cycles_back_to_draft_on_refrigerant_transition
        """
        ctx = setup_certified_case_model()
        low_gwp = seed_low_gwp_refrigerant(max_charge_grams=8000)
        assert low_gwp["gwp_100yr"] == 146

        validate_success(
            open_engineering_change(
                ctx,
                refrigerant_id=low_gwp["id"],
                charge_grams=3600,
                line_set_length_ft=120,
                change_note="R-454C transition for the 2027 GWP step-down",
            )
        )

        remodelled = validate_success(
            api.run_airflow_model(
                ctx["case_model"]["id"], TEST_USERS["design_engineer_headers"]
            )
        )
        assert remodelled["status"] == "MODELED"
        assert remodelled["design_revision"] == 2
        assert remodelled["installed_charge_grams"] == 6720
        assert remodelled["nameplate_co2e_kg"] == pytest.approx(525.6, abs=0.01)
        assert remodelled["installed_co2e_kg"] == pytest.approx(981.1, abs=0.01)

        resubmitted = validate_success(
            api.submit_case_model_for_test(
                ctx["case_model"]["id"], TEST_USERS["design_engineer_headers"]
            )
        )
        assert resubmitted["status"] == "SUBMITTED_FOR_TEST"
        assert resubmitted["design_revision"] == 2
        assert resubmitted["submitted_by_user_id"] == DESIGN_ENGINEER_USER_ID
