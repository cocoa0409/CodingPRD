"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- Board ----
    def create_board(self, payload, headers):
        return self._request("POST", "/civic/boards", payload, headers)

    def list_boards(self, headers, params=None):
        return self._request("GET", "/civic/boards", headers=headers, params=params)

    def get_board(self, board_id, headers):
        return self._request("GET", f"/civic/boards/{board_id}", headers=headers)

    def get_roster(self, board_id, headers):
        return self._request("GET", f"/civic/boards/{board_id}/roster", headers=headers)

    def get_compliance_report(self, board_id, headers):
        return self._request("GET", f"/civic/boards/{board_id}/compliance-report",
                             headers=headers)

    # ---- Seat ----
    def create_seat(self, payload, headers):
        return self._request("POST", "/civic/seats", payload, headers)

    def list_seats(self, headers, params=None):
        return self._request("GET", "/civic/seats", headers=headers, params=params)

    def get_seat(self, seat_id, headers):
        return self._request("GET", f"/civic/seats/{seat_id}", headers=headers)

    # ---- Vacancy ----
    def create_vacancy(self, payload, headers):
        return self._request("POST", "/civic/vacancies", payload, headers)

    def list_vacancies(self, headers, params=None):
        return self._request("GET", "/civic/vacancies", headers=headers, params=params)

    def get_vacancy(self, vacancy_id, headers):
        return self._request("GET", f"/civic/vacancies/{vacancy_id}", headers=headers)

    def close_vacancy(self, vacancy_id, headers):
        return self._request("POST", f"/civic/vacancies/{vacancy_id}/close",
                             {}, headers)

    # ---- Applicant ----
    def create_applicant(self, payload, headers):
        return self._request("POST", "/civic/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/civic/applicants/{applicant_id}", headers=headers)

    # ---- Application ----
    def create_application(self, payload, headers):
        return self._request("POST", "/civic/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/civic/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/civic/applications/{application_id}", headers=headers)

    def start_review(self, application_id, headers):
        return self._request("POST", f"/civic/applications/{application_id}/start-review",
                             {}, headers)

    def return_for_info(self, application_id, payload, headers):
        return self._request("POST", f"/civic/applications/{application_id}/return-for-info",
                             payload, headers)

    def resubmit_application(self, application_id, payload, headers):
        return self._request("POST", f"/civic/applications/{application_id}/resubmit",
                             payload, headers)

    def decide_eligibility(self, application_id, payload, headers):
        return self._request("POST", f"/civic/applications/{application_id}/decide-eligibility",
                             payload, headers)

    # ---- Appointment ----
    def create_appointment(self, payload, headers):
        return self._request("POST", "/civic/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/civic/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/civic/appointments/{appointment_id}", headers=headers)

    def confirm_appointment(self, appointment_id, payload, headers):
        return self._request("POST", f"/civic/appointments/{appointment_id}/confirm",
                             payload, headers)

    def reject_appointment(self, appointment_id, payload, headers):
        return self._request("POST", f"/civic/appointments/{appointment_id}/reject",
                             payload, headers)

    # ---- Term ----
    def list_terms(self, headers, params=None):
        return self._request("GET", "/civic/terms", headers=headers, params=params)

    def get_term(self, term_id, headers):
        return self._request("GET", f"/civic/terms/{term_id}", headers=headers)

    def expire_term(self, term_id, headers):
        return self._request("POST", f"/civic/terms/{term_id}/expire", {}, headers)

    # ---- Meeting ----
    def create_meeting(self, payload, headers):
        return self._request("POST", "/civic/meetings", payload, headers)

    def list_meetings(self, headers, params=None):
        return self._request("GET", "/civic/meetings", headers=headers, params=params)

    def get_meeting(self, meeting_id, headers):
        return self._request("GET", f"/civic/meetings/{meeting_id}", headers=headers)

    def post_notice(self, meeting_id, headers):
        return self._request("POST", f"/civic/meetings/{meeting_id}/post-notice",
                             {}, headers)

    def hold_meeting(self, meeting_id, headers):
        return self._request("POST", f"/civic/meetings/{meeting_id}/hold", {}, headers)

    # ---- Attendance ----
    def create_attendance(self, payload, headers):
        return self._request("POST", "/civic/attendance", payload, headers)

    def list_attendance(self, headers, params=None):
        return self._request("GET", "/civic/attendance", headers=headers, params=params)

    def get_attendance(self, attendance_id, headers):
        return self._request("GET", f"/civic/attendance/{attendance_id}", headers=headers)

    # ---- DisclosureFiling ----
    def list_disclosures(self, headers, params=None):
        return self._request("GET", "/civic/disclosures", headers=headers, params=params)

    def get_disclosure(self, disclosure_id, headers):
        return self._request("GET", f"/civic/disclosures/{disclosure_id}", headers=headers)

    def file_disclosure(self, disclosure_id, payload, headers):
        return self._request("POST", f"/civic/disclosures/{disclosure_id}/file",
                             payload, headers)

    def review_disclosure(self, disclosure_id, payload, headers):
        return self._request("POST", f"/civic/disclosures/{disclosure_id}/review",
                             payload, headers)

    # ---- RemovalAction ----
    def create_removal(self, payload, headers):
        return self._request("POST", "/civic/removals", payload, headers)

    def list_removals(self, headers, params=None):
        return self._request("GET", "/civic/removals", headers=headers, params=params)

    def get_removal(self, removal_id, headers):
        return self._request("GET", f"/civic/removals/{removal_id}", headers=headers)

    def execute_removal(self, removal_id, headers):
        return self._request("POST", f"/civic/removals/{removal_id}/execute", {}, headers)

    # ---- ReappointmentRequest ----
    def create_reappointment(self, payload, headers):
        return self._request("POST", "/civic/reappointments", payload, headers)

    def list_reappointments(self, headers, params=None):
        return self._request("GET", "/civic/reappointments", headers=headers, params=params)

    def get_reappointment(self, reappointment_id, headers):
        return self._request("GET", f"/civic/reappointments/{reappointment_id}", headers=headers)

    def decide_reappointment(self, reappointment_id, payload, headers):
        return self._request("POST", f"/civic/reappointments/{reappointment_id}/decide",
                             payload, headers)


api_client = ApiClient()
