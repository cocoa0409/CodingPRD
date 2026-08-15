"""API client: one method per endpoint defined in the PRD (all under /plant)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- CustomerAccount ---
    def create_customer_account(self, payload, headers):
        return self._request("POST", "/plant/customer-accounts", payload, headers)

    def get_customer_account(self, customer_id, headers):
        return self._request("GET", f"/plant/customer-accounts/{customer_id}", headers=headers)

    def list_customer_accounts(self, headers, params=None):
        return self._request("GET", "/plant/customer-accounts", headers=headers, params=params)

    def update_customer_account(self, customer_id, payload, headers):
        return self._request("PATCH", f"/plant/customer-accounts/{customer_id}", payload, headers)

    # --- Engineer ---
    def create_engineer(self, payload, headers):
        return self._request("POST", "/plant/engineers", payload, headers)

    def get_engineer(self, engineer_id, headers):
        return self._request("GET", f"/plant/engineers/{engineer_id}", headers=headers)

    def list_engineers(self, headers, params=None):
        return self._request("GET", "/plant/engineers", headers=headers, params=params)

    # --- Job ---
    def create_job(self, payload, headers):
        return self._request("POST", "/plant/jobs", payload, headers)

    def get_job(self, job_id, headers):
        return self._request("GET", f"/plant/jobs/{job_id}", headers=headers)

    def list_jobs(self, headers, params=None):
        return self._request("GET", "/plant/jobs", headers=headers, params=params)

    def confirm_job(self, job_id, headers):
        return self._request("POST", f"/plant/jobs/{job_id}/confirm", None, headers)

    def cancel_job(self, job_id, headers):
        return self._request("POST", f"/plant/jobs/{job_id}/cancel", None, headers)

    # --- ComponentDesign ---
    def create_design(self, job_id, payload, headers):
        return self._request("POST", f"/plant/jobs/{job_id}/designs", payload, headers)

    def get_design(self, design_id, headers):
        return self._request("GET", f"/plant/designs/{design_id}", headers=headers)

    def list_designs(self, headers, params=None):
        return self._request("GET", "/plant/designs", headers=headers, params=params)

    def transition_design(self, design_id, payload, headers):
        return self._request("POST", f"/plant/designs/{design_id}/transition", payload, headers)

    # --- CutList / CutListLine ---
    def create_cut_list(self, design_id, payload, headers):
        return self._request("POST", f"/plant/designs/{design_id}/cut-lists", payload, headers)

    def get_cut_list(self, cut_list_id, headers):
        return self._request("GET", f"/plant/cut-lists/{cut_list_id}", headers=headers)

    def list_cut_lists(self, headers, params=None):
        return self._request("GET", "/plant/cut-lists", headers=headers, params=params)

    def release_cut_list(self, cut_list_id, headers):
        return self._request("POST", f"/plant/cut-lists/{cut_list_id}/release", None, headers)

    def reconcile_cut_list(self, cut_list_id, headers):
        return self._request("POST", f"/plant/cut-lists/{cut_list_id}/reconcile", None, headers)

    def list_cut_list_lines(self, headers, params=None):
        return self._request("GET", "/plant/cut-list-lines", headers=headers, params=params)

    def get_cut_list_line(self, line_id, headers):
        return self._request("GET", f"/plant/cut-list-lines/{line_id}", headers=headers)

    def mark_cut_line(self, line_id, headers):
        return self._request("POST", f"/plant/cut-list-lines/{line_id}/mark-cut", None, headers)

    def scrap_line(self, line_id, headers):
        return self._request("POST", f"/plant/cut-list-lines/{line_id}/scrap", None, headers)

    # --- JigSetup ---
    def create_jig_setup(self, payload, headers):
        return self._request("POST", "/plant/jig-setups", payload, headers)

    def get_jig_setup(self, jig_id, headers):
        return self._request("GET", f"/plant/jig-setups/{jig_id}", headers=headers)

    def list_jig_setups(self, headers, params=None):
        return self._request("GET", "/plant/jig-setups", headers=headers, params=params)

    # --- InventoryLot ---
    def create_inventory_lot(self, payload, headers):
        return self._request("POST", "/plant/inventory-lots", payload, headers)

    def get_inventory_lot(self, lot_id, headers):
        return self._request("GET", f"/plant/inventory-lots/{lot_id}", headers=headers)

    def list_inventory_lots(self, headers, params=None):
        return self._request("GET", "/plant/inventory-lots", headers=headers, params=params)

    def adjust_inventory_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/plant/inventory-lots/{lot_id}/adjust", payload, headers)

    def transition_inventory_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/plant/inventory-lots/{lot_id}/transition", payload, headers)

    # --- MaterialReservation ---
    def create_reservation(self, payload, headers):
        return self._request("POST", "/plant/material-reservations", payload, headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/plant/material-reservations", headers=headers, params=params)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/plant/material-reservations/{reservation_id}", headers=headers)

    def consume_reservation(self, reservation_id, headers):
        return self._request("POST", f"/plant/material-reservations/{reservation_id}/consume", None, headers)

    def release_reservation(self, reservation_id, headers):
        return self._request("POST", f"/plant/material-reservations/{reservation_id}/release", None, headers)

    # --- CraneResource / CraneSlot ---
    def create_crane(self, payload, headers):
        return self._request("POST", "/plant/cranes", payload, headers)

    def get_crane(self, crane_id, headers):
        return self._request("GET", f"/plant/cranes/{crane_id}", headers=headers)

    def list_cranes(self, headers, params=None):
        return self._request("GET", "/plant/cranes", headers=headers, params=params)

    def transition_crane(self, crane_id, payload, headers):
        return self._request("POST", f"/plant/cranes/{crane_id}/transition", payload, headers)

    def create_crane_slot(self, payload, headers):
        return self._request("POST", "/plant/crane-slots", payload, headers)

    def list_crane_slots(self, headers, params=None):
        return self._request("GET", "/plant/crane-slots", headers=headers, params=params)

    def get_crane_slot(self, slot_id, headers):
        return self._request("GET", f"/plant/crane-slots/{slot_id}", headers=headers)

    def transition_crane_slot(self, slot_id, payload, headers):
        return self._request("POST", f"/plant/crane-slots/{slot_id}/transition", payload, headers)

    # --- ProductionBatch ---
    def create_batch(self, job_id, payload, headers):
        return self._request("POST", f"/plant/jobs/{job_id}/batches", payload, headers)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/plant/batches/{batch_id}", headers=headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/plant/batches", headers=headers, params=params)

    def transition_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/plant/batches/{batch_id}/transition", payload, headers)

    # --- DeliveryLoad / Bundle ---
    def create_load(self, job_id, payload, headers):
        return self._request("POST", f"/plant/jobs/{job_id}/loads", payload, headers)

    def get_load(self, load_id, headers):
        return self._request("GET", f"/plant/loads/{load_id}", headers=headers)

    def list_loads(self, headers, params=None):
        return self._request("GET", "/plant/loads", headers=headers, params=params)

    def transition_load(self, load_id, payload, headers):
        return self._request("POST", f"/plant/loads/{load_id}/transition", payload, headers)

    def create_bundle(self, load_id, payload, headers):
        return self._request("POST", f"/plant/loads/{load_id}/bundles", payload, headers)

    def get_bundle(self, bundle_id, headers):
        return self._request("GET", f"/plant/bundles/{bundle_id}", headers=headers)

    def list_bundles(self, headers, params=None):
        return self._request("GET", "/plant/bundles", headers=headers, params=params)

    # --- DamageClaim ---
    def create_claim(self, load_id, payload, headers):
        return self._request("POST", f"/plant/loads/{load_id}/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/plant/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/plant/claims", headers=headers, params=params)

    def triage_claim(self, claim_id, headers):
        return self._request("POST", f"/plant/claims/{claim_id}/triage", None, headers)

    def decide_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/plant/claims/{claim_id}/decide", payload, headers)

    def settle_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/plant/claims/{claim_id}/settle", payload, headers)

    def void_claim(self, claim_id, headers):
        return self._request("POST", f"/plant/claims/{claim_id}/void", None, headers)

    # --- DesignChangeOrder ---
    def create_change_order(self, job_id, payload, headers):
        return self._request("POST", f"/plant/jobs/{job_id}/change-orders", payload, headers)

    def get_change_order(self, order_id, headers):
        return self._request("GET", f"/plant/change-orders/{order_id}", headers=headers)

    def list_change_orders(self, headers, params=None):
        return self._request("GET", "/plant/change-orders", headers=headers, params=params)

    def assess_change_order(self, order_id, payload, headers):
        return self._request("POST", f"/plant/change-orders/{order_id}/assess", payload, headers)

    def approve_change_order(self, order_id, headers):
        return self._request("POST", f"/plant/change-orders/{order_id}/approve", None, headers)

    def reject_change_order(self, order_id, headers):
        return self._request("POST", f"/plant/change-orders/{order_id}/reject", None, headers)

    def apply_change_order(self, order_id, headers):
        return self._request("POST", f"/plant/change-orders/{order_id}/apply", None, headers)

    def withdraw_change_order(self, order_id, headers):
        return self._request("POST", f"/plant/change-orders/{order_id}/withdraw", None, headers)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/plant/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
