"""API client: one method per endpoint defined in the PRD endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """PRD-specific endpoint methods. All methods return raw requests.Response."""

    # --- Projects ---
    def create_project(self, payload, headers):
        return self._request("POST", "/v1/projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/v1/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/v1/projects/{project_id}", headers=headers)

    def advance_project(self, project_id, headers):
        return self._request("POST", f"/v1/projects/{project_id}/advance", {}, headers)

    # --- Site surveys ---
    def create_site_survey(self, payload, headers):
        return self._request("POST", "/v1/site-surveys", payload, headers)

    def list_site_surveys(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/v1/projects/{project_id}/site-surveys", headers=headers, params=params
        )

    def submit_site_survey(self, survey_id, headers):
        return self._request("POST", f"/v1/site-surveys/{survey_id}/submit", {}, headers)

    def review_site_survey(self, survey_id, payload, headers):
        return self._request("POST", f"/v1/site-surveys/{survey_id}/review", payload, headers)

    # --- Safety plans ---
    def create_safety_plan(self, payload, headers):
        return self._request("POST", "/v1/safety-plans", payload, headers)

    def list_safety_plans(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/v1/projects/{project_id}/safety-plans", headers=headers, params=params
        )

    def activate_safety_plan(self, plan_id, headers):
        return self._request("POST", f"/v1/safety-plans/{plan_id}/activate", {}, headers)

    def suspend_safety_plan(self, plan_id, headers):
        return self._request("POST", f"/v1/safety-plans/{plan_id}/suspend", {}, headers)

    def resume_safety_plan(self, plan_id, headers):
        return self._request("POST", f"/v1/safety-plans/{plan_id}/resume", {}, headers)

    def close_safety_plan(self, plan_id, headers):
        return self._request("POST", f"/v1/safety-plans/{plan_id}/close", {}, headers)

    # --- Lockout windows ---
    def create_lockout_window(self, payload, headers):
        return self._request("POST", "/v1/lockout-windows", payload, headers)

    def list_lockout_windows(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/v1/projects/{project_id}/lockout-windows", headers=headers, params=params
        )

    def cancel_lockout_window(self, window_id, headers):
        return self._request("POST", f"/v1/lockout-windows/{window_id}/cancel", {}, headers)

    def release_lockout_window(self, window_id, headers):
        return self._request("POST", f"/v1/lockout-windows/{window_id}/release", {}, headers)

    # --- Rigging plans ---
    def create_rigging_plan(self, payload, headers):
        return self._request("POST", "/v1/rigging-plans", payload, headers)

    def list_rigging_plans(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/v1/projects/{project_id}/rigging-plans", headers=headers, params=params
        )

    def submit_rigging_plan(self, plan_id, headers):
        return self._request("POST", f"/v1/rigging-plans/{plan_id}/submit", {}, headers)

    def review_rigging_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/v1/rigging-plans/{plan_id}/review", payload, headers)

    def revise_rigging_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/v1/rigging-plans/{plan_id}/revise", payload, headers)

    # --- Lift permits ---
    def create_lift_permit(self, payload, headers):
        return self._request("POST", "/v1/lift-permits", payload, headers)

    def list_lift_permits(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/v1/projects/{project_id}/lift-permits", headers=headers, params=params
        )

    def execute_lift_permit(self, permit_id, headers):
        return self._request("POST", f"/v1/lift-permits/{permit_id}/execute", {}, headers)

    def cancel_lift_permit(self, permit_id, headers):
        return self._request("POST", f"/v1/lift-permits/{permit_id}/cancel", {}, headers)

    # --- Alignment records ---
    def create_alignment_record(self, payload, headers):
        return self._request("POST", "/v1/alignment-records", payload, headers)

    def list_alignment_records(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/v1/projects/{project_id}/alignment-records", headers=headers, params=params
        )

    def review_alignment_record(self, record_id, payload, headers):
        return self._request(
            "POST", f"/v1/alignment-records/{record_id}/review", payload, headers
        )

    # --- Commissioning checklists ---
    def create_commissioning_checklist(self, payload, headers):
        return self._request("POST", "/v1/commissioning-checklists", payload, headers)

    def list_commissioning_checklists(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"/v1/projects/{project_id}/commissioning-checklists",
            headers=headers,
            params=params,
        )

    def check_checklist_item(self, checklist_id, payload, headers):
        return self._request(
            "POST", f"/v1/commissioning-checklists/{checklist_id}/check-item", payload, headers
        )

    def submit_commissioning_checklist(self, checklist_id, headers):
        return self._request(
            "POST", f"/v1/commissioning-checklists/{checklist_id}/submit", {}, headers
        )

    def sign_off_checklist(self, checklist_id, payload, headers):
        return self._request(
            "POST", f"/v1/commissioning-checklists/{checklist_id}/sign-off", payload, headers
        )

    # --- Labor entries ---
    def create_labor_entry(self, payload, headers):
        return self._request("POST", "/v1/labor-entries", payload, headers)

    def list_labor_entries(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/v1/projects/{project_id}/labor-entries", headers=headers, params=params
        )

    def submit_labor_entry(self, entry_id, headers):
        return self._request("POST", f"/v1/labor-entries/{entry_id}/submit", {}, headers)

    def approve_labor_entry(self, entry_id, headers):
        return self._request("POST", f"/v1/labor-entries/{entry_id}/approve", {}, headers)

    def reject_labor_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/v1/labor-entries/{entry_id}/reject", payload, headers)

    # --- Invoices ---
    def create_invoice(self, payload, headers):
        return self._request("POST", "/v1/invoices", payload, headers)

    def list_invoices(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/v1/projects/{project_id}/invoices", headers=headers, params=params
        )

    # --- Test-driving logical clock ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/v1/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
