"""Difficulty Rule 1 — dual_variant_calc.

Tests where the same input pool yields two demonstrably different numbers under
two valid algorithms baked into the PRD: visa availability (FINAL_ACTION vs
FILING_DATE) and officer workload (weighted_complexity vs flat_count).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    set_clock,
    publish_visa_bulletin,
    register_applicant,
    create_draft_case,
    file_case,
    setup_officer_two_case_pool,
    make_applicant_headers,
    TEST_USERS,
)


class TestVisaFinalActionVsFilingDateDivergence:
    """The visa-availability advisory returns BOTH chart variants for the same
    case in one response, demonstrating two valid algorithms diverging on
    identical (priority_date, category, country, evaluation_month) inputs.
    """

    def test_final_action_retrogressed_filing_date_current_on_same_case(self, api):
        """PRD §3.4: "for the same (priority_date, preference_category, country, evaluation_month) tuple
        the two variants can disagree (for example, FILING_DATE may be CURRENT
        while FINAL_ACTION is RETROGRESSED) when the bulletin's filing-date cutoff
        falls later than its final-action cutoff."
        PRD §3.4: "the result is CURRENT precisely when the case's priority_date is strictly
        less than the entry's cutoff_date, and RETROGRESSED otherwise."

        Design: Difficulty/dual_variant_calc/visa_final_action_vs_filing_date_divergence_on_case_visabulletin
        """
        # File the case at 2026-01-15 so priority_date = 2026-01-15.
        set_clock("2026-01-15T00:00:00Z")
        applicant = register_applicant(country_of_chargeability="INDIA",
                                       date_of_birth="1990-01-15")
        case = create_draft_case(applicant, case_type="I-130",
                                 preference_category="F2A")
        filed = file_case(case, applicant)
        assert filed["priority_date"] == "2026-01-15"

        # Advance the clock to 2026-06; publish two bulletin rows for that month.
        set_clock("2026-06-15T00:00:00Z")
        publish_visa_bulletin("2026-06", "F2A", "INDIA",
                              "FINAL_ACTION", "2024-08-15")
        publish_visa_bulletin("2026-06", "F2A", "INDIA",
                              "FILING_DATE", "CURRENT")

        # Read the case's visa availability through the advisory endpoint.
        headers = make_applicant_headers(applicant["id"])
        res = api.get_visa_availability(filed["id"], headers)
        body = validate_success(res, 200)
        assert body["final_action"] == "RETROGRESSED"
        assert body["filing_date"] == "CURRENT"
        assert body["evaluation_month"] == "2026-06"

    def test_visa_advisory_response_carries_both_charts_and_evaluation_month(self, api):
        """PRD §3.4: "The advisory read on a case returns both, in a single response
        carrying `final_action`, `filing_date`, and the `evaluation_month` used for the lookup."

        Design: Difficulty/dual_variant_calc/visa_final_action_vs_filing_date_divergence_on_case_visabulletin
        """
        set_clock("2026-01-15T00:00:00Z")
        applicant = register_applicant(country_of_chargeability="INDIA",
                                       date_of_birth="1990-01-15")
        case = create_draft_case(applicant, case_type="I-130",
                                 preference_category="F2A")
        filed = file_case(case, applicant)
        set_clock("2026-06-15T00:00:00Z")
        publish_visa_bulletin("2026-06", "F2A", "INDIA",
                              "FINAL_ACTION", "2024-08-15")
        publish_visa_bulletin("2026-06", "F2A", "INDIA",
                              "FILING_DATE", "CURRENT")

        headers = make_applicant_headers(applicant["id"])
        body = validate_success(api.get_visa_availability(filed["id"], headers), 200)
        # Every key the PRD names in the response is present.
        assert "final_action" in body
        assert "filing_date" in body
        assert "evaluation_month" in body
        # Each is one of the documented enum values per §3.4 (the algorithm
        # returns CURRENT or RETROGRESSED).
        assert body["final_action"] in {"CURRENT", "RETROGRESSED"}
        assert body["filing_date"] in {"CURRENT", "RETROGRESSED"}


class TestOfficerWorkloadWeightedVsFlatCountDivergence:
    """The workload endpoint returns BOTH variants on the same pool. With a pool
    of 1 BIOMETRICS_SCHEDULED + 1 UNDER_REVIEW case aged 14 days, the weighted
    score is 6.23 while the flat count is 2.
    """

    def test_two_variants_diverge_on_identical_pool(self, api):
        """PRD §3.8: "The system computes two values from one shared pool of cases."
        PRD §3.8: "For an officer with even a single case in a status whose weight is not 1
        or whose age is greater than zero, the two variants will differ by construction."

        Design: Difficulty/dual_variant_calc/officer_workload_weighted_vs_flat_count_divergence_on_officer_pool
        """
        officer_id, _officer_headers, _case_a, _case_b = setup_officer_two_case_pool(
            initial_clock="2026-06-01T00:00:00Z",
            final_clock="2026-06-15T00:00:00Z",
            biom_at="2026-07-01T15:00:00Z",
            asc_location_code="ASC-SF-01",
        )
        res = api.get_officer_workload(officer_id,
                                       TEST_USERS["field_office_admin_headers"])
        body = validate_success(res, 200)
        assert body["officer_id"] == officer_id
        assert body["case_count"] == 2
        # weighted_complexity diverges from the flat count of 2.
        assert body["workload_score"] != 2

    def test_workload_pool_excludes_terminal_cases_but_count_matches(self, api):
        """PRD §3.8: "every Case whose assigned_officer_id equals the requested officer identifier
        and whose status is not one of the terminal states APPROVED, DENIED, or ABANDONED."

        Design: Difficulty/dual_variant_calc/officer_workload_weighted_vs_flat_count_divergence_on_officer_pool
        """
        officer_id, _officer_headers, _case_a, _case_b = setup_officer_two_case_pool(
            initial_clock="2026-06-01T00:00:00Z",
            final_clock="2026-06-15T00:00:00Z",
        )
        res = api.get_officer_workload(officer_id,
                                       TEST_USERS["field_office_admin_headers"])
        body = validate_success(res, 200)
        # Two non-terminal cases assigned → flat count of exactly 2.
        assert body["case_count"] == 2
        # Weighted score is a positive number greater than the flat count (since
        # at least one case has weight != 1 and age > 0).
        assert body["workload_score"] > body["case_count"]
