"""API client: one method per endpoint defined in the PRD (§4 routing table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- Index publications ---
    def create_index_publication(self, payload, headers):
        return self._request("POST", "/api/index-publications", payload, headers)

    def list_index_publications(self, headers, params=None):
        return self._request("GET", "/api/index-publications", headers=headers, params=params)

    # --- Customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/api/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/api/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/api/customers/{customer_id}", headers=headers)

    def list_customer_parts(self, customer_id, headers, params=None):
        return self._request("GET", f"/api/customers/{customer_id}/parts", headers=headers, params=params)

    # --- Parts ---
    def create_part(self, payload, headers):
        return self._request("POST", "/api/parts", payload, headers)

    def list_parts(self, headers, params=None):
        return self._request("GET", "/api/parts", headers=headers, params=params)

    def get_part(self, part_id, headers):
        return self._request("GET", f"/api/parts/{part_id}", headers=headers)

    def list_part_strip_layouts(self, part_id, headers, params=None):
        return self._request("GET", f"/api/parts/{part_id}/strip-layouts", headers=headers, params=params)

    def list_part_ppap_submissions(self, part_id, headers, params=None):
        return self._request("GET", f"/api/parts/{part_id}/ppap-submissions", headers=headers, params=params)

    def list_part_die_assignments(self, part_id, headers, params=None):
        return self._request("GET", f"/api/parts/{part_id}/die-assignments", headers=headers, params=params)

    # --- Dies ---
    def create_die(self, payload, headers):
        return self._request("POST", "/api/dies", payload, headers)

    def list_dies(self, headers, params=None):
        return self._request("GET", "/api/dies", headers=headers, params=params)

    def get_die(self, die_id, headers):
        return self._request("GET", f"/api/dies/{die_id}", headers=headers)

    def send_die_to_repair(self, die_id, headers):
        return self._request("POST", f"/api/dies/{die_id}/send-to-repair", {}, headers)

    def complete_die_repair(self, die_id, headers):
        return self._request("POST", f"/api/dies/{die_id}/complete-repair", {}, headers)

    def retire_die(self, die_id, headers):
        return self._request("POST", f"/api/dies/{die_id}/retire", {}, headers)

    # --- Presses ---
    def create_press(self, payload, headers):
        return self._request("POST", "/api/presses", payload, headers)

    def list_presses(self, headers, params=None):
        return self._request("GET", "/api/presses", headers=headers, params=params)

    def get_press(self, press_id, headers):
        return self._request("GET", f"/api/presses/{press_id}", headers=headers)

    def list_press_die_change_events(self, press_id, headers, params=None):
        return self._request("GET", f"/api/presses/{press_id}/die-change-events", headers=headers, params=params)

    def list_press_production_runs(self, press_id, headers, params=None):
        return self._request("GET", f"/api/presses/{press_id}/production-runs", headers=headers, params=params)

    def list_press_layered_audits(self, press_id, headers, params=None):
        return self._request("GET", f"/api/presses/{press_id}/layered-audits", headers=headers, params=params)

    def get_press_smed_performance(self, press_id, headers):
        return self._request("GET", f"/api/presses/{press_id}/smed-performance", headers=headers)

    # --- Part-die assignments ---
    def create_part_die_assignment(self, payload, headers):
        return self._request("POST", "/api/part-die-assignments", payload, headers)

    def list_part_die_assignments_filtered(self, headers, params=None):
        return self._request("GET", "/api/part-die-assignments", headers=headers, params=params)

    def get_part_die_assignment(self, assignment_id, headers):
        return self._request("GET", f"/api/part-die-assignments/{assignment_id}", headers=headers)

    # --- Die change events ---
    def list_die_change_events(self, headers, params=None):
        return self._request("GET", "/api/die-change-events", headers=headers, params=params)

    def create_die_change_event(self, payload, headers):
        return self._request("POST", "/api/die-change-events", payload, headers)

    def get_die_change_event(self, event_id, headers):
        return self._request("GET", f"/api/die-change-events/{event_id}", headers=headers)

    def start_die_change_event(self, event_id, headers):
        return self._request("POST", f"/api/die-change-events/{event_id}/start", {}, headers)

    def complete_die_change_event(self, event_id, headers):
        return self._request("POST", f"/api/die-change-events/{event_id}/complete", {}, headers)

    def cancel_die_change_event(self, event_id, headers):
        return self._request("POST", f"/api/die-change-events/{event_id}/cancel", {}, headers)

    # --- Production runs ---
    def list_production_runs(self, headers, params=None):
        return self._request("GET", "/api/production-runs", headers=headers, params=params)

    def create_production_run(self, payload, headers):
        return self._request("POST", "/api/production-runs", payload, headers)

    def get_production_run(self, run_id, headers):
        return self._request("GET", f"/api/production-runs/{run_id}", headers=headers)

    def start_production_run(self, run_id, headers):
        return self._request("POST", f"/api/production-runs/{run_id}/start", {}, headers)

    def complete_production_run(self, run_id, payload, headers):
        return self._request("POST", f"/api/production-runs/{run_id}/complete", payload, headers)

    def abort_production_run(self, run_id, headers):
        return self._request("POST", f"/api/production-runs/{run_id}/abort", {}, headers)

    def list_run_reject_events(self, run_id, headers, params=None):
        return self._request("GET", f"/api/production-runs/{run_id}/reject-events", headers=headers, params=params)

    def create_reject_event(self, run_id, payload, headers):
        return self._request("POST", f"/api/production-runs/{run_id}/reject-events", payload, headers)

    # --- Steel coils ---
    def create_steel_coil(self, payload, headers):
        return self._request("POST", "/api/steel-coils", payload, headers)

    def list_steel_coils(self, headers, params=None):
        return self._request("GET", "/api/steel-coils", headers=headers, params=params)

    def get_steel_coil(self, coil_id, headers):
        return self._request("GET", f"/api/steel-coils/{coil_id}", headers=headers)

    def approve_steel_coil(self, coil_id, headers):
        return self._request("POST", f"/api/steel-coils/{coil_id}/approve", {}, headers)

    def reject_steel_coil(self, coil_id, headers):
        return self._request("POST", f"/api/steel-coils/{coil_id}/reject", {}, headers)

    def hold_steel_coil(self, coil_id, headers):
        return self._request("POST", f"/api/steel-coils/{coil_id}/hold", {}, headers)

    def release_hold_steel_coil(self, coil_id, headers):
        return self._request("POST", f"/api/steel-coils/{coil_id}/release-hold", {}, headers)

    # --- Heat-lot exposure computed read ---
    def get_heat_lot_exposure(self, heat_lot_number, headers):
        return self._request("GET", f"/api/heat-lots/{heat_lot_number}/exposure", headers=headers)

    # --- Strip layouts ---
    def create_strip_layout(self, payload, headers):
        return self._request("POST", "/api/strip-layouts", payload, headers)

    def get_strip_layout(self, layout_id, headers):
        return self._request("GET", f"/api/strip-layouts/{layout_id}", headers=headers)

    def approve_strip_layout(self, layout_id, payload, headers):
        return self._request("POST", f"/api/strip-layouts/{layout_id}/approve", payload, headers)

    # --- Production orders ---
    def create_production_order(self, payload, headers):
        return self._request("POST", "/api/production-orders", payload, headers)

    def list_production_orders(self, headers, params=None):
        return self._request("GET", "/api/production-orders", headers=headers, params=params)

    def get_production_order(self, order_id, headers):
        return self._request("GET", f"/api/production-orders/{order_id}", headers=headers)

    def release_production_order(self, order_id, payload, headers):
        return self._request("POST", f"/api/production-orders/{order_id}/release", payload, headers)

    def complete_production_order(self, order_id, headers):
        return self._request("POST", f"/api/production-orders/{order_id}/complete", {}, headers)

    def close_production_order(self, order_id, headers):
        return self._request("POST", f"/api/production-orders/{order_id}/close", {}, headers)

    def cancel_production_order(self, order_id, headers):
        return self._request("POST", f"/api/production-orders/{order_id}/cancel", {}, headers)

    def list_order_production_runs(self, order_id, headers, params=None):
        return self._request("GET", f"/api/production-orders/{order_id}/production-runs", headers=headers, params=params)

    def list_order_price_adjustments(self, order_id, headers, params=None):
        return self._request("GET", f"/api/production-orders/{order_id}/price-adjustments", headers=headers, params=params)

    def list_order_outside_processing_orders(self, order_id, headers, params=None):
        return self._request("GET", f"/api/production-orders/{order_id}/outside-processing-orders", headers=headers, params=params)

    # --- Outside processing ---
    def create_outside_processing_order(self, payload, headers):
        return self._request("POST", "/api/outside-processing-orders", payload, headers)

    def get_outside_processing_order(self, opo_id, headers):
        return self._request("GET", f"/api/outside-processing-orders/{opo_id}", headers=headers)

    def receive_outside_processing_return(self, opo_id, payload, headers):
        return self._request("POST", f"/api/outside-processing-orders/{opo_id}/receive-return", payload, headers)

    def close_short_outside_processing_order(self, opo_id, payload, headers):
        return self._request("POST", f"/api/outside-processing-orders/{opo_id}/close-short", payload, headers)

    # --- PPAP submissions ---
    def create_ppap_submission(self, payload, headers):
        return self._request("POST", "/api/ppap-submissions", payload, headers)

    def get_ppap_submission(self, submission_id, headers):
        return self._request("GET", f"/api/ppap-submissions/{submission_id}", headers=headers)

    def begin_ppap_review(self, submission_id, headers):
        return self._request("POST", f"/api/ppap-submissions/{submission_id}/begin-review", {}, headers)

    def approve_ppap_submission(self, submission_id, headers):
        return self._request("POST", f"/api/ppap-submissions/{submission_id}/approve", {}, headers)

    def reject_ppap_submission(self, submission_id, payload, headers):
        return self._request("POST", f"/api/ppap-submissions/{submission_id}/reject", payload, headers)

    # --- Layered audits ---
    def create_layered_audit(self, payload, headers):
        return self._request("POST", "/api/layered-audits", payload, headers)

    def list_layered_audits(self, headers, params=None):
        return self._request("GET", "/api/layered-audits", headers=headers, params=params)

    def get_layered_audit(self, audit_id, headers):
        return self._request("GET", f"/api/layered-audits/{audit_id}", headers=headers)

    def record_layered_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/api/layered-audits/{audit_id}/record", payload, headers)


api_client = ApiClient()
