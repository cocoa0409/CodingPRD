"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Program ---
    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    # --- Truck ---
    def create_truck(self, payload, headers):
        return self._request("POST", "/trucks", payload, headers)

    def get_truck(self, truck_id, headers):
        return self._request("GET", f"/trucks/{truck_id}", headers=headers)

    # --- Instructor ---
    def create_instructor(self, payload, headers):
        return self._request("POST", "/instructors", payload, headers)

    def get_instructor(self, instructor_id, headers):
        return self._request("GET", f"/instructors/{instructor_id}", headers=headers)

    # --- Carrier ---
    def create_carrier(self, payload, headers):
        return self._request("POST", "/carriers", payload, headers)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"/carriers/{carrier_id}", headers=headers)

    # --- Enrollment ---
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def withdraw_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/withdraw", {}, headers)

    # --- PrereqDocument ---
    def create_prereq_document(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/prereq-documents", payload, headers)

    def list_enrollment_prereq_documents(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/prereq-documents", headers=headers, params=params)

    def list_prereq_documents(self, headers, params=None):
        return self._request("GET", "/prereq-documents", headers=headers, params=params)

    def get_prereq_document(self, document_id, headers):
        return self._request("GET", f"/prereq-documents/{document_id}", headers=headers)

    def approve_prereq_document(self, document_id, headers):
        return self._request("POST", f"/prereq-documents/{document_id}/approve", {}, headers)

    def reject_prereq_document(self, document_id, headers):
        return self._request("POST", f"/prereq-documents/{document_id}/reject", {}, headers)

    def expire_prereq_document(self, document_id, headers):
        return self._request("POST", f"/prereq-documents/{document_id}/expire", {}, headers)

    # --- ClockSession ---
    def create_clock_session(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/clock-sessions", payload, headers)

    def list_enrollment_clock_sessions(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/clock-sessions", headers=headers, params=params)

    def list_clock_sessions(self, headers, params=None):
        return self._request("GET", "/clock-sessions", headers=headers, params=params)

    def get_clock_session(self, session_id, headers):
        return self._request("GET", f"/clock-sessions/{session_id}", headers=headers)

    def complete_clock_session(self, session_id, headers):
        return self._request("POST", f"/clock-sessions/{session_id}/complete", {}, headers)

    def cancel_clock_session(self, session_id, headers):
        return self._request("POST", f"/clock-sessions/{session_id}/cancel", {}, headers)

    # --- SkillsTest ---
    def create_skills_test(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/skills-tests", payload, headers)

    def list_enrollment_skills_tests(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/skills-tests", headers=headers, params=params)

    def list_skills_tests(self, headers, params=None):
        return self._request("GET", "/skills-tests", headers=headers, params=params)

    def get_skills_test(self, test_id, headers):
        return self._request("GET", f"/skills-tests/{test_id}", headers=headers)

    def grade_skills_test(self, test_id, payload, headers):
        return self._request("POST", f"/skills-tests/{test_id}/grade", payload, headers)

    def void_skills_test(self, test_id, headers):
        return self._request("POST", f"/skills-tests/{test_id}/void", {}, headers)

    # --- SponsorshipOffer ---
    def create_sponsorship_offer(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/sponsorship-offers", payload, headers)

    def list_enrollment_sponsorship_offers(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/sponsorship-offers", headers=headers, params=params)

    def list_sponsorship_offers(self, headers, params=None):
        return self._request("GET", "/sponsorship-offers", headers=headers, params=params)

    def get_sponsorship_offer(self, offer_id, headers):
        return self._request("GET", f"/sponsorship-offers/{offer_id}", headers=headers)

    def accept_sponsorship_offer(self, offer_id, headers):
        return self._request("POST", f"/sponsorship-offers/{offer_id}/accept", {}, headers)

    def decline_sponsorship_offer(self, offer_id, headers):
        return self._request("POST", f"/sponsorship-offers/{offer_id}/decline", {}, headers)

    def forfeit_sponsorship_offer(self, offer_id, headers):
        return self._request("POST", f"/sponsorship-offers/{offer_id}/forfeit", {}, headers)

    # --- FinancePlan ---
    def create_finance_plan(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/finance-plans", payload, headers)

    def list_enrollment_finance_plans(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/finance-plans", headers=headers, params=params)

    def list_finance_plans(self, headers, params=None):
        return self._request("GET", "/finance-plans", headers=headers, params=params)

    def get_finance_plan(self, plan_id, headers):
        return self._request("GET", f"/finance-plans/{plan_id}", headers=headers)

    # --- CompletionReport ---
    def create_completion_report(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/completion-reports", payload, headers)

    def list_enrollment_completion_reports(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/completion-reports", headers=headers, params=params)

    def list_completion_reports(self, headers, params=None):
        return self._request("GET", "/completion-reports", headers=headers, params=params)

    def get_completion_report(self, report_id, headers):
        return self._request("GET", f"/completion-reports/{report_id}", headers=headers)

    def transmit_completion_report(self, report_id, headers):
        return self._request("POST", f"/completion-reports/{report_id}/transmit", {}, headers)

    # --- Test-driving clock endpoints ---
    def set_current_utc(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def advance_service_months(self, offer_id, months, headers):
        return self._request("POST", "/_clock/advance_service_months",
                             {"offer_id": offer_id, "months": months}, headers)


api_client = ApiClient()
