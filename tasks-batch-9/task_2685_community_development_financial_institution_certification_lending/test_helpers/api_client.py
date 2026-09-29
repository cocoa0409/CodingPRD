"""API client for the CDFI certification and lending API.

One method per endpoint published by the PRD. All paths are mounted under
the ``/cdfi`` prefix.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/cdfi"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    def set_clock_raw(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", payload, headers
        )

    # ------------------------------------------------------------------
    # Institution
    # ------------------------------------------------------------------
    def create_institution(self, payload, headers):
        return self._request("POST", f"{PREFIX}/institutions", payload, headers)

    def get_institution(self, institution_id, headers):
        return self._request(
            "GET", f"{PREFIX}/institutions/{institution_id}", headers=headers
        )

    def list_institutions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/institutions", headers=headers, params=params
        )

    def run_servicing(self, institution_id, headers):
        return self._request(
            "POST", f"{PREFIX}/institutions/{institution_id}/servicing-runs",
            {}, headers,
        )

    # ------------------------------------------------------------------
    # TargetMarket
    # ------------------------------------------------------------------
    def create_target_market(self, institution_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/institutions/{institution_id}/target-markets",
            payload, headers,
        )

    def list_institution_target_markets(self, institution_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/institutions/{institution_id}/target-markets",
            headers=headers, params=params,
        )

    def approve_target_market(self, target_market_id, headers):
        return self._request(
            "POST", f"{PREFIX}/target-markets/{target_market_id}/approve", {}, headers
        )

    def get_target_market(self, target_market_id, headers):
        return self._request(
            "GET", f"{PREFIX}/target-markets/{target_market_id}", headers=headers
        )

    def list_target_markets(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/target-markets", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # BoardSeat
    # ------------------------------------------------------------------
    def create_board_seat(self, institution_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/institutions/{institution_id}/board-seats",
            payload, headers,
        )

    def get_board_seat(self, board_seat_id, headers):
        return self._request(
            "GET", f"{PREFIX}/board-seats/{board_seat_id}", headers=headers
        )

    def list_board_seats(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/board-seats", headers=headers, params=params
        )

    def resign_board_seat(self, board_seat_id, headers):
        return self._request(
            "POST", f"{PREFIX}/board-seats/{board_seat_id}/resign", {}, headers
        )

    # ------------------------------------------------------------------
    # CertificationApplication
    # ------------------------------------------------------------------
    def create_certification_application(self, institution_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/institutions/{institution_id}/certification-applications",
            payload, headers,
        )

    def get_certification_application(self, application_id, headers):
        return self._request(
            "GET", f"{PREFIX}/certification-applications/{application_id}",
            headers=headers,
        )

    def list_institution_certification_applications(
        self, institution_id, headers, params=None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/institutions/{institution_id}/certification-applications",
            headers=headers, params=params,
        )

    def list_certification_applications(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/certification-applications",
            headers=headers, params=params,
        )

    def submit_certification_application(self, application_id, headers):
        return self._request(
            "POST", f"{PREFIX}/certification-applications/{application_id}/submit",
            {}, headers,
        )

    def begin_certification_review(self, application_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/certification-applications/{application_id}/begin-review",
            {}, headers,
        )

    def evaluate_certification_test(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/certification-applications/{application_id}/evaluate-test",
            payload, headers,
        )

    def request_certification_info(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/certification-applications/{application_id}/request-info",
            payload, headers,
        )

    def resubmit_certification_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/certification-applications/{application_id}/resubmit",
            payload, headers,
        )

    def decide_certification_application(self, application_id, headers):
        return self._request(
            "POST", f"{PREFIX}/certification-applications/{application_id}/decide",
            {}, headers,
        )

    # ------------------------------------------------------------------
    # Borrower
    # ------------------------------------------------------------------
    def create_borrower(self, institution_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/institutions/{institution_id}/borrowers",
            payload, headers,
        )

    def list_institution_borrowers(self, institution_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/institutions/{institution_id}/borrowers",
            headers=headers, params=params,
        )

    def geocode_borrower(self, borrower_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/borrowers/{borrower_id}/geocode", payload, headers
        )

    def get_borrower(self, borrower_id, headers):
        return self._request(
            "GET", f"{PREFIX}/borrowers/{borrower_id}", headers=headers
        )

    def list_borrowers(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/borrowers", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # LoanProduct
    # ------------------------------------------------------------------
    def create_loan_product(self, institution_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/institutions/{institution_id}/loan-products",
            payload, headers,
        )

    def list_institution_loan_products(self, institution_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/institutions/{institution_id}/loan-products",
            headers=headers, params=params,
        )

    def get_loan_product(self, product_id, headers):
        return self._request(
            "GET", f"{PREFIX}/loan-products/{product_id}", headers=headers
        )

    def list_loan_products(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/loan-products", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Loan
    # ------------------------------------------------------------------
    def create_loan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/loans", payload, headers)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"{PREFIX}/loans/{loan_id}", headers=headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/loans", headers=headers, params=params)

    def underwrite_loan(self, loan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/loans/{loan_id}/underwrite", payload, headers
        )

    def decide_loan(self, loan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/loans/{loan_id}/decision", payload, headers
        )

    def disburse_loan(self, loan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/loans/{loan_id}/disbursements", payload, headers
        )

    def pay_loan(self, loan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/loans/{loan_id}/payments", payload, headers
        )

    def charge_off_loan(self, loan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/loans/{loan_id}/charge-off", payload, headers
        )

    # ------------------------------------------------------------------
    # TAEngagement
    # ------------------------------------------------------------------
    def create_ta_engagement(self, institution_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/institutions/{institution_id}/ta-engagements",
            payload, headers,
        )

    def get_ta_engagement(self, engagement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/ta-engagements/{engagement_id}", headers=headers
        )

    def list_ta_engagements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/ta-engagements", headers=headers, params=params
        )

    def close_ta_engagement(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/ta-engagements/{engagement_id}/close", payload, headers
        )

    # ------------------------------------------------------------------
    # ImpactReport
    # ------------------------------------------------------------------
    def create_impact_report(self, loan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/loans/{loan_id}/impact-reports", payload, headers
        )

    def get_impact_report(self, impact_report_id, headers):
        return self._request(
            "GET", f"{PREFIX}/impact-reports/{impact_report_id}", headers=headers
        )

    def list_impact_reports(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/impact-reports", headers=headers, params=params
        )

    def verify_impact_report(self, impact_report_id, headers):
        return self._request(
            "POST", f"{PREFIX}/impact-reports/{impact_report_id}/verify", {}, headers
        )

    def dispute_impact_report(self, impact_report_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/impact-reports/{impact_report_id}/dispute",
            payload, headers,
        )

    def resubmit_impact_report(self, impact_report_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/impact-reports/{impact_report_id}/resubmit",
            payload, headers,
        )

    # ------------------------------------------------------------------
    # ComplianceMeasurement
    # ------------------------------------------------------------------
    def create_compliance_measurement(self, institution_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/institutions/{institution_id}/compliance-measurements",
            payload, headers,
        )

    def list_institution_compliance_measurements(
        self, institution_id, headers, params=None
    ):
        return self._request(
            "GET", f"{PREFIX}/institutions/{institution_id}/compliance-measurements",
            headers=headers, params=params,
        )

    def get_compliance_measurement(self, measurement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/compliance-measurements/{measurement_id}",
            headers=headers,
        )

    def list_compliance_measurements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/compliance-measurements", headers=headers, params=params
        )

    def finalize_compliance_measurement(self, measurement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/compliance-measurements/{measurement_id}/finalize",
            {}, headers,
        )

    def void_compliance_measurement(self, measurement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/compliance-measurements/{measurement_id}/void",
            payload, headers,
        )

    # ------------------------------------------------------------------
    # AwardApplication
    # ------------------------------------------------------------------
    def create_award_application(self, institution_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/institutions/{institution_id}/award-applications",
            payload, headers,
        )

    def get_award_application(self, award_id, headers):
        return self._request(
            "GET", f"{PREFIX}/award-applications/{award_id}", headers=headers
        )

    def list_institution_award_applications(self, institution_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/institutions/{institution_id}/award-applications",
            headers=headers, params=params,
        )

    def list_award_applications(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/award-applications", headers=headers, params=params
        )

    def submit_award_application(self, award_id, headers):
        return self._request(
            "POST", f"{PREFIX}/award-applications/{award_id}/submit", {}, headers
        )

    def decide_award_application(self, award_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/award-applications/{award_id}/decide", payload, headers
        )

    def activate_award_disbursing(self, award_id, headers):
        return self._request(
            "POST", f"{PREFIX}/award-applications/{award_id}/activate-disbursing",
            {}, headers,
        )

    def resume_award_draws(self, award_id, headers):
        return self._request(
            "POST", f"{PREFIX}/award-applications/{award_id}/resume-draws", {}, headers
        )

    # ------------------------------------------------------------------
    # MatchingFundCommitment
    # ------------------------------------------------------------------
    def create_matching_fund_commitment(self, award_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/award-applications/{award_id}/matching-fund-commitments",
            payload, headers,
        )

    def list_award_matching_fund_commitments(self, award_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/award-applications/{award_id}/matching-fund-commitments",
            headers=headers, params=params,
        )

    def get_matching_fund_commitment(self, commitment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/matching-fund-commitments/{commitment_id}",
            headers=headers,
        )

    def list_matching_fund_commitments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/matching-fund-commitments",
            headers=headers, params=params,
        )

    def verify_matching_fund_commitment(self, commitment_id, headers):
        return self._request(
            "POST", f"{PREFIX}/matching-fund-commitments/{commitment_id}/verify",
            {}, headers,
        )

    def withdraw_matching_fund_commitment(self, commitment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/matching-fund-commitments/{commitment_id}/withdraw",
            payload, headers,
        )


api_client = ApiClient()
