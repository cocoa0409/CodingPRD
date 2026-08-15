"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- RoleProfile ---
    def create_role_profile(self, payload, headers):
        return self._request("POST", "/api/role-profiles", payload, headers)

    def get_role_profile(self, profile_id, headers):
        return self._request("GET", f"/api/role-profiles/{profile_id}", headers=headers)

    def update_role_profile(self, profile_id, payload, headers):
        return self._request("PUT", f"/api/role-profiles/{profile_id}", payload, headers)

    def publish_role_profile(self, profile_id, headers):
        return self._request("POST", f"/api/role-profiles/{profile_id}/publish", headers=headers)

    # --- Employee ---
    def create_employee(self, payload, headers):
        return self._request("POST", "/api/employees", payload, headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/api/employees", headers=headers, params=params)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/api/employees/{employee_id}", headers=headers)

    def deactivate_employee(self, employee_id, headers):
        return self._request("POST", f"/api/employees/{employee_id}/deactivate", headers=headers)

    def list_employee_checkins(self, employee_id, headers, params=None):
        return self._request("GET", f"/api/employees/{employee_id}/check-ins", headers=headers, params=params)

    # --- NewHire ---
    def create_new_hire(self, payload, headers):
        return self._request("POST", "/api/new-hires", payload, headers)

    def get_new_hire(self, new_hire_id, headers):
        return self._request("GET", f"/api/new-hires/{new_hire_id}", headers=headers)

    # --- OnboardingCase ---
    def create_onboarding_case(self, payload, headers):
        return self._request("POST", "/api/onboarding-cases", payload, headers)

    def list_onboarding_cases(self, headers, params=None):
        return self._request("GET", "/api/onboarding-cases", headers=headers, params=params)

    def get_onboarding_case(self, case_id, headers):
        return self._request("GET", f"/api/onboarding-cases/{case_id}", headers=headers)

    def get_case_summary(self, case_id, headers):
        return self._request("GET", f"/api/onboarding-cases/{case_id}/summary", headers=headers)

    def submit_for_clearance(self, case_id, headers):
        return self._request("POST", f"/api/onboarding-cases/{case_id}/submit-for-clearance", headers=headers)

    def withdraw_case(self, case_id, headers):
        return self._request("POST", f"/api/onboarding-cases/{case_id}/withdraw", headers=headers)

    def reassign_manager(self, case_id, payload, headers):
        return self._request("POST", f"/api/onboarding-cases/{case_id}/reassign-manager", payload, headers)

    def book_orientation(self, case_id, payload, headers):
        return self._request("POST", f"/api/onboarding-cases/{case_id}/orientation-booking", payload, headers)

    def cancel_orientation_booking(self, case_id, headers):
        return self._request("POST", f"/api/onboarding-cases/{case_id}/orientation-booking/cancel", headers=headers)

    # --- Case sub-resources ---
    def list_case_tasks(self, case_id, headers, params=None):
        return self._request("GET", f"/api/onboarding-cases/{case_id}/tasks", headers=headers, params=params)

    def list_case_clearance_cases(self, case_id, headers, params=None):
        return self._request("GET", f"/api/onboarding-cases/{case_id}/clearance-cases", headers=headers, params=params)

    def list_case_provisioning_orders(self, case_id, headers, params=None):
        return self._request("GET", f"/api/onboarding-cases/{case_id}/provisioning-orders", headers=headers, params=params)

    def list_case_check_ins(self, case_id, headers, params=None):
        return self._request("GET", f"/api/onboarding-cases/{case_id}/check-ins", headers=headers, params=params)

    def list_case_training_assignments(self, case_id, headers, params=None):
        return self._request("GET", f"/api/onboarding-cases/{case_id}/training-assignments", headers=headers, params=params)

    def list_case_probation_cycles(self, case_id, headers, params=None):
        return self._request("GET", f"/api/onboarding-cases/{case_id}/probation-cycles", headers=headers, params=params)

    def list_case_payroll_handoffs(self, case_id, headers, params=None):
        return self._request("GET", f"/api/onboarding-cases/{case_id}/payroll-handoffs", headers=headers, params=params)

    def list_case_surveys(self, case_id, headers, params=None):
        return self._request("GET", f"/api/onboarding-cases/{case_id}/surveys", headers=headers, params=params)

    # --- OnboardingTask actions ---
    def submit_task(self, task_id, payload, headers):
        return self._request("POST", f"/api/onboarding-tasks/{task_id}/submit", payload, headers)

    def review_task(self, task_id, payload, headers):
        return self._request("POST", f"/api/onboarding-tasks/{task_id}/review", payload, headers)

    def waive_task(self, task_id, headers):
        return self._request("POST", f"/api/onboarding-tasks/{task_id}/waive", headers=headers)

    # --- ClearanceCase actions ---
    def record_clearance_result(self, clearance_id, payload, headers):
        return self._request("POST", f"/api/clearance-cases/{clearance_id}/record-result", payload, headers)

    def adjudicate_clearance(self, clearance_id, payload, headers):
        return self._request("POST", f"/api/clearance-cases/{clearance_id}/adjudicate", payload, headers)

    # --- Provisioning ---
    def get_provisioning_order(self, order_id, headers):
        return self._request("GET", f"/api/provisioning-orders/{order_id}", headers=headers)

    def submit_provisioning_order(self, order_id, headers):
        return self._request("POST", f"/api/provisioning-orders/{order_id}/submit", headers=headers)

    def list_provisioning_items(self, order_id, headers, params=None):
        return self._request("GET", f"/api/provisioning-orders/{order_id}/items", headers=headers, params=params)

    def transition_provisioning_item(self, item_id, payload, headers):
        return self._request("POST", f"/api/provisioning-items/{item_id}/transition", payload, headers)

    # --- OrientationSession ---
    def create_orientation_session(self, payload, headers):
        return self._request("POST", "/api/orientation-sessions", payload, headers)

    def list_orientation_sessions(self, headers, params=None):
        return self._request("GET", "/api/orientation-sessions", headers=headers, params=params)

    def cancel_orientation_session(self, session_id, headers):
        return self._request("POST", f"/api/orientation-sessions/{session_id}/cancel", headers=headers)

    def mark_attendance(self, session_id, payload, headers):
        return self._request("POST", f"/api/orientation-sessions/{session_id}/attendance", payload, headers)

    # --- CheckIn actions ---
    def complete_check_in(self, checkin_id, payload, headers):
        return self._request("POST", f"/api/check-ins/{checkin_id}/complete", payload, headers)

    def reschedule_check_in(self, checkin_id, payload, headers):
        return self._request("POST", f"/api/check-ins/{checkin_id}/reschedule", payload, headers)

    # --- TrainingAssignment actions ---
    def complete_training(self, training_id, payload, headers):
        return self._request("POST", f"/api/training-assignments/{training_id}/complete", payload, headers)

    # --- ProbationCycle actions ---
    def evaluate_probation_cycle(self, cycle_id, payload, headers):
        return self._request("POST", f"/api/probation-cycles/{cycle_id}/evaluate", payload, headers)

    # --- PayrollHandoff ---
    def create_payroll_handoff(self, case_id, payload, headers):
        return self._request("POST", f"/api/onboarding-cases/{case_id}/payroll-handoffs", payload, headers)

    def get_payroll_handoff(self, handoff_id, headers):
        return self._request("GET", f"/api/payroll-handoffs/{handoff_id}", headers=headers)

    def transmit_payroll_handoff(self, handoff_id, headers):
        return self._request("POST", f"/api/payroll-handoffs/{handoff_id}/transmit", headers=headers)

    def acknowledge_payroll_handoff(self, handoff_id, headers):
        return self._request("POST", f"/api/payroll-handoffs/{handoff_id}/acknowledge", headers=headers)

    def reject_payroll_handoff(self, handoff_id, payload, headers):
        return self._request("POST", f"/api/payroll-handoffs/{handoff_id}/reject", payload, headers)

    def withdraw_payroll_handoff(self, handoff_id, headers):
        return self._request("POST", f"/api/payroll-handoffs/{handoff_id}/withdraw", headers=headers)

    # --- Survey ---
    def submit_survey(self, survey_id, payload, headers):
        return self._request("POST", f"/api/surveys/{survey_id}/submit", payload, headers)

    # --- Test-driving clock ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
