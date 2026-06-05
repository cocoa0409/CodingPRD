"""API client: one method per endpoint defined in the Warehouse Management PRD (Section 4).

All paths are mounted under the /warehouse prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Sku ────────────────────────────────────────────────────────────────
    def create_sku(self, payload, headers):
        return self._request("POST", "/warehouse/skus", payload, headers)

    def get_sku(self, sku_id, headers):
        return self._request("GET", f"/warehouse/skus/{sku_id}", headers=headers)

    def list_skus(self, headers, params=None):
        return self._request("GET", "/warehouse/skus", headers=headers, params=params)

    # ── Location ───────────────────────────────────────────────────────────
    def create_location(self, payload, headers):
        return self._request("POST", "/warehouse/locations", payload, headers)

    def get_location(self, location_id, headers):
        return self._request("GET", f"/warehouse/locations/{location_id}", headers=headers)

    def list_locations(self, headers, params=None):
        return self._request("GET", "/warehouse/locations", headers=headers, params=params)

    def block_location(self, location_id, headers):
        return self._request("POST", f"/warehouse/locations/{location_id}/block", {}, headers)

    def unblock_location(self, location_id, headers):
        return self._request("POST", f"/warehouse/locations/{location_id}/unblock", {}, headers)

    # ── InboundAsn / AsnLine / ReceiptEvent ──────────────────────────────────
    def create_inbound_asn(self, payload, headers):
        return self._request("POST", "/warehouse/inbound-asns", payload, headers)

    def get_inbound_asn(self, asn_id, headers):
        return self._request("GET", f"/warehouse/inbound-asns/{asn_id}", headers=headers)

    def list_inbound_asns(self, headers, params=None):
        return self._request("GET", "/warehouse/inbound-asns", headers=headers, params=params)

    def add_asn_line(self, asn_id, payload, headers):
        return self._request("POST", f"/warehouse/inbound-asns/{asn_id}/lines", payload, headers)

    def list_asn_lines_of_asn(self, asn_id, headers):
        return self._request("GET", f"/warehouse/inbound-asns/{asn_id}/lines", headers=headers)

    def get_asn_line(self, line_id, headers):
        return self._request("GET", f"/warehouse/asn-lines/{line_id}", headers=headers)

    def list_asn_lines(self, headers, params=None):
        return self._request("GET", "/warehouse/asn-lines", headers=headers, params=params)

    def post_receipt(self, asn_id, payload, headers):
        return self._request("POST", f"/warehouse/inbound-asns/{asn_id}/receipts", payload, headers)

    def list_receipts_of_asn(self, asn_id, headers):
        return self._request("GET", f"/warehouse/inbound-asns/{asn_id}/receipts", headers=headers)

    def get_receipt_event(self, receipt_id, headers):
        return self._request("GET", f"/warehouse/receipt-events/{receipt_id}", headers=headers)

    def list_receipt_events(self, headers, params=None):
        return self._request("GET", "/warehouse/receipt-events", headers=headers, params=params)

    def close_asn(self, asn_id, headers):
        return self._request("POST", f"/warehouse/inbound-asns/{asn_id}/close", {}, headers)

    def close_crossdock_asn(self, asn_id, headers):
        return self._request("POST", f"/warehouse/inbound-asns/{asn_id}/close-crossdock", {}, headers)

    def cancel_asn(self, asn_id, headers):
        return self._request("POST", f"/warehouse/inbound-asns/{asn_id}/cancel", {}, headers)

    # ── LicensePlate ─────────────────────────────────────────────────────────
    def get_license_plate(self, lpn_id, headers):
        return self._request("GET", f"/warehouse/license-plates/{lpn_id}", headers=headers)

    def list_license_plates(self, headers, params=None):
        return self._request("GET", "/warehouse/license-plates", headers=headers, params=params)

    # ── PutawayTask ──────────────────────────────────────────────────────────
    def get_putaway_task(self, task_id, headers):
        return self._request("GET", f"/warehouse/putaway-tasks/{task_id}", headers=headers)

    def list_putaway_tasks(self, headers, params=None):
        return self._request("GET", "/warehouse/putaway-tasks", headers=headers, params=params)

    def assign_putaway_task(self, task_id, headers):
        return self._request("POST", f"/warehouse/putaway-tasks/{task_id}/assign", {}, headers)

    def complete_putaway_task(self, task_id, headers):
        return self._request("POST", f"/warehouse/putaway-tasks/{task_id}/complete", {}, headers)

    def cancel_putaway_task(self, task_id, headers):
        return self._request("POST", f"/warehouse/putaway-tasks/{task_id}/cancel", {}, headers)

    # ── OutboundOrder / OrderLine ────────────────────────────────────────────
    def create_outbound_order(self, payload, headers):
        return self._request("POST", "/warehouse/outbound-orders", payload, headers)

    def get_outbound_order(self, order_id, headers):
        return self._request("GET", f"/warehouse/outbound-orders/{order_id}", headers=headers)

    def list_outbound_orders(self, headers, params=None):
        return self._request("GET", "/warehouse/outbound-orders", headers=headers, params=params)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/warehouse/outbound-orders/{order_id}/lines", payload, headers)

    def list_order_lines_of_order(self, order_id, headers):
        return self._request("GET", f"/warehouse/outbound-orders/{order_id}/lines", headers=headers)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/warehouse/order-lines/{line_id}", headers=headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/warehouse/order-lines", headers=headers, params=params)

    def ship_order(self, order_id, headers):
        return self._request("POST", f"/warehouse/outbound-orders/{order_id}/ship", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/warehouse/outbound-orders/{order_id}/cancel", {}, headers)

    # ── InventoryAllocation ──────────────────────────────────────────────────
    def create_allocation(self, payload, headers):
        return self._request("POST", "/warehouse/allocations", payload, headers)

    def get_allocation(self, alloc_id, headers):
        return self._request("GET", f"/warehouse/allocations/{alloc_id}", headers=headers)

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/warehouse/allocations", headers=headers, params=params)

    def cancel_allocation(self, alloc_id, headers):
        return self._request("POST", f"/warehouse/allocations/{alloc_id}/cancel", {}, headers)

    # ── Wave / PickTask ──────────────────────────────────────────────────────
    def create_wave(self, payload, headers):
        return self._request("POST", "/warehouse/waves", payload, headers)

    def get_wave(self, wave_id, headers):
        return self._request("GET", f"/warehouse/waves/{wave_id}", headers=headers)

    def list_waves(self, headers, params=None):
        return self._request("GET", "/warehouse/waves", headers=headers, params=params)

    def add_order_to_wave(self, wave_id, payload, headers):
        return self._request("POST", f"/warehouse/waves/{wave_id}/add-order", payload, headers)

    def release_wave(self, wave_id, payload, headers):
        return self._request("POST", f"/warehouse/waves/{wave_id}/release", payload, headers)

    def start_picking_wave(self, wave_id, headers):
        return self._request("POST", f"/warehouse/waves/{wave_id}/start-picking", {}, headers)

    def list_wave_pick_tasks(self, wave_id, headers):
        return self._request("GET", f"/warehouse/waves/{wave_id}/pick-tasks", headers=headers)

    def get_pick_task(self, task_id, headers):
        return self._request("GET", f"/warehouse/pick-tasks/{task_id}", headers=headers)

    def list_pick_tasks(self, headers, params=None):
        return self._request("GET", "/warehouse/pick-tasks", headers=headers, params=params)

    def start_pick_task(self, task_id, headers):
        return self._request("POST", f"/warehouse/pick-tasks/{task_id}/start", {}, headers)

    def confirm_pick_task(self, task_id, payload, headers):
        return self._request("POST", f"/warehouse/pick-tasks/{task_id}/confirm", payload, headers)

    def short_pick_task(self, task_id, headers):
        return self._request("POST", f"/warehouse/pick-tasks/{task_id}/short", {}, headers)

    def cancel_pick_task(self, task_id, headers):
        return self._request("POST", f"/warehouse/pick-tasks/{task_id}/cancel", {}, headers)

    # ── CycleCount ───────────────────────────────────────────────────────────
    def create_cycle_count(self, payload, headers):
        return self._request("POST", "/warehouse/cycle-counts", payload, headers)

    def get_cycle_count(self, count_id, headers):
        return self._request("GET", f"/warehouse/cycle-counts/{count_id}", headers=headers)

    def list_cycle_counts(self, headers, params=None):
        return self._request("GET", "/warehouse/cycle-counts", headers=headers, params=params)

    def submit_cycle_count(self, count_id, payload, headers):
        return self._request("POST", f"/warehouse/cycle-counts/{count_id}/submit", payload, headers)

    def approve_cycle_count(self, count_id, headers):
        return self._request("POST", f"/warehouse/cycle-counts/{count_id}/approve", {}, headers)

    def reject_cycle_count(self, count_id, headers):
        return self._request("POST", f"/warehouse/cycle-counts/{count_id}/reject", {}, headers)

    # ── ReplenishmentTask ────────────────────────────────────────────────────
    def create_replenishment_task(self, payload, headers):
        return self._request("POST", "/warehouse/replenishment-tasks", payload, headers)

    def get_replenishment_task(self, task_id, headers):
        return self._request("GET", f"/warehouse/replenishment-tasks/{task_id}", headers=headers)

    def list_replenishment_tasks(self, headers, params=None):
        return self._request("GET", "/warehouse/replenishment-tasks", headers=headers, params=params)

    def assign_replenishment_task(self, task_id, headers):
        return self._request("POST", f"/warehouse/replenishment-tasks/{task_id}/assign", {}, headers)

    def complete_replenishment_task(self, task_id, headers):
        return self._request("POST", f"/warehouse/replenishment-tasks/{task_id}/complete", {}, headers)

    def cancel_replenishment_task(self, task_id, headers):
        return self._request("POST", f"/warehouse/replenishment-tasks/{task_id}/cancel", {}, headers)

    # ── Test-driving clock ───────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/warehouse/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
