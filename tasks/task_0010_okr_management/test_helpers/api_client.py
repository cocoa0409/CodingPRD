"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Departments ---
    def create_department(self, payload, headers):
        return self._request("POST", "/departments", payload, headers)

    def list_departments(self, headers, params=None):
        return self._request("GET", "/departments", headers=headers, params=params)

    # --- Users ---
    def create_user(self, payload, headers):
        return self._request("POST", "/users", payload, headers)

    def list_users(self, headers, params=None):
        return self._request("GET", "/users", headers=headers, params=params)

    def get_user(self, user_id, headers):
        return self._request("GET", f"/users/{user_id}", headers=headers)

    # --- Cycles ---
    def create_cycle(self, payload, headers):
        return self._request("POST", "/cycles", payload, headers)

    def list_cycles(self, headers, params=None):
        return self._request("GET", "/cycles", headers=headers, params=params)

    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"/cycles/{cycle_id}", headers=headers)

    def open_cycle(self, cycle_id, headers, payload=None):
        return self._request("POST", f"/cycles/{cycle_id}/open", payload or {}, headers)

    def start_review_cycle(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/start-review", {}, headers)

    def lock_cycle(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/lock", {}, headers)

    def archive_cycle(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/archive", {}, headers)

    # --- Objectives ---
    def create_objective(self, payload, headers):
        return self._request("POST", "/objectives", payload, headers)

    def list_objectives(self, headers, params=None):
        return self._request("GET", "/objectives", headers=headers, params=params)

    def get_objective(self, objective_id, headers):
        return self._request("GET", f"/objectives/{objective_id}", headers=headers)

    def patch_objective(self, objective_id, payload, headers):
        return self._request("PATCH", f"/objectives/{objective_id}", payload, headers)

    def publish_objective(self, objective_id, headers):
        return self._request("POST", f"/objectives/{objective_id}/publish", {}, headers)

    def revert_objective(self, objective_id, headers):
        return self._request("POST", f"/objectives/{objective_id}/revert", {}, headers)

    def archive_objective(self, objective_id, headers):
        return self._request("POST", f"/objectives/{objective_id}/archive", {}, headers)

    def get_impact_graph(self, objective_id, headers):
        return self._request("GET", f"/objectives/{objective_id}/impact-graph", headers=headers)

    # --- Key Results ---
    def create_key_result(self, objective_id, payload, headers):
        return self._request("POST", f"/objectives/{objective_id}/key-results", payload, headers)

    def list_key_results(self, objective_id, headers, params=None):
        return self._request("GET", f"/objectives/{objective_id}/key-results", headers=headers, params=params)

    def get_key_result(self, kr_id, headers):
        return self._request("GET", f"/key-results/{kr_id}", headers=headers)

    def patch_key_result(self, kr_id, payload, headers):
        return self._request("PATCH", f"/key-results/{kr_id}", payload, headers)

    def delete_key_result(self, kr_id, headers):
        return self._request("DELETE", f"/key-results/{kr_id}", headers=headers)

    def post_progress(self, kr_id, payload, headers):
        return self._request("POST", f"/key-results/{kr_id}/progress", payload, headers)

    def list_progress(self, kr_id, headers, params=None):
        return self._request("GET", f"/key-results/{kr_id}/progress", headers=headers, params=params)

    # --- Alignment links ---
    def create_alignment_link(self, payload, headers):
        return self._request("POST", "/alignment-links", payload, headers)

    def list_alignment_links(self, headers, params=None):
        return self._request("GET", "/alignment-links", headers=headers, params=params)

    def accept_alignment_link(self, link_id, headers):
        return self._request("POST", f"/alignment-links/{link_id}/accept", {}, headers)

    def reject_alignment_link(self, link_id, payload, headers):
        return self._request("POST", f"/alignment-links/{link_id}/reject", payload, headers)

    # --- Co-ownership ---
    def add_co_owner(self, objective_id, payload, headers):
        return self._request("POST", f"/objectives/{objective_id}/co-owners", payload, headers)

    def remove_co_owner(self, objective_id, user_id, headers):
        return self._request("DELETE", f"/objectives/{objective_id}/co-owners/{user_id}", headers=headers)

    def list_co_owners(self, objective_id, headers):
        return self._request("GET", f"/objectives/{objective_id}/co-owners", headers=headers)

    # --- Reviews ---
    def get_review(self, review_id, headers):
        return self._request("GET", f"/reviews/{review_id}", headers=headers)

    def self_submit_review(self, review_id, payload, headers):
        return self._request("POST", f"/reviews/{review_id}/self-submit", payload, headers)

    def manager_submit_review(self, review_id, payload, headers):
        return self._request("POST", f"/reviews/{review_id}/manager-submit", payload, headers)

    def manager_return_review(self, review_id, headers):
        return self._request("POST", f"/reviews/{review_id}/manager-return", {}, headers)

    def calibrate_review(self, review_id, payload, headers):
        return self._request("POST", f"/reviews/{review_id}/calibrate", payload, headers)

    def calibration_return_review(self, review_id, headers):
        return self._request("POST", f"/reviews/{review_id}/calibration-return", {}, headers)

    def lock_review(self, review_id, headers):
        return self._request("POST", f"/reviews/{review_id}/lock", {}, headers)

    # --- Confidential access grants ---
    def create_access_grant(self, objective_id, payload, headers):
        return self._request("POST", f"/objectives/{objective_id}/access-grants", payload, headers)

    def revoke_access_grant(self, objective_id, user_id, headers):
        return self._request("DELETE", f"/objectives/{objective_id}/access-grants/{user_id}", headers=headers)

    def list_access_grants(self, objective_id, headers):
        return self._request("GET", f"/objectives/{objective_id}/access-grants", headers=headers)

    # --- External events ---
    def create_external_event(self, payload, headers):
        return self._request("POST", "/external-events", payload, headers)

    def list_external_events(self, headers, params=None):
        return self._request("GET", "/external-events", headers=headers, params=params)

    # --- Audit logs ---
    def list_audit_logs(self, headers, params=None):
        return self._request("GET", "/audit-logs", headers=headers, params=params)

    # --- Test-driving endpoints ---
    def advance_clock(self, seconds, headers):
        return self._request("POST", "/_clock/advance", {"seconds": seconds}, headers)

    def sweep_stale_kr_reminders(self, headers):
        return self._request("POST", "/_sweep/stale-kr-reminders", {}, headers)


api_client = ApiClient()
