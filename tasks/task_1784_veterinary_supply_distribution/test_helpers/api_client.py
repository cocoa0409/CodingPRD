"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (PRD §2.4)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/vet/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Clinics (PRD §3.1)
    # ------------------------------------------------------------------
    def create_clinic(self, payload, headers):
        return self._request("POST", "/vet/clinics", payload, headers)

    def get_clinic(self, clinic_id, headers):
        return self._request("GET", f"/vet/clinics/{clinic_id}", headers=headers)

    def patch_clinic(self, clinic_id, payload, headers):
        return self._request("PATCH", f"/vet/clinics/{clinic_id}", payload, headers)

    def activate_clinic(self, clinic_id, headers):
        return self._request("POST", f"/vet/clinics/{clinic_id}/activate", {}, headers)

    def suspend_clinic(self, clinic_id, headers):
        return self._request("POST", f"/vet/clinics/{clinic_id}/suspend", {}, headers)

    def reinstate_clinic(self, clinic_id, headers):
        return self._request("POST", f"/vet/clinics/{clinic_id}/reinstate", {}, headers)

    # ------------------------------------------------------------------
    # Products (PRD §3.2)
    # ------------------------------------------------------------------
    def create_product(self, payload, headers):
        return self._request("POST", "/vet/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/vet/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/vet/products/{product_id}", headers=headers)

    def discontinue_product(self, product_id, headers):
        return self._request("POST", f"/vet/products/{product_id}/discontinue", {}, headers)

    # ------------------------------------------------------------------
    # Manufacturer authorizations (PRD §3.3)
    # ------------------------------------------------------------------
    def create_authorization(self, payload, headers):
        return self._request("POST", "/vet/manufacturer-authorizations", payload, headers)

    def list_authorizations(self, headers, params=None):
        return self._request("GET", "/vet/manufacturer-authorizations",
                             headers=headers, params=params)

    def get_authorization(self, authorization_id, headers):
        return self._request("GET", f"/vet/manufacturer-authorizations/{authorization_id}",
                             headers=headers)

    def approve_authorization(self, authorization_id, headers):
        return self._request("POST",
                             f"/vet/manufacturer-authorizations/{authorization_id}/approve",
                             {}, headers)

    def suspend_authorization(self, authorization_id, headers):
        return self._request("POST",
                             f"/vet/manufacturer-authorizations/{authorization_id}/suspend",
                             {}, headers)

    def reinstate_authorization(self, authorization_id, headers):
        return self._request("POST",
                             f"/vet/manufacturer-authorizations/{authorization_id}/reinstate",
                             {}, headers)

    def revoke_authorization(self, authorization_id, headers):
        return self._request("POST",
                             f"/vet/manufacturer-authorizations/{authorization_id}/revoke",
                             {}, headers)

    # ------------------------------------------------------------------
    # Inventory lots (PRD §3.2)
    # ------------------------------------------------------------------
    def create_lot(self, payload, headers):
        return self._request("POST", "/vet/inventory-lots", payload, headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/vet/inventory-lots", headers=headers, params=params)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/vet/inventory-lots/{lot_id}", headers=headers)

    # ------------------------------------------------------------------
    # Orders, order lines, backorder lines (PRD §3.4–§3.6)
    # ------------------------------------------------------------------
    def create_order(self, payload, headers):
        return self._request("POST", "/vet/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/vet/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/vet/orders/{order_id}", headers=headers)

    def submit_order(self, order_id, headers):
        return self._request("POST", f"/vet/orders/{order_id}/submit", {}, headers)

    def approve_order(self, order_id, headers):
        return self._request("POST", f"/vet/orders/{order_id}/approve", {}, headers)

    def reject_order(self, order_id, payload, headers):
        return self._request("POST", f"/vet/orders/{order_id}/reject", payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/vet/orders/{order_id}/cancel", {}, headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/vet/order-lines", headers=headers, params=params)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/vet/order-lines/{line_id}", headers=headers)

    def list_backorder_lines(self, line_id, headers, params=None):
        return self._request("GET", f"/vet/order-lines/{line_id}/backorder-lines",
                             headers=headers, params=params)

    def cancel_backorder_line(self, backorder_id, headers):
        return self._request("POST", f"/vet/backorder-lines/{backorder_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Shipments and cold chain (PRD §3.7)
    # ------------------------------------------------------------------
    def create_shipment(self, payload, headers):
        return self._request("POST", "/vet/shipments", payload, headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/vet/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/vet/shipments/{shipment_id}", headers=headers)

    def dispatch_shipment(self, shipment_id, headers):
        return self._request("POST", f"/vet/shipments/{shipment_id}/dispatch", {}, headers)

    def deliver_shipment(self, shipment_id, headers):
        return self._request("POST", f"/vet/shipments/{shipment_id}/deliver", {}, headers)

    def add_temperature_reading(self, shipment_id, payload, headers):
        return self._request("POST", f"/vet/shipments/{shipment_id}/temperature-readings",
                             payload, headers)

    def resolve_quarantine(self, shipment_id, outcome, headers):
        return self._request("POST", f"/vet/shipments/{shipment_id}/resolve-quarantine",
                             {"outcome": outcome}, headers)

    # ------------------------------------------------------------------
    # Bundle programs, enrollments, rebate accruals (PRD §3.8)
    # ------------------------------------------------------------------
    def create_bundle_program(self, payload, headers):
        return self._request("POST", "/vet/bundle-programs", payload, headers)

    def get_bundle_program(self, program_id, headers):
        return self._request("GET", f"/vet/bundle-programs/{program_id}", headers=headers)

    def activate_bundle_program(self, program_id, headers):
        return self._request("POST", f"/vet/bundle-programs/{program_id}/activate",
                             {}, headers)

    def close_bundle_program(self, program_id, headers):
        return self._request("POST", f"/vet/bundle-programs/{program_id}/close",
                             {}, headers)

    def create_bundle_enrollment(self, clinic_id, payload, headers):
        return self._request("POST", f"/vet/clinics/{clinic_id}/bundle-enrollments",
                             payload, headers)

    def list_bundle_enrollments(self, headers, params=None):
        return self._request("GET", "/vet/bundle-enrollments", headers=headers,
                             params=params)

    def get_bundle_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/vet/bundle-enrollments/{enrollment_id}",
                             headers=headers)

    def list_rebate_accruals(self, headers, params=None):
        return self._request("GET", "/vet/rebate-accruals", headers=headers, params=params)

    def get_rebate_accrual(self, accrual_id, headers):
        return self._request("GET", f"/vet/rebate-accruals/{accrual_id}", headers=headers)

    # ------------------------------------------------------------------
    # Short-date credits (PRD §3.9)
    # ------------------------------------------------------------------
    def create_short_date_credit(self, payload, headers):
        return self._request("POST", "/vet/short-date-credits", payload, headers)

    def list_short_date_credits(self, headers, params=None):
        return self._request("GET", "/vet/short-date-credits", headers=headers,
                             params=params)

    def get_short_date_credit(self, credit_id, headers):
        return self._request("GET", f"/vet/short-date-credits/{credit_id}", headers=headers)

    def approve_short_date_credit(self, credit_id, headers):
        return self._request("POST", f"/vet/short-date-credits/{credit_id}/approve",
                             {}, headers)

    def deny_short_date_credit(self, credit_id, headers):
        return self._request("POST", f"/vet/short-date-credits/{credit_id}/deny",
                             {}, headers)

    def finalize_short_date_credit(self, credit_id, received_qty, headers):
        return self._request("POST", f"/vet/short-date-credits/{credit_id}/finalize",
                             {"received_qty": received_qty}, headers)


api_client = ApiClient()
