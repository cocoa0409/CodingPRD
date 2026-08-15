"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.5) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Customers (PRD §3.1) ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def set_credit_status(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/credit-status", payload, headers)

    # --- Profiles (PRD §3.1) ---
    def create_profile(self, payload, headers):
        return self._request("POST", "/profiles", payload, headers)

    def get_profile(self, profile_id, headers):
        return self._request("GET", f"/profiles/{profile_id}", headers=headers)

    def list_profiles(self, headers, params=None):
        return self._request("GET", "/profiles", headers=headers, params=params)

    # --- Dies (PRD §3.2) ---
    def create_die(self, payload, headers):
        return self._request("POST", "/dies", payload, headers)

    def get_die(self, die_id, headers):
        return self._request("GET", f"/dies/{die_id}", headers=headers)

    def list_dies(self, headers, params=None):
        return self._request("GET", "/dies", headers=headers, params=params)

    def transition_die(self, die_id, payload, headers):
        return self._request("POST", f"/dies/{die_id}/transition", payload, headers)

    def post_amortization_adjustment(self, die_id, payload, headers):
        return self._request("POST", f"/dies/{die_id}/amortization-adjustments", payload, headers)

    # --- Extrusion lines (PRD §3.5) ---
    def create_line(self, payload, headers):
        return self._request("POST", "/lines", payload, headers)

    def get_line(self, line_id, headers):
        return self._request("GET", f"/lines/{line_id}", headers=headers)

    # --- Resin lots (PRD §3.3) ---
    def create_resin_lot(self, payload, headers):
        return self._request("POST", "/resin-lots", payload, headers)

    def get_resin_lot(self, lot_id, headers):
        return self._request("GET", f"/resin-lots/{lot_id}", headers=headers)

    def qc_resin_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/resin-lots/{lot_id}/qc", payload, headers)

    # --- Formulations (PRD §3.3) ---
    def create_formulation(self, payload, headers):
        return self._request("POST", "/formulations", payload, headers)

    def get_formulation(self, formulation_id, headers):
        return self._request("GET", f"/formulations/{formulation_id}", headers=headers)

    def list_formulations(self, headers, params=None):
        return self._request("GET", "/formulations", headers=headers, params=params)

    # --- Blend batches (PRD §3.3) ---
    def create_blend_batch(self, payload, headers):
        return self._request("POST", "/blend-batches", payload, headers)

    def get_blend_batch(self, batch_id, headers):
        return self._request("GET", f"/blend-batches/{batch_id}", headers=headers)

    def list_blend_batches(self, headers, params=None):
        return self._request("GET", "/blend-batches", headers=headers, params=params)

    def qc_blend_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/blend-batches/{batch_id}/qc", payload, headers)

    # --- Work orders (PRD §3.4) ---
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def confirm_work_order(self, work_order_id, headers, payload=None):
        return self._request("POST", f"/work-orders/{work_order_id}/confirm", payload or {}, headers)

    def reprice_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/reprice", payload, headers)

    def cancel_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/cancel", {}, headers)

    def invoice_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/invoice", {}, headers)

    # --- Line assignments (PRD §3.5) ---
    def create_line_assignment(self, payload, headers):
        return self._request("POST", "/line-assignments", payload, headers)

    def get_line_assignment(self, assignment_id, headers):
        return self._request("GET", f"/line-assignments/{assignment_id}", headers=headers)

    def list_line_assignments(self, headers, params=None):
        return self._request("GET", "/line-assignments", headers=headers, params=params)

    def activate_assignment(self, assignment_id, headers):
        return self._request("POST", f"/line-assignments/{assignment_id}/activate", {}, headers)

    def close_assignment(self, assignment_id, headers):
        return self._request("POST", f"/line-assignments/{assignment_id}/close", {}, headers)

    def cancel_assignment(self, assignment_id, headers):
        return self._request("POST", f"/line-assignments/{assignment_id}/cancel", {}, headers)

    # --- Production runs (PRD §3.6, §3.7) ---
    def create_run(self, payload, headers):
        return self._request("POST", "/runs", payload, headers)

    def get_run(self, run_id, headers):
        return self._request("GET", f"/runs/{run_id}", headers=headers)

    def list_runs(self, headers, params=None):
        return self._request("GET", "/runs", headers=headers, params=params)

    def set_run_hold_status(self, run_id, payload, headers):
        return self._request("POST", f"/runs/{run_id}/hold-status", payload, headers)

    def complete_run(self, run_id, payload, headers):
        return self._request("POST", f"/runs/{run_id}/complete", payload, headers)

    # --- SPC samples (PRD §3.7) ---
    def create_spc_sample(self, payload, headers):
        return self._request("POST", "/spc-samples", payload, headers)

    def list_spc_samples(self, run_id, headers, params=None):
        return self._request("GET", f"/runs/{run_id}/spc-samples", headers=headers, params=params)

    # --- Cut bundles (PRD §3.7) ---
    def list_bundles(self, run_id, headers, params=None):
        return self._request("GET", f"/runs/{run_id}/bundles", headers=headers, params=params)

    # --- Purge events (PRD §3.5) ---
    def create_purge_event(self, payload, headers):
        return self._request("POST", "/purge-events", payload, headers)

    def list_purge_events(self, line_id, headers, params=None):
        return self._request("GET", f"/lines/{line_id}/purge-events", headers=headers, params=params)

    # --- Resin index points (PRD §3.4) ---
    def create_resin_index_point(self, payload, headers):
        return self._request("POST", "/resin-index-points", payload, headers)

    def get_resin_index_point(self, month, headers):
        return self._request("GET", f"/resin-index-points/{month}", headers=headers)

    def restate_resin_index_point(self, month, payload, headers):
        return self._request("POST", f"/resin-index-points/{month}/restate", payload, headers)


api_client = ApiClient()
