"""API client: one method per endpoint defined in the PRD (all under /compliance)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Regulators ---
    def create_regulator(self, payload, headers):
        return self._request("POST", "/compliance/regulators", payload, headers)

    def get_regulator(self, regulator_id, headers):
        return self._request("GET", f"/compliance/regulators/{regulator_id}", headers=headers)

    def update_regulator(self, regulator_id, payload, headers):
        return self._request("PATCH", f"/compliance/regulators/{regulator_id}", payload, headers)

    # --- Roles & requirements ---
    def create_role(self, payload, headers):
        return self._request("POST", "/compliance/roles", payload, headers)

    def get_role(self, role_id, headers):
        return self._request("GET", f"/compliance/roles/{role_id}", headers=headers)

    def retire_role(self, role_id, headers):
        return self._request("POST", f"/compliance/roles/{role_id}/retire", {}, headers)

    def list_role_employees(self, role_id, headers):
        return self._request("GET", f"/compliance/roles/{role_id}/employees", headers=headers)

    def create_requirement(self, role_id, payload, headers):
        return self._request("POST", f"/compliance/roles/{role_id}/requirements", payload, headers)

    def list_role_requirements(self, role_id, headers):
        return self._request("GET", f"/compliance/roles/{role_id}/requirements", headers=headers)

    def retire_requirement(self, requirement_id, headers):
        return self._request("POST", f"/compliance/requirements/{requirement_id}/retire", {}, headers)

    def list_curriculum_requirements(self, curriculum_id, headers):
        return self._request("GET", f"/compliance/curricula/{curriculum_id}/requirements", headers=headers)

    # --- Curricula & versions ---
    def create_curriculum(self, payload, headers):
        return self._request("POST", "/compliance/curricula", payload, headers)

    def list_curricula(self, headers, params=None):
        return self._request("GET", "/compliance/curricula", headers=headers, params=params)

    def get_curriculum(self, curriculum_id, headers):
        return self._request("GET", f"/compliance/curricula/{curriculum_id}", headers=headers)

    def update_curriculum(self, curriculum_id, payload, headers):
        return self._request("PATCH", f"/compliance/curricula/{curriculum_id}", payload, headers)

    def create_curriculum_version(self, curriculum_id, payload, headers):
        return self._request("POST", f"/compliance/curricula/{curriculum_id}/versions", payload, headers)

    def list_curriculum_versions(self, curriculum_id, headers):
        return self._request("GET", f"/compliance/curricula/{curriculum_id}/versions", headers=headers)

    def get_curriculum_effectiveness(self, curriculum_id, headers):
        return self._request("GET", f"/compliance/curricula/{curriculum_id}/effectiveness", headers=headers)

    # --- Employees, leaves, role changes ---
    def create_employee(self, payload, headers):
        return self._request("POST", "/compliance/employees", payload, headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/compliance/employees", headers=headers, params=params)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/compliance/employees/{employee_id}", headers=headers)

    def terminate_employee(self, employee_id, headers):
        return self._request("POST", f"/compliance/employees/{employee_id}/terminate", {}, headers)

    def create_leave(self, employee_id, payload, headers):
        return self._request("POST", f"/compliance/employees/{employee_id}/leaves", payload, headers)

    def list_leaves(self, employee_id, headers):
        return self._request("GET", f"/compliance/employees/{employee_id}/leaves", headers=headers)

    def create_role_change(self, employee_id, payload, headers):
        return self._request("POST", f"/compliance/employees/{employee_id}/role-changes", payload, headers)

    def list_role_changes(self, headers, params=None):
        return self._request("GET", "/compliance/role-changes", headers=headers, params=params)

    def get_role_change(self, role_change_id, headers):
        return self._request("GET", f"/compliance/role-changes/{role_change_id}", headers=headers)

    def cancel_role_change(self, role_change_id, headers):
        return self._request("POST", f"/compliance/role-changes/{role_change_id}/cancel", {}, headers)

    def reverse_role_change(self, role_change_id, headers):
        return self._request("POST", f"/compliance/role-changes/{role_change_id}/reverse", {}, headers)

    # --- Assignments & extensions ---
    def create_manual_assignment(self, employee_id, payload, headers):
        return self._request("POST", f"/compliance/employees/{employee_id}/assignments", payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/compliance/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/compliance/assignments/{assignment_id}", headers=headers)

    def start_assignment(self, assignment_id, headers):
        return self._request("POST", f"/compliance/assignments/{assignment_id}/start", {}, headers)

    def grant_extension(self, assignment_id, payload, headers):
        return self._request("POST", f"/compliance/assignments/{assignment_id}/extensions", payload, headers)

    def revoke_extension(self, assignment_id, payload, headers):
        return self._request("POST", f"/compliance/assignments/{assignment_id}/extensions/revoke", payload, headers)

    def cancel_assignment(self, assignment_id, headers):
        return self._request("POST", f"/compliance/assignments/{assignment_id}/cancel", {}, headers)

    # --- Completion records ---
    def submit_completion(self, assignment_id, payload, headers):
        return self._request("POST", f"/compliance/assignments/{assignment_id}/completions", payload, headers)

    def list_completions(self, assignment_id, headers):
        return self._request("GET", f"/compliance/assignments/{assignment_id}/completions", headers=headers)

    def accept_completion(self, completion_id, payload, headers):
        return self._request("POST", f"/compliance/completions/{completion_id}/accept", payload, headers)

    def reject_completion(self, completion_id, payload, headers):
        return self._request("POST", f"/compliance/completions/{completion_id}/reject", payload, headers)

    def void_completion(self, completion_id, payload, headers):
        return self._request("POST", f"/compliance/completions/{completion_id}/void", payload, headers)

    # --- Escalations ---
    def list_assignment_escalations(self, assignment_id, headers):
        return self._request("GET", f"/compliance/assignments/{assignment_id}/escalations", headers=headers)

    def list_employee_escalations(self, employee_id, headers):
        return self._request("GET", f"/compliance/employees/{employee_id}/escalations", headers=headers)

    def acknowledge_escalation(self, notice_id, headers):
        return self._request("POST", f"/compliance/escalations/{notice_id}/acknowledge", {}, headers)

    # --- Campaigns, attestations, exceptions ---
    def create_campaign(self, payload, headers):
        return self._request("POST", "/compliance/campaigns", payload, headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", "/compliance/campaigns", headers=headers, params=params)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/compliance/campaigns/{campaign_id}", headers=headers)

    def open_campaign(self, campaign_id, headers):
        return self._request("POST", f"/compliance/campaigns/{campaign_id}/open", {}, headers)

    def close_campaign(self, campaign_id, headers):
        return self._request("POST", f"/compliance/campaigns/{campaign_id}/close", {}, headers)

    def finalize_campaign(self, campaign_id, headers):
        return self._request("POST", f"/compliance/campaigns/{campaign_id}/finalize", {}, headers)

    def list_campaign_attestations(self, campaign_id, headers):
        return self._request("GET", f"/compliance/campaigns/{campaign_id}/attestations", headers=headers)

    def list_employee_attestations(self, employee_id, headers):
        return self._request("GET", f"/compliance/employees/{employee_id}/attestations", headers=headers)

    def get_attestation(self, attestation_id, headers):
        return self._request("GET", f"/compliance/attestations/{attestation_id}", headers=headers)

    def attest(self, attestation_id, headers):
        return self._request("POST", f"/compliance/attestations/{attestation_id}/attest", {}, headers)

    def request_exception(self, attestation_id, payload, headers):
        return self._request("POST", f"/compliance/attestations/{attestation_id}/exceptions", payload, headers)

    def list_attestation_exceptions(self, attestation_id, headers):
        return self._request("GET", f"/compliance/attestations/{attestation_id}/exceptions", headers=headers)

    def list_requested_exceptions(self, employee_id, headers):
        return self._request("GET", f"/compliance/employees/{employee_id}/requested-exceptions", headers=headers)

    def approve_exception(self, exception_id, headers):
        return self._request("POST", f"/compliance/exceptions/{exception_id}/approve", {}, headers)

    def deny_exception(self, exception_id, payload, headers):
        return self._request("POST", f"/compliance/exceptions/{exception_id}/deny", payload, headers)

    # --- Audit reports ---
    def create_audit_report(self, payload, headers):
        return self._request("POST", "/compliance/audit-reports", payload, headers)

    def get_audit_report(self, report_id, headers):
        return self._request("GET", f"/compliance/audit-reports/{report_id}", headers=headers)

    # --- Test-driving endpoints ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/compliance/_clock/set_current_utc", payload, headers)

    def run_sweep(self, headers):
        return self._request("POST", "/compliance/_sweeps/run", {}, headers)


api_client = ApiClient()
