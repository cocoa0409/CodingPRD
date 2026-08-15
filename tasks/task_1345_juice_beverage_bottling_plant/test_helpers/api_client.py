"""API client: one method per endpoint defined in the PRD endpoint table (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/v1/_clock/set_current_utc", payload, headers)

    # --- CustomerAccount ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/v1/customer-accounts", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/v1/customer-accounts", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/v1/customer-accounts/{customer_id}", headers=headers)

    def approve_credit(self, customer_id, headers):
        return self._request("POST", f"/v1/customer-accounts/{customer_id}/approve-credit", {}, headers)

    def suspend_customer(self, customer_id, headers):
        return self._request("POST", f"/v1/customer-accounts/{customer_id}/suspend", {}, headers)

    def reactivate_customer(self, customer_id, headers):
        return self._request("POST", f"/v1/customer-accounts/{customer_id}/reactivate", {}, headers)

    def close_customer(self, customer_id, headers):
        return self._request("POST", f"/v1/customer-accounts/{customer_id}/close", {}, headers)

    def post_payment(self, customer_id, payload, headers):
        return self._request("POST", f"/v1/customer-accounts/{customer_id}/payments", payload, headers)

    def list_customer_production_runs(self, customer_id, headers, params=None):
        return self._request("GET", f"/v1/customer-accounts/{customer_id}/production-runs", headers=headers, params=params)

    def list_customer_shipment_orders(self, customer_id, headers, params=None):
        return self._request("GET", f"/v1/customer-accounts/{customer_id}/shipment-orders", headers=headers, params=params)

    def get_customer_pallet_account(self, customer_id, headers):
        return self._request("GET", f"/v1/customer-accounts/{customer_id}/pallet-account", headers=headers)

    # --- PalletAccount / PalletEntry ---
    def get_pallet_account(self, account_id, headers):
        return self._request("GET", f"/v1/pallet-accounts/{account_id}", headers=headers)

    def post_pallet_return(self, account_id, payload, headers):
        return self._request("POST", f"/v1/pallet-accounts/{account_id}/returns", payload, headers)

    def list_pallet_entries(self, account_id, headers, params=None):
        return self._request("GET", f"/v1/pallet-accounts/{account_id}/entries", headers=headers, params=params)

    # --- Formula / LabelClaimReview ---
    def create_formula(self, payload, headers):
        return self._request("POST", "/v1/formulas", payload, headers)

    def list_formulas(self, headers, params=None):
        return self._request("GET", "/v1/formulas", headers=headers, params=params)

    def get_formula(self, formula_id, headers):
        return self._request("GET", f"/v1/formulas/{formula_id}", headers=headers)

    def submit_label_review(self, formula_id, payload, headers):
        return self._request("POST", f"/v1/formulas/{formula_id}/submit-label-review", payload, headers)

    def retire_formula(self, formula_id, headers):
        return self._request("POST", f"/v1/formulas/{formula_id}/retire", {}, headers)

    def list_formula_label_reviews(self, formula_id, headers, params=None):
        return self._request("GET", f"/v1/formulas/{formula_id}/label-reviews", headers=headers, params=params)

    def list_formula_batches(self, formula_id, headers, params=None):
        return self._request("GET", f"/v1/formulas/{formula_id}/batches", headers=headers, params=params)

    def get_label_review(self, review_id, headers):
        return self._request("GET", f"/v1/label-reviews/{review_id}", headers=headers)

    def approve_label_review(self, review_id, headers):
        return self._request("POST", f"/v1/label-reviews/{review_id}/approve", {}, headers)

    def reject_label_review(self, review_id, payload, headers):
        return self._request("POST", f"/v1/label-reviews/{review_id}/reject", payload, headers)

    # --- BlendingTank ---
    def create_tank(self, payload, headers):
        return self._request("POST", "/v1/blending-tanks", payload, headers)

    def list_tanks(self, headers, params=None):
        return self._request("GET", "/v1/blending-tanks", headers=headers, params=params)

    def get_tank(self, tank_id, headers):
        return self._request("GET", f"/v1/blending-tanks/{tank_id}", headers=headers)

    def start_cip(self, tank_id, headers):
        return self._request("POST", f"/v1/blending-tanks/{tank_id}/start-cip", {}, headers)

    def complete_cip(self, tank_id, headers):
        return self._request("POST", f"/v1/blending-tanks/{tank_id}/complete-cip", {}, headers)

    def list_tank_batches(self, tank_id, headers, params=None):
        return self._request("GET", f"/v1/blending-tanks/{tank_id}/batches", headers=headers, params=params)

    # --- Batch ---
    def create_batch(self, payload, headers):
        return self._request("POST", "/v1/batches", payload, headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/v1/batches", headers=headers, params=params)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/v1/batches/{batch_id}", headers=headers)

    def start_blend(self, batch_id, headers):
        return self._request("POST", f"/v1/batches/{batch_id}/start-blend", {}, headers)

    def record_blend(self, batch_id, payload, headers):
        return self._request("POST", f"/v1/batches/{batch_id}/record-blend", payload, headers)

    def qa_verdict(self, batch_id, payload, headers):
        return self._request("POST", f"/v1/batches/{batch_id}/qa-verdict", payload, headers)

    def apply_adjustment(self, batch_id, headers):
        return self._request("POST", f"/v1/batches/{batch_id}/apply-adjustment", {}, headers)

    def condemn_batch(self, batch_id, headers):
        return self._request("POST", f"/v1/batches/{batch_id}/condemn", {}, headers)

    def release_batch(self, batch_id, headers):
        return self._request("POST", f"/v1/batches/{batch_id}/release", {}, headers)

    def list_batch_process_runs(self, batch_id, headers, params=None):
        return self._request("GET", f"/v1/batches/{batch_id}/process-runs", headers=headers, params=params)

    def list_batch_production_runs(self, batch_id, headers, params=None):
        return self._request("GET", f"/v1/batches/{batch_id}/production-runs", headers=headers, params=params)

    # --- ProcessRun ---
    def create_process_run(self, payload, headers):
        return self._request("POST", "/v1/process-runs", payload, headers)

    def get_process_run(self, process_run_id, headers):
        return self._request("GET", f"/v1/process-runs/{process_run_id}", headers=headers)

    def start_process_run(self, process_run_id, headers):
        return self._request("POST", f"/v1/process-runs/{process_run_id}/start", {}, headers)

    def complete_process_run(self, process_run_id, payload, headers):
        return self._request("POST", f"/v1/process-runs/{process_run_id}/complete", payload, headers)

    def abort_process_run(self, process_run_id, headers):
        return self._request("POST", f"/v1/process-runs/{process_run_id}/abort", {}, headers)

    def qa_disposition(self, process_run_id, payload, headers):
        return self._request("POST", f"/v1/process-runs/{process_run_id}/qa-disposition", payload, headers)

    # --- ContainerLot ---
    def create_container_lot(self, payload, headers):
        return self._request("POST", "/v1/container-lots", payload, headers)

    def list_container_lots(self, headers, params=None):
        return self._request("GET", "/v1/container-lots", headers=headers, params=params)

    def get_container_lot(self, lot_id, headers):
        return self._request("GET", f"/v1/container-lots/{lot_id}", headers=headers)

    def container_qc_verdict(self, lot_id, payload, headers):
        return self._request("POST", f"/v1/container-lots/{lot_id}/qc-verdict", payload, headers)

    def return_container_lot(self, lot_id, headers):
        return self._request("POST", f"/v1/container-lots/{lot_id}/return", {}, headers)

    # --- BottlingLine ---
    def create_line(self, payload, headers):
        return self._request("POST", "/v1/bottling-lines", payload, headers)

    def list_lines(self, headers, params=None):
        return self._request("GET", "/v1/bottling-lines", headers=headers, params=params)

    def get_line(self, line_id, headers):
        return self._request("GET", f"/v1/bottling-lines/{line_id}", headers=headers)

    def set_line_maintenance(self, line_id, headers):
        return self._request("POST", f"/v1/bottling-lines/{line_id}/set-maintenance", {}, headers)

    def set_line_active(self, line_id, headers):
        return self._request("POST", f"/v1/bottling-lines/{line_id}/set-active", {}, headers)

    def list_line_production_runs(self, line_id, headers, params=None):
        return self._request("GET", f"/v1/bottling-lines/{line_id}/production-runs", headers=headers, params=params)

    # --- ProductionRun ---
    def create_production_run(self, payload, headers):
        return self._request("POST", "/v1/production-runs", payload, headers)

    def list_production_runs(self, headers, params=None):
        return self._request("GET", "/v1/production-runs", headers=headers, params=params)

    def get_production_run(self, run_id, headers):
        return self._request("GET", f"/v1/production-runs/{run_id}", headers=headers)

    def confirm_run(self, run_id, headers):
        return self._request("POST", f"/v1/production-runs/{run_id}/confirm", {}, headers)

    def schedule_run(self, run_id, payload, headers):
        return self._request("POST", f"/v1/production-runs/{run_id}/schedule", payload, headers)

    def start_run(self, run_id, headers):
        return self._request("POST", f"/v1/production-runs/{run_id}/start", {}, headers)

    def complete_run(self, run_id, payload, headers):
        return self._request("POST", f"/v1/production-runs/{run_id}/complete", payload, headers)

    def finalize_invoice(self, run_id, headers):
        return self._request("POST", f"/v1/production-runs/{run_id}/finalize-invoice", {}, headers)

    def cancel_run(self, run_id, headers):
        return self._request("POST", f"/v1/production-runs/{run_id}/cancel", {}, headers)

    def list_run_finished_lots(self, run_id, headers, params=None):
        return self._request("GET", f"/v1/production-runs/{run_id}/finished-good-lots", headers=headers, params=params)

    # --- FinishedGoodLot / WarehouseZone ---
    def list_finished_lots(self, headers, params=None):
        return self._request("GET", "/v1/finished-good-lots", headers=headers, params=params)

    def get_finished_lot(self, lot_id, headers):
        return self._request("GET", f"/v1/finished-good-lots/{lot_id}", headers=headers)

    def recall_finished_lot(self, lot_id, headers):
        return self._request("POST", f"/v1/finished-good-lots/{lot_id}/recall", {}, headers)

    def create_zone(self, payload, headers):
        return self._request("POST", "/v1/warehouse-zones", payload, headers)

    def list_zones(self, headers, params=None):
        return self._request("GET", "/v1/warehouse-zones", headers=headers, params=params)

    def get_zone(self, zone_id, headers):
        return self._request("GET", f"/v1/warehouse-zones/{zone_id}", headers=headers)

    def list_zone_finished_lots(self, zone_id, headers, params=None):
        return self._request("GET", f"/v1/warehouse-zones/{zone_id}/finished-good-lots", headers=headers, params=params)

    # --- ShipmentOrder ---
    def create_shipment_order(self, payload, headers):
        return self._request("POST", "/v1/shipment-orders", payload, headers)

    def list_shipment_orders(self, headers, params=None):
        return self._request("GET", "/v1/shipment-orders", headers=headers, params=params)

    def get_shipment_order(self, order_id, headers):
        return self._request("GET", f"/v1/shipment-orders/{order_id}", headers=headers)

    def allocate_order(self, order_id, payload, headers):
        return self._request("POST", f"/v1/shipment-orders/{order_id}/allocate", payload, headers)

    def pick_order(self, order_id, headers):
        return self._request("POST", f"/v1/shipment-orders/{order_id}/pick", {}, headers)

    def ship_order(self, order_id, headers):
        return self._request("POST", f"/v1/shipment-orders/{order_id}/ship", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/v1/shipment-orders/{order_id}/cancel", {}, headers)

    # --- Ops run ---
    def post_ops_run(self, headers):
        return self._request("POST", "/v1/ops-runs", {}, headers)


api_client = ApiClient()
