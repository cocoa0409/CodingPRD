"""Water-quality certification cascades and the license-application gate."""
import pytest

from test_helpers import (
    TEST_USERS,
    U_LICENSEE_A,
    U_LICENSEE_B,
    advance_environmental_review,
    api_client,
    application_payload,
    assert_ledger_matches,
    assert_measure_costs,
    assert_postures,
    certify_with_conditions,
    file_pad,
    list_measures,
    make_licensee_headers,
    new_measure,
    new_project,
    new_study,
    read_application,
    read_measure,
    read_project,
    record_definitive_estimate,
    request_certification,
    set_clock,
    setup_application_under_review,
    setup_study_phase_project,
    validate_error,
    validate_paginated,
)

REGULATOR_HEADERS = TEST_USERS["regulator_headers"]
LICENSEE_HEADERS = make_licensee_headers(U_LICENSEE_A)
FULL_HEIGHT_LADDER = dict(
    measure_name="Full-height fish ladder",
    resource_category="FISH_PASSAGE",
    capital_cost_usd=4000000.00,
    annual_om_cost_usd=100000.00,
    construction_start_year=2026,
    implementation_months=24,
    flow_release_cfs=300,
    gross_head_ft=90,
    release_days=200,
)


class TestCertificationConditionCascade:
    def _certified_small_project(self):
        ctx = setup_study_phase_project(
            sites=[dict(river_mile=2.0)],
            project_name="Little Bend",
            installed_capacity_mw=12.0,
            base_annual_generation_mwh=50000,
            license_expiration_date="2033-12-31",
        )
        new_study(
            ctx["plan"]["id"],
            ctx["sites"][0]["id"],
            resource_category="WATER_QUALITY",
            study_title="Temperature study",
        )
        wqc = request_certification(ctx["project"]["id"])
        ctx["wqc"] = certify_with_conditions(
            wqc["id"], conditions=[dict(FULL_HEIGHT_LADDER)]
        )
        return ctx

    def test_the_state_condition_becomes_an_included_preliminary_measure(self):
        """One certifier call creates the measure the licensee never asked for.

        PRD §3.6: "The system sets `condition_count` to the number of elements and then, for each element, creates a mitigation measure whose `source` is `WQC_CONDITION`, whose status is `INCLUDED` immediately — state conditions are not proposals to be negotiated — and whose `cost_estimate_variant` is `PRELIMINARY`, with all six derived cost and generation figures computed under the preliminary variant of §3.7."

        Design: Difficulty/transitive_cascade/wqc_condition_issuance_cascades_into_restricted_posture
        """
        ctx = self._certified_small_project()

        assert ctx["wqc"]["status"] == "CERTIFIED_WITH_CONDITIONS"
        assert ctx["wqc"]["condition_count"] == 1
        measures = list_measures(ctx["project"]["id"], source="WQC_CONDITION")
        assert len(measures) == 1
        condition_measure = measures[0]
        assert condition_measure["status"] == "INCLUDED"
        assert condition_measure["cost_estimate_variant"] == "PRELIMINARY"
        assert_measure_costs(
            condition_measure,
            escalated_capital_usd=5000000.00,
            annualized_capital_usd=166666.67,
            annual_cost_usd=266666.67,
            annual_generation_loss_mwh=2880.0,
            annual_generation_value_usd=120960.00,
        )

    def test_the_condition_drives_the_ledger_into_a_restricted_posture(self):
        """The same request walks measure to ledger to infeasibility to posture.

        PRD §3.6: "Because those measures are `INCLUDED` on arrival, each insertion feeds the project burden ledger: `total_pme_annual_cost_usd`, `total_generation_loss_mwh`, `administrative_annual_charge_usd`, `total_annual_burden_usd` and `burden_ratio_pct` are all recomputed, the recomputed `burden_ratio_pct` sets `economically_infeasible`, and that flag recomputes `regulatory_posture` — moving the project from `OPEN` to `RESTRICTED` the moment the ratio reaches 15.00 with no infeasibility waiver in force."

        Design: Difficulty/transitive_cascade/wqc_condition_issuance_cascades_into_restricted_posture
        """
        ctx = self._certified_small_project()

        project = read_project(ctx["project"]["id"])

        assert_ledger_matches(
            project,
            total_pme_annual_cost_usd=266666.67,
            total_generation_loss_mwh=2880.0,
            administrative_annual_charge_usd=5333.33,
            total_annual_burden_usd=392960.00,
            burden_ratio_pct=18.71,
        )
        assert project["economically_infeasible"] is True
        assert_postures(project, regulatory_posture="RESTRICTED")
        assert project["wqc_status"] == "CERTIFIED_WITH_CONDITIONS"


class TestApplicationFilingErrorPrecedence:
    def _premature_and_infeasible_project(self):
        set_clock("2026-08-01T00:00:00Z")
        project = new_project(
            project_name="Priority Pair Falls",
            installed_capacity_mw=12.0,
            base_annual_generation_mwh=50000,
            license_expiration_date="2033-12-31",
        )
        file_pad(project["id"])
        new_measure(project["id"], source="AGENCY_PRESCRIPTION", **FULL_HEIGHT_LADDER)
        return read_project(project["id"])

    def test_the_stage_error_answers_before_the_burden_ratio_error(self):
        """Both violations are live and the stage rule sits higher on the ladder.

        PRD §2.12: "16. The project's `stage` permits the operation — `ERR_PROJECT_STAGE_INVALID` (409)."
        PRD §2.12: "42. Application filing is rejected when the project's `burden_ratio_pct` has reached the economic-feasibility ceiling and no infeasibility waiver is in force — `ERR_BURDEN_RATIO_EXCEEDED` (422)."

        Design: Difficulty/priority_pair_validation_conflict/application_filing_stage_error_precedes_burden_ratio_error
        """
        project = self._premature_and_infeasible_project()
        assert project["stage"] == "PAD_FILED"
        assert project["burden_ratio_pct"] == pytest.approx(18.71, abs=0.01)
        assert_postures(project, regulatory_posture="RESTRICTED")

        response = api_client.create_application(
            application_payload(
                project["id"], project["version"], filing_note="premature filing"
            ),
            LICENSEE_HEADERS,
        )

        validate_error(response, "ERR_PROJECT_STAGE_INVALID", 409)

    def test_the_refused_filing_creates_nothing_and_leaves_the_project_alone(self):
        """No application row appears and the project keeps its stage and version.

        PRD §3.8: "The project's `stage` must be `STUDY_PHASE`, or the filing is rejected with `ERR_PROJECT_STAGE_INVALID`."

        Design: Difficulty/priority_pair_validation_conflict/application_filing_stage_error_precedes_burden_ratio_error
        """
        project = self._premature_and_infeasible_project()

        api_client.create_application(
            application_payload(
                project["id"], project["version"], filing_note="premature filing"
            ),
            LICENSEE_HEADERS,
        )

        rows, _meta = validate_paginated(
            api_client.list_applications(
                REGULATOR_HEADERS, params={"project_id": project["id"]}
            )
        )
        assert rows == []
        after = read_project(project["id"])
        assert after["stage"] == "PAD_FILED"
        assert after["version"] == project["version"]


class TestFinalEnvironmentalAssessmentGate:
    def _application_at_draft_ea(self):
        return setup_application_under_review(
            ea_stage="DRAFT_EA",
            definitive=False,
            study_overrides=dict(
                resource_category="WATER_QUALITY", study_title="Temperature study"
            ),
            site_overrides=dict(river_mile=6.0),
            project_name="Draft EA Dam",
            installed_capacity_mw=22.0,
            base_annual_generation_mwh=250000,
            license_expiration_date="2033-12-31",
        )

    def test_a_preliminary_state_condition_blocks_the_final_assessment(self):
        """The advance depends on an entity the request never names.

        PRD §3.8: "A `target_stage` of `FINAL_EA` moves `ea_stage` `DRAFT_EA → FINAL_EA`, requires `filing_status` to be `UNDER_REVIEW`, and imposes one cross-entity condition: every measure of the project whose `source` is `WQC_CONDITION` must carry a `cost_estimate_variant` of `DEFINITIVE`."
        PRD §3.8: "A state condition still priced at a preliminary estimate blocks the final environmental document, and the attempt is rejected with `ERR_DEFINITIVE_ESTIMATE_REQUIRED`."

        Design: Difficulty/cross_entity_state_dependency/final_ea_advance_blocked_by_preliminary_wqc_condition_estimate
        """
        ctx = self._application_at_draft_ea()
        condition_measure = ctx["condition_measures"][0]
        assert condition_measure["cost_estimate_variant"] == "PRELIMINARY"
        assert ctx["application"]["ea_stage"] == "DRAFT_EA"

        response = api_client.advance_environmental_review(
            ctx["application"]["id"], {"target_stage": "FINAL_EA"}, REGULATOR_HEADERS
        )

        validate_error(response, "ERR_DEFINITIVE_ESTIMATE_REQUIRED", 409)
        unchanged = read_application(ctx["application"]["id"])
        assert unchanged["ea_stage"] == "DRAFT_EA"
        assert unchanged["filing_status"] == "UNDER_REVIEW"

    def test_repricing_the_condition_lets_the_identical_advance_succeed(self):
        """A licensee cost estimate unblocks the regulator's unchanged request.

        PRD §3.7: "The cost component falls while the generation component rises, and the two move independently."
        PRD §3.7: "`annual_generation_value_usd` is `annual_generation_loss_mwh` multiplied by an energy price of 42.00 dollars per megawatt-hour, rounded half up to two decimal places."

        Design: Difficulty/cross_entity_state_dependency/final_ea_advance_blocked_by_preliminary_wqc_condition_estimate
        """
        ctx = self._application_at_draft_ea()
        condition_measure = ctx["condition_measures"][0]
        validate_error(
            api_client.advance_environmental_review(
                ctx["application"]["id"], {"target_stage": "FINAL_EA"}, REGULATOR_HEADERS
            ),
            "ERR_DEFINITIVE_ESTIMATE_REQUIRED",
            409,
        )

        repriced = record_definitive_estimate(
            condition_measure["id"], user_id=U_LICENSEE_B
        )
        advanced = advance_environmental_review(ctx["application"]["id"], "FINAL_EA")

        assert repriced["cost_estimate_variant"] == "DEFINITIVE"
        assert advanced["ea_stage"] == "FINAL_EA"
        assert read_application(ctx["application"]["id"])["ea_stage"] == "FINAL_EA"
        assert_measure_costs(
            read_measure(condition_measure["id"]),
            annual_cost_usd=53000.00,
            annual_generation_loss_mwh=497.9,
        )
        project = read_project(ctx["project"]["id"])
        assert project["total_annual_burden_usd"] == pytest.approx(74971.80, abs=0.01)
        assert project["burden_ratio_pct"] == pytest.approx(0.71, abs=0.01)
