"""API client: one method per endpoint defined in the 3PL fulfillment PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Client ---
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def suspend_client(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/suspend", {}, headers)

    # --- Sku ---
    def create_sku(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/skus", payload, headers)

    def list_client_skus(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/skus", headers=headers, params=params)

    def list_skus(self, headers, params=None):
        return self._request("GET", "/skus", headers=headers, params=params)

    def get_client_sku(self, client_id, sku_id, headers):
        return self._request("GET", f"/clients/{client_id}/skus/{sku_id}", headers=headers)

    def get_sku(self, sku_id, headers):
        return self._request("GET", f"/skus/{sku_id}", headers=headers)

    def discontinue_sku(self, client_id, sku_id, headers):
        return self._request("POST", f"/clients/{client_id}/skus/{sku_id}/discontinue", {}, headers)

    # --- Bin ---
    def create_bin(self, payload, headers):
        return self._request("POST", "/bins", payload, headers)

    def list_bins(self, headers, params=None):
        return self._request("GET", "/bins", headers=headers, params=params)

    def get_bin(self, bin_id, headers):
        return self._request("GET", f"/bins/{bin_id}", headers=headers)

    def block_bin(self, bin_id, headers):
        return self._request("POST", f"/bins/{bin_id}/block", {}, headers)

    # --- InventoryLot ---
    def list_inventory_lots(self, headers, params=None):
        return self._request("GET", "/inventory-lots", headers=headers, params=params)

    def get_inventory_lot(self, lot_id, headers):
        return self._request("GET", f"/inventory-lots/{lot_id}", headers=headers)

    # --- Receipt ---
    def create_receipt(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/receipts", payload, headers)

    def list_client_receipts(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/receipts", headers=headers, params=params)

    def list_receipts(self, headers, params=None):
        return self._request("GET", "/receipts", headers=headers, params=params)

    def get_client_receipt(self, client_id, receipt_id, headers):
        return self._request("GET", f"/clients/{client_id}/receipts/{receipt_id}", headers=headers)

    def get_receipt(self, receipt_id, headers):
        return self._request("GET", f"/receipts/{receipt_id}", headers=headers)

    def receive_receipt(self, client_id, receipt_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/receipts/{receipt_id}/receive", payload, headers)

    def putaway_receipt(self, client_id, receipt_id, headers):
        return self._request("POST", f"/clients/{client_id}/receipts/{receipt_id}/putaway", {}, headers)

    def cancel_receipt(self, client_id, receipt_id, headers):
        return self._request("POST", f"/clients/{client_id}/receipts/{receipt_id}/cancel", {}, headers)

    # --- Order ---
    def create_order(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/orders", payload, headers)

    def list_client_orders(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/orders", headers=headers, params=params)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def get_client_order(self, client_id, order_id, headers):
        return self._request("GET", f"/clients/{client_id}/orders/{order_id}", headers=headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def pack_order(self, client_id, order_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/orders/{order_id}/pack", payload, headers)

    def ship_order(self, client_id, order_id, headers):
        return self._request("POST", f"/clients/{client_id}/orders/{order_id}/ship", {}, headers)

    def short_order(self, client_id, order_id, headers):
        return self._request("POST", f"/clients/{client_id}/orders/{order_id}/short", {}, headers)

    def cancel_order(self, client_id, order_id, headers):
        return self._request("POST", f"/clients/{client_id}/orders/{order_id}/cancel", {}, headers)

    # --- Wave ---
    def create_wave(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/waves", {}, headers)

    def list_client_waves(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/waves", headers=headers, params=params)

    def list_waves(self, headers, params=None):
        return self._request("GET", "/waves", headers=headers, params=params)

    def get_client_wave(self, client_id, wave_id, headers):
        return self._request("GET", f"/clients/{client_id}/waves/{wave_id}", headers=headers)

    def get_wave(self, wave_id, headers):
        return self._request("GET", f"/waves/{wave_id}", headers=headers)

    def add_order_to_wave(self, client_id, wave_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/waves/{wave_id}/add-order", payload, headers)

    def release_wave(self, client_id, wave_id, headers):
        return self._request("POST", f"/clients/{client_id}/waves/{wave_id}/release", {}, headers)

    def cancel_wave(self, client_id, wave_id, headers):
        return self._request("POST", f"/clients/{client_id}/waves/{wave_id}/cancel", {}, headers)

    # --- PickTask ---
    def list_pick_tasks(self, headers, params=None):
        return self._request("GET", "/pick-tasks", headers=headers, params=params)

    def get_pick_task(self, pick_task_id, headers):
        return self._request("GET", f"/pick-tasks/{pick_task_id}", headers=headers)

    def confirm_pick(self, client_id, pick_task_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/pick-tasks/{pick_task_id}/confirm", payload, headers)

    # --- Carton ---
    def list_cartons(self, headers, params=None):
        return self._request("GET", "/cartons", headers=headers, params=params)

    def get_carton(self, carton_id, headers):
        return self._request("GET", f"/cartons/{carton_id}", headers=headers)

    # --- Shipment ---
    def create_shipment(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/shipments", payload, headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/shipments/{shipment_id}", headers=headers)

    def deliver_shipment(self, client_id, shipment_id, headers):
        return self._request("POST", f"/clients/{client_id}/shipments/{shipment_id}/deliver", {}, headers)

    def void_shipment(self, client_id, shipment_id, headers):
        return self._request("POST", f"/clients/{client_id}/shipments/{shipment_id}/void", {}, headers)

    # --- Return ---
    def create_return(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/returns", payload, headers)

    def list_client_returns(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/returns", headers=headers, params=params)

    def list_returns(self, headers, params=None):
        return self._request("GET", "/returns", headers=headers, params=params)

    def get_client_return(self, client_id, return_id, headers):
        return self._request("GET", f"/clients/{client_id}/returns/{return_id}", headers=headers)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/returns/{return_id}", headers=headers)

    def grade_return(self, client_id, return_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/returns/{return_id}/grade", payload, headers)

    def close_return(self, client_id, return_id, headers):
        return self._request("POST", f"/clients/{client_id}/returns/{return_id}/close", {}, headers)

    # --- CycleCount ---
    def create_cycle_count(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/cycle-counts", payload, headers)

    def list_cycle_counts(self, headers, params=None):
        return self._request("GET", "/cycle-counts", headers=headers, params=params)

    def get_cycle_count(self, cycle_count_id, headers):
        return self._request("GET", f"/cycle-counts/{cycle_count_id}", headers=headers)

    # --- BillingCharge ---
    def accrue_storage(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/storage/accrue", payload, headers)

    def list_billing_charges(self, headers, params=None):
        return self._request("GET", "/billing-charges", headers=headers, params=params)

    def get_billing_charge(self, charge_id, headers):
        return self._request("GET", f"/billing-charges/{charge_id}", headers=headers)

    def list_client_billing_charges(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/billing-charges", headers=headers, params=params)

    def get_client_billing_charge(self, client_id, charge_id, headers):
        return self._request("GET", f"/clients/{client_id}/billing-charges/{charge_id}", headers=headers)


api_client = ApiClient()
