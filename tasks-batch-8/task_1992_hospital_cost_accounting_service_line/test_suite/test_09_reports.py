"""Decision-support reports: physician margin, DRG margin, payer mix,
service-line profitability (PRD §3.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_implant,
    add_supply_line,
    create_case,
    create_payer_contract,
    create_physician,
    post_case,
    setup_case_with_lines,
    setup_card_rvu,
    setup_ortho_tdabc,
    setup_posted_card_case,
    validate_error,
    validate_success,
)

FC = TEST_USERS["finance_controller_headers"]
CA = TEST_USERS["cost_analyst_headers"]
SLM = TEST_USERS["service_line_manager_headers"]


class TestPhysicianMarginReport:
    def test_physician_margin_empty_set_zero_case(self, api):
        """PRD §3.7: "`margin_per_case` is the `margin` divided by `case_count`,
        rounded half-up to two decimal places; when no cases qualify,
        `margin_per_case` is 0 and the returned `cases` list is empty."

        Design: Difficulty/boundary_precision_check/physician_margin_empty_set_zero_case
        """
        phys = create_physician(npi="1000000009", full_name="Dr. Nine", specialty="ENT")
        report = validate_success(
            api.get_physician_margin_report(
                FC, params={"physician_id": phys["id"], "period": "2026-08"}
            )
        )
        assert report["case_count"] == 0
        assert report["margin"] == pytest.approx(0, abs=0.005)
        assert report["margin_per_case"] == pytest.approx(0, abs=0.005)
        assert report["cases"] == []

    def test_physician_margin_empty_set_total_revenue_zero(self, api):
        """PRD §3.7: "It returns `case_count`, `total_revenue` as the sum of
        `expected_reimbursement` across the qualifying cases, `total_cost` as the
        sum of their `total_cost`, and `margin` as revenue minus cost."

        Design: Difficulty/boundary_precision_check/physician_margin_empty_set_zero_case
        """
        phys = create_physician(npi="1000000009", full_name="Dr. Nine", specialty="ENT")
        report = validate_success(
            api.get_physician_margin_report(
                FC, params={"physician_id": phys["id"], "period": "2026-08"}
            )
        )
        assert report["total_revenue"] == pytest.approx(0, abs=0.005)
        assert report["total_cost"] == pytest.approx(0, abs=0.005)
        assert report["case_count"] == 0

    def test_physician_margin_report_excludes_voided_and_draft(self, api):
        """PRD §3.7: "Every report draws exclusively on `POSTED` and `LOCKED`
        cases — `DRAFT` cases are unpriced and `VOIDED` cases are compensated
        away, so neither ever appears."

        Design: Corner/entities/physician_margin_report_excludes_voided_and_draft
        """
        scenario = setup_ortho_tdabc(rate_factor=1.00)
        ph = scenario["physician"]

        # Case A: POSTED, 100 min -> activity 150.00 + pool 7000.00, rev 30000.
        case_a = setup_case_with_lines(scenario, [100], expected_reimbursement=30000.00)
        posted_a = post_case(case_a["id"], scenario["model_version"])

        # Case B: posted then voided.
        case_b = setup_case_with_lines(scenario, [50], expected_reimbursement=10000.00)
        post_case(case_b["id"], scenario["model_version"])
        validate_success(api.void_case(case_b["id"], CA))

        # Case C: left DRAFT.
        setup_case_with_lines(scenario, [25], expected_reimbursement=5000.00)

        report = validate_success(
            api.get_physician_margin_report(
                FC, params={"physician_id": ph["id"], "period": "2026-08"}
            )
        )
        assert report["case_count"] == 1
        assert report["total_revenue"] == pytest.approx(30000.00, abs=0.005)
        # total_cost = base 9000 + activity 150.00 + pool 7000.00 = 16150.00
        assert report["total_cost"] == pytest.approx(16150.00, abs=0.005)
        assert report["margin"] == pytest.approx(30000.00 - 16150.00, abs=0.005)
        assert len(report["cases"]) == 1
        assert report["cases"][0]["id"] == posted_a["id"]


class TestDrgMarginReport:
    def test_drg_margin_compliance_over_at_target(self, api):
        """PRD §3.7: "It returns `case_count`, `avg_indirect` — the average of
        `total_indirect_allocated` across the qualifying cases, rounded half-up
        to two decimal places — the DRG's `target_cost`, and `target_variance` as
        `avg_indirect` minus `target_cost`. The `compliance` flag reads `OVER`
        when the variance is positive, `ON_TARGET` when it is exactly zero, and
        `UNDER` when it is negative."

        Design: Corner/calculations/drg_margin_compliance_over_at_target
        """
        scenario = setup_ortho_tdabc(rate_factor=1.20)
        # 4 lines at 100/120/130/80 min under rate 1.50 * factor 1.20 = 1.80/min:
        # 180.00 + 216.00 + 234.00 + 144.00 = 774.00 activity; +7000 pool ->
        # total_indirect_allocated 7774.00. avg_indirect = 7774.00.
        case = setup_case_with_lines(scenario, [100, 120, 130, 80])
        post_case(case["id"], scenario["model_version"])

        report = validate_success(
            api.get_drg_margin_report(
                FC, params={"drg_id": scenario["drg"]["id"], "period": "2026-08"}
            )
        )
        assert report["case_count"] == 1
        assert report["avg_indirect"] == pytest.approx(7774.00, abs=0.005)
        assert report["target_cost"] == pytest.approx(750.00, abs=0.005)
        assert report["target_variance"] == pytest.approx(7774.00 - 750.00, abs=0.005)
        assert report["compliance"] == "OVER"


class TestPayerMixReport:
    def test_payer_mix_cost_share_remainder_to_largest_payer(self, api):
        """PRD §3.7: "For each `payer_type`, the report computes `revenue_pt` as
        the sum of `contracted_rate` over its cases, then a cost share
        `cost_share_pt` — the total `total_cost` of all matched cases, multiplied
        by that payer type's `revenue_pt`, divided by the total revenue of all
        matched cases, rounded half-up to two decimal places — and
        `contribution_pt` as `revenue_pt` minus `cost_share_pt`. Any residual
        rounding difference between the matched cases' total cost and the sum of
        the per-type shares is assigned to the payer type with the largest
        `revenue_pt`, with ties resolved in the fixed payer-type order
        `MEDICARE`, `MEDICAID`, `COMMERCIAL`, `SELF_PAY`."

        Design: Corner/calculations/payer_mix_cost_share_remainder_to_largest_payer
        """
        scenario = setup_card_rvu(period="2026-08")
        sl = scenario["service_line"]
        create_payer_contract(
            service_line_id=sl["id"], payer_name="Medicare", payer_type="MEDICARE",
            contracted_rate=30000.00, effective_period="2026-01")

        case = create_case(
            service_line_id=sl["id"], physician_id=scenario["physician"]["id"],
            drg_id=scenario["drg"]["id"], cost_model_id=scenario["model"]["id"],
            period="2026-08", expected_reimbursement=30000.00)
        from test_helpers import add_activity_line
        add_activity_line(case["id"], scenario["cc_lab"]["id"], 4)
        add_activity_line(case["id"], scenario["cc_rad"]["id"], 6)
        add_implant(case["id"], item_code="STENT-1", vendor="V1",
                    unit_cost=12000.00, quantity=1)
        add_supply_line(case["id"], supply_code="S1", unit_cost=500.00, quantity=1)
        add_supply_line(case["id"], supply_code="S2", unit_cost=300.00, quantity=1)
        posted = post_case(case["id"], scenario["model_version"])

        # direct = 10000 base + 12000 implant + 500 + 300 = 22800.00;
        # indirect = 28000 activity + 7000 pool = 35000.00; total 57800.00.
        assert posted["total_cost"] == pytest.approx(57800.00, abs=0.005)

        report = validate_success(
            api.get_payer_mix_report(FC, params={"service_line_id": sl["id"],
                                                 "period": "2026-08"})
        )
        assert report["matched_case_count"] == 1
        assert report["unmatched_count"] == 0
        medicare = [p for p in report["payers"] if p["payer_type"] == "MEDICARE"]
        assert len(medicare) == 1
        # Single matched payer takes the whole cost share.
        assert medicare[0]["revenue_pt"] == pytest.approx(30000.00, abs=0.005)
        assert medicare[0]["cost_share_pt"] == pytest.approx(57800.00, abs=0.005)
        assert medicare[0]["contribution_pt"] == pytest.approx(-27800.00, abs=0.005)


class TestReportQueryParams:
    def test_reports_require_query_params(self, api):
        """PRD §3.7: "The **physician margin report**, requested with a
        `physician_id` and a `period`, surveys one surgeon's book."
        PRD §2.10: "10. **Numeric sanity and enum validity** — missing required
        fields, type mismatches, invalid enum values, and non-positive numbers
        where a positive value is required all surface as `ERR_INVALID_REQUEST`."

        Design: Corner/endpoints/reports_require_query_params
        """
        resp = api.get_physician_margin_report(FC)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestServiceLineProfitability:
    def test_service_line_profitability_report(self, api):
        """PRD §3.7: "It returns the period's `case_count` — the line's `POSTED`
        and `LOCKED` cases in that period — together with `total_revenue` as the
        sum of those cases' `expected_reimbursement`, `total_direct_cost` as the
        sum of their `total_direct_cost`, and `contribution_margin` as
        `total_revenue` minus `total_direct_cost`."

        Design: Corner/endpoints/service_line_profitability_report
        """
        scenario = setup_ortho_tdabc(rate_factor=1.20)
        # Case direct cost = base 9000 (no implants/supplies).
        case = setup_case_with_lines(scenario, [100, 120, 130, 80])
        post_case(case["id"], scenario["model_version"])

        report = validate_success(
            api.get_service_line_profitability_report(
                SLM, params={"service_line_id": scenario["service_line"]["id"],
                             "period": "2026-08"}
            )
        )
        assert report["case_count"] == 1
        assert report["total_revenue"] == pytest.approx(30000.00, abs=0.005)
        assert report["total_direct_cost"] == pytest.approx(9000.00, abs=0.005)
        assert report["contribution_margin"] == pytest.approx(21000.00, abs=0.005)
