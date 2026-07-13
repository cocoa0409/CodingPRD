"""API client: one method per endpoint defined in the Monument & Headstone PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Config / roots (Admin) ---
    def create_cemetery(self, payload, headers):
        return self._request("POST", "/memorials/cemeteries", payload, headers)

    def create_customer(self, payload, headers):
        return self._request("POST", "/memorials/customers", payload, headers)

    def create_workshop(self, payload, headers):
        return self._request("POST", "/memorials/workshops", payload, headers)

    def create_crew(self, payload, headers):
        return self._request("POST", "/memorials/crews", payload, headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- MonumentOrder ---
    def create_order(self, payload, headers):
        return self._request("POST", "/memorials/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/memorials/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/memorials/orders", headers=headers, params=params)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/memorials/orders/{order_id}/cancel", {}, headers)

    # --- DesignProof ---
    def create_design_proof(self, payload, headers):
        return self._request("POST", "/memorials/design-proofs", payload, headers)

    def list_order_design_proofs(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/memorials/orders/{order_id}/design-proofs", headers=headers, params=params
        )

    def submit_design_proof(self, proof_id, headers):
        return self._request("POST", f"/memorials/design-proofs/{proof_id}/submit", {}, headers)

    def approve_design_proof(self, proof_id, headers):
        return self._request("POST", f"/memorials/design-proofs/{proof_id}/approve", {}, headers)

    def request_changes_design_proof(self, proof_id, headers):
        return self._request(
            "POST", f"/memorials/design-proofs/{proof_id}/request-changes", {}, headers
        )

    # --- Payment ---
    def create_payment(self, payload, headers):
        return self._request("POST", "/memorials/payments", payload, headers)

    def list_order_payments(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/memorials/orders/{order_id}/payments", headers=headers, params=params
        )

    # --- FabricationJob ---
    def create_fabrication_job(self, payload, headers):
        return self._request("POST", "/memorials/fabrication-jobs", payload, headers)

    def get_fabrication_job(self, job_id, headers):
        return self._request("GET", f"/memorials/fabrication-jobs/{job_id}", headers=headers)

    def list_fabrication_jobs(self, headers, params=None):
        return self._request("GET", "/memorials/fabrication-jobs", headers=headers, params=params)

    def complete_fabrication_job(self, job_id, headers):
        return self._request(
            "POST", f"/memorials/fabrication-jobs/{job_id}/complete", {}, headers
        )

    # --- CemeteryPermit ---
    def create_permit(self, payload, headers):
        return self._request("POST", "/memorials/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/memorials/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/memorials/permits", headers=headers, params=params)

    def issue_permit(self, permit_id, headers):
        return self._request("POST", f"/memorials/permits/{permit_id}/issue", {}, headers)

    # --- Installation ---
    def create_installation(self, payload, headers):
        return self._request("POST", "/memorials/installations", payload, headers)

    def get_installation(self, installation_id, headers):
        return self._request("GET", f"/memorials/installations/{installation_id}", headers=headers)

    def list_installations(self, headers, params=None):
        return self._request("GET", "/memorials/installations", headers=headers, params=params)

    def complete_installation(self, installation_id, headers):
        return self._request(
            "POST", f"/memorials/installations/{installation_id}/complete", {}, headers
        )

    # --- RestorationJob ---
    def create_restoration(self, payload, headers):
        return self._request("POST", "/memorials/restorations", payload, headers)

    def get_restoration(self, restoration_id, headers):
        return self._request("GET", f"/memorials/restorations/{restoration_id}", headers=headers)

    def list_restorations(self, headers, params=None):
        return self._request("GET", "/memorials/restorations", headers=headers, params=params)

    def assess_restoration(self, restoration_id, payload, headers):
        return self._request(
            "POST", f"/memorials/restorations/{restoration_id}/assess", payload, headers
        )


api_client = ApiClient()
