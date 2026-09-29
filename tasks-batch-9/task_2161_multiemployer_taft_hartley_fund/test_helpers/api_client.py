"""API client: one method per endpoint the PRD publishes."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------ funds
    def create_fund(self, payload, headers):
        return self._request("POST", "/funds", payload, headers)

    def get_fund(self, fund_id, headers):
        return self._request("GET", f"/funds/{fund_id}", headers=headers)

    def list_fund_trustees(self, fund_id, headers, params=None):
        return self._request(
            "GET", f"/funds/{fund_id}/trustees", headers=headers, params=params
        )

    def run_collections(self, fund_id, headers):
        return self._request("POST", f"/funds/{fund_id}/run-collections", {}, headers)

    # -------------------------------------------------------------- employers
    def create_employer(self, payload, headers):
        return self._request("POST", "/employers", payload, headers)

    def get_employer(self, employer_id, headers):
        return self._request("GET", f"/employers/{employer_id}", headers=headers)

    def list_employers(self, headers, params=None):
        return self._request("GET", "/employers", headers=headers, params=params)

    # ----------------------------------------------------------- participants
    def create_participant(self, payload, headers):
        return self._request("POST", "/participants", payload, headers)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/participants/{participant_id}", headers=headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", "/participants", headers=headers, params=params)

    def list_pension_accruals(self, participant_id, headers, params=None):
        return self._request(
            "GET",
            f"/participants/{participant_id}/pension-accruals",
            headers=headers,
            params=params,
        )

    def list_participant_contribution_lines(self, participant_id, headers, params=None):
        return self._request(
            "GET",
            f"/participants/{participant_id}/contribution-lines",
            headers=headers,
            params=params,
        )

    # --------------------------------------------------------------- trustees
    def create_trustee(self, payload, headers):
        return self._request("POST", "/trustees", payload, headers)

    # -------------------------------------------------------- coverage months
    def get_coverage_month(self, coverage_month_id, headers):
        return self._request(
            "GET", f"/coverage-months/{coverage_month_id}", headers=headers
        )

    def list_coverage_months(self, headers, params=None):
        return self._request("GET", "/coverage-months", headers=headers, params=params)

    # --------------------------------------------------- contribution reports
    def create_contribution_report(self, payload, headers):
        return self._request("POST", "/contribution-reports", payload, headers)

    def get_contribution_report(self, report_id, headers):
        return self._request(
            "GET", f"/contribution-reports/{report_id}", headers=headers
        )

    def list_contribution_reports(self, headers, params=None):
        return self._request(
            "GET", "/contribution-reports", headers=headers, params=params
        )

    def list_report_lines(self, report_id, headers, params=None):
        return self._request(
            "GET",
            f"/contribution-reports/{report_id}/lines",
            headers=headers,
            params=params,
        )

    def remit_contribution_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/contribution-reports/{report_id}/remit", payload, headers
        )

    def post_contribution_report(self, report_id, headers):
        return self._request(
            "POST", f"/contribution-reports/{report_id}/post", {}, headers
        )

    # ------------------------------------------------ delinquency assessments
    def list_report_delinquency_assessments(self, report_id, headers, params=None):
        return self._request(
            "GET",
            f"/contribution-reports/{report_id}/delinquency-assessments",
            headers=headers,
            params=params,
        )

    def create_delinquency_assessment(self, report_id, payload, headers):
        return self._request(
            "POST",
            f"/contribution-reports/{report_id}/delinquency-assessments",
            payload,
            headers,
        )

    def settle_delinquency_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"/delinquency-assessments/{assessment_id}/settle", payload, headers
        )

    # --------------------------------------------------------- payroll audits
    def create_payroll_audit(self, payload, headers):
        return self._request("POST", "/payroll-audits", payload, headers)

    def get_payroll_audit(self, audit_id, headers):
        return self._request("GET", f"/payroll-audits/{audit_id}", headers=headers)

    def list_payroll_audits(self, headers, params=None):
        return self._request("GET", "/payroll-audits", headers=headers, params=params)

    def issue_audit_findings(self, audit_id, payload, headers):
        return self._request(
            "POST", f"/payroll-audits/{audit_id}/findings", payload, headers
        )

    def respond_to_audit(self, audit_id, payload, headers):
        return self._request(
            "POST", f"/payroll-audits/{audit_id}/respond", payload, headers
        )

    def finalize_payroll_audit(self, audit_id, headers):
        return self._request(
            "POST", f"/payroll-audits/{audit_id}/finalize", {}, headers
        )

    # -------------------------------------------------- withdrawal assessment
    def create_withdrawal_assessment(self, payload, headers):
        return self._request("POST", "/withdrawal-assessments", payload, headers)

    def get_withdrawal_assessment(self, assessment_id, headers):
        return self._request(
            "GET", f"/withdrawal-assessments/{assessment_id}", headers=headers
        )

    def list_withdrawal_assessments(self, headers, params=None):
        return self._request(
            "GET", "/withdrawal-assessments", headers=headers, params=params
        )

    def list_installments(self, assessment_id, headers, params=None):
        return self._request(
            "GET",
            f"/withdrawal-assessments/{assessment_id}/installments",
            headers=headers,
            params=params,
        )

    def certify_withdrawal_assessment(self, assessment_id, headers):
        return self._request(
            "POST", f"/withdrawal-assessments/{assessment_id}/certify", {}, headers
        )

    def demand_withdrawal_assessment(self, assessment_id, headers):
        return self._request(
            "POST", f"/withdrawal-assessments/{assessment_id}/demand", {}, headers
        )

    def request_withdrawal_review(self, assessment_id, payload, headers):
        return self._request(
            "POST",
            f"/withdrawal-assessments/{assessment_id}/review-request",
            payload,
            headers,
        )

    def decide_withdrawal_review(self, assessment_id, payload, headers):
        return self._request(
            "POST",
            f"/withdrawal-assessments/{assessment_id}/review-decision",
            payload,
            headers,
        )

    def pay_installment(self, installment_id, payload, headers):
        return self._request(
            "POST", f"/payment-installments/{installment_id}/pay", payload, headers
        )

    # ---------------------------------------------------------- board motions
    def create_board_motion(self, payload, headers):
        return self._request("POST", "/board-motions", payload, headers)

    def get_board_motion(self, motion_id, headers):
        return self._request("GET", f"/board-motions/{motion_id}", headers=headers)

    def list_board_motions(self, headers, params=None):
        return self._request("GET", "/board-motions", headers=headers, params=params)

    def tally_board_motion(self, motion_id, payload, headers):
        return self._request(
            "POST", f"/board-motions/{motion_id}/tally", payload or {}, headers
        )

    def create_motion_vote(self, payload, headers):
        return self._request("POST", "/motion-votes", payload, headers)

    def get_motion_vote(self, vote_id, headers):
        return self._request("GET", f"/motion-votes/{vote_id}", headers=headers)

    def list_motion_votes(self, headers, params=None):
        return self._request("GET", "/motion-votes", headers=headers, params=params)

    # --------------------------------------------------- reciprocity transfers
    def create_reciprocity_transfer(self, payload, headers):
        return self._request("POST", "/reciprocity-transfers", payload, headers)

    def get_reciprocity_transfer(self, transfer_id, headers):
        return self._request(
            "GET", f"/reciprocity-transfers/{transfer_id}", headers=headers
        )

    def list_reciprocity_transfers(self, headers, params=None):
        return self._request(
            "GET", "/reciprocity-transfers", headers=headers, params=params
        )

    def decide_reciprocity_transfer(self, transfer_id, payload, headers):
        return self._request(
            "POST", f"/reciprocity-transfers/{transfer_id}/decision", payload, headers
        )

    # ------------------------------------------------------------ logical clock
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
