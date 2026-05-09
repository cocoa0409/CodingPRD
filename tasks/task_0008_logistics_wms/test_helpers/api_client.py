"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- Warehouse -----
    def create_warehouse(self, payload, headers):
        return self._request("POST", "/warehouses", payload, headers)

    def get_warehouse(self, warehouse_id, headers):
        return self._request("GET", f"/warehouses/{warehouse_id}", headers=headers)

    def run_ops(self, warehouse_id, headers):
        return self._request("POST", f"/warehouses/{warehouse_id}/run_ops", {}, headers)

    # ----- Bin -----
    def create_bin(self, warehouse_id, payload, headers):
        return self._request("POST", f"/warehouses/{warehouse_id}/bins", payload, headers)

    def get_bin(self, warehouse_id, bin_id, headers):
        return self._request("GET", f"/warehouses/{warehouse_id}/bins/{bin_id}", headers=headers)

    def list_bins(self, warehouse_id, headers, params=None):
        return self._request("GET", f"/warehouses/{warehouse_id}/bins", headers=headers, params=params)

    # ----- Lot -----
    def create_lot(self, warehouse_id, payload, headers):
        return self._request("POST", f"/warehouses/{warehouse_id}/lots", payload, headers)

    def get_lot(self, warehouse_id, lot_id, headers):
        return self._request("GET", f"/warehouses/{warehouse_id}/lots/{lot_id}", headers=headers)

    def recall_lot(self, warehouse_id, lot_id, payload, headers):
        return self._request("POST", f"/warehouses/{warehouse_id}/lots/{lot_id}/recall", payload, headers)

    def dispose_lot(self, warehouse_id, lot_id, headers):
        return self._request("POST", f"/warehouses/{warehouse_id}/lots/{lot_id}/dispose", {}, headers)

    # ----- InboundShipment -----
    def create_inbound_shipment(self, warehouse_id, payload, headers):
        return self._request("POST", f"/warehouses/{warehouse_id}/inbound_shipments", payload, headers)

    def get_inbound_shipment(self, warehouse_id, shipment_id, headers):
        return self._request("GET", f"/warehouses/{warehouse_id}/inbound_shipments/{shipment_id}", headers=headers)

    def start_inspection(self, warehouse_id, shipment_id, headers):
        return self._request("POST", f"/warehouses/{warehouse_id}/inbound_shipments/{shipment_id}/start_inspection", {}, headers)

    def complete_inspection(self, warehouse_id, shipment_id, payload, headers):
        return self._request("POST", f"/warehouses/{warehouse_id}/inbound_shipments/{shipment_id}/complete_inspection", payload, headers)

    def rework_inbound_shipment(self, warehouse_id, shipment_id, headers):
        return self._request("POST", f"/warehouses/{warehouse_id}/inbound_shipments/{shipment_id}/rework", {}, headers)

    def putaway_inbound_shipment(self, warehouse_id, shipment_id, headers):
        return self._request("POST", f"/warehouses/{warehouse_id}/inbound_shipments/{shipment_id}/putaway", {}, headers)

    def quarantine_inbound_shipment(self, warehouse_id, shipment_id, headers):
        return self._request("POST", f"/warehouses/{warehouse_id}/inbound_shipments/{shipment_id}/quarantine", {}, headers)

    # ----- Inventory -----
    def list_inventory(self, warehouse_id, headers, params=None):
        return self._request("GET", f"/warehouses/{warehouse_id}/inventory", headers=headers, params=params)

    # ----- Wave -----
    def create_wave(self, warehouse_id, payload, headers):
        return self._request("POST", f"/warehouses/{warehouse_id}/waves", payload, headers)

    def get_wave(self, warehouse_id, wave_id, headers):
        return self._request("GET", f"/warehouses/{warehouse_id}/waves/{wave_id}", headers=headers)

    def release_wave(self, warehouse_id, wave_id, headers):
        return self._request("POST", f"/warehouses/{warehouse_id}/waves/{wave_id}/release", {}, headers)

    def cancel_wave(self, warehouse_id, wave_id, headers):
        return self._request("POST", f"/warehouses/{warehouse_id}/waves/{wave_id}/cancel", {}, headers)

    # ----- Order -----
    def create_order(self, warehouse_id, payload, headers):
        return self._request("POST", f"/warehouses/{warehouse_id}/orders", payload, headers)

    def get_order(self, warehouse_id, order_id, headers):
        return self._request("GET", f"/warehouses/{warehouse_id}/orders/{order_id}", headers=headers)

    def allocate_order(self, warehouse_id, order_id, headers):
        return self._request("POST", f"/warehouses/{warehouse_id}/orders/{order_id}/allocate", {}, headers)

    def cancel_order(self, warehouse_id, order_id, headers):
        return self._request("POST", f"/warehouses/{warehouse_id}/orders/{order_id}/cancel", {}, headers)

    def replan_order(self, warehouse_id, order_id, headers):
        return self._request("POST", f"/warehouses/{warehouse_id}/orders/{order_id}/replan", {}, headers)

    def pack_order(self, warehouse_id, order_id, payload, headers):
        return self._request("POST", f"/warehouses/{warehouse_id}/orders/{order_id}/pack", payload, headers)

    def ship_order(self, warehouse_id, order_id, headers):
        return self._request("POST", f"/warehouses/{warehouse_id}/orders/{order_id}/ship", {}, headers)

    # ----- PickTask -----
    def get_pick_task(self, warehouse_id, pick_task_id, headers):
        return self._request("GET", f"/warehouses/{warehouse_id}/pick_tasks/{pick_task_id}", headers=headers)

    def start_pick_task(self, warehouse_id, pick_task_id, headers):
        return self._request("POST", f"/warehouses/{warehouse_id}/pick_tasks/{pick_task_id}/start", {}, headers)

    def complete_pick_task(self, warehouse_id, pick_task_id, payload, headers):
        return self._request("POST", f"/warehouses/{warehouse_id}/pick_tasks/{pick_task_id}/complete", payload, headers)

    # ----- CycleCount -----
    def create_cycle_count(self, warehouse_id, payload, headers):
        return self._request("POST", f"/warehouses/{warehouse_id}/cycle_counts", payload, headers)

    def get_cycle_count(self, warehouse_id, cycle_count_id, headers):
        return self._request("GET", f"/warehouses/{warehouse_id}/cycle_counts/{cycle_count_id}", headers=headers)

    def start_cycle_count(self, warehouse_id, cycle_count_id, headers):
        return self._request("POST", f"/warehouses/{warehouse_id}/cycle_counts/{cycle_count_id}/start", {}, headers)

    def submit_cycle_count(self, warehouse_id, cycle_count_id, payload, headers):
        return self._request("POST", f"/warehouses/{warehouse_id}/cycle_counts/{cycle_count_id}/submit_count", payload, headers)

    def approve_cycle_count(self, warehouse_id, cycle_count_id, headers):
        return self._request("POST", f"/warehouses/{warehouse_id}/cycle_counts/{cycle_count_id}/approve_adjustment", {}, headers)

    def dispute_cycle_count(self, warehouse_id, cycle_count_id, headers):
        return self._request("POST", f"/warehouses/{warehouse_id}/cycle_counts/{cycle_count_id}/dispute", {}, headers)

    # ----- Clock (test driver) -----
    def advance_clock(self, payload, headers):
        return self._request("POST", "/_clock/advance", payload, headers)


api_client = ApiClient()
