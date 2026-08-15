"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock & ops checkpoint ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/pd/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def run_ops(self, headers):
        return self._request("POST", "/pd/ops-runs", {}, headers)

    # --- Buildings ---
    def create_building(self, payload, headers):
        return self._request("POST", "/pd/buildings", payload, headers)

    def get_building(self, building_id, headers):
        return self._request("GET", f"/pd/buildings/{building_id}", headers=headers)

    def list_buildings(self, headers, params=None):
        return self._request("GET", "/pd/buildings", headers=headers, params=params)

    # --- Building budgets ---
    def create_budget(self, payload, headers):
        return self._request("POST", "/pd/budgets", payload, headers)

    def get_budget(self, budget_id, headers):
        return self._request("GET", f"/pd/budgets/{budget_id}", headers=headers)

    def list_budgets(self, headers, params=None):
        return self._request("GET", "/pd/budgets", headers=headers, params=params)

    def open_budget(self, budget_id, headers):
        return self._request("POST", f"/pd/budgets/{budget_id}/open", {}, headers)

    def close_budget(self, budget_id, headers):
        return self._request("POST", f"/pd/budgets/{budget_id}/close", {}, headers)

    def get_budget_summary(self, budget_id, headers):
        return self._request("GET", f"/pd/budgets/{budget_id}/summary", headers=headers)

    # --- Employees ---
    def create_employee(self, payload, headers):
        return self._request("POST", "/pd/employees", payload, headers)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/pd/employees/{employee_id}", headers=headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/pd/employees", headers=headers, params=params)

    def set_employee_status(self, employee_id, payload, headers):
        return self._request("POST", f"/pd/employees/{employee_id}/set-status", payload, headers)

    def advance_lane(self, employee_id, headers):
        return self._request("POST", f"/pd/employees/{employee_id}/advance-lane", {}, headers)

    def get_transcript(self, employee_id, headers, params=None):
        return self._request("GET", f"/pd/employees/{employee_id}/transcript",
                             headers=headers, params=params)

    # --- Courses ---
    def create_course(self, payload, headers):
        return self._request("POST", "/pd/courses", payload, headers)

    def get_course(self, course_id, headers):
        return self._request("GET", f"/pd/courses/{course_id}", headers=headers)

    def list_courses(self, headers, params=None):
        return self._request("GET", "/pd/courses", headers=headers, params=params)

    def retire_course(self, course_id, headers):
        return self._request("POST", f"/pd/courses/{course_id}/retire", {}, headers)

    # --- Sections & meetings ---
    def create_section(self, payload, headers):
        return self._request("POST", "/pd/sections", payload, headers)

    def get_section(self, section_id, headers):
        return self._request("GET", f"/pd/sections/{section_id}", headers=headers)

    def list_sections(self, headers, params=None):
        return self._request("GET", "/pd/sections", headers=headers, params=params)

    def publish_section(self, section_id, headers):
        return self._request("POST", f"/pd/sections/{section_id}/publish", {}, headers)

    def patch_section(self, section_id, payload, headers):
        return self._request("PATCH", f"/pd/sections/{section_id}", payload, headers)

    def cancel_section(self, section_id, headers):
        return self._request("POST", f"/pd/sections/{section_id}/cancel", {}, headers)

    def add_meeting(self, section_id, payload, headers):
        return self._request("POST", f"/pd/sections/{section_id}/meetings", payload, headers)

    def list_meetings(self, section_id, headers, params=None):
        return self._request("GET", f"/pd/sections/{section_id}/meetings",
                             headers=headers, params=params)

    def get_meeting(self, meeting_id, headers):
        return self._request("GET", f"/pd/meetings/{meeting_id}", headers=headers)

    def record_attendance(self, meeting_id, payload, headers):
        return self._request("POST", f"/pd/meetings/{meeting_id}/attendance", payload, headers)

    def get_meeting_attendance(self, meeting_id, headers, params=None):
        return self._request("GET", f"/pd/meetings/{meeting_id}/attendance",
                             headers=headers, params=params)

    # --- Registrations ---
    def create_registration(self, payload, headers):
        return self._request("POST", "/pd/registrations", payload, headers)

    def get_registration(self, registration_id, headers):
        return self._request("GET", f"/pd/registrations/{registration_id}", headers=headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/pd/registrations", headers=headers, params=params)

    def get_registration_attendance(self, registration_id, headers, params=None):
        return self._request("GET", f"/pd/registrations/{registration_id}/attendance",
                             headers=headers, params=params)

    def drop_registration(self, registration_id, headers):
        return self._request("POST", f"/pd/registrations/{registration_id}/drop", {}, headers)

    def withdraw_registration(self, registration_id, headers):
        return self._request("POST", f"/pd/registrations/{registration_id}/withdraw", {}, headers)

    def verify_attendance(self, registration_id, headers):
        return self._request("POST", f"/pd/registrations/{registration_id}/verify-attendance",
                             {}, headers)

    def waive_survey(self, registration_id, payload, headers):
        return self._request("POST", f"/pd/registrations/{registration_id}/waive-survey",
                             payload, headers)

    def complete_registration(self, registration_id, headers):
        return self._request("POST", f"/pd/registrations/{registration_id}/complete", {}, headers)

    def submit_survey(self, registration_id, payload, headers):
        return self._request("POST", f"/pd/registrations/{registration_id}/survey",
                             payload, headers)

    def get_survey(self, registration_id, headers, params=None):
        return self._request("GET", f"/pd/registrations/{registration_id}/survey",
                             headers=headers, params=params)

    # --- External workshop requests ---
    def create_workshop(self, payload, headers):
        return self._request("POST", "/pd/workshop-requests", payload, headers)

    def get_workshop(self, workshop_id, headers):
        return self._request("GET", f"/pd/workshop-requests/{workshop_id}", headers=headers)

    def list_workshops(self, headers, params=None):
        return self._request("GET", "/pd/workshop-requests", headers=headers, params=params)

    def submit_workshop(self, workshop_id, headers):
        return self._request("POST", f"/pd/workshop-requests/{workshop_id}/submit", {}, headers)

    def approve_workshop(self, workshop_id, headers):
        return self._request("POST", f"/pd/workshop-requests/{workshop_id}/approve", {}, headers)

    def reject_workshop(self, workshop_id, payload, headers):
        return self._request("POST", f"/pd/workshop-requests/{workshop_id}/reject",
                             payload, headers)

    def revise_workshop(self, workshop_id, payload, headers):
        return self._request("POST", f"/pd/workshop-requests/{workshop_id}/revise",
                             payload, headers)

    def complete_workshop(self, workshop_id, payload, headers):
        return self._request("POST", f"/pd/workshop-requests/{workshop_id}/complete",
                             payload, headers)

    def reimburse_workshop(self, workshop_id, headers):
        return self._request("POST", f"/pd/workshop-requests/{workshop_id}/reimburse",
                             {}, headers)

    def deny_reimbursement(self, workshop_id, payload, headers):
        return self._request("POST", f"/pd/workshop-requests/{workshop_id}/deny-reimbursement",
                             payload, headers)

    # --- Growth plans ---
    def create_growth_plan(self, payload, headers):
        return self._request("POST", "/pd/growth-plans", payload, headers)

    def get_growth_plan(self, plan_id, headers):
        return self._request("GET", f"/pd/growth-plans/{plan_id}", headers=headers)

    def list_growth_plans(self, headers, params=None):
        return self._request("GET", "/pd/growth-plans", headers=headers, params=params)

    def get_plan_transcript_entries(self, plan_id, headers, params=None):
        return self._request("GET", f"/pd/growth-plans/{plan_id}/transcript-entries",
                             headers=headers, params=params)

    def submit_plan(self, plan_id, headers):
        return self._request("POST", f"/pd/growth-plans/{plan_id}/submit", {}, headers)

    def approve_plan(self, plan_id, headers):
        return self._request("POST", f"/pd/growth-plans/{plan_id}/approve", {}, headers)

    def return_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/pd/growth-plans/{plan_id}/return", payload, headers)

    def close_plan(self, plan_id, headers):
        return self._request("POST", f"/pd/growth-plans/{plan_id}/close", {}, headers)

    # --- Compliance assignments ---
    def create_assignment(self, payload, headers):
        return self._request("POST", "/pd/compliance-assignments", payload, headers)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/pd/compliance-assignments/{assignment_id}",
                             headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/pd/compliance-assignments", headers=headers, params=params)

    def waive_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/pd/compliance-assignments/{assignment_id}/waive",
                             payload, headers)

    def extend_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/pd/compliance-assignments/{assignment_id}/extend",
                             payload, headers)

    # --- Audit cases ---
    def create_audit_case(self, payload, headers):
        return self._request("POST", "/pd/audit-cases", payload, headers)

    def get_audit_case(self, case_id, headers):
        return self._request("GET", f"/pd/audit-cases/{case_id}", headers=headers)

    def list_audit_cases(self, headers, params=None):
        return self._request("GET", "/pd/audit-cases", headers=headers, params=params)

    def raise_finding(self, case_id, payload, headers):
        return self._request("POST", f"/pd/audit-cases/{case_id}/raise-finding",
                             payload, headers)

    def reverse_entry(self, case_id, payload, headers):
        return self._request("POST", f"/pd/audit-cases/{case_id}/reverse-entry",
                             payload, headers)

    def resolve_case(self, case_id, headers):
        return self._request("POST", f"/pd/audit-cases/{case_id}/resolve", {}, headers)

    def close_clean_case(self, case_id, headers):
        return self._request("POST", f"/pd/audit-cases/{case_id}/close-clean", {}, headers)

    # --- Transcript entries ---
    def get_transcript_entry(self, entry_id, headers):
        return self._request("GET", f"/pd/transcript-entries/{entry_id}", headers=headers)


api_client = ApiClient()
