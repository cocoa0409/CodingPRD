"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def _request(self, method, path, payload=None, headers=None, params=None):
        # per-test-server isolation restarts the server before every test;
        # forcing Connection: close prevents the session-scoped client from
        # reusing a stale keep-alive connection to the previous server
        # process (RemoteDisconnected flakes on the first request of a test).
        hdrs = dict(headers or {})
        hdrs.setdefault("Connection", "close")
        return super()._request(method, path, payload, hdrs, params)

    # --- Customer ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/crating/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/crating/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/crating/customers", headers=headers, params=params)

    def patch_customer(self, customer_id, payload, headers):
        return self._request("PATCH", f"/crating/customers/{customer_id}", payload, headers)

    def suspend_customer(self, customer_id, headers):
        return self._request("POST", f"/crating/customers/{customer_id}/suspend", headers=headers)

    def reinstate_customer(self, customer_id, headers):
        return self._request("POST", f"/crating/customers/{customer_id}/reinstate", headers=headers)

    # --- PackingJob ---
    def create_packing_job(self, payload, headers):
        return self._request("POST", "/crating/packing-jobs", payload, headers)

    def get_packing_job(self, job_id, headers):
        return self._request("GET", f"/crating/packing-jobs/{job_id}", headers=headers)

    def list_packing_jobs(self, headers, params=None):
        return self._request("GET", "/crating/packing-jobs", headers=headers, params=params)

    def patch_packing_job(self, job_id, payload, headers):
        return self._request("PATCH", f"/crating/packing-jobs/{job_id}", payload, headers)

    def accept_quote(self, job_id, headers):
        return self._request("POST", f"/crating/packing-jobs/{job_id}/accept-quote", headers=headers)

    def start_packing(self, job_id, headers):
        return self._request("POST", f"/crating/packing-jobs/{job_id}/start-packing", headers=headers)

    def ship_job(self, job_id, headers):
        return self._request("POST", f"/crating/packing-jobs/{job_id}/ship", headers=headers)

    def deliver_job(self, job_id, headers):
        return self._request("POST", f"/crating/packing-jobs/{job_id}/deliver", headers=headers)

    def close_job(self, job_id, headers):
        return self._request("POST", f"/crating/packing-jobs/{job_id}/close", headers=headers)

    def cancel_job(self, job_id, headers):
        return self._request("POST", f"/crating/packing-jobs/{job_id}/cancel", headers=headers)

    def get_quote(self, job_id, headers):
        return self._request("GET", f"/crating/packing-jobs/{job_id}/quote", headers=headers)

    # --- Item ---
    def create_item(self, job_id, payload, headers):
        return self._request("POST", f"/crating/packing-jobs/{job_id}/items", payload, headers)

    def get_item(self, item_id, headers):
        return self._request("GET", f"/crating/items/{item_id}", headers=headers)

    def list_items(self, headers, params=None):
        return self._request("GET", "/crating/items", headers=headers, params=params)

    def patch_item(self, item_id, payload, headers):
        return self._request("PATCH", f"/crating/items/{item_id}", payload, headers)

    # --- CrateDesign ---
    def create_design(self, item_id, payload, headers):
        return self._request("POST", f"/crating/items/{item_id}/designs", payload, headers)

    def get_design(self, design_id, headers):
        return self._request("GET", f"/crating/designs/{design_id}", headers=headers)

    def list_designs(self, headers, params=None):
        return self._request("GET", "/crating/designs", headers=headers, params=params)

    def submit_design(self, design_id, headers):
        return self._request("POST", f"/crating/designs/{design_id}/submit", headers=headers)

    def approve_design(self, design_id, payload, headers):
        return self._request("POST", f"/crating/designs/{design_id}/approve", payload, headers)

    def reject_design(self, design_id, payload, headers):
        return self._request("POST", f"/crating/designs/{design_id}/reject", payload, headers)

    def revise_design(self, design_id, headers):
        return self._request("POST", f"/crating/designs/{design_id}/revise", headers=headers)

    # --- WoodBatch ---
    def create_wood_batch(self, payload, headers):
        return self._request("POST", "/crating/wood-batches", payload, headers)

    def get_wood_batch(self, batch_id, headers):
        return self._request("GET", f"/crating/wood-batches/{batch_id}", headers=headers)

    def list_wood_batches(self, headers, params=None):
        return self._request("GET", "/crating/wood-batches", headers=headers, params=params)

    def suspend_wood_batch(self, batch_id, headers):
        return self._request("POST", f"/crating/wood-batches/{batch_id}/suspend", headers=headers)

    def reinstate_wood_batch(self, batch_id, headers):
        return self._request("POST", f"/crating/wood-batches/{batch_id}/reinstate", headers=headers)

    # --- Crate ---
    def create_crate(self, item_id, payload, headers):
        return self._request("POST", f"/crating/items/{item_id}/crates", payload, headers)

    def get_crate(self, crate_id, headers):
        return self._request("GET", f"/crating/crates/{crate_id}", headers=headers)

    def list_crates(self, headers, params=None):
        return self._request("GET", "/crating/crates", headers=headers, params=params)

    def build_crate(self, crate_id, headers):
        return self._request("POST", f"/crating/crates/{crate_id}/build", headers=headers)

    def pack_crate(self, crate_id, payload, headers):
        return self._request("POST", f"/crating/crates/{crate_id}/pack", payload, headers)

    def seal_crate(self, crate_id, headers):
        return self._request("POST", f"/crating/crates/{crate_id}/seal", headers=headers)

    def reopen_crate(self, crate_id, headers):
        return self._request("POST", f"/crating/crates/{crate_id}/reopen", headers=headers)

    # --- HazmatDeclaration ---
    def create_hazmat_declaration(self, item_id, payload, headers):
        return self._request("POST", f"/crating/items/{item_id}/hazmat-declarations", payload, headers)

    def get_hazmat_declaration(self, decl_id, headers):
        return self._request("GET", f"/crating/hazmat-declarations/{decl_id}", headers=headers)

    def list_hazmat_declarations(self, headers, params=None):
        return self._request("GET", "/crating/hazmat-declarations", headers=headers, params=params)

    def submit_hazmat_declaration(self, decl_id, headers):
        return self._request("POST", f"/crating/hazmat-declarations/{decl_id}/submit", headers=headers)

    def approve_hazmat_declaration(self, decl_id, headers):
        return self._request("POST", f"/crating/hazmat-declarations/{decl_id}/approve", headers=headers)

    def reject_hazmat_declaration(self, decl_id, headers):
        return self._request("POST", f"/crating/hazmat-declarations/{decl_id}/reject", headers=headers)

    def revise_hazmat_declaration(self, decl_id, headers):
        return self._request("POST", f"/crating/hazmat-declarations/{decl_id}/revise", headers=headers)

    # --- Export documents ---
    def upsert_packing_list(self, job_id, payload, headers):
        return self._request("POST", f"/crating/packing-jobs/{job_id}/packing-list", payload, headers)

    def get_packing_list(self, pl_id, headers):
        return self._request("GET", f"/crating/packing-lists/{pl_id}", headers=headers)

    def list_packing_lists(self, headers, params=None):
        return self._request("GET", "/crating/packing-lists", headers=headers, params=params)

    def upsert_commercial_invoice(self, job_id, payload, headers):
        return self._request("POST", f"/crating/packing-jobs/{job_id}/commercial-invoice", payload, headers)

    def get_commercial_invoice(self, ci_id, headers):
        return self._request("GET", f"/crating/commercial-invoices/{ci_id}", headers=headers)

    def list_commercial_invoices(self, headers, params=None):
        return self._request("GET", "/crating/commercial-invoices", headers=headers, params=params)

    def finalize_docs(self, job_id, headers):
        return self._request("POST", f"/crating/packing-jobs/{job_id}/finalize-docs", headers=headers)

    def release_docs(self, job_id, headers):
        return self._request("POST", f"/crating/packing-jobs/{job_id}/release-docs", headers=headers)

    def amend_docs(self, job_id, headers):
        return self._request("POST", f"/crating/packing-jobs/{job_id}/amend-docs", headers=headers)

    # --- Crew / LaborBooking / OnsitePermit ---
    def create_crew(self, payload, headers):
        return self._request("POST", "/crating/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/crating/crews/{crew_id}", headers=headers)

    def create_labor_booking(self, job_id, payload, headers):
        return self._request("POST", f"/crating/packing-jobs/{job_id}/labor-bookings", payload, headers)

    def get_labor_booking(self, booking_id, headers):
        return self._request("GET", f"/crating/labor-bookings/{booking_id}", headers=headers)

    def list_labor_bookings(self, headers, params=None):
        return self._request("GET", "/crating/labor-bookings", headers=headers, params=params)

    def confirm_labor_booking(self, booking_id, headers):
        return self._request("POST", f"/crating/labor-bookings/{booking_id}/confirm", headers=headers)

    def complete_labor_booking(self, booking_id, headers):
        return self._request("POST", f"/crating/labor-bookings/{booking_id}/complete", headers=headers)

    def cancel_labor_booking(self, booking_id, headers):
        return self._request("POST", f"/crating/labor-bookings/{booking_id}/cancel", headers=headers)

    def create_onsite_permit(self, job_id, payload, headers):
        return self._request("POST", f"/crating/packing-jobs/{job_id}/onsite-permit", payload, headers)

    def get_onsite_permit(self, permit_id, headers):
        return self._request("GET", f"/crating/onsite-permits/{permit_id}", headers=headers)

    def list_onsite_permits(self, headers, params=None):
        return self._request("GET", "/crating/onsite-permits", headers=headers, params=params)

    def confirm_onsite_permit(self, permit_id, headers):
        return self._request("POST", f"/crating/onsite-permits/{permit_id}/confirm", headers=headers)

    # --- Container / load plan ---
    def create_container(self, payload, headers):
        return self._request("POST", "/crating/containers", payload, headers)

    def get_container(self, container_id, headers):
        return self._request("GET", f"/crating/containers/{container_id}", headers=headers)

    def lock_container(self, container_id, headers):
        return self._request("POST", f"/crating/containers/{container_id}/lock", headers=headers)

    def unlock_container(self, container_id, headers):
        return self._request("POST", f"/crating/containers/{container_id}/unlock", headers=headers)

    def load_crate(self, container_id, payload, headers):
        return self._request("POST", f"/crating/containers/{container_id}/load-crate", payload, headers)

    def unload_crate(self, container_id, payload, headers):
        return self._request("POST", f"/crating/containers/{container_id}/unload-crate", payload, headers)

    def gate_out_container(self, container_id, headers):
        return self._request("POST", f"/crating/containers/{container_id}/gate-out", headers=headers)

    # --- DamageClaim ---
    def create_claim(self, job_id, payload, headers):
        return self._request("POST", f"/crating/packing-jobs/{job_id}/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/crating/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/crating/claims", headers=headers, params=params)

    def review_claim(self, claim_id, headers):
        return self._request("POST", f"/crating/claims/{claim_id}/review", headers=headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/crating/claims/{claim_id}/approve", headers=headers)

    def deny_claim(self, claim_id, headers):
        return self._request("POST", f"/crating/claims/{claim_id}/deny", headers=headers)

    def settle_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/crating/claims/{claim_id}/settle", payload, headers)

    def appeal_claim(self, claim_id, headers):
        return self._request("POST", f"/crating/claims/{claim_id}/appeal", headers=headers)

    # --- Test-driving clock ---
    def set_logical_clock(self, payload, headers):
        return self._request("POST", "/crating/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
