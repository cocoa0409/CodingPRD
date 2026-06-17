"""API client: one method per endpoint defined in the PRD.

Subclasses GenericApiClient; the base _request() handles the envelope and headers.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── RFQ ───────────────────────────────────────────────────────────────
    def create_rfq(self, payload, headers):
        return self._request("POST", "/rfqs", payload, headers=headers)

    def get_rfq(self, rfq_id, headers):
        return self._request("GET", f"/rfqs/{rfq_id}", headers=headers)

    def list_rfqs(self, headers, params=None):
        return self._request("GET", "/rfqs", headers=headers, params=params)

    def submit_rfq(self, rfq_id, headers):
        return self._request("POST", f"/rfqs/{rfq_id}/submit", {}, headers=headers)

    def close_rfq(self, rfq_id, headers):
        return self._request("POST", f"/rfqs/{rfq_id}/close", {}, headers=headers)

    def cancel_rfq(self, rfq_id, headers):
        return self._request("POST", f"/rfqs/{rfq_id}/cancel", {}, headers=headers)

    # ─── PartLine ──────────────────────────────────────────────────────────
    def create_part_line(self, rfq_id, payload, headers):
        return self._request("POST", f"/rfqs/{rfq_id}/part-lines", payload, headers=headers)

    def list_part_lines_for_rfq(self, rfq_id, headers, params=None):
        return self._request("GET", f"/rfqs/{rfq_id}/part-lines", headers=headers, params=params)

    def list_part_lines(self, headers, params=None):
        return self._request("GET", "/part-lines", headers=headers, params=params)

    def get_part_line(self, part_line_id, headers):
        return self._request("GET", f"/part-lines/{part_line_id}", headers=headers)

    # ─── Quote ─────────────────────────────────────────────────────────────
    def create_quote(self, payload, headers):
        return self._request("POST", "/quotes", payload, headers=headers)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    def create_routing_op(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/routing-ops", payload, headers=headers)

    def list_routing_ops_for_quote(self, quote_id, headers, params=None):
        return self._request("GET", f"/quotes/{quote_id}/routing-ops", headers=headers, params=params)

    def price_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/price", {}, headers=headers)

    def approve_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/approve", payload, headers=headers)

    def reject_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/reject", payload, headers=headers)

    def reopen_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/reopen", {}, headers=headers)

    # ─── RoutingOp ─────────────────────────────────────────────────────────
    def get_routing_op(self, op_id, headers):
        return self._request("GET", f"/routing-ops/{op_id}", headers=headers)

    def list_routing_ops(self, headers, params=None):
        return self._request("GET", "/routing-ops", headers=headers, params=params)

    def complete_routing_op(self, op_id, payload, headers):
        return self._request("POST", f"/routing-ops/{op_id}/complete", payload, headers=headers)

    # ─── WorkOrder ─────────────────────────────────────────────────────────
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers=headers)

    def get_work_order(self, wo_id, headers):
        return self._request("GET", f"/work-orders/{wo_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def allocate_material(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/allocate-material", {}, headers=headers)

    def release_work_order(self, wo_id, payload, headers):
        return self._request("POST", f"/work-orders/{wo_id}/release", payload, headers=headers)

    def close_work_order(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/close", {}, headers=headers)

    def cancel_work_order(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/cancel", {}, headers=headers)

    def list_lot_allocations_for_work_order(self, wo_id, headers, params=None):
        return self._request("GET", f"/work-orders/{wo_id}/lot-allocations", headers=headers, params=params)

    def list_inspections_for_work_order(self, wo_id, headers, params=None):
        return self._request("GET", f"/work-orders/{wo_id}/inspections", headers=headers, params=params)

    # ─── MaterialLot ───────────────────────────────────────────────────────
    def create_material_lot(self, payload, headers):
        return self._request("POST", "/material-lots", payload, headers=headers)

    def get_material_lot(self, lot_id, headers):
        return self._request("GET", f"/material-lots/{lot_id}", headers=headers)

    def list_material_lots(self, headers, params=None):
        return self._request("GET", "/material-lots", headers=headers, params=params)

    def list_lot_allocations_for_lot(self, lot_id, headers, params=None):
        return self._request("GET", f"/material-lots/{lot_id}/lot-allocations", headers=headers, params=params)

    # ─── LotAllocation ─────────────────────────────────────────────────────
    def get_lot_allocation(self, allocation_id, headers):
        return self._request("GET", f"/lot-allocations/{allocation_id}", headers=headers)

    def list_lot_allocations(self, headers, params=None):
        return self._request("GET", "/lot-allocations", headers=headers, params=params)

    # ─── MachineSlot ───────────────────────────────────────────────────────
    def create_machine_slot(self, payload, headers):
        return self._request("POST", "/machine-slots", payload, headers=headers)

    def get_machine_slot(self, slot_id, headers):
        return self._request("GET", f"/machine-slots/{slot_id}", headers=headers)

    def list_machine_slots(self, headers, params=None):
        return self._request("GET", "/machine-slots", headers=headers, params=params)

    def release_machine_slot(self, slot_id, headers):
        return self._request("POST", f"/machine-slots/{slot_id}/release", {}, headers=headers)

    # ─── InspectionStation ─────────────────────────────────────────────────
    def create_inspection_station(self, payload, headers):
        return self._request("POST", "/inspection-stations", payload, headers=headers)

    def get_inspection_station(self, station_id, headers):
        return self._request("GET", f"/inspection-stations/{station_id}", headers=headers)

    # ─── Inspection ────────────────────────────────────────────────────────
    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers=headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    def disposition_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/disposition", payload, headers=headers)

    # ─── Shipment ──────────────────────────────────────────────────────────
    def create_shipment(self, payload, headers):
        return self._request("POST", "/shipments", payload, headers=headers)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/shipments/{shipment_id}", headers=headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/shipments", headers=headers, params=params)

    def void_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/void", {}, headers=headers)

    # ─── Invoice ───────────────────────────────────────────────────────────
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers=headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/pay", {}, headers=headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", {}, headers=headers)


api_client = ApiClient()
