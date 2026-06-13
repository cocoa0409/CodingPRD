"""API client: one method per endpoint defined in the PRD (Junk Removal & Hauling)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- PricingPolicy -----
    def create_pricing_policy(self, payload, headers):
        return self._request("POST", "/pricing-policies", payload, headers)

    def get_pricing_policy(self, policy_id, headers):
        return self._request("GET", f"/pricing-policies/{policy_id}", headers=headers)

    # ----- Customer -----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customer_haul_jobs(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/haul-jobs", headers=headers, params=params)

    def list_customer_invoices(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/invoices", headers=headers, params=params)

    # ----- Crew -----
    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/crews/{crew_id}", headers=headers)

    def list_crew_dispatches(self, crew_id, headers, params=None):
        return self._request("GET", f"/crews/{crew_id}/dispatches", headers=headers, params=params)

    def set_crew_status(self, crew_id, payload, headers):
        return self._request("POST", f"/crews/{crew_id}/status", payload, headers)

    # ----- Truck -----
    def create_truck(self, payload, headers):
        return self._request("POST", "/trucks", payload, headers)

    def get_truck(self, truck_id, headers):
        return self._request("GET", f"/trucks/{truck_id}", headers=headers)

    def list_truck_dispatches(self, truck_id, headers, params=None):
        return self._request("GET", f"/trucks/{truck_id}/dispatches", headers=headers, params=params)

    def set_truck_status(self, truck_id, payload, headers):
        return self._request("POST", f"/trucks/{truck_id}/status", payload, headers)

    # ----- HaulJob -----
    def create_haul_job(self, payload, headers):
        return self._request("POST", "/haul-jobs", payload, headers)

    def list_haul_jobs(self, headers, params=None):
        return self._request("GET", "/haul-jobs", headers=headers, params=params)

    def get_haul_job(self, job_id, headers):
        return self._request("GET", f"/haul-jobs/{job_id}", headers=headers)

    def add_job_item(self, job_id, payload, headers):
        return self._request("POST", f"/haul-jobs/{job_id}/items", payload, headers)

    def list_job_items(self, job_id, headers, params=None):
        return self._request("GET", f"/haul-jobs/{job_id}/items", headers=headers, params=params)

    def submit_photo_estimate(self, job_id, payload, headers):
        return self._request("POST", f"/haul-jobs/{job_id}/photo-estimates", payload, headers)

    def list_photo_estimates(self, job_id, headers, params=None):
        return self._request("GET", f"/haul-jobs/{job_id}/photo-estimates", headers=headers, params=params)

    def accept_photo_estimate(self, job_id, estimate_id, headers):
        return self._request("POST", f"/haul-jobs/{job_id}/photo-estimates/{estimate_id}/accept", {}, headers)

    def revise_haul_job(self, job_id, payload, headers):
        return self._request("POST", f"/haul-jobs/{job_id}/revise", payload, headers)

    def arrive_haul_job(self, job_id, headers):
        return self._request("POST", f"/haul-jobs/{job_id}/arrive", {}, headers)

    def load_haul_job(self, job_id, payload, headers):
        return self._request("POST", f"/haul-jobs/{job_id}/load", payload, headers)

    def complete_haul_job(self, job_id, headers):
        return self._request("POST", f"/haul-jobs/{job_id}/complete", {}, headers)

    def cancel_haul_job(self, job_id, headers):
        return self._request("POST", f"/haul-jobs/{job_id}/cancel", {}, headers)

    def list_diversions(self, job_id, headers, params=None):
        return self._request("GET", f"/haul-jobs/{job_id}/diversions", headers=headers, params=params)

    def record_diversion(self, job_id, payload, headers):
        return self._request("POST", f"/haul-jobs/{job_id}/diversions", payload, headers)

    def list_dump_tickets(self, job_id, headers, params=None):
        return self._request("GET", f"/haul-jobs/{job_id}/dump-tickets", headers=headers, params=params)

    def record_dump_ticket(self, job_id, payload, headers):
        return self._request("POST", f"/haul-jobs/{job_id}/dump-tickets", payload, headers)

    def list_job_invoices(self, job_id, headers, params=None):
        return self._request("GET", f"/haul-jobs/{job_id}/invoices", headers=headers, params=params)

    # ----- Dispatch -----
    def create_dispatch(self, payload, headers):
        return self._request("POST", "/dispatches", payload, headers)

    def list_dispatches(self, headers, params=None):
        return self._request("GET", "/dispatches", headers=headers, params=params)

    def get_dispatch(self, dispatch_id, headers):
        return self._request("GET", f"/dispatches/{dispatch_id}", headers=headers)

    def activate_dispatch(self, dispatch_id, headers):
        return self._request("POST", f"/dispatches/{dispatch_id}/activate", {}, headers)

    # ----- Invoice -----
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def settle_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/settle", {}, headers)

    def dispute_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/dispute", {}, headers)

    def resolve_dispute(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/resolve-dispute", {}, headers)

    # ----- Test-driving clock -----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
