"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() is inherited.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock -----------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/tms/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- Carrier -----------------------------------------------------------
    def create_carrier(self, payload, headers):
        return self._request("POST", "/tms/carriers", payload, headers)

    def list_carriers(self, headers, params=None):
        return self._request("GET", "/tms/carriers", headers=headers, params=params)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"/tms/carriers/{carrier_id}", headers=headers)

    def suspend_carrier(self, carrier_id, headers):
        return self._request("POST", f"/tms/carriers/{carrier_id}/suspend", {}, headers)

    def reinstate_carrier(self, carrier_id, headers):
        return self._request("POST", f"/tms/carriers/{carrier_id}/reinstate", {}, headers)

    # --- ContractRate ------------------------------------------------------
    def create_contract_rate(self, payload, headers):
        return self._request("POST", "/tms/contract-rates", payload, headers)

    def list_contract_rates(self, headers, params=None):
        return self._request("GET", "/tms/contract-rates", headers=headers, params=params)

    def get_contract_rate(self, rate_id, headers):
        return self._request("GET", f"/tms/contract-rates/{rate_id}", headers=headers)

    def retire_contract_rate(self, rate_id, headers):
        return self._request("POST", f"/tms/contract-rates/{rate_id}/retire", {}, headers)

    # --- Order -------------------------------------------------------------
    def create_order(self, payload, headers):
        return self._request("POST", "/tms/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/tms/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/tms/orders/{order_id}", headers=headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/tms/orders/{order_id}/cancel", {}, headers)

    # --- Shipment ----------------------------------------------------------
    def create_shipment(self, payload, headers):
        return self._request("POST", "/tms/shipments", payload, headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/tms/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/tms/shipments/{shipment_id}", headers=headers)

    def depart_shipment(self, shipment_id, headers):
        return self._request("POST", f"/tms/shipments/{shipment_id}/depart", {}, headers)

    def deliver_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/tms/shipments/{shipment_id}/deliver", payload, headers)

    def cancel_shipment(self, shipment_id, headers):
        return self._request("POST", f"/tms/shipments/{shipment_id}/cancel", {}, headers)

    # --- Tender ------------------------------------------------------------
    def create_tender(self, shipment_id, payload, headers):
        return self._request("POST", f"/tms/shipments/{shipment_id}/tenders", payload, headers)

    def list_shipment_tenders(self, shipment_id, headers, params=None):
        return self._request("GET", f"/tms/shipments/{shipment_id}/tenders", headers=headers, params=params)

    def list_tenders(self, headers, params=None):
        return self._request("GET", "/tms/tenders", headers=headers, params=params)

    def get_tender(self, tender_id, headers):
        return self._request("GET", f"/tms/tenders/{tender_id}", headers=headers)

    def accept_tender(self, tender_id, headers):
        return self._request("POST", f"/tms/tenders/{tender_id}/accept", {}, headers)

    def decline_tender(self, tender_id, headers):
        return self._request("POST", f"/tms/tenders/{tender_id}/decline", {}, headers)

    def expire_tender(self, tender_id, headers):
        return self._request("POST", f"/tms/tenders/{tender_id}/expire", {}, headers)

    # --- Load --------------------------------------------------------------
    def create_load(self, payload, headers):
        return self._request("POST", "/tms/loads", payload, headers)

    def list_loads(self, headers, params=None):
        return self._request("GET", "/tms/loads", headers=headers, params=params)

    def get_load(self, load_id, headers):
        return self._request("GET", f"/tms/loads/{load_id}", headers=headers)

    def list_load_shipments(self, load_id, headers, params=None):
        return self._request("GET", f"/tms/loads/{load_id}/shipments", headers=headers, params=params)

    def add_shipment_to_load(self, load_id, payload, headers):
        return self._request("POST", f"/tms/loads/{load_id}/shipments", payload, headers)

    def dispatch_load(self, load_id, headers):
        return self._request("POST", f"/tms/loads/{load_id}/dispatch", {}, headers)

    def close_load(self, load_id, headers):
        return self._request("POST", f"/tms/loads/{load_id}/close", {}, headers)

    # --- DockAppointment ---------------------------------------------------
    def create_dock_appointment(self, payload, headers):
        return self._request("POST", "/tms/dock-appointments", payload, headers)

    def list_dock_appointments(self, headers, params=None):
        return self._request("GET", "/tms/dock-appointments", headers=headers, params=params)

    def get_dock_appointment(self, appt_id, headers):
        return self._request("GET", f"/tms/dock-appointments/{appt_id}", headers=headers)

    def check_in_dock_appointment(self, appt_id, headers):
        return self._request("POST", f"/tms/dock-appointments/{appt_id}/check-in", {}, headers)

    def release_dock_appointment(self, appt_id, headers):
        return self._request("POST", f"/tms/dock-appointments/{appt_id}/release", {}, headers)

    def cancel_dock_appointment(self, appt_id, headers):
        return self._request("POST", f"/tms/dock-appointments/{appt_id}/cancel", {}, headers)

    # --- FreightInvoice ----------------------------------------------------
    def create_freight_invoice(self, payload, headers):
        return self._request("POST", "/tms/freight-invoices", payload, headers)

    def list_freight_invoices(self, headers, params=None):
        return self._request("GET", "/tms/freight-invoices", headers=headers, params=params)

    def get_freight_invoice(self, invoice_id, headers):
        return self._request("GET", f"/tms/freight-invoices/{invoice_id}", headers=headers)

    def audit_freight_invoice(self, invoice_id, headers):
        return self._request("POST", f"/tms/freight-invoices/{invoice_id}/audit", {}, headers)

    def approve_freight_invoice(self, invoice_id, headers):
        return self._request("POST", f"/tms/freight-invoices/{invoice_id}/approve", {}, headers)

    def dispute_freight_invoice(self, invoice_id, headers):
        return self._request("POST", f"/tms/freight-invoices/{invoice_id}/dispute", {}, headers)

    # --- Claim -------------------------------------------------------------
    def create_claim(self, payload, headers):
        return self._request("POST", "/tms/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/tms/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/tms/claims/{claim_id}", headers=headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/tms/claims/{claim_id}/approve", {}, headers)

    def deny_claim(self, claim_id, headers):
        return self._request("POST", f"/tms/claims/{claim_id}/deny", {}, headers)


api_client = ApiClient()
