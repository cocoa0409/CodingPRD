"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock (test-driving admin capability, PRD §2.5) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Schools ---
    def create_school(self, payload, headers):
        return self._request("POST", "/schools", payload, headers)

    def list_schools(self, headers, params=None):
        return self._request("GET", "/schools", headers=headers, params=params)

    def get_school(self, school_id, headers):
        return self._request("GET", f"/schools/{school_id}", headers=headers)

    def get_school_compliance_summary(self, school_id, headers):
        return self._request("GET", f"/schools/{school_id}/compliance-summary", headers=headers)

    # --- Staff members ---
    def create_staff_member(self, payload, headers):
        return self._request("POST", "/staff-members", payload, headers)

    def list_staff_members(self, headers, params=None):
        return self._request("GET", "/staff-members", headers=headers, params=params)

    def get_staff_member(self, staff_id, headers):
        return self._request("GET", f"/staff-members/{staff_id}", headers=headers)

    # --- Training records ---
    def create_training_record(self, payload, headers):
        return self._request("POST", "/training-records", payload, headers)

    def list_training_records(self, headers, params=None):
        return self._request("GET", "/training-records", headers=headers, params=params)

    def get_training_record(self, record_id, headers):
        return self._request("GET", f"/training-records/{record_id}", headers=headers)

    # --- Students ---
    def create_student(self, payload, headers):
        return self._request("POST", "/students", payload, headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/students", headers=headers, params=params)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}", headers=headers)

    def update_student(self, student_id, payload, headers):
        return self._request("PATCH", f"/students/{student_id}", payload, headers)

    # --- Referrals ---
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def start_referral_review(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/start-review", {}, headers)

    def initiate_evaluation(self, referral_id, payload, headers):
        return self._request("POST", f"/referrals/{referral_id}/initiate-evaluation", payload, headers)

    def reject_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/reject", {}, headers)

    def withdraw_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/withdraw", {}, headers)

    # --- Eligibility evaluations ---
    def list_evaluations(self, headers, params=None):
        return self._request("GET", "/evaluations", headers=headers, params=params)

    def get_evaluation(self, evaluation_id, headers):
        return self._request("GET", f"/evaluations/{evaluation_id}", headers=headers)

    def request_evaluation_consent(self, evaluation_id, headers):
        return self._request("POST", f"/evaluations/{evaluation_id}/request-consent", {}, headers)

    def record_evaluation_consent(self, evaluation_id, payload, headers):
        return self._request("POST", f"/evaluations/{evaluation_id}/record-consent", payload, headers)

    def start_evaluation(self, evaluation_id, headers):
        return self._request("POST", f"/evaluations/{evaluation_id}/start", {}, headers)

    def determine_evaluation(self, evaluation_id, payload, headers):
        return self._request("POST", f"/evaluations/{evaluation_id}/determine", payload, headers)

    # --- Plans ---
    def create_plan(self, payload, headers):
        return self._request("POST", "/plans", payload, headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/plans", headers=headers, params=params)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/plans/{plan_id}", headers=headers)

    def get_plan_compliance_summary(self, plan_id, headers):
        return self._request("GET", f"/plans/{plan_id}/compliance-summary", headers=headers)

    def submit_plan_for_consent(self, plan_id, payload, headers):
        return self._request("POST", f"/plans/{plan_id}/submit-for-consent", payload, headers)

    def record_plan_parent_consent(self, plan_id, payload, headers):
        return self._request("POST", f"/plans/{plan_id}/record-parent-consent", payload, headers)

    def suspend_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/plans/{plan_id}/suspend", payload, headers)

    def reinstate_plan(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/reinstate", {}, headers)

    # --- Accommodations ---
    def create_accommodation(self, payload, headers):
        return self._request("POST", "/accommodations", payload, headers)

    def list_accommodations(self, headers, params=None):
        return self._request("GET", "/accommodations", headers=headers, params=params)

    def get_accommodation(self, accommodation_id, headers):
        return self._request("GET", f"/accommodations/{accommodation_id}", headers=headers)

    def suspend_accommodation(self, accommodation_id, headers):
        return self._request("POST", f"/accommodations/{accommodation_id}/suspend", {}, headers)

    def resume_accommodation(self, accommodation_id, headers):
        return self._request("POST", f"/accommodations/{accommodation_id}/resume", {}, headers)

    def discontinue_accommodation(self, accommodation_id, headers):
        return self._request("POST", f"/accommodations/{accommodation_id}/discontinue", {}, headers)

    # --- Teacher acknowledgments ---
    def create_teacher_ack(self, payload, headers):
        return self._request("POST", "/teacher-acks", payload, headers)

    def list_teacher_acks(self, headers, params=None):
        return self._request("GET", "/teacher-acks", headers=headers, params=params)

    def get_teacher_ack(self, ack_id, headers):
        return self._request("GET", f"/teacher-acks/{ack_id}", headers=headers)

    def acknowledge_teacher_ack(self, ack_id, headers):
        return self._request("POST", f"/teacher-acks/{ack_id}/acknowledge", {}, headers)

    def decline_teacher_ack(self, ack_id, headers):
        return self._request("POST", f"/teacher-acks/{ack_id}/decline", {}, headers)

    # --- Implementation logs ---
    def create_implementation_log(self, payload, headers):
        return self._request("POST", "/implementation-logs", payload, headers)

    def list_implementation_logs(self, headers, params=None):
        return self._request("GET", "/implementation-logs", headers=headers, params=params)

    def get_implementation_log(self, log_id, headers):
        return self._request("GET", f"/implementation-logs/{log_id}", headers=headers)

    # --- Review events ---
    def create_review(self, payload, headers):
        return self._request("POST", "/reviews", payload, headers)

    def list_reviews(self, headers, params=None):
        return self._request("GET", "/reviews", headers=headers, params=params)

    def get_review(self, review_id, headers):
        return self._request("GET", f"/reviews/{review_id}", headers=headers)

    def start_review(self, review_id, headers):
        return self._request("POST", f"/reviews/{review_id}/start", {}, headers)

    def complete_review(self, review_id, payload, headers):
        return self._request("POST", f"/reviews/{review_id}/complete", payload, headers)

    def cancel_review(self, review_id, headers):
        return self._request("POST", f"/reviews/{review_id}/cancel", {}, headers)

    # --- Testing accommodation requests ---
    def create_testing_request(self, payload, headers):
        return self._request("POST", "/testing-requests", payload, headers)

    def list_testing_requests(self, headers, params=None):
        return self._request("GET", "/testing-requests", headers=headers, params=params)

    def get_testing_request(self, request_id, headers):
        return self._request("GET", f"/testing-requests/{request_id}", headers=headers)

    def forward_testing_request(self, request_id, headers):
        return self._request("POST", f"/testing-requests/{request_id}/forward-to-district", {}, headers)

    def approve_testing_request(self, request_id, headers):
        return self._request("POST", f"/testing-requests/{request_id}/approve", {}, headers)

    def deny_testing_request(self, request_id, headers):
        return self._request("POST", f"/testing-requests/{request_id}/deny", {}, headers)

    def flag_testing_request(self, request_id, headers):
        return self._request("POST", f"/testing-requests/{request_id}/flag", {}, headers)

    # --- Parent consent records ---
    def create_consent_record(self, payload, headers):
        return self._request("POST", "/consent-records", payload, headers)

    def list_consent_records(self, headers, params=None):
        return self._request("GET", "/consent-records", headers=headers, params=params)

    def get_consent_record(self, consent_id, headers):
        return self._request("GET", f"/consent-records/{consent_id}", headers=headers)

    def record_consent_response(self, consent_id, payload, headers):
        return self._request("POST", f"/consent-records/{consent_id}/record-response", payload, headers)

    # --- Grievances ---
    def create_grievance(self, payload, headers):
        return self._request("POST", "/grievances", payload, headers)

    def list_grievances(self, headers, params=None):
        return self._request("GET", "/grievances", headers=headers, params=params)

    def get_grievance(self, grievance_id, headers):
        return self._request("GET", f"/grievances/{grievance_id}", headers=headers)

    def begin_informal_grievance(self, grievance_id, headers):
        return self._request("POST", f"/grievances/{grievance_id}/begin-informal", {}, headers)

    def escalate_grievance_to_formal(self, grievance_id, headers):
        return self._request("POST", f"/grievances/{grievance_id}/escalate-to-formal", {}, headers)

    def resolve_grievance(self, grievance_id, payload, headers):
        return self._request("POST", f"/grievances/{grievance_id}/resolve", payload, headers)

    def escalate_grievance_to_ocr(self, grievance_id, headers):
        return self._request("POST", f"/grievances/{grievance_id}/escalate-to-ocr", {}, headers)

    def close_grievance(self, grievance_id, headers):
        return self._request("POST", f"/grievances/{grievance_id}/close", {}, headers)

    # --- Compliance audit events ---
    def list_audit_events(self, headers, params=None):
        return self._request("GET", "/audit-events", headers=headers, params=params)

    def get_audit_event(self, event_id, headers):
        return self._request("GET", f"/audit-events/{event_id}", headers=headers)


api_client = ApiClient()
