"""Boundary precision tests (Difficulty rule 6)."""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    make_hr_analyst_headers,
    setup_intake_channel,
    setup_employee,
    setup_investigator,
    setup_investigating_case,
    schedule_interview,
    complete_interview,
    log_evidence,
    admit_evidence,
    create_assessment,
    create_draft_finding,
    set_clock,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
)


class TestCredibilityBoundary:
    def test_score_exactly_050_allows_substantiation(self):
        """PRD §3.5: "One consistency gate then applies: when every credibility
        assessment on the case has its active score — the score named by its
        `active_variant` — below 0.50, the outcome may not be `SUBSTANTIATED`,
        and the attempt fails with `ERR_INSUFFICIENT_CREDIBILITY` (HTTP 422)."

        The gate is strictly-below-0.50; at exactly 0.50 the gate passes.

        Design: Difficulty/boundary_precision_check/credibility_exactly_050_allows_substantiation
        """
        channel = setup_intake_channel(
            channel_code="HOTLINE", display_name="Hotline G",
            default_category="HARASSMENT", default_severity="MEDIUM",
            sla_business_days=10,
        )
        reporter = setup_employee()
        subject = setup_employee()
        _, inv1 = setup_investigator()
        case = setup_investigating_case(
            channel["id"], subject["id"], inv1["id"],
            reporter_employee_id=reporter["id"],
            category="HARASSMENT", severity="MEDIUM",
        )
        iv = schedule_interview(case["id"], inv1["id"], subject["id"])
        complete_interview(iv["id"], inv1["id"])
        ev = log_evidence(case["id"], inv1["id"], reporter["id"])
        admit_evidence(ev["id"], inv1["id"], weight=0.5)
        # 0.50 + 0.10*3 - 0.15*2 = 0.50 exactly
        ca = create_assessment(case["id"], inv1["id"], subject["id"],
                                corroboration_count=3, contradiction_count=2,
                                account_age_days=0)
        assert ca["score_corroboration"] == pytest.approx(0.50, abs=1e-6), (
            f"score_corroboration expected exactly 0.50, got {ca['score_corroboration']}"
        )
        finding = create_draft_finding(case["id"], inv1["id"])
        resp = api_client.substantiate_finding(
            finding["id"], {"outcome": "SUBSTANTIATED"},
            make_inv_headers(inv1["id"]),
        )
        result = validate_success(resp, 200)
        assert result["substantiation_status"] == "SUBSTANTIATED", (
            "At exactly 0.50 the gate must pass; SUBSTANTIATED expected"
        )

    def test_score_just_below_050_rejects_substantiation(self):
        """PRD §3.5: "One consistency gate then applies: when every credibility
        assessment on the case has its active score — the score named by its
        `active_variant` — below 0.50, the outcome may not be `SUBSTANTIATED`."

        Design: Difficulty/boundary_precision_check/credibility_exactly_050_allows_substantiation
        """
        channel = setup_intake_channel(
            channel_code="HOTLINE", display_name="Hotline G",
            default_category="HARASSMENT", default_severity="MEDIUM",
            sla_business_days=10,
        )
        reporter = setup_employee()
        subject = setup_employee()
        _, inv1 = setup_investigator()
        case = setup_investigating_case(
            channel["id"], subject["id"], inv1["id"],
            reporter_employee_id=reporter["id"],
            category="HARASSMENT", severity="MEDIUM",
        )
        iv = schedule_interview(case["id"], inv1["id"], subject["id"])
        complete_interview(iv["id"], inv1["id"])
        ev = log_evidence(case["id"], inv1["id"], reporter["id"])
        admit_evidence(ev["id"], inv1["id"], weight=0.4)
        # 0.50 + 0.10*1 - 0.15*1 = 0.45 < 0.50
        ca = create_assessment(case["id"], inv1["id"], subject["id"],
                                corroboration_count=1, contradiction_count=1,
                                account_age_days=0)
        assert ca["score_corroboration"] == pytest.approx(0.45, abs=1e-6)
        finding = create_draft_finding(case["id"], inv1["id"])
        resp = api_client.substantiate_finding(
            finding["id"], {"outcome": "SUBSTANTIATED"},
            make_inv_headers(inv1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CREDIBILITY, 422)


def make_inv_headers(inv_id):
    from test_helpers import make_investigator_headers
    return make_investigator_headers(inv_id)


class TestTrendZeroHeadcount:
    def test_zero_headcount_zero_cases_yields_zero_rate(self):
        """PRD §3.7: "A zero headcount is an error only when there is something
        to explain: with no closed cases in the window the rate is simply 0.00,
        but with one or more closed cases the request fails with
        `ERR_TREND_HEADCOUNT_ZERO` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/trend_zero_headcount_zero_cases_yields_zero_rate
        """
        # SEA has a TERMINATED employee — zero ACTIVE headcount, zero closed cases
        setup_employee(location_code="SEA", employment_status="TERMINATED",
                       hire_date="2015-01-01T00:00:00Z")
        set_clock("2026-08-20T00:00:00Z")
        resp = api_client.create_trend_snapshot(
            {"scope_type": "LOCATION", "scope_key": "SEA", "window_kind": "ROLLING_90D"},
            make_hr_analyst_headers(),
        )
        ts = validate_success(resp, 201)
        assert ts["closed_case_count"] == 0
        assert ts["case_rate_per_100"] == pytest.approx(0.00, abs=1e-6), (
            f"Zero-headcount zero-case rate must be 0.00, got {ts['case_rate_per_100']}"
        )

    def test_zero_headcount_zero_cases_no_error_raised(self):
        """PRD §3.7: "with no closed cases in the window the rate is simply
        0.00, but with one or more closed cases the request fails with
        `ERR_TREND_HEADCOUNT_ZERO` (HTTP 422)."

        The success path asserts no ERR_TREND_HEADCOUNT_ZERO is raised.

        Design: Difficulty/boundary_precision_check/trend_zero_headcount_zero_cases_yields_zero_rate
        """
        setup_employee(location_code="SEA", employment_status="TERMINATED",
                       hire_date="2015-01-01T00:00:00Z")
        set_clock("2026-08-20T00:00:00Z")
        resp = api_client.create_trend_snapshot(
            {"scope_type": "LOCATION", "scope_key": "SEA", "window_kind": "ROLLING_90D"},
            make_hr_analyst_headers(),
        )
        # 201, not 422
        assert resp.status_code == 201, (
            f"Expected 201 (no error) when closed_case_count == 0, got {resp.status_code}: {resp.text}"
        )
        ts = validate_success(resp, 201)
        assert ts["case_rate_per_100"] == pytest.approx(0.00, abs=1e-6)
