"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/school/_clock/set_current_utc", payload, headers)

    # --- SchoolYear ---
    def create_school_year(self, payload, headers):
        return self._request("POST", "/school/school-years", payload, headers)

    def get_school_year(self, year_id, headers):
        return self._request("GET", f"/school/school-years/{year_id}", headers=headers)

    def open_school_year(self, year_id, headers):
        return self._request("POST", f"/school/school-years/{year_id}/open", {}, headers)

    def close_school_year(self, year_id, headers):
        return self._request("POST", f"/school/school-years/{year_id}/close", {}, headers)

    def accrue_late_fees(self, year_id, headers):
        return self._request("POST", f"/school/school-years/{year_id}/accrue-late-fees", {}, headers)

    # --- SecurityPlan ---
    def create_security_plan(self, year_id, payload, headers):
        return self._request("POST", f"/school/school-years/{year_id}/security-plan", payload, headers)

    def list_security_plans(self, year_id, headers):
        return self._request("GET", f"/school/school-years/{year_id}/security-plan", headers=headers)

    def submit_security_plan(self, plan_id, headers):
        return self._request("POST", f"/school/security-plans/{plan_id}/submit", {}, headers)

    def approve_security_plan(self, plan_id, headers):
        return self._request("POST", f"/school/security-plans/{plan_id}/approve", {}, headers)

    def reject_security_plan(self, plan_id, headers):
        return self._request("POST", f"/school/security-plans/{plan_id}/reject", {}, headers)

    def retire_security_plan(self, plan_id, headers):
        return self._request("POST", f"/school/security-plans/{plan_id}/retire", {}, headers)

    # --- CalendarClosure ---
    def create_closure(self, year_id, payload, headers):
        return self._request("POST", f"/school/school-years/{year_id}/closures", payload, headers)

    def list_closures(self, year_id, headers):
        return self._request("GET", f"/school/school-years/{year_id}/closures", headers=headers)

    # --- Family / Student ---
    def create_family(self, payload, headers):
        return self._request("POST", "/school/families", payload, headers)

    def get_family(self, family_id, headers):
        return self._request("GET", f"/school/families/{family_id}", headers=headers)

    def create_student(self, family_id, payload, headers):
        return self._request("POST", f"/school/families/{family_id}/students", payload, headers)

    def list_students(self, family_id, headers):
        return self._request("GET", f"/school/families/{family_id}/students", headers=headers)

    # --- Teacher ---
    def create_teacher(self, payload, headers):
        return self._request("POST", "/school/teachers", payload, headers)

    def get_teacher(self, teacher_id, headers):
        return self._request("GET", f"/school/teachers/{teacher_id}", headers=headers)

    def vet_teacher(self, teacher_id, headers):
        return self._request("POST", f"/school/teachers/{teacher_id}/vet", {}, headers)

    def hire_teacher(self, teacher_id, headers):
        return self._request("POST", f"/school/teachers/{teacher_id}/hire", {}, headers)

    def separate_teacher(self, teacher_id, headers):
        return self._request("POST", f"/school/teachers/{teacher_id}/separate", {}, headers)

    # --- Section ---
    def create_section(self, year_id, payload, headers):
        return self._request("POST", f"/school/school-years/{year_id}/sections", payload, headers)

    def get_section(self, section_id, headers):
        return self._request("GET", f"/school/sections/{section_id}", headers=headers)

    def list_sections(self, headers, params=None):
        return self._request("GET", "/school/sections", headers=headers, params=params)

    def patch_section(self, section_id, payload, headers):
        return self._request("PATCH", f"/school/sections/{section_id}", payload, headers)

    # --- Enrollment ---
    def create_enrollment(self, section_id, payload, headers):
        return self._request("POST", f"/school/sections/{section_id}/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/school/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/school/enrollments", headers=headers, params=params)

    def withdraw_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/school/enrollments/{enrollment_id}/withdraw", {}, headers)

    # --- TuitionInvoice ---
    def issue_invoice(self, family_id, payload, headers):
        return self._request("POST", f"/school/families/{family_id}/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/school/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/school/invoices", headers=headers, params=params)

    # --- Payment ---
    def post_payment(self, family_id, payload, headers):
        return self._request("POST", f"/school/families/{family_id}/payments", payload, headers)

    def list_payments(self, family_id, headers):
        return self._request("GET", f"/school/families/{family_id}/payments", headers=headers)

    def void_payment(self, payment_id, headers):
        return self._request("POST", f"/school/payments/{payment_id}/void", {}, headers)

    # --- AssistanceApplication ---
    def create_application(self, family_id, payload, headers):
        return self._request("POST", f"/school/families/{family_id}/assistance-applications", payload, headers)

    def list_family_applications(self, family_id, headers):
        return self._request("GET", f"/school/families/{family_id}/assistance-applications", headers=headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/school/assistance-applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/school/assistance-applications", headers=headers, params=params)

    def start_review(self, application_id, headers):
        return self._request("POST", f"/school/assistance-applications/{application_id}/start-review", {}, headers)

    def request_info(self, application_id, headers):
        return self._request("POST", f"/school/assistance-applications/{application_id}/request-info", {}, headers)

    def decide_application(self, application_id, payload, headers):
        return self._request("POST", f"/school/assistance-applications/{application_id}/decide", payload, headers)

    # --- Session / Attendance ---
    def create_session(self, section_id, payload, headers):
        return self._request("POST", f"/school/sections/{section_id}/sessions", payload, headers)

    def list_sessions(self, section_id, headers):
        return self._request("GET", f"/school/sections/{section_id}/sessions", headers=headers)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/school/sessions/{session_id}", headers=headers)

    def hold_session(self, session_id, headers):
        return self._request("POST", f"/school/sessions/{session_id}/hold", {}, headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/school/sessions/{session_id}/cancel", {}, headers)

    def post_attendance(self, session_id, payload, headers):
        return self._request("POST", f"/school/sessions/{session_id}/attendance", payload, headers)

    # --- Milestone ---
    def get_milestone(self, milestone_id, headers):
        return self._request("GET", f"/school/milestones/{milestone_id}", headers=headers)

    def list_milestones(self, headers, params=None):
        return self._request("GET", "/school/milestones", headers=headers, params=params)

    def evaluate_milestone(self, milestone_id, headers):
        return self._request("POST", f"/school/milestones/{milestone_id}/evaluate", {}, headers)

    def schedule_milestone(self, milestone_id, payload, headers):
        return self._request("POST", f"/school/milestones/{milestone_id}/schedule", payload, headers)

    def complete_milestone(self, milestone_id, headers):
        return self._request("POST", f"/school/milestones/{milestone_id}/complete", {}, headers)

    # --- VolunteerCommitment ---
    def get_commitment(self, commitment_id, headers):
        return self._request("GET", f"/school/volunteer-commitments/{commitment_id}", headers=headers)

    def list_commitments(self, headers, params=None):
        return self._request("GET", "/school/volunteer-commitments", headers=headers, params=params)

    def add_volunteer_entry(self, commitment_id, payload, headers):
        return self._request("POST", f"/school/volunteer-commitments/{commitment_id}/entries", payload, headers)

    def void_volunteer_entry(self, commitment_id, entry_id, headers):
        return self._request(
            "POST",
            f"/school/volunteer-commitments/{commitment_id}/entries/{entry_id}/void",
            {},
            headers,
        )

    def waive_commitment(self, commitment_id, headers):
        return self._request("POST", f"/school/volunteer-commitments/{commitment_id}/waive", {}, headers)


api_client = ApiClient()
