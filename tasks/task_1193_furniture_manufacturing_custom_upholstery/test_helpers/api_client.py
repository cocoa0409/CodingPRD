"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Clock ────────────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/mill/_clock/set_current_utc", payload, headers)

    # ─── ProductModel ─────────────────────────────────────────────────
    def create_product_model(self, payload, headers):
        return self._request("POST", "/mill/product-models", payload, headers)

    def list_product_models(self, headers, params=None):
        return self._request("GET", "/mill/product-models", headers=headers, params=params)

    def get_product_model(self, model_id, headers):
        return self._request("GET", f"/mill/product-models/{model_id}", headers=headers)

    def discontinue_product_model(self, model_id, headers):
        return self._request("POST", f"/mill/product-models/{model_id}/discontinue", headers=headers)

    # ─── FabricSpec ───────────────────────────────────────────────────
    def create_fabric_spec(self, payload, headers):
        return self._request("POST", "/mill/fabric-specs", payload, headers)

    def list_fabric_specs(self, headers, params=None):
        return self._request("GET", "/mill/fabric-specs", headers=headers, params=params)

    def get_fabric_spec(self, spec_id, headers):
        return self._request("GET", f"/mill/fabric-specs/{spec_id}", headers=headers)

    # ─── DealerAccount ────────────────────────────────────────────────
    def create_dealer_account(self, payload, headers):
        return self._request("POST", "/mill/dealer-accounts", payload, headers)

    def list_dealer_accounts(self, headers, params=None):
        return self._request("GET", "/mill/dealer-accounts", headers=headers, params=params)

    def get_dealer_account(self, dealer_id, headers):
        return self._request("GET", f"/mill/dealer-accounts/{dealer_id}", headers=headers)

    def set_dealer_status(self, dealer_id, payload, headers):
        return self._request("POST", f"/mill/dealer-accounts/{dealer_id}/set-status", payload, headers)

    # ─── CustomerOrder ────────────────────────────────────────────────
    def create_customer_order(self, payload, headers):
        return self._request("POST", "/mill/customer-orders", payload, headers)

    def list_customer_orders(self, headers, params=None):
        return self._request("GET", "/mill/customer-orders", headers=headers, params=params)

    def get_customer_order(self, order_id, headers):
        return self._request("GET", f"/mill/customer-orders/{order_id}", headers=headers)

    def confirm_order(self, order_id, headers):
        return self._request("POST", f"/mill/customer-orders/{order_id}/confirm", headers=headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/mill/customer-orders/{order_id}/cancel", headers=headers)

    def pass_quality(self, order_id, headers):
        return self._request("POST", f"/mill/customer-orders/{order_id}/pass-quality", headers=headers)

    def fail_quality(self, order_id, payload, headers):
        return self._request("POST", f"/mill/customer-orders/{order_id}/fail-quality", payload, headers)

    # ─── OrderLine ────────────────────────────────────────────────────
    def create_order_line(self, payload, headers):
        return self._request("POST", "/mill/order-lines", payload, headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/mill/order-lines", headers=headers, params=params)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/mill/order-lines/{line_id}", headers=headers)

    # ─── MaterialLot ──────────────────────────────────────────────────
    def create_material_lot(self, payload, headers):
        return self._request("POST", "/mill/material-lots", payload, headers)

    def list_material_lots(self, headers, params=None):
        return self._request("GET", "/mill/material-lots", headers=headers, params=params)

    def get_material_lot(self, lot_id, headers):
        return self._request("GET", f"/mill/material-lots/{lot_id}", headers=headers)

    def receive_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/mill/material-lots/{lot_id}/receive", payload, headers)

    def inspect_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/mill/material-lots/{lot_id}/inspect", payload, headers)

    def reject_lot(self, lot_id, headers):
        return self._request("POST", f"/mill/material-lots/{lot_id}/reject-lot", headers=headers)

    def return_lot_to_customer(self, lot_id, headers):
        return self._request("POST", f"/mill/material-lots/{lot_id}/return-to-customer", headers=headers)

    def split_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/mill/material-lots/{lot_id}/split", payload, headers)

    # ─── MaterialAllocation ───────────────────────────────────────────
    def create_material_allocation(self, payload, headers):
        return self._request("POST", "/mill/material-allocations", payload, headers)

    def list_material_allocations(self, headers, params=None):
        return self._request("GET", "/mill/material-allocations", headers=headers, params=params)

    def get_material_allocation(self, alloc_id, headers):
        return self._request("GET", f"/mill/material-allocations/{alloc_id}", headers=headers)

    def release_allocation(self, alloc_id, headers):
        return self._request("POST", f"/mill/material-allocations/{alloc_id}/release", headers=headers)

    # ─── CutPlan ──────────────────────────────────────────────────────
    def create_cut_plan(self, line_id, payload, headers):
        return self._request("POST", f"/mill/order-lines/{line_id}/cut-plans", payload, headers)

    def list_cut_plans(self, headers, params=None):
        return self._request("GET", "/mill/cut-plans", headers=headers, params=params)

    def get_cut_plan(self, plan_id, headers):
        return self._request("GET", f"/mill/cut-plans/{plan_id}", headers=headers)

    def approve_cut_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/mill/cut-plans/{plan_id}/approve", payload, headers)

    def revise_cut_plan(self, plan_id, headers):
        return self._request("POST", f"/mill/cut-plans/{plan_id}/revise", headers=headers)

    def record_cut(self, plan_id, headers):
        return self._request("POST", f"/mill/cut-plans/{plan_id}/record-cut", headers=headers)

    # ─── Cell ─────────────────────────────────────────────────────────
    def create_cell(self, payload, headers):
        return self._request("POST", "/mill/cells", payload, headers)

    def list_cells(self, headers, params=None):
        return self._request("GET", "/mill/cells", headers=headers, params=params)

    def get_cell(self, cell_id, headers):
        return self._request("GET", f"/mill/cells/{cell_id}", headers=headers)

    def set_cell_status(self, cell_id, payload, headers):
        return self._request("POST", f"/mill/cells/{cell_id}/set-status", payload, headers)

    # ─── CellBooking ──────────────────────────────────────────────────
    def create_cell_booking(self, payload, headers):
        return self._request("POST", "/mill/cell-bookings", payload, headers)

    def list_cell_bookings(self, headers, params=None):
        return self._request("GET", "/mill/cell-bookings", headers=headers, params=params)

    def get_cell_booking(self, booking_id, headers):
        return self._request("GET", f"/mill/cell-bookings/{booking_id}", headers=headers)

    def start_booking(self, booking_id, headers):
        return self._request("POST", f"/mill/cell-bookings/{booking_id}/start", headers=headers)

    def complete_booking(self, booking_id, headers):
        return self._request("POST", f"/mill/cell-bookings/{booking_id}/complete", headers=headers)

    def release_booking(self, booking_id, headers):
        return self._request("POST", f"/mill/cell-bookings/{booking_id}/release", headers=headers)

    # ─── ComplianceCertificate ────────────────────────────────────────
    def create_compliance_certificate(self, payload, headers):
        return self._request("POST", "/mill/compliance-certificates", payload, headers)

    def list_compliance_certificates(self, headers, params=None):
        return self._request("GET", "/mill/compliance-certificates", headers=headers, params=params)

    def get_compliance_certificate(self, cert_id, headers):
        return self._request("GET", f"/mill/compliance-certificates/{cert_id}", headers=headers)

    def certify_certificate(self, cert_id, headers):
        return self._request("POST", f"/mill/compliance-certificates/{cert_id}/certify", headers=headers)

    def void_certificate(self, cert_id, headers):
        return self._request("POST", f"/mill/compliance-certificates/{cert_id}/void", headers=headers)

    # ─── SupplyRequisition ────────────────────────────────────────────
    def create_supply_requisition(self, payload, headers):
        return self._request("POST", "/mill/supply-requisitions", payload, headers)

    def list_supply_requisitions(self, headers, params=None):
        return self._request("GET", "/mill/supply-requisitions", headers=headers, params=params)

    def get_supply_requisition(self, req_id, headers):
        return self._request("GET", f"/mill/supply-requisitions/{req_id}", headers=headers)

    def place_requisition(self, req_id, headers):
        return self._request("POST", f"/mill/supply-requisitions/{req_id}/place", headers=headers)

    def receive_requisition(self, req_id, headers):
        return self._request("POST", f"/mill/supply-requisitions/{req_id}/receive", headers=headers)

    # ─── ShowroomSample ───────────────────────────────────────────────
    def create_showroom_sample(self, payload, headers):
        return self._request("POST", "/mill/showroom-samples", payload, headers)

    def list_showroom_samples(self, headers, params=None):
        return self._request("GET", "/mill/showroom-samples", headers=headers, params=params)

    def get_showroom_sample(self, sample_id, headers):
        return self._request("GET", f"/mill/showroom-samples/{sample_id}", headers=headers)

    def return_sample(self, sample_id, headers):
        return self._request("POST", f"/mill/showroom-samples/{sample_id}/return", headers=headers)

    def sell_sample(self, sample_id, headers):
        return self._request("POST", f"/mill/showroom-samples/{sample_id}/sell", headers=headers)

    def write_off_sample(self, sample_id, headers):
        return self._request("POST", f"/mill/showroom-samples/{sample_id}/write-off", headers=headers)

    # ─── Shipment ─────────────────────────────────────────────────────
    def create_shipment(self, payload, headers):
        return self._request("POST", "/mill/shipments", payload, headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/mill/shipments", headers=headers, params=params)

    def get_shipment(self, ship_id, headers):
        return self._request("GET", f"/mill/shipments/{ship_id}", headers=headers)

    def rate_shipment(self, ship_id, headers):
        return self._request("POST", f"/mill/shipments/{ship_id}/rate", headers=headers)

    def tender_shipment(self, ship_id, headers):
        return self._request("POST", f"/mill/shipments/{ship_id}/tender", headers=headers)

    def record_pickup(self, ship_id, payload, headers):
        return self._request("POST", f"/mill/shipments/{ship_id}/record-pickup", payload, headers)

    def record_delivery(self, ship_id, headers):
        return self._request("POST", f"/mill/shipments/{ship_id}/record-delivery", headers=headers)


api_client = ApiClient()
