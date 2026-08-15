"""API client: one method per endpoint defined in PRD §4."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (PRD §2.5) ---
    def set_clock(self, to_iso8601: str, headers: Dict):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers,
        )

    # --- seasons ---
    def create_season(self, payload: Dict, headers: Dict):
        return self._request("POST", "/seasons", payload, headers)

    def get_season(self, season_id: str, headers: Dict):
        return self._request("GET", f"/seasons/{season_id}", headers=headers)

    def publish_season(self, season_id: str, headers: Dict):
        return self._request("POST", f"/seasons/{season_id}/publish", {}, headers)

    def close_season(self, season_id: str, headers: Dict):
        return self._request("POST", f"/seasons/{season_id}/close", {}, headers)

    def run_season_sweep(self, season_id: str, headers: Dict):
        return self._request("POST", f"/seasons/{season_id}/sweeps", {}, headers)

    # --- programs ---
    def create_program(self, payload: Dict, headers: Dict):
        return self._request("POST", "/programs", payload, headers)

    def list_programs(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/programs", headers=headers, params=params)

    def get_program(self, program_id: str, headers: Dict):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    # --- rooms ---
    def create_room(self, payload: Dict, headers: Dict):
        return self._request("POST", "/rooms", payload, headers)

    def get_room(self, room_id: str, headers: Dict):
        return self._request("GET", f"/rooms/{room_id}", headers=headers)

    def patch_room(self, room_id: str, payload: Dict, headers: Dict):
        return self._request("PATCH", f"/rooms/{room_id}", payload, headers)

    # --- instructors ---
    def create_instructor(self, payload: Dict, headers: Dict):
        return self._request("POST", "/instructors", payload, headers)

    def get_instructor(self, instructor_id: str, headers: Dict):
        return self._request("GET", f"/instructors/{instructor_id}", headers=headers)

    # --- class sessions ---
    def create_class_session(self, payload: Dict, headers: Dict):
        return self._request("POST", "/class-sessions", payload, headers)

    def list_class_sessions(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/class-sessions", headers=headers, params=params)

    def get_class_session(self, session_id: str, headers: Dict):
        return self._request("GET", f"/class-sessions/{session_id}", headers=headers)

    def patch_class_session(self, session_id: str, payload: Dict, headers: Dict):
        return self._request("PATCH", f"/class-sessions/{session_id}", payload, headers)

    def publish_class_session(self, session_id: str, headers: Dict):
        return self._request("POST", f"/class-sessions/{session_id}/publish", {}, headers)

    def cancel_class_session(self, session_id: str, headers: Dict):
        return self._request("POST", f"/class-sessions/{session_id}/cancel", {}, headers)

    def complete_class_session(self, session_id: str, headers: Dict):
        return self._request("POST", f"/class-sessions/{session_id}/complete", {}, headers)

    # --- class meetings ---
    def create_class_meeting(self, payload: Dict, headers: Dict):
        return self._request("POST", "/class-meetings", payload, headers)

    def list_class_meetings(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/class-meetings", headers=headers, params=params)

    def get_class_meeting(self, meeting_id: str, headers: Dict):
        return self._request("GET", f"/class-meetings/{meeting_id}", headers=headers)

    def patch_class_meeting(self, meeting_id: str, payload: Dict, headers: Dict):
        return self._request("PATCH", f"/class-meetings/{meeting_id}", payload, headers)

    # --- instructor contracts ---
    def create_instructor_contract(self, payload: Dict, headers: Dict):
        return self._request("POST", "/instructor-contracts", payload, headers)

    def list_instructor_contracts(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/instructor-contracts", headers=headers, params=params)

    def get_instructor_contract(self, contract_id: str, headers: Dict):
        return self._request("GET", f"/instructor-contracts/{contract_id}", headers=headers)

    def accept_instructor_contract(self, contract_id: str, headers: Dict):
        return self._request(
            "POST", f"/instructor-contracts/{contract_id}/accept", {}, headers,
        )

    def decline_instructor_contract(self, contract_id: str, headers: Dict):
        return self._request(
            "POST", f"/instructor-contracts/{contract_id}/decline", {}, headers,
        )

    # --- households ---
    def create_household(self, payload: Dict, headers: Dict):
        return self._request("POST", "/households", payload, headers)

    def get_household(self, household_id: str, headers: Dict):
        return self._request("GET", f"/households/{household_id}", headers=headers)

    def verify_residency(self, household_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/households/{household_id}/verify-residency", payload, headers,
        )

    # --- participants ---
    def create_participant(self, payload: Dict, headers: Dict):
        return self._request("POST", "/participants", payload, headers)

    def list_participants(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/participants", headers=headers, params=params)

    def get_participant(self, participant_id: str, headers: Dict):
        return self._request("GET", f"/participants/{participant_id}", headers=headers)

    # --- safety forms ---
    def create_safety_form(self, payload: Dict, headers: Dict):
        return self._request("POST", "/safety-forms", payload, headers)

    def list_safety_forms(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/safety-forms", headers=headers, params=params)

    def get_safety_form(self, form_id: str, headers: Dict):
        return self._request("GET", f"/safety-forms/{form_id}", headers=headers)

    def verify_safety_form(self, form_id: str, headers: Dict):
        return self._request("POST", f"/safety-forms/{form_id}/verify", {}, headers)

    def reject_safety_form(self, form_id: str, headers: Dict, payload: Optional[Dict] = None):
        return self._request(
            "POST", f"/safety-forms/{form_id}/reject", payload or {}, headers,
        )

    # --- scholarship applications ---
    def create_scholarship_application(self, payload: Dict, headers: Dict):
        return self._request("POST", "/scholarship-applications", payload, headers)

    def list_scholarship_applications(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/scholarship-applications", headers=headers, params=params)

    def get_scholarship_application(self, application_id: str, headers: Dict):
        return self._request(
            "GET", f"/scholarship-applications/{application_id}", headers=headers,
        )

    def start_review_scholarship_application(self, application_id: str, headers: Dict):
        return self._request(
            "POST", f"/scholarship-applications/{application_id}/start-review", {}, headers,
        )

    def request_info_scholarship_application(self, application_id: str, payload: Dict,
                                             headers: Dict):
        return self._request(
            "POST", f"/scholarship-applications/{application_id}/request-info",
            payload, headers,
        )

    def resubmit_scholarship_application(self, application_id: str, payload: Dict,
                                         headers: Dict):
        return self._request(
            "POST", f"/scholarship-applications/{application_id}/resubmit",
            payload, headers,
        )

    def approve_scholarship_application(self, application_id: str, payload: Dict,
                                        headers: Dict):
        return self._request(
            "POST", f"/scholarship-applications/{application_id}/approve", payload, headers,
        )

    def deny_scholarship_application(self, application_id: str, headers: Dict,
                                     payload: Optional[Dict] = None):
        return self._request(
            "POST", f"/scholarship-applications/{application_id}/deny",
            payload or {}, headers,
        )

    def withdraw_scholarship_application(self, application_id: str, headers: Dict):
        return self._request(
            "POST", f"/scholarship-applications/{application_id}/withdraw", {}, headers,
        )

    def revoke_scholarship_application(self, application_id: str, headers: Dict):
        return self._request(
            "POST", f"/scholarship-applications/{application_id}/revoke", {}, headers,
        )

    # --- registrations ---
    def create_registration(self, payload: Dict, headers: Dict):
        return self._request("POST", "/registrations", payload, headers)

    def list_registrations(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/registrations", headers=headers, params=params)

    def get_registration(self, registration_id: str, headers: Dict):
        return self._request("GET", f"/registrations/{registration_id}", headers=headers)

    def drop_registration(self, registration_id: str, headers: Dict):
        return self._request(
            "POST", f"/registrations/{registration_id}/drop", {}, headers,
        )

    def pay_registration(self, registration_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/registrations/{registration_id}/payment", payload, headers,
        )

    # --- payment transactions ---
    def list_payments(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def get_payment(self, payment_id: str, headers: Dict):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def approve_refund(self, payment_id: str, headers: Dict):
        return self._request(
            "POST", f"/payments/{payment_id}/approve-refund", {}, headers,
        )

    # --- attendance records ---
    def create_attendance_record(self, payload: Dict, headers: Dict):
        return self._request("POST", "/attendance-records", payload, headers)

    def list_attendance_records(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/attendance-records", headers=headers, params=params)

    def get_attendance_record(self, attendance_id: str, headers: Dict):
        return self._request("GET", f"/attendance-records/{attendance_id}", headers=headers)

    def patch_attendance_record(self, attendance_id: str, payload: Dict, headers: Dict):
        return self._request(
            "PATCH", f"/attendance-records/{attendance_id}", payload, headers,
        )


api_client = ApiClient()
