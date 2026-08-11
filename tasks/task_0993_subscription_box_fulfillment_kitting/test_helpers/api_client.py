"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Client ---
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def create_credit_adjustment(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/credit-adjustments", payload, headers)

    def list_client_billing_statements(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/billing-statements", headers=headers, params=params)

    def get_fulfillment_summary(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/reports/fulfillment-summary", headers=headers, params=params)

    # --- BoxPlan ---
    def create_box_plan(self, payload, headers):
        return self._request("POST", "/box-plans", payload, headers)

    def list_box_plans(self, headers, params=None):
        return self._request("GET", "/box-plans", headers=headers, params=params)

    def get_box_plan(self, plan_id, headers):
        return self._request("GET", f"/box-plans/{plan_id}", headers=headers)

    def activate_box_plan(self, plan_id, headers):
        return self._request("POST", f"/box-plans/{plan_id}/activate", headers=headers)

    def retire_box_plan(self, plan_id, headers):
        return self._request("POST", f"/box-plans/{plan_id}/retire", headers=headers)

    def create_kit_revision(self, plan_id, payload, headers):
        return self._request("POST", f"/box-plans/{plan_id}/kit-revisions", payload, headers)

    def list_plan_kit_revisions(self, plan_id, headers, params=None):
        return self._request("GET", f"/box-plans/{plan_id}/kit-revisions", headers=headers, params=params)

    def create_import_batch(self, plan_id, payload, headers):
        return self._request("POST", f"/box-plans/{plan_id}/import-batches", payload, headers)

    def list_import_batches(self, plan_id, headers, params=None):
        return self._request("GET", f"/box-plans/{plan_id}/import-batches", headers=headers, params=params)

    def list_plan_assembly_runs(self, plan_id, headers, params=None):
        return self._request("GET", f"/box-plans/{plan_id}/assembly-runs", headers=headers, params=params)

    # --- KitRevision / BOM ---
    def get_kit_revision(self, revision_id, headers):
        return self._request("GET", f"/kit-revisions/{revision_id}", headers=headers)

    def list_kit_revisions(self, headers, params=None):
        return self._request("GET", "/kit-revisions", headers=headers, params=params)

    def approve_kit_revision(self, revision_id, headers):
        return self._request("POST", f"/kit-revisions/{revision_id}/approve", headers=headers)

    def put_bom_lines(self, revision_id, payload, headers):
        return self._request("PUT", f"/kit-revisions/{revision_id}/bom-lines", payload, headers)

    def list_bom_lines(self, revision_id, headers):
        return self._request("GET", f"/kit-revisions/{revision_id}/bom-lines", headers=headers)

    # --- Component / inventory ---
    def create_component(self, payload, headers):
        return self._request("POST", "/components", payload, headers)

    def get_component(self, component_id, headers):
        return self._request("GET", f"/components/{component_id}", headers=headers)

    def list_component_bom_lines(self, component_id, headers):
        return self._request("GET", f"/components/{component_id}/bom-lines", headers=headers)

    def create_receipt(self, component_id, payload, headers):
        return self._request("POST", f"/components/{component_id}/receipts", payload, headers)

    def list_component_inventory_events(self, component_id, headers, params=None):
        return self._request("GET", f"/components/{component_id}/inventory-events", headers=headers, params=params)

    # --- Import / Subscriber ---
    def get_import_batch(self, batch_id, headers):
        return self._request("GET", f"/import-batches/{batch_id}", headers=headers)

    def commit_import_batch(self, batch_id, headers):
        return self._request("POST", f"/import-batches/{batch_id}/commit", headers=headers)

    def list_subscribers(self, headers, params=None):
        return self._request("GET", "/subscribers", headers=headers, params=params)

    def get_subscriber(self, subscriber_id, headers):
        return self._request("GET", f"/subscribers/{subscriber_id}", headers=headers)

    def pause_subscriber(self, subscriber_id, headers):
        return self._request("POST", f"/subscribers/{subscriber_id}/pause", headers=headers)

    def resume_subscriber(self, subscriber_id, headers):
        return self._request("POST", f"/subscribers/{subscriber_id}/resume", headers=headers)

    def churn_subscriber(self, subscriber_id, payload, headers):
        return self._request("POST", f"/subscribers/{subscriber_id}/churn", payload, headers)

    def list_subscriber_shipments(self, subscriber_id, headers, params=None):
        return self._request("GET", f"/subscribers/{subscriber_id}/shipments", headers=headers, params=params)

    # --- AssemblyRun ---
    def create_assembly_run(self, payload, headers):
        return self._request("POST", "/assembly-runs", payload, headers)

    def get_assembly_run(self, run_id, headers):
        return self._request("GET", f"/assembly-runs/{run_id}", headers=headers)

    def list_run_shipments(self, run_id, headers, params=None):
        return self._request("GET", f"/assembly-runs/{run_id}/shipments", headers=headers, params=params)

    def list_run_inventory_events(self, run_id, headers, params=None):
        return self._request("GET", f"/assembly-runs/{run_id}/inventory-events", headers=headers, params=params)

    def lock_assembly_run(self, run_id, headers):
        return self._request("POST", f"/assembly-runs/{run_id}/lock", headers=headers)

    def start_kitting(self, run_id, headers):
        return self._request("POST", f"/assembly-runs/{run_id}/start-kitting", headers=headers)

    def complete_kitting(self, run_id, payload, headers):
        return self._request("POST", f"/assembly-runs/{run_id}/complete-kitting", payload, headers)

    def rework_assembly_run(self, run_id, payload, headers):
        return self._request("POST", f"/assembly-runs/{run_id}/rework", payload, headers)

    def close_assembly_run(self, run_id, headers):
        return self._request("POST", f"/assembly-runs/{run_id}/close", headers=headers)

    def cancel_assembly_run(self, run_id, headers):
        return self._request("POST", f"/assembly-runs/{run_id}/cancel", headers=headers)

    # --- ShippingWave / labels ---
    def create_shipping_wave(self, payload, headers):
        return self._request("POST", "/shipping-waves", payload, headers)

    def get_shipping_wave(self, wave_id, headers):
        return self._request("GET", f"/shipping-waves/{wave_id}", headers=headers)

    def list_wave_shipments(self, wave_id, headers, params=None):
        return self._request("GET", f"/shipping-waves/{wave_id}/shipments", headers=headers, params=params)

    def assign_shipments(self, wave_id, payload, headers):
        return self._request("POST", f"/shipping-waves/{wave_id}/assign-shipments", payload, headers)

    def manifest_wave(self, wave_id, headers):
        return self._request("POST", f"/shipping-waves/{wave_id}/manifest", headers=headers)

    def tender_wave(self, wave_id, headers):
        return self._request("POST", f"/shipping-waves/{wave_id}/tender", headers=headers)

    def cancel_wave(self, wave_id, headers):
        return self._request("POST", f"/shipping-waves/{wave_id}/cancel", headers=headers)

    # --- Shipment ---
    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/shipments/{shipment_id}", headers=headers)

    def cancel_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/cancel", headers=headers)

    def void_label(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/void-label", headers=headers)

    def scan_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/shipments/{shipment_id}/scan", payload, headers)

    # --- ReturnCase ---
    def create_return_case(self, payload, headers):
        return self._request("POST", "/return-cases", payload, headers)

    def list_return_cases(self, headers, params=None):
        return self._request("GET", "/return-cases", headers=headers, params=params)

    def get_return_case(self, case_id, headers):
        return self._request("GET", f"/return-cases/{case_id}", headers=headers)

    def approve_return_case(self, case_id, headers):
        return self._request("POST", f"/return-cases/{case_id}/approve", headers=headers)

    def reject_return_case(self, case_id, payload, headers):
        return self._request("POST", f"/return-cases/{case_id}/reject", payload, headers)

    def receive_return_case(self, case_id, headers):
        return self._request("POST", f"/return-cases/{case_id}/receive", headers=headers)

    def resolve_return_case(self, case_id, headers):
        return self._request("POST", f"/return-cases/{case_id}/resolve", headers=headers)

    # --- BillingStatement ---
    def get_billing_statement(self, statement_id, headers):
        return self._request("GET", f"/billing-statements/{statement_id}", headers=headers)

    def finalize_statement(self, statement_id, headers):
        return self._request("POST", f"/billing-statements/{statement_id}/finalize", headers=headers)

    def dispute_statement(self, statement_id, headers):
        return self._request("POST", f"/billing-statements/{statement_id}/dispute", headers=headers)

    def resolve_dispute(self, statement_id, payload, headers):
        return self._request("POST", f"/billing-statements/{statement_id}/resolve-dispute", payload, headers)

    def mark_paid(self, statement_id, headers):
        return self._request("POST", f"/billing-statements/{statement_id}/mark-paid", headers=headers)


api_client = ApiClient()
