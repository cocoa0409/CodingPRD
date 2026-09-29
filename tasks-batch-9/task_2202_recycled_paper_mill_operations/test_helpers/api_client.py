"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers=headers)

    # ------------------------------------------------------------ customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers=headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def patch_customer_status(self, customer_id, status, headers):
        return self._request("PATCH", f"/customers/{customer_id}/status",
                             {"status": status}, headers=headers)

    # ------------------------------------------------------------ suppliers ---
    def create_supplier(self, payload, headers):
        return self._request("POST", "/suppliers", payload, headers=headers)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"/suppliers/{supplier_id}", headers=headers)

    # --------------------------------------------------------- fiber grades ---
    def create_fiber_grade(self, payload, headers):
        return self._request("POST", "/fiber-grades", payload, headers=headers)

    def list_fiber_grades(self, headers, params=None):
        return self._request("GET", "/fiber-grades", headers=headers, params=params)

    # -------------------------------------------------------- index quotes ---
    def create_market_index_quote(self, payload, headers):
        return self._request("POST", "/market-index-quotes", payload, headers=headers)

    def list_market_index_quotes(self, headers, params=None):
        return self._request("GET", "/market-index-quotes", headers=headers, params=params)

    # ---------------------------------------------------- paper grade specs ---
    def create_paper_grade_spec(self, payload, headers):
        return self._request("POST", "/paper-grade-specs", payload, headers=headers)

    def list_paper_grade_specs(self, headers, params=None):
        return self._request("GET", "/paper-grade-specs", headers=headers, params=params)

    # ------------------------------------------------------- paper machines ---
    def create_paper_machine(self, payload, headers):
        return self._request("POST", "/paper-machines", payload, headers=headers)

    def get_paper_machine(self, machine_id, headers):
        return self._request("GET", f"/paper-machines/{machine_id}", headers=headers)

    def patch_paper_machine_status(self, machine_id, payload, headers):
        return self._request("PATCH", f"/paper-machines/{machine_id}/status",
                             payload, headers=headers)

    # ------------------------------------------------- fiber purchase orders ---
    def create_purchase_order(self, payload, headers):
        return self._request("POST", "/fiber-purchase-orders", payload, headers=headers)

    def get_purchase_order(self, po_id, headers):
        return self._request("GET", f"/fiber-purchase-orders/{po_id}", headers=headers)

    def list_purchase_orders(self, headers, params=None):
        return self._request("GET", "/fiber-purchase-orders", headers=headers, params=params)

    def price_purchase_order(self, po_id, payload, headers):
        return self._request("POST", f"/fiber-purchase-orders/{po_id}/price",
                             payload, headers=headers)

    def withdraw_purchase_order_pricing(self, po_id, payload, headers):
        return self._request("POST", f"/fiber-purchase-orders/{po_id}/withdraw-pricing",
                             payload, headers=headers)

    def confirm_purchase_order(self, po_id, headers):
        return self._request("POST", f"/fiber-purchase-orders/{po_id}/confirm",
                             {}, headers=headers)

    def cancel_purchase_order(self, po_id, headers):
        return self._request("POST", f"/fiber-purchase-orders/{po_id}/cancel",
                             {}, headers=headers)

    def create_receipt(self, po_id, payload, headers):
        return self._request("POST", f"/fiber-purchase-orders/{po_id}/receipts",
                             payload, headers=headers)

    # -------------------------------------------------------- fiber receipts ---
    def get_receipt(self, receipt_id, headers):
        return self._request("GET", f"/fiber-receipts/{receipt_id}", headers=headers)

    def list_receipts(self, headers, params=None):
        return self._request("GET", "/fiber-receipts", headers=headers, params=params)

    def disposition_receipt(self, receipt_id, payload, headers):
        return self._request("POST", f"/fiber-receipts/{receipt_id}/disposition",
                             payload, headers=headers)

    # -------------------------------------------------------- inventory lots ---
    def get_inventory_lot(self, lot_id, headers):
        return self._request("GET", f"/fiber-inventory-lots/{lot_id}", headers=headers)

    def list_inventory_lots(self, headers, params=None):
        return self._request("GET", "/fiber-inventory-lots", headers=headers, params=params)

    # ----------------------------------------------------------- pulp batches ---
    def create_pulp_batch(self, payload, headers):
        return self._request("POST", "/pulp-batches", payload, headers=headers)

    def get_pulp_batch(self, batch_id, headers):
        return self._request("GET", f"/pulp-batches/{batch_id}", headers=headers)

    def list_pulp_batches(self, headers, params=None):
        return self._request("GET", "/pulp-batches", headers=headers, params=params)

    def start_pulp_batch(self, batch_id, headers):
        return self._request("POST", f"/pulp-batches/{batch_id}/start", {}, headers=headers)

    def screen_pulp_batch(self, batch_id, headers):
        return self._request("POST", f"/pulp-batches/{batch_id}/screen", {}, headers=headers)

    def clean_pulp_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/pulp-batches/{batch_id}/clean", payload, headers=headers)

    def deink_pulp_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/pulp-batches/{batch_id}/deink", payload, headers=headers)

    def record_brightness(self, batch_id, payload, headers):
        return self._request("POST", f"/pulp-batches/{batch_id}/brightness",
                             payload, headers=headers)

    def approve_pulp_batch(self, batch_id, headers):
        return self._request("POST", f"/pulp-batches/{batch_id}/approve", {}, headers=headers)

    def divert_pulp_batch(self, batch_id, headers):
        return self._request("POST", f"/pulp-batches/{batch_id}/divert", {}, headers=headers)

    def cancel_pulp_batch(self, batch_id, headers):
        return self._request("POST", f"/pulp-batches/{batch_id}/cancel", {}, headers=headers)

    # -------------------------------------------------------- production runs ---
    def create_run(self, machine_id, payload, headers):
        return self._request("POST", f"/paper-machines/{machine_id}/runs",
                             payload, headers=headers)

    def list_machine_runs(self, machine_id, headers, params=None):
        return self._request("GET", f"/paper-machines/{machine_id}/runs",
                             headers=headers, params=params)

    def get_run(self, run_id, headers):
        return self._request("GET", f"/production-runs/{run_id}", headers=headers)

    def list_runs(self, headers, params=None):
        return self._request("GET", "/production-runs", headers=headers, params=params)

    def start_run(self, machine_id, run_id, headers):
        return self._request("POST", f"/paper-machines/{machine_id}/runs/{run_id}/start",
                             {}, headers=headers)

    def complete_run(self, machine_id, run_id, payload, headers):
        return self._request("POST", f"/paper-machines/{machine_id}/runs/{run_id}/complete",
                             payload, headers=headers)

    def abort_run(self, machine_id, run_id, headers):
        return self._request("POST", f"/paper-machines/{machine_id}/runs/{run_id}/abort",
                             {}, headers=headers)

    def certify_run(self, machine_id, run_id, headers):
        return self._request("POST", f"/paper-machines/{machine_id}/runs/{run_id}/certify",
                             {}, headers=headers)

    def hold_run(self, machine_id, run_id, headers):
        return self._request("POST", f"/paper-machines/{machine_id}/runs/{run_id}/hold",
                             {}, headers=headers)

    def rework_run(self, machine_id, run_id, headers):
        return self._request("POST", f"/paper-machines/{machine_id}/runs/{run_id}/rework",
                             {}, headers=headers)

    def resubmit_run_quality(self, machine_id, run_id, payload, headers):
        return self._request(
            "POST", f"/paper-machines/{machine_id}/runs/{run_id}/resubmit-quality",
            payload, headers=headers)

    def condemn_run(self, machine_id, run_id, headers):
        return self._request("POST", f"/paper-machines/{machine_id}/runs/{run_id}/condemn",
                             {}, headers=headers)

    # ---------------------------------------------------------- grade changes ---
    def create_grade_change(self, machine_id, payload, headers):
        return self._request("POST", f"/paper-machines/{machine_id}/grade-changes",
                             payload, headers=headers)

    def get_grade_change(self, gc_id, headers):
        return self._request("GET", f"/grade-changes/{gc_id}", headers=headers)

    def list_grade_changes(self, headers, params=None):
        return self._request("GET", "/grade-changes", headers=headers, params=params)

    def void_grade_change(self, gc_id, headers):
        return self._request("POST", f"/grade-changes/{gc_id}/void", {}, headers=headers)

    # --------------------------------------------------------------- roll sets ---
    def create_roll_set(self, run_id, payload, headers):
        return self._request("POST", f"/production-runs/{run_id}/roll-sets",
                             payload, headers=headers)

    def get_roll_set(self, roll_set_id, headers):
        return self._request("GET", f"/roll-sets/{roll_set_id}", headers=headers)

    def list_roll_sets(self, headers, params=None):
        return self._request("GET", "/roll-sets", headers=headers, params=params)

    def wrap_roll_set(self, roll_set_id, payload, headers):
        return self._request("POST", f"/roll-sets/{roll_set_id}/wrap", payload, headers=headers)

    def allocate_roll_set(self, roll_set_id, payload, headers):
        return self._request("POST", f"/roll-sets/{roll_set_id}/allocate",
                             payload, headers=headers)

    def quarantine_roll_set(self, roll_set_id, payload, headers):
        return self._request("POST", f"/roll-sets/{roll_set_id}/quarantine",
                             payload, headers=headers)

    def rewind_roll_set(self, roll_set_id, headers):
        return self._request("POST", f"/roll-sets/{roll_set_id}/rewind", {}, headers=headers)

    def rewind_complete_roll_set(self, roll_set_id, payload, headers):
        return self._request("POST", f"/roll-sets/{roll_set_id}/rewind-complete",
                             payload, headers=headers)

    def scrap_roll_set(self, roll_set_id, headers):
        return self._request("POST", f"/roll-sets/{roll_set_id}/scrap", {}, headers=headers)

    # ---------------------------------------------------------- customer orders ---
    def create_customer_order(self, payload, headers):
        return self._request("POST", "/customer-orders", payload, headers=headers)

    def get_customer_order(self, order_id, headers):
        return self._request("GET", f"/customer-orders/{order_id}", headers=headers)

    def list_customer_orders(self, headers, params=None):
        return self._request("GET", "/customer-orders", headers=headers, params=params)

    def schedule_customer_order(self, order_id, payload, headers):
        return self._request("POST", f"/customer-orders/{order_id}/schedule",
                             payload, headers=headers)

    def deschedule_customer_order(self, order_id, headers):
        return self._request("POST", f"/customer-orders/{order_id}/deschedule",
                             {}, headers=headers)

    def ship_customer_order(self, order_id, headers):
        return self._request("POST", f"/customer-orders/{order_id}/ship", {}, headers=headers)

    def short_close_customer_order(self, order_id, headers):
        return self._request("POST", f"/customer-orders/{order_id}/short-close",
                             {}, headers=headers)

    def cancel_customer_order(self, order_id, headers):
        return self._request("POST", f"/customer-orders/{order_id}/cancel", {}, headers=headers)

    # -------------------------------------------------------- effluent permits ---
    def create_effluent_permit(self, payload, headers):
        return self._request("POST", "/effluent-permits", payload, headers=headers)

    def get_effluent_permit(self, permit_id, headers):
        return self._request("GET", f"/effluent-permits/{permit_id}", headers=headers)

    def create_effluent_reading(self, permit_id, payload, headers):
        return self._request("POST", f"/effluent-permits/{permit_id}/readings",
                             payload, headers=headers)

    def list_permit_readings(self, permit_id, headers, params=None):
        return self._request("GET", f"/effluent-permits/{permit_id}/readings",
                             headers=headers, params=params)

    def get_effluent_reading(self, reading_id, headers):
        return self._request("GET", f"/effluent-readings/{reading_id}", headers=headers)

    def void_effluent_reading(self, reading_id, headers):
        return self._request("POST", f"/effluent-readings/{reading_id}/void",
                             {}, headers=headers)

    # -------------------------------------------------------- sludge manifests ---
    def create_sludge_manifest(self, payload, headers):
        return self._request("POST", "/sludge-manifests", payload, headers=headers)

    def get_sludge_manifest(self, manifest_id, headers):
        return self._request("GET", f"/sludge-manifests/{manifest_id}", headers=headers)

    def sign_sludge_manifest(self, manifest_id, headers):
        return self._request("POST", f"/sludge-manifests/{manifest_id}/sign",
                             {}, headers=headers)

    def void_sludge_manifest(self, manifest_id, headers):
        return self._request("POST", f"/sludge-manifests/{manifest_id}/void",
                             {}, headers=headers)

    # ---------------------------------------------------------- reject streams ---
    def get_reject_stream(self, row_id, headers):
        return self._request("GET", f"/reject-streams/{row_id}", headers=headers)

    def list_reject_streams(self, headers, params=None):
        return self._request("GET", "/reject-streams", headers=headers, params=params)

    def reverse_reject_stream(self, row_id, headers):
        return self._request("POST", f"/reject-streams/{row_id}/reverse", {}, headers=headers)

    def get_solids_summary(self, headers):
        return self._request("GET", "/reject-streams/summary", headers=headers)

    def get_fiber_balance(self, headers):
        return self._request("GET", "/mill/fiber-balance", headers=headers)

    # -------------------------------------------------------- steam allocations ---
    def create_steam_allocation(self, payload, headers):
        return self._request("POST", "/steam-allocations", payload, headers=headers)

    def get_steam_allocation(self, allocation_id, headers):
        return self._request("GET", f"/steam-allocations/{allocation_id}", headers=headers)

    def list_steam_allocations(self, headers, params=None):
        return self._request("GET", "/steam-allocations", headers=headers, params=params)

    def release_steam_allocation(self, allocation_id, headers):
        return self._request("POST", f"/steam-allocations/{allocation_id}/release",
                             {}, headers=headers)


api_client = ApiClient()
