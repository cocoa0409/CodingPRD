"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock (test-driving) ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers=headers)

    # ---- Customer ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers=headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ---- Project ----
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers=headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/projects", headers=headers, params=params)

    def cancel_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/cancel", {}, headers=headers)

    def close_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/close", {}, headers=headers)

    # ---- Measure ----
    def create_measure(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/measures", payload, headers=headers)

    def list_measures(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/measures", headers=headers, params=params)

    def get_measure(self, measure_id, headers):
        return self._request("GET", f"/measures/{measure_id}", headers=headers)

    def complete_measure(self, project_id, measure_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/measures/{measure_id}/complete",
                             payload, headers=headers)

    def cancel_measure(self, project_id, measure_id, headers):
        return self._request("POST", f"/projects/{project_id}/measures/{measure_id}/cancel",
                             {}, headers=headers)

    # ---- Quote ----
    def create_quote(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/quotes", payload, headers=headers)

    def list_project_quotes(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/quotes", headers=headers, params=params)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def issue_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/issue", {}, headers=headers)

    def reopen_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/reopen", {}, headers=headers)

    def approve_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/approve", payload, headers=headers)

    def decline_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/decline", {}, headers=headers)

    # ---- AddOn ----
    def create_addon(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/addons", payload, headers=headers)

    def list_addons(self, quote_id, headers, params=None):
        return self._request("GET", f"/quotes/{quote_id}/addons", headers=headers, params=params)

    def approve_addon(self, addon_id, headers):
        return self._request("POST", f"/addons/{addon_id}/approve", {}, headers=headers)

    def remove_addon(self, addon_id, headers):
        return self._request("POST", f"/addons/{addon_id}/remove", {}, headers=headers)

    # ---- ChangeOrder ----
    def create_change_order(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/change-orders", payload, headers=headers)

    def list_change_orders(self, quote_id, headers, params=None):
        return self._request("GET", f"/quotes/{quote_id}/change-orders", headers=headers, params=params)

    def get_change_order(self, change_order_id, headers):
        return self._request("GET", f"/change-orders/{change_order_id}", headers=headers)

    def accept_change_order(self, change_order_id, payload, headers):
        return self._request("POST", f"/change-orders/{change_order_id}/accept", payload, headers=headers)

    def reject_change_order(self, change_order_id, headers):
        return self._request("POST", f"/change-orders/{change_order_id}/reject", {}, headers=headers)

    # ---- MaterialOrder ----
    def create_material_order(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/material-orders", payload, headers=headers)

    def list_project_material_orders(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/material-orders", headers=headers, params=params)

    def get_material_order(self, material_order_id, headers):
        return self._request("GET", f"/material-orders/{material_order_id}", headers=headers)

    def list_material_orders(self, headers, params=None):
        return self._request("GET", "/material-orders", headers=headers, params=params)

    def mark_ready_material_order(self, material_order_id, headers):
        return self._request("POST", f"/material-orders/{material_order_id}/mark-ready", {}, headers=headers)

    def receive_material_order(self, material_order_id, headers):
        return self._request("POST", f"/material-orders/{material_order_id}/receive", {}, headers=headers)

    def cancel_material_order(self, material_order_id, headers):
        return self._request("POST", f"/material-orders/{material_order_id}/cancel", {}, headers=headers)

    # ---- Crew ----
    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers=headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/crews/{crew_id}", headers=headers)

    def list_crews(self, headers, params=None):
        return self._request("GET", "/crews", headers=headers, params=params)

    # ---- InstallJob ----
    def create_install_job(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/install-jobs", payload, headers=headers)

    def list_project_install_jobs(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/install-jobs", headers=headers, params=params)

    def get_install_job(self, install_job_id, headers):
        return self._request("GET", f"/install-jobs/{install_job_id}", headers=headers)

    def list_install_jobs(self, headers, params=None):
        return self._request("GET", "/install-jobs", headers=headers, params=params)

    def start_install_job(self, install_job_id, headers):
        return self._request("POST", f"/install-jobs/{install_job_id}/start", {}, headers=headers)

    def complete_install_job(self, install_job_id, headers):
        return self._request("POST", f"/install-jobs/{install_job_id}/complete", {}, headers=headers)

    def cancel_install_job(self, install_job_id, headers):
        return self._request("POST", f"/install-jobs/{install_job_id}/cancel", {}, headers=headers)

    # ---- WarrantyClaim ----
    def create_warranty_claim(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/warranty-claims", payload, headers=headers)

    def list_warranty_claims(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/warranty-claims", headers=headers, params=params)

    def get_warranty_claim(self, warranty_claim_id, headers):
        return self._request("GET", f"/warranty-claims/{warranty_claim_id}", headers=headers)

    def adjudicate_warranty_claim(self, warranty_claim_id, payload, headers):
        return self._request("POST", f"/warranty-claims/{warranty_claim_id}/adjudicate", payload, headers=headers)

    def resolve_warranty_claim(self, warranty_claim_id, headers):
        return self._request("POST", f"/warranty-claims/{warranty_claim_id}/resolve", {}, headers=headers)

    # ---- FinancingApplication ----
    def create_financing_application(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/financing-applications", payload, headers=headers)

    def list_project_financing_applications(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/financing-applications", headers=headers, params=params)

    def get_financing_application(self, financing_application_id, headers):
        return self._request("GET", f"/financing-applications/{financing_application_id}", headers=headers)

    def list_financing_applications(self, headers, params=None):
        return self._request("GET", "/financing-applications", headers=headers, params=params)

    def approve_financing_application(self, financing_application_id, headers):
        return self._request("POST", f"/financing-applications/{financing_application_id}/approve", {}, headers=headers)

    def decline_financing_application(self, financing_application_id, headers):
        return self._request("POST", f"/financing-applications/{financing_application_id}/decline", {}, headers=headers)


api_client = ApiClient()
