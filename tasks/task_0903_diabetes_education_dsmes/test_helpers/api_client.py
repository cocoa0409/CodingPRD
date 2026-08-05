"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers=headers)

    # ---- Program ----
    def create_program(self, payload, headers):
        return self._request("POST", "/dsmes/programs", payload, headers=headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/dsmes/programs/{program_id}", headers=headers)

    # ---- Curriculum ----
    def create_curriculum(self, payload, headers):
        return self._request("POST", "/dsmes/curricula", payload, headers=headers)

    def get_curriculum(self, curriculum_id, headers):
        return self._request("GET", f"/dsmes/curricula/{curriculum_id}", headers=headers)

    # ---- Patient ----
    def create_patient(self, payload, headers):
        return self._request("POST", "/dsmes/patients", payload, headers=headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/dsmes/patients/{patient_id}", headers=headers)

    # ---- Dietitian ----
    def create_dietitian(self, payload, headers):
        return self._request("POST", "/dsmes/dietitians", payload, headers=headers)

    def get_dietitian(self, dietitian_id, headers):
        return self._request("GET", f"/dsmes/dietitians/{dietitian_id}", headers=headers)

    # ---- Referral ----
    def create_referral(self, payload, headers):
        return self._request("POST", "/dsmes/referrals", payload, headers=headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/dsmes/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/dsmes/referrals", headers=headers, params=params)

    def assess_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/dsmes/referrals/{referral_id}/assess", payload, headers=headers)

    def reject_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/dsmes/referrals/{referral_id}/reject", payload, headers=headers)

    # ---- Enrollment ----
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/dsmes/enrollments", payload, headers=headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/dsmes/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/dsmes/enrollments", headers=headers, params=params)

    def activate_enrollment(self, enrollment_id, headers, payload=None):
        return self._request("POST", f"/dsmes/enrollments/{enrollment_id}/activate", payload or {}, headers=headers)

    def reinstate_enrollment(self, enrollment_id, headers, payload=None):
        return self._request("POST", f"/dsmes/enrollments/{enrollment_id}/reinstate", payload or {}, headers=headers)

    def withdraw_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/dsmes/enrollments/{enrollment_id}/withdraw", payload or {}, headers=headers)

    # ---- Session (individual) ----
    def create_session(self, payload, headers):
        return self._request("POST", "/dsmes/sessions", payload, headers=headers)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/dsmes/sessions/{session_id}", headers=headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/dsmes/sessions", headers=headers, params=params)

    def check_in_session(self, session_id, headers, payload=None):
        return self._request("POST", f"/dsmes/sessions/{session_id}/check-in", payload or {}, headers=headers)

    def complete_session(self, session_id, payload, headers):
        return self._request("POST", f"/dsmes/sessions/{session_id}/complete", payload, headers=headers)

    def no_show_session(self, session_id, headers, payload=None):
        return self._request("POST", f"/dsmes/sessions/{session_id}/no-show", payload or {}, headers=headers)

    def cancel_session(self, session_id, payload, headers):
        return self._request("POST", f"/dsmes/sessions/{session_id}/cancel", payload or {}, headers=headers)

    def adjudicate_session(self, session_id, payload, headers):
        return self._request("POST", f"/dsmes/sessions/{session_id}/adjudicate", payload, headers=headers)

    # ---- GroupClass ----
    def create_group_class(self, payload, headers):
        return self._request("POST", "/dsmes/group-classes", payload, headers=headers)

    def get_group_class(self, group_class_id, headers):
        return self._request("GET", f"/dsmes/group-classes/{group_class_id}", headers=headers)

    def list_group_classes(self, headers, params=None):
        return self._request("GET", "/dsmes/group-classes", headers=headers, params=params)

    def reserve_group_seat(self, group_class_id, payload, headers):
        return self._request("POST", f"/dsmes/group-classes/{group_class_id}/sessions", payload, headers=headers)

    # ---- DeviceEnrollment ----
    def create_device_enrollment(self, payload, headers):
        return self._request("POST", "/dsmes/device-enrollments", payload, headers=headers)

    def get_device_enrollment(self, device_id, headers):
        return self._request("GET", f"/dsmes/device-enrollments/{device_id}", headers=headers)

    def list_device_enrollments(self, headers, params=None):
        return self._request("GET", "/dsmes/device-enrollments", headers=headers, params=params)

    def activate_device(self, device_id, headers, payload=None):
        return self._request("POST", f"/dsmes/device-enrollments/{device_id}/activate", payload or {}, headers=headers)

    def return_device(self, device_id, headers, payload=None):
        return self._request("POST", f"/dsmes/device-enrollments/{device_id}/return", payload or {}, headers=headers)

    def ingest_reading(self, device_id, payload, headers):
        return self._request("POST", f"/dsmes/device-enrollments/{device_id}/readings", payload, headers=headers)

    def list_readings(self, device_id, headers, params=None):
        return self._request("GET", f"/dsmes/device-enrollments/{device_id}/readings", headers=headers, params=params)

    # ---- CarePlan ----
    def create_care_plan(self, payload, headers):
        return self._request("POST", "/dsmes/care-plans", payload, headers=headers)

    def get_care_plan(self, care_plan_id, headers):
        return self._request("GET", f"/dsmes/care-plans/{care_plan_id}", headers=headers)

    def list_care_plans(self, headers, params=None):
        return self._request("GET", "/dsmes/care-plans", headers=headers, params=params)

    def revise_care_plan(self, care_plan_id, payload, headers):
        return self._request("POST", f"/dsmes/care-plans/{care_plan_id}/revise", payload, headers=headers)

    def reopen_care_plan(self, care_plan_id, headers, payload=None):
        return self._request("POST", f"/dsmes/care-plans/{care_plan_id}/reopen", payload or {}, headers=headers)

    def close_care_plan(self, care_plan_id, payload, headers):
        return self._request("POST", f"/dsmes/care-plans/{care_plan_id}/close", payload, headers=headers)


api_client = ApiClient()
