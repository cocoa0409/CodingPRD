"""Measure escalation, ledger membership, the statutory waiver clock and due-date topology."""
import pytest

from test_helpers import (
    TEST_USERS,
    U_LICENSEE_A,
    api_client,
    assert_ledger_matches,
    assert_measure_costs,
    assert_postures,
    certify_obligation,
    file_pad,
    issue_order,
    list_obligations,
    make_licensee_headers,
    new_measure,
    new_project,
    new_settlement,
    read_measure,
    read_project,
    request_certification,
    run_sweep,
    schedule_obligation,
    set_clock,
    setup_application_under_review,
    setup_study_phase_project,
    validate_error,
    validate_success,
)

REGULATOR_HEADERS = TEST_USERS["regulator_headers"]
LICENSEE_HEADERS = make_licensee_headers(U_LICENSEE_A)
LADDER_INPUTS = dict(
    resource_category="FISH_PASSAGE",
    capital_cost_usd=1200000.00,
    annual_om_cost_usd=45000.00,
    implementation_months=6,
    flow_release_cfs=120,
    gross_head_ft=85,
    release_days=180,
)
FLOW_RELEASE_INPUTS = dict(
    resource_category="WATER_QUALITY",
    capital_cost_usd=600000.00,
    annual_om_cost_usd=20000.00,
    construction_start_year=2026,
    flow_release_cfs=40,
    gross_head_ft=60,
    release_days=120,
)


class TestLedgerMembership:
    def test_a_proposed_settlement_measure_is_priced_but_never_counted(self):
        """The bargaining chip carries its own six figures and moves no ledger field.

        PRD §3.7: "A measure whose `source` is `SETTLEMENT` begins in `PROPOSED` — it is a bargaining chip, not yet a commitment, and it contributes nothing to the ledger."
        PRD §3.7: "The live set is every measure of the project whose status is `INCLUDED` or `IMPLEMENTED`; measures in `PROPOSED`, `WITHDRAWN` or `SUPERSEDED` are excluded."

        Design: Corner/calculations/ledger_excludes_proposed_measures_from_every_ledger_field
        """
        ctx = setup_study_phase_project(
            project_name="Ledger Filter Dam",
            installed_capacity_mw=24.0,
            base_annual_generation_mwh=250000,
            license_expiration_date="2035-06-30",
        )
        project_id = ctx["project"]["id"]
        settlement = new_settlement(project_id, title="Draft settlement")

        proposed = new_measure(
            project_id,
            source="SETTLEMENT",
            settlement_id=settlement["id"],
            measure_name="Volitional fishway",
            resource_category="FISH_PASSAGE",
            capital_cost_usd=3000000.00,
            annual_om_cost_usd=200000.00,
            construction_start_year=2026,
            implementation_months=30,
            flow_release_cfs=200,
            gross_head_ft=80,
            release_days=300,
        )

        assert proposed["status"] == "PROPOSED"
        assert_measure_costs(
            proposed,
            annual_cost_usd=325000.00,
            annual_generation_loss_mwh=2880.0,
            annual_burden_usd=445960.00,
        )
        assert_ledger_matches(
            read_project(project_id),
            total_pme_annual_cost_usd=0.00,
            total_generation_loss_mwh=0.0,
            administrative_annual_charge_usd=0.00,
            total_annual_burden_usd=0.00,
            burden_ratio_pct=0.00,
        )

        included = new_measure(
            project_id,
            source="AGENCY_PRESCRIPTION",
            measure_name="Minimum flow release",
            implementation_months=6,
            **FLOW_RELEASE_INPUTS,
        )

        assert included["status"] == "INCLUDED"
        assert included["annual_cost_usd"] == pytest.approx(57500.00, abs=0.01)
        project = read_project(project_id)
        assert_ledger_matches(
            project,
            total_pme_annual_cost_usd=57500.00,
            total_generation_loss_mwh=230.4,
            administrative_annual_charge_usd=1150.00,
            total_annual_burden_usd=68326.80,
            burden_ratio_pct=0.65,
        )
        assert project["economically_infeasible"] is False
        assert read_measure(proposed["id"])["status"] == "PROPOSED"


class TestCapitalEscalation:
    def test_a_construction_year_at_or_before_the_pad_year_is_never_de_escalated(self):
        """Three identical ladders differ only in construction year, and two of them tie.

        PRD §3.7: "The number of escalation years is `construction_start_year` minus the project's `pad_year`, floored at zero so that a measure built before or during the pre-application year is never de-escalated."
        PRD §3.7: "`escalated_capital_usd` is `capital_cost_usd`, multiplied by one plus the contingency allowance, multiplied by 1.03 raised to the power of the escalation years — a 3 percent annual escalation compounded over the interval — and the product is rounded half up to two decimal places."

        Design: Corner/calculations/escalation_years_clamp_to_zero_below_the_pad_year
        """
        set_clock("2026-08-01T00:00:00Z")
        project = new_project(
            project_name="Escalation Reach",
            installed_capacity_mw=24.0,
            base_annual_generation_mwh=250000,
            license_expiration_date="2035-06-30",
        )
        filed = file_pad(project["id"])
        assert filed["pad_year"] == 2026

        same_year = new_measure(
            project["id"],
            source="AGENCY_PRESCRIPTION",
            measure_name="Ladder same year",
            construction_start_year=2026,
            **LADDER_INPUTS,
        )
        earlier_year = new_measure(
            project["id"],
            source="AGENCY_PRESCRIPTION",
            measure_name="Ladder earlier year",
            construction_start_year=2024,
            **LADDER_INPUTS,
        )
        three_years_out = new_measure(
            project["id"],
            source="AGENCY_PRESCRIPTION",
            measure_name="Ladder three years out",
            construction_start_year=2029,
            **LADDER_INPUTS,
        )

        assert same_year["cost_estimate_variant"] == "PRELIMINARY"
        assert_measure_costs(
            same_year,
            escalated_capital_usd=1500000.00,
            annualized_capital_usd=50000.00,
            annual_cost_usd=95000.00,
            annual_generation_loss_mwh=1036.8,
        )
        assert_measure_costs(
            earlier_year,
            escalated_capital_usd=1500000.00,
            annualized_capital_usd=50000.00,
            annual_cost_usd=95000.00,
        )
        assert_measure_costs(
            three_years_out,
            escalated_capital_usd=1639090.50,
            annualized_capital_usd=54636.35,
            annual_cost_usd=99636.35,
            annual_generation_loss_mwh=1036.8,
        )
        assert_ledger_matches(
            read_project(project["id"]),
            total_pme_annual_cost_usd=289636.35,
            total_generation_loss_mwh=3110.4,
            administrative_annual_charge_usd=5792.73,
            total_annual_burden_usd=426065.88,
            burden_ratio_pct=4.06,
        )


class TestStatutoryWaiverClock:
    def test_the_waiver_lands_twelve_months_out_and_the_sweep_honours_the_boundary(self):
        """A sweep the day before leaves the request alone; the sweep on the date waives it.

        PRD §3.6: "It stamps `requested_at` from the logical clock and derives `statutory_waiver_date` as the date of `requested_at` plus 12 calendar months, with day-of-month clamping."
        PRD §3.6: "When the compliance sweep of §3.9 runs at a logical-clock date on or after a `REQUESTED` certification's `statutory_waiver_date`, the certification moves `REQUESTED → WAIVED` by operation of the statutory clock rather than by anyone's decision: `decided_at` is stamped from the logical clock, the project's `wqc_status` becomes `WAIVED`, `regulatory_posture` is recomputed and the project's `version` is incremented."

        Design: Corner/calculations/wqc_statutory_waiver_date_constant_and_sweep_boundary
        """
        ctx = setup_study_phase_project(
            project_name="Waiver Clock Reach",
            installed_capacity_mw=9.0,
            base_annual_generation_mwh=50000,
            license_expiration_date="2035-06-30",
        )
        project_id = ctx["project"]["id"]
        wqc = request_certification(project_id)
        assert wqc["status"] == "REQUESTED"
        assert wqc["requested_at"].startswith("2026-08-01T00:00:00")
        assert wqc["statutory_waiver_date"] == "2027-08-01"

        set_clock("2027-07-31T00:00:00Z")
        day_before = run_sweep(project_id)
        untouched = validate_success(
            api_client.get_water_quality_certification(wqc["id"], REGULATOR_HEADERS)
        )

        assert day_before["wqc_status"] == "REQUESTED"
        assert day_before["last_sweep_at"].startswith("2027-07-31T00:00:00")
        assert untouched["status"] == "REQUESTED"
        assert untouched["decided_at"] is None

        set_clock("2027-08-01T00:00:00Z")
        on_the_date = run_sweep(project_id)
        waived = validate_success(
            api_client.get_water_quality_certification(wqc["id"], REGULATOR_HEADERS)
        )

        assert waived["status"] == "WAIVED"
        assert waived["decided_at"].startswith("2027-08-01T00:00:00")
        assert on_the_date["wqc_status"] == "WAIVED"
        assert_postures(
            on_the_date, timeline_posture="ON_TRACK", regulatory_posture="OPEN"
        )


class TestPrerequisiteChainScheduling:
    def test_a_prerequisite_pushes_the_dependent_due_date_and_gates_its_scheduling(self):
        """Nine months of its own work loses to six months of lag behind the root.

        PRD §3.9: "A measure that names a prerequisite has a `due_date` equal to the later of two candidates: the order's `effective_date` plus its own `implementation_months`, and the prerequisite's already-computed `due_date` plus a 6-month prerequisite lag."
        PRD §3.9: "For a `PME_IMPLEMENTATION` obligation whose measure names a `prerequisite_measure_id`, that prerequisite measure's status must be `IMPLEMENTED`, and anything else is rejected with `ERR_PREREQUISITE_NOT_IMPLEMENTED`."

        Design: Corner/calculations/obligation_prerequisite_chain_pushes_due_dates_topologically
        """
        ctx = setup_application_under_review(
            ea_stage="FINAL_EA",
            site_overrides=dict(site_code="S1", river_mile=1.0),
            project_name="Topo Chain Dam",
            installed_capacity_mw=24.0,
            base_annual_generation_mwh=250000,
            license_expiration_date="2035-06-30",
        )
        project_id = ctx["project"]["id"]
        root = ctx["condition_measures"][0]
        assert root["annual_cost_usd"] == pytest.approx(53000.00, abs=0.01)
        dependent = new_measure(
            project_id,
            source="AGENCY_PRESCRIPTION",
            prerequisite_measure_id=root["id"],
            measure_name="Downstream bypass",
            implementation_months=9,
            **FLOW_RELEASE_INPUTS,
        )
        assert dependent["annual_cost_usd"] == pytest.approx(57500.00, abs=0.01)
        before_filing = read_project(project_id)
        assert before_filing["total_pme_annual_cost_usd"] == pytest.approx(
            110500.00, abs=0.01
        )
        assert before_filing["burden_ratio_pct"] == pytest.approx(1.36, abs=0.01)

        order = issue_order(ctx["application"]["id"], "ORD-9029")

        assert order["effective_date"] == "2026-08-01"
        assert order["article_count"] == 2
        obligations = {o["pme_measure_id"]: o for o in list_obligations(order["id"])}
        root_obligation = obligations[root["id"]]
        dependent_obligation = obligations[dependent["id"]]
        assert root_obligation["due_date"] == "2027-02-01"
        assert root_obligation["status"] == "PENDING"
        assert dependent_obligation["due_date"] == "2027-08-01"

        too_soon = api_client.schedule_obligation(
            dependent_obligation["id"],
            {"activity_window_start": "2027-06-01", "activity_window_end": "2027-06-30"},
            LICENSEE_HEADERS,
        )

        validate_error(too_soon, "ERR_PREREQUISITE_NOT_IMPLEMENTED", 409)

        schedule_obligation(root_obligation["id"], "2027-01-01", "2027-01-31")
        set_clock("2027-01-01T00:00:00Z")
        certified = certify_obligation(root_obligation["id"])
        scheduled = schedule_obligation(
            dependent_obligation["id"], "2027-06-01", "2027-06-30"
        )

        assert certified["status"] == "CERTIFIED"
        assert read_measure(root["id"])["status"] == "IMPLEMENTED"
        assert scheduled["status"] == "SCHEDULED"
        assert_ledger_matches(
            read_project(project_id),
            total_pme_annual_cost_usd=110500.00,
            total_generation_loss_mwh=728.3,
            administrative_annual_charge_usd=2210.00,
            total_annual_burden_usd=143298.60,
            burden_ratio_pct=1.36,
        )
