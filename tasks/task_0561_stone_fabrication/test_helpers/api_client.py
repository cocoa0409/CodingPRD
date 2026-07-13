"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- config / inventory ---
    def create_bay(self, payload, headers):
        return self._request("POST", "/bays", payload, headers=headers)

    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers=headers)

    def create_slab(self, payload, headers):
        return self._request("POST", "/slabs", payload, headers=headers)

    def get_slab(self, slab_id, headers):
        return self._request("GET", f"/slabs/{slab_id}", headers=headers)

    def list_slab_remnants(self, slab_id, headers, params=None):
        return self._request("GET", f"/slabs/{slab_id}/remnants", headers=headers, params=params)

    # --- projects ---
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers=headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    # --- quotes ---
    def create_quote(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/quotes", payload, headers=headers)

    def list_quotes(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/quotes", headers=headers, params=params)

    # --- payments ---
    def create_payment(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/payments", payload, headers=headers)

    def refund_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/refund", headers=headers)

    def list_payments(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/payments", headers=headers, params=params)

    # --- change orders ---
    def create_change_order(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/change-orders", payload, headers=headers)

    def approve_change_order(self, change_order_id, headers):
        return self._request("POST", f"/change-orders/{change_order_id}/approve", headers=headers)

    def list_change_orders(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/change-orders", headers=headers, params=params)

    # --- templates + cutouts ---
    def create_template(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/templates", payload, headers=headers)

    def list_templates(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/templates", headers=headers, params=params)

    def get_template(self, template_id, headers):
        return self._request("GET", f"/templates/{template_id}", headers=headers)

    def create_cutout(self, template_id, payload, headers):
        return self._request("POST", f"/templates/{template_id}/cutouts", payload, headers=headers)

    def list_cutouts(self, template_id, headers, params=None):
        return self._request("GET", f"/templates/{template_id}/cutouts", headers=headers, params=params)

    def approve_template(self, template_id, headers):
        return self._request("POST", f"/templates/{template_id}/approve", headers=headers)

    # --- fabrication ---
    def create_fabrication_order(self, payload, headers):
        return self._request("POST", "/fabrication-orders", payload, headers=headers)

    def get_fabrication_order(self, fab_order_id, headers):
        return self._request("GET", f"/fabrication-orders/{fab_order_id}", headers=headers)

    def list_fabrication_orders(self, headers, params=None):
        return self._request("GET", "/fabrication-orders", headers=headers, params=params)

    def start_cut(self, fab_order_id, headers):
        return self._request("POST", f"/fabrication-orders/{fab_order_id}/start-cut", headers=headers)

    def qc_fabrication_order(self, fab_order_id, payload, headers):
        return self._request("POST", f"/fabrication-orders/{fab_order_id}/qc", payload, headers=headers)

    def complete_fabrication_order(self, fab_order_id, headers):
        return self._request("POST", f"/fabrication-orders/{fab_order_id}/complete", headers=headers)

    def cancel_fabrication_order(self, fab_order_id, headers):
        return self._request("POST", f"/fabrication-orders/{fab_order_id}/cancel", headers=headers)

    # --- install ---
    def create_install_job(self, payload, headers):
        return self._request("POST", "/install-jobs", payload, headers=headers)

    def get_install_job(self, install_job_id, headers):
        return self._request("GET", f"/install-jobs/{install_job_id}", headers=headers)

    def list_install_jobs(self, headers, params=None):
        return self._request("GET", "/install-jobs", headers=headers, params=params)

    def start_install(self, install_job_id, headers):
        return self._request("POST", f"/install-jobs/{install_job_id}/start", headers=headers)

    def complete_install(self, install_job_id, headers):
        return self._request("POST", f"/install-jobs/{install_job_id}/complete", headers=headers)

    # --- warranty ---
    def create_warranty_claim(self, install_job_id, payload, headers):
        return self._request("POST", f"/install-jobs/{install_job_id}/warranty-claims", payload, headers=headers)

    def list_warranty_claims(self, install_job_id, headers, params=None):
        return self._request("GET", f"/install-jobs/{install_job_id}/warranty-claims", headers=headers, params=params)

    def resolve_warranty_claim(self, warranty_claim_id, payload, headers):
        return self._request("POST", f"/warranty-claims/{warranty_claim_id}/resolve", payload, headers=headers)

    # --- test-driving clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers=headers)


api_client = ApiClient()
