"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Account ----
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def suspend_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/suspend", {}, headers=headers)

    def reinstate_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/reinstate", {}, headers=headers)

    # ---- TaxExemptCertificate ----
    def create_certificate(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/tax-certificates", payload, headers=headers)

    def list_account_certificates(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/tax-certificates", headers=headers, params=params)

    def list_certificates(self, headers, params=None):
        return self._request("GET", "/tax-certificates", headers=headers, params=params)

    def get_certificate(self, cert_id, headers):
        return self._request("GET", f"/tax-certificates/{cert_id}", headers=headers)

    def approve_certificate(self, cert_id, headers):
        return self._request("POST", f"/tax-certificates/{cert_id}/approve", {}, headers=headers)

    def reject_certificate(self, cert_id, headers):
        return self._request("POST", f"/tax-certificates/{cert_id}/reject", {}, headers=headers)

    def resubmit_certificate(self, cert_id, headers):
        return self._request("POST", f"/tax-certificates/{cert_id}/resubmit", {}, headers=headers)

    # ---- Product ----
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def restock_product(self, product_id, payload, headers):
        return self._request("POST", f"/products/{product_id}/restock", payload, headers=headers)

    # ---- PurchaseOrder ----
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/lines", payload, headers=headers)

    def list_order_lines(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/lines", headers=headers, params=params)

    def list_order_lines_filtered(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def get_order_line(self, order_line_id, headers):
        return self._request("GET", f"/order-lines/{order_line_id}", headers=headers)

    def confirm_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/confirm", payload, headers=headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers=headers)

    def invoice_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/invoice", {}, headers=headers)

    def pay_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/pay", {}, headers=headers)

    # ---- Shipment ----
    def create_shipment(self, payload, headers):
        return self._request("POST", "/shipments", payload, headers=headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/shipments/{shipment_id}", headers=headers)

    def book_shipment(self, shipment_id, headers, payload=None):
        return self._request("POST", f"/shipments/{shipment_id}/book", payload or {}, headers=headers)

    def deliver_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/deliver", {}, headers=headers)

    def cancel_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/cancel", {}, headers=headers)

    # ---- ReturnAuthorization / ReturnLine ----
    def create_return(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/returns", payload, headers=headers)

    def list_returns(self, headers, params=None):
        return self._request("GET", "/returns", headers=headers, params=params)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/returns/{return_id}", headers=headers)

    def add_return_line(self, return_id, payload, headers):
        return self._request("POST", f"/returns/{return_id}/lines", payload, headers=headers)

    def list_return_lines(self, return_id, headers, params=None):
        return self._request("GET", f"/returns/{return_id}/lines", headers=headers, params=params)

    def list_return_lines_filtered(self, headers, params=None):
        return self._request("GET", "/return-lines", headers=headers, params=params)

    def get_return_line(self, return_line_id, headers):
        return self._request("GET", f"/return-lines/{return_line_id}", headers=headers)

    def approve_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/approve", {}, headers=headers)

    def revise_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/revise", {}, headers=headers)

    def reject_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/reject", {}, headers=headers)

    def receive_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/receive", {}, headers=headers)

    def refund_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/refund", {}, headers=headers)

    # ---- Dock / DeliveryAppointment ----
    def create_dock(self, payload, headers):
        return self._request("POST", "/docks", payload, headers=headers)

    def list_docks(self, headers, params=None):
        return self._request("GET", "/docks", headers=headers, params=params)

    def get_dock(self, dock_id, headers):
        return self._request("GET", f"/docks/{dock_id}", headers=headers)

    def create_appointment(self, payload, headers):
        return self._request("POST", "/delivery-appointments", payload, headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/delivery-appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/delivery-appointments/{appointment_id}", headers=headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/delivery-appointments/{appointment_id}/cancel", {}, headers=headers)

    # ---- InstallCrew / InstallJob ----
    def create_crew(self, payload, headers):
        return self._request("POST", "/install-crews", payload, headers=headers)

    def list_crews(self, headers, params=None):
        return self._request("GET", "/install-crews", headers=headers, params=params)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/install-crews/{crew_id}", headers=headers)

    def create_install_job(self, payload, headers):
        return self._request("POST", "/install-jobs", payload, headers=headers)

    def list_install_jobs(self, headers, params=None):
        return self._request("GET", "/install-jobs", headers=headers, params=params)

    def get_install_job(self, job_id, headers):
        return self._request("GET", f"/install-jobs/{job_id}", headers=headers)

    def cancel_install_job(self, job_id, headers):
        return self._request("POST", f"/install-jobs/{job_id}/cancel", {}, headers=headers)

    # ---- Logical clock (test-driving) ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers=headers)


api_client = ApiClient()
