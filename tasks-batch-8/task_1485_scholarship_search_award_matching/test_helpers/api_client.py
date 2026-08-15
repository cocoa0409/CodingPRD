"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock and daily operations run
    # ------------------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    def run_daily(self, headers):
        return self._request("POST", "/api/_ops/run_daily", {}, headers)

    # ------------------------------------------------------------------
    # Students
    # ------------------------------------------------------------------
    def create_student(self, payload, headers):
        return self._request("POST", "/api/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/api/students/{student_id}", headers=headers)

    def patch_student(self, student_id, payload, headers):
        return self._request("PATCH", f"/api/students/{student_id}", payload, headers)

    def archive_student(self, student_id, headers):
        return self._request(
            "POST", f"/api/students/{student_id}/archive", {}, headers
        )

    def get_aid_summary(self, student_id, headers):
        return self._request(
            "GET", f"/api/students/{student_id}/aid-summary", headers=headers
        )

    # ------------------------------------------------------------------
    # Donors
    # ------------------------------------------------------------------
    def create_donor(self, payload, headers):
        return self._request("POST", "/api/donors", payload, headers)

    def get_donor(self, donor_id, headers):
        return self._request("GET", f"/api/donors/{donor_id}", headers=headers)

    # ------------------------------------------------------------------
    # Award funds
    # ------------------------------------------------------------------
    def create_fund(self, payload, headers):
        return self._request("POST", "/api/award-funds", payload, headers)

    def get_fund(self, fund_id, headers):
        return self._request("GET", f"/api/award-funds/{fund_id}", headers=headers)

    def add_commitment(self, fund_id, payload, headers):
        return self._request(
            "POST", f"/api/award-funds/{fund_id}/commitments", payload, headers
        )

    # ------------------------------------------------------------------
    # Scholarship programs
    # ------------------------------------------------------------------
    def create_program(self, payload, headers):
        return self._request("POST", "/api/scholarship-programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request(
            "GET", "/api/scholarship-programs", headers=headers, params=params
        )

    def get_program(self, program_id, headers):
        return self._request(
            "GET", f"/api/scholarship-programs/{program_id}", headers=headers
        )

    def update_program(self, program_id, payload, headers):
        return self._request(
            "PUT", f"/api/scholarship-programs/{program_id}", payload, headers
        )

    def publish_program(self, program_id, headers):
        return self._request(
            "POST", f"/api/scholarship-programs/{program_id}/publish", {}, headers
        )

    def close_program(self, program_id, headers):
        return self._request(
            "POST", f"/api/scholarship-programs/{program_id}/close", {}, headers
        )

    def extend_program(self, program_id, payload, headers):
        return self._request(
            "POST", f"/api/scholarship-programs/{program_id}/extend", payload, headers
        )

    def archive_program(self, program_id, headers):
        return self._request(
            "POST", f"/api/scholarship-programs/{program_id}/archive", {}, headers
        )

    # ------------------------------------------------------------------
    # Applications
    # ------------------------------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", "/api/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request(
            "GET", "/api/applications", headers=headers, params=params
        )

    def get_application(self, application_id, headers):
        return self._request(
            "GET", f"/api/applications/{application_id}", headers=headers
        )

    def submit_application(self, application_id, headers):
        return self._request(
            "POST", f"/api/applications/{application_id}/submit", {}, headers
        )

    def return_application(self, application_id, headers):
        return self._request(
            "POST", f"/api/applications/{application_id}/return", {}, headers
        )

    def withdraw_application(self, application_id, headers):
        return self._request(
            "POST", f"/api/applications/{application_id}/withdraw", {}, headers
        )

    # ------------------------------------------------------------------
    # Application components
    # ------------------------------------------------------------------
    def add_component(self, application_id, payload, headers):
        return self._request(
            "POST", f"/api/applications/{application_id}/components", payload, headers
        )

    def list_components(self, application_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/applications/{application_id}/components",
            headers=headers,
            params=params,
        )

    def get_component(self, component_id, headers):
        return self._request(
            "GET", f"/api/components/{component_id}", headers=headers
        )

    def receive_component(self, component_id, payload, headers):
        return self._request(
            "POST", f"/api/components/{component_id}/receive", payload, headers
        )

    def accept_component(self, component_id, headers):
        return self._request(
            "POST", f"/api/components/{component_id}/accept", {}, headers
        )

    def reject_component(self, component_id, headers):
        return self._request(
            "POST", f"/api/components/{component_id}/reject", {}, headers
        )

    def waive_component(self, component_id, headers):
        return self._request(
            "POST", f"/api/components/{component_id}/waive", {}, headers
        )

    # ------------------------------------------------------------------
    # Reminders
    # ------------------------------------------------------------------
    def list_reminders(self, application_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/applications/{application_id}/reminders",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Review cycles
    # ------------------------------------------------------------------
    def create_cycle(self, payload, headers):
        return self._request("POST", "/api/review-cycles", payload, headers)

    def list_cycles(self, headers, params=None):
        return self._request("GET", "/api/review-cycles", headers=headers, params=params)

    def get_cycle(self, cycle_id, headers):
        return self._request(
            "GET", f"/api/review-cycles/{cycle_id}", headers=headers
        )

    def open_scoring(self, cycle_id, headers):
        return self._request(
            "POST", f"/api/review-cycles/{cycle_id}/open-scoring", {}, headers
        )

    def open_deliberation(self, cycle_id, headers):
        return self._request(
            "POST", f"/api/review-cycles/{cycle_id}/open-deliberation", {}, headers
        )

    def reopen_scoring(self, cycle_id, headers):
        return self._request(
            "POST", f"/api/review-cycles/{cycle_id}/reopen-scoring", {}, headers
        )

    def finalize_cycle(self, cycle_id, headers):
        return self._request(
            "POST", f"/api/review-cycles/{cycle_id}/finalize", {}, headers
        )

    # ------------------------------------------------------------------
    # Review scores
    # ------------------------------------------------------------------
    def create_score(self, payload, headers):
        return self._request("POST", "/api/review-scores", payload, headers)

    def list_scores(self, headers, params=None):
        return self._request("GET", "/api/review-scores", headers=headers, params=params)

    def get_score(self, score_id, headers):
        return self._request("GET", f"/api/review-scores/{score_id}", headers=headers)

    def submit_score(self, score_id, headers):
        return self._request(
            "POST", f"/api/review-scores/{score_id}/submit", {}, headers
        )

    def recall_score(self, score_id, headers):
        return self._request(
            "POST", f"/api/review-scores/{score_id}/recall", {}, headers
        )

    # ------------------------------------------------------------------
    # Awards
    # ------------------------------------------------------------------
    def create_award(self, payload, headers):
        return self._request("POST", "/api/awards", payload, headers)

    def list_awards(self, headers, params=None):
        return self._request("GET", "/api/awards", headers=headers, params=params)

    def get_award(self, award_id, headers):
        return self._request("GET", f"/api/awards/{award_id}", headers=headers)

    def patch_award(self, award_id, payload, headers):
        return self._request("PATCH", f"/api/awards/{award_id}", payload, headers)

    def accept_award(self, award_id, headers):
        return self._request("POST", f"/api/awards/{award_id}/accept", {}, headers)

    def decline_award(self, award_id, headers):
        return self._request("POST", f"/api/awards/{award_id}/decline", {}, headers)

    def revoke_award(self, award_id, headers):
        return self._request("POST", f"/api/awards/{award_id}/revoke", {}, headers)

    def schedule_split(self, award_id, payload, headers):
        return self._request(
            "POST", f"/api/awards/{award_id}/schedule-split", payload, headers
        )

    # ------------------------------------------------------------------
    # Disbursements
    # ------------------------------------------------------------------
    def create_disbursement(self, payload, headers):
        return self._request("POST", "/api/disbursements", payload, headers)

    def list_disbursements(self, headers, params=None):
        return self._request(
            "GET", "/api/disbursements", headers=headers, params=params
        )

    def get_disbursement(self, disbursement_id, headers):
        return self._request(
            "GET", f"/api/disbursements/{disbursement_id}", headers=headers
        )

    def send_disbursement(self, disbursement_id, headers):
        return self._request(
            "POST", f"/api/disbursements/{disbursement_id}/send", {}, headers
        )

    def confirm_disbursement(self, disbursement_id, headers):
        return self._request(
            "POST", f"/api/disbursements/{disbursement_id}/confirm", {}, headers
        )

    def mark_returned(self, disbursement_id, payload, headers):
        return self._request(
            "POST",
            f"/api/disbursements/{disbursement_id}/mark-returned",
            payload,
            headers,
        )

    def reschedule_disbursement(self, disbursement_id, payload, headers):
        return self._request(
            "POST",
            f"/api/disbursements/{disbursement_id}/reschedule",
            payload,
            headers,
        )

    def cancel_disbursement(self, disbursement_id, headers):
        return self._request(
            "POST", f"/api/disbursements/{disbursement_id}/cancel", {}, headers
        )

    # ------------------------------------------------------------------
    # Award adjustments
    # ------------------------------------------------------------------
    def create_adjustment(self, payload, headers):
        return self._request("POST", "/api/award-adjustments", payload, headers)

    def list_adjustments(self, headers, params=None):
        return self._request(
            "GET", "/api/award-adjustments", headers=headers, params=params
        )

    def get_adjustment(self, adjustment_id, headers):
        return self._request(
            "GET", f"/api/award-adjustments/{adjustment_id}", headers=headers
        )

    def submit_adjustment(self, adjustment_id, headers):
        return self._request(
            "POST", f"/api/award-adjustments/{adjustment_id}/submit", {}, headers
        )

    def approve_adjustment(self, adjustment_id, headers):
        return self._request(
            "POST", f"/api/award-adjustments/{adjustment_id}/approve", {}, headers
        )

    def reject_adjustment(self, adjustment_id, headers):
        return self._request(
            "POST", f"/api/award-adjustments/{adjustment_id}/reject", {}, headers
        )

    # ------------------------------------------------------------------
    # Renewal evaluations
    # ------------------------------------------------------------------
    def create_renewal_evaluation(self, payload, headers):
        return self._request("POST", "/api/renewal-evaluations", payload, headers)

    def list_renewal_evaluations(self, headers, params=None):
        return self._request(
            "GET", "/api/renewal-evaluations", headers=headers, params=params
        )

    def get_renewal_evaluation(self, evaluation_id, headers):
        return self._request(
            "GET", f"/api/renewal-evaluations/{evaluation_id}", headers=headers
        )

    def verify_renewal(self, evaluation_id, payload, headers):
        return self._request(
            "POST",
            f"/api/renewal-evaluations/{evaluation_id}/verify",
            payload,
            headers,
        )

    def appeal_renewal(self, evaluation_id, payload, headers):
        return self._request(
            "POST",
            f"/api/renewal-evaluations/{evaluation_id}/appeal",
            payload,
            headers,
        )

    def finalize_renewal(self, evaluation_id, payload, headers):
        return self._request(
            "POST",
            f"/api/renewal-evaluations/{evaluation_id}/finalize-renewal",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Thank-you letters
    # ------------------------------------------------------------------
    def list_letters(self, headers, params=None):
        return self._request(
            "GET", "/api/thank-you-letters", headers=headers, params=params
        )

    def get_letter(self, letter_id, headers):
        return self._request(
            "GET", f"/api/thank-you-letters/{letter_id}", headers=headers
        )

    def submit_letter(self, letter_id, payload, headers):
        return self._request(
            "POST", f"/api/thank-you-letters/{letter_id}/submit", payload, headers
        )

    def request_revision(self, letter_id, headers):
        return self._request(
            "POST",
            f"/api/thank-you-letters/{letter_id}/request-revision",
            {},
            headers,
        )

    def approve_letter(self, letter_id, headers):
        return self._request(
            "POST", f"/api/thank-you-letters/{letter_id}/approve", {}, headers
        )

    def deliver_letter(self, letter_id, headers):
        return self._request(
            "POST", f"/api/thank-you-letters/{letter_id}/deliver", {}, headers
        )

    def waive_letter(self, letter_id, headers):
        return self._request(
            "POST", f"/api/thank-you-letters/{letter_id}/waive", {}, headers
        )

    # ------------------------------------------------------------------
    # Donor reports
    # ------------------------------------------------------------------
    def create_report(self, payload, headers):
        return self._request("POST", "/api/donor-reports", payload, headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/api/donor-reports", headers=headers, params=params)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/api/donor-reports/{report_id}", headers=headers)

    def generate_report(self, report_id, headers):
        return self._request(
            "POST", f"/api/donor-reports/{report_id}/generate", {}, headers
        )

    def send_report(self, report_id, headers):
        return self._request(
            "POST", f"/api/donor-reports/{report_id}/send", {}, headers
        )

    def acknowledge_report(self, report_id, headers):
        return self._request(
            "POST", f"/api/donor-reports/{report_id}/acknowledge", {}, headers
        )


api_client = ApiClient()
