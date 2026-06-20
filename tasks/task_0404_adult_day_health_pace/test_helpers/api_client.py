"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock control ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Program ---
    def create_program(self, payload, headers):
        return self._request("POST", "/pace/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/pace/programs/{program_id}", headers=headers)

    def suspend_program(self, program_id, headers):
        return self._request("POST", f"/pace/programs/{program_id}/suspend", headers=headers)

    def reopen_program(self, program_id, headers):
        return self._request("POST", f"/pace/programs/{program_id}/reopen", headers=headers)

    # --- Participant ---
    def create_participant(self, payload, headers):
        return self._request("POST", "/pace/participants", payload, headers)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/pace/participants/{participant_id}", headers=headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", "/pace/participants", headers=headers, params=params)

    def enroll_participant(self, participant_id, payload, headers):
        return self._request("POST", f"/pace/participants/{participant_id}/enroll", payload, headers)

    def get_attendance_summary(self, participant_id, headers, params=None):
        return self._request("GET", f"/pace/participants/{participant_id}/attendance-summary",
                             headers=headers, params=params)

    # --- Enrollment ---
    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/pace/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/pace/enrollments", headers=headers, params=params)

    # --- Level of Care ---
    def create_loc_assessment(self, payload, headers):
        return self._request("POST", "/pace/loc-assessments", payload, headers)

    def get_loc_assessment(self, assessment_id, headers):
        return self._request("GET", f"/pace/loc-assessments/{assessment_id}", headers=headers)

    def list_loc_assessments(self, headers, params=None):
        return self._request("GET", "/pace/loc-assessments", headers=headers, params=params)

    def certify_loc_assessment(self, assessment_id, headers):
        return self._request("POST", f"/pace/loc-assessments/{assessment_id}/certify", headers=headers)

    def deny_loc_assessment(self, assessment_id, headers):
        return self._request("POST", f"/pace/loc-assessments/{assessment_id}/deny", headers=headers)

    # --- Care Plan ---
    def create_care_plan(self, payload, headers):
        return self._request("POST", "/pace/care-plans", payload, headers)

    def get_care_plan(self, care_plan_id, headers):
        return self._request("GET", f"/pace/care-plans/{care_plan_id}", headers=headers)

    def list_care_plans(self, headers, params=None):
        return self._request("GET", "/pace/care-plans", headers=headers, params=params)

    def add_care_plan_goal(self, care_plan_id, payload, headers):
        return self._request("POST", f"/pace/care-plans/{care_plan_id}/goals", payload, headers)

    def get_care_plan_goal(self, goal_id, headers):
        return self._request("GET", f"/pace/care-plan-goals/{goal_id}", headers=headers)

    def list_care_plan_goals(self, headers, params=None):
        return self._request("GET", "/pace/care-plan-goals", headers=headers, params=params)

    def sign_care_plan(self, care_plan_id, payload, headers):
        return self._request("POST", f"/pace/care-plans/{care_plan_id}/sign", payload, headers)

    def submit_care_plan(self, care_plan_id, headers):
        return self._request("POST", f"/pace/care-plans/{care_plan_id}/submit", headers=headers)

    def request_care_plan_revision(self, care_plan_id, headers):
        return self._request("POST", f"/pace/care-plans/{care_plan_id}/request-revision", headers=headers)

    def activate_care_plan(self, care_plan_id, headers):
        return self._request("POST", f"/pace/care-plans/{care_plan_id}/activate", headers=headers)

    def void_care_plan(self, care_plan_id, headers):
        return self._request("POST", f"/pace/care-plans/{care_plan_id}/void", headers=headers)

    # --- Attendance ---
    def create_attendance_day(self, payload, headers):
        return self._request("POST", "/pace/attendance-days", payload, headers)

    def get_attendance_day(self, day_id, headers):
        return self._request("GET", f"/pace/attendance-days/{day_id}", headers=headers)

    def list_attendance_days(self, headers, params=None):
        return self._request("GET", "/pace/attendance-days", headers=headers, params=params)

    def check_in_attendance_day(self, day_id, headers):
        return self._request("POST", f"/pace/attendance-days/{day_id}/check-in", headers=headers)

    def complete_attendance_day(self, day_id, headers):
        return self._request("POST", f"/pace/attendance-days/{day_id}/complete", headers=headers)

    def no_show_attendance_day(self, day_id, headers):
        return self._request("POST", f"/pace/attendance-days/{day_id}/no-show", headers=headers)

    def cancel_attendance_day(self, day_id, headers):
        return self._request("POST", f"/pace/attendance-days/{day_id}/cancel", headers=headers)

    # --- Transport ---
    def create_transport_leg(self, payload, headers):
        return self._request("POST", "/pace/transport-legs", payload, headers)

    def get_transport_leg(self, leg_id, headers):
        return self._request("GET", f"/pace/transport-legs/{leg_id}", headers=headers)

    def list_transport_legs(self, headers, params=None):
        return self._request("GET", "/pace/transport-legs", headers=headers, params=params)

    # --- Medication ---
    def create_medication_order(self, payload, headers):
        return self._request("POST", "/pace/medication-orders", payload, headers)

    def get_medication_order(self, order_id, headers):
        return self._request("GET", f"/pace/medication-orders/{order_id}", headers=headers)

    def list_medication_orders(self, headers, params=None):
        return self._request("GET", "/pace/medication-orders", headers=headers, params=params)

    def activate_medication_order(self, order_id, headers):
        return self._request("POST", f"/pace/medication-orders/{order_id}/activate", headers=headers)

    def hold_medication_order(self, order_id, headers):
        return self._request("POST", f"/pace/medication-orders/{order_id}/hold", headers=headers)

    def resume_medication_order(self, order_id, headers):
        return self._request("POST", f"/pace/medication-orders/{order_id}/resume", headers=headers)

    def discontinue_medication_order(self, order_id, headers):
        return self._request("POST", f"/pace/medication-orders/{order_id}/discontinue", headers=headers)

    def create_medication_administration(self, payload, headers):
        return self._request("POST", "/pace/medication-administrations", payload, headers)

    def get_medication_administration(self, administration_id, headers):
        return self._request("GET", f"/pace/medication-administrations/{administration_id}", headers=headers)

    def list_medication_administrations(self, headers, params=None):
        return self._request("GET", "/pace/medication-administrations", headers=headers, params=params)

    # --- Capitation ---
    def create_capitation_payment(self, payload, headers):
        return self._request("POST", "/pace/capitation-payments", payload, headers)

    def get_capitation_payment(self, payment_id, headers):
        return self._request("GET", f"/pace/capitation-payments/{payment_id}", headers=headers)

    def list_capitation_payments(self, headers, params=None):
        return self._request("GET", "/pace/capitation-payments", headers=headers, params=params)

    def finalize_capitation_payment(self, payment_id, payload, headers):
        return self._request("POST", f"/pace/capitation-payments/{payment_id}/finalize", payload, headers)

    def reconcile_capitation_payment(self, payment_id, payload, headers):
        return self._request("POST", f"/pace/capitation-payments/{payment_id}/reconcile", payload, headers)

    def void_capitation_payment(self, payment_id, headers):
        return self._request("POST", f"/pace/capitation-payments/{payment_id}/void", headers=headers)

    # --- Disenrollment ---
    def create_disenrollment_request(self, payload, headers):
        return self._request("POST", "/pace/disenrollment-requests", payload, headers)

    def get_disenrollment_request(self, request_id, headers):
        return self._request("GET", f"/pace/disenrollment-requests/{request_id}", headers=headers)

    def list_disenrollment_requests(self, headers, params=None):
        return self._request("GET", "/pace/disenrollment-requests", headers=headers, params=params)

    def approve_disenrollment_request(self, request_id, headers):
        return self._request("POST", f"/pace/disenrollment-requests/{request_id}/approve", headers=headers)

    def deny_disenrollment_request(self, request_id, headers):
        return self._request("POST", f"/pace/disenrollment-requests/{request_id}/deny", headers=headers)

    def finalize_disenrollment_request(self, request_id, payload, headers):
        return self._request("POST", f"/pace/disenrollment-requests/{request_id}/finalize", payload, headers)

    def withdraw_disenrollment_request(self, request_id, headers):
        return self._request("POST", f"/pace/disenrollment-requests/{request_id}/withdraw", headers=headers)


api_client = ApiClient()
