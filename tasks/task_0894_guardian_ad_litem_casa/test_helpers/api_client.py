"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------- Logical clock
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # -------------------------------------------------------------- Volunteers
    def create_volunteer(self, payload, headers):
        return self._request("POST", "/volunteers", payload, headers)

    def list_volunteers(self, headers, params=None):
        return self._request("GET", "/volunteers", headers=headers, params=params)

    def get_volunteer(self, volunteer_id, headers):
        return self._request("GET", f"/volunteers/{volunteer_id}", headers=headers)

    def start_screening(self, volunteer_id, headers):
        return self._request(
            "POST", f"/volunteers/{volunteer_id}/start-screening", {}, headers
        )

    def swear_in(self, volunteer_id, headers):
        return self._request(
            "POST", f"/volunteers/{volunteer_id}/swear-in", {}, headers
        )

    def deactivate_volunteer(self, volunteer_id, payload, headers):
        return self._request(
            "POST", f"/volunteers/{volunteer_id}/deactivate", payload, headers
        )

    def resign_volunteer(self, volunteer_id, payload, headers):
        return self._request(
            "POST", f"/volunteers/{volunteer_id}/resign", payload, headers
        )

    def list_volunteer_assignments(self, volunteer_id, headers, params=None):
        return self._request(
            "GET", f"/volunteers/{volunteer_id}/assignments", headers=headers, params=params
        )

    def list_volunteer_visits(self, volunteer_id, headers, params=None):
        return self._request(
            "GET", f"/volunteers/{volunteer_id}/visits", headers=headers, params=params
        )

    def list_training_records(self, volunteer_id, headers, params=None):
        return self._request(
            "GET", f"/volunteers/{volunteer_id}/training-records", headers=headers, params=params
        )

    def create_training_record(self, volunteer_id, payload, headers):
        return self._request(
            "POST", f"/volunteers/{volunteer_id}/training-records", payload, headers
        )

    def list_background_checks(self, volunteer_id, headers, params=None):
        return self._request(
            "GET", f"/volunteers/{volunteer_id}/background-checks", headers=headers, params=params
        )

    def create_background_check(self, volunteer_id, payload, headers):
        return self._request(
            "POST", f"/volunteers/{volunteer_id}/background-checks", payload, headers
        )

    # -------------------------------------------------------- Background checks
    def clear_background_check(self, check_id, headers):
        return self._request(
            "POST", f"/background-checks/{check_id}/clear", {}, headers
        )

    def flag_background_check(self, check_id, payload, headers):
        return self._request(
            "POST", f"/background-checks/{check_id}/flag", payload, headers
        )

    # ------------------------------------------------------------- Supervisors
    def create_supervisor(self, payload, headers):
        return self._request("POST", "/supervisors", payload, headers)

    def get_supervisor(self, supervisor_id, headers):
        return self._request("GET", f"/supervisors/{supervisor_id}", headers=headers)

    def list_supervisor_review_notes(self, supervisor_id, headers, params=None):
        return self._request(
            "GET", f"/supervisors/{supervisor_id}/review-notes", headers=headers, params=params
        )

    # ------------------------------------------------------------------- Cases
    def create_case(self, payload, headers):
        return self._request("POST", "/cases", payload, headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/cases", headers=headers, params=params)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def create_assignment(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/assignments", payload, headers)

    def list_case_assignments(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/cases/{case_id}/assignments", headers=headers, params=params
        )

    def end_assignment(self, case_id, assignment_id, payload, headers):
        return self._request(
            "POST", f"/cases/{case_id}/assignments/{assignment_id}/end", payload, headers
        )

    def close_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/close", payload, headers)

    def create_visit(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/visits", payload, headers)

    def list_case_visits(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/cases/{case_id}/visits", headers=headers, params=params
        )

    def create_hearing(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/hearings", payload, headers)

    def list_case_hearings(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/cases/{case_id}/hearings", headers=headers, params=params
        )

    def create_court_report(self, case_id, payload, headers):
        return self._request(
            "POST", f"/cases/{case_id}/court-reports", payload, headers
        )

    # ---------------------------------------------------------------- Hearings
    def hold_hearing(self, hearing_id, headers):
        return self._request("POST", f"/hearings/{hearing_id}/hold", {}, headers)

    def continue_hearing(self, hearing_id, headers):
        return self._request("POST", f"/hearings/{hearing_id}/continue", {}, headers)

    def cancel_hearing(self, hearing_id, headers):
        return self._request("POST", f"/hearings/{hearing_id}/cancel", {}, headers)

    # ------------------------------------------------------------ Court reports
    def get_court_report(self, report_id, headers):
        return self._request("GET", f"/court-reports/{report_id}", headers=headers)

    def list_court_reports(self, headers, params=None):
        return self._request("GET", "/court-reports", headers=headers, params=params)

    def list_report_review_notes(self, report_id, headers, params=None):
        return self._request(
            "GET", f"/court-reports/{report_id}/review-notes", headers=headers, params=params
        )

    def submit_report(self, report_id, headers):
        return self._request("POST", f"/court-reports/{report_id}/submit", {}, headers)

    def review_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/court-reports/{report_id}/review", payload, headers
        )

    def revise_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/court-reports/{report_id}/revise", payload, headers
        )

    def file_report(self, report_id, headers):
        return self._request("POST", f"/court-reports/{report_id}/file", {}, headers)

    # ------------------------------------------------------------------ Visits
    def void_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/void", payload, headers)

    # ---------------------------------------------------------- Expense claims
    def create_expense_claim(self, payload, headers):
        return self._request("POST", "/expense-claims", payload, headers)

    def get_expense_claim(self, claim_id, headers):
        return self._request("GET", f"/expense-claims/{claim_id}", headers=headers)

    def list_expense_claims(self, headers, params=None):
        return self._request("GET", "/expense-claims", headers=headers, params=params)

    def approve_expense(self, claim_id, headers):
        return self._request("POST", f"/expense-claims/{claim_id}/approve", {}, headers)

    def reject_expense(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/expense-claims/{claim_id}/reject", payload, headers
        )

    def pay_expense(self, claim_id, headers):
        return self._request("POST", f"/expense-claims/{claim_id}/pay", {}, headers)

    def void_expense(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/expense-claims/{claim_id}/void", payload, headers
        )


api_client = ApiClient()
