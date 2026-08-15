"""API client: one method per endpoint defined in PRD §4.

All paths live under the /chandlery prefix. The base _request() method is
inherited from GenericApiClient.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/chandlery/_clock/set_current_utc", payload, headers)

    # --- ShipAgent ---
    def create_ship_agent(self, payload, headers):
        return self._request("POST", "/chandlery/ship-agents", payload, headers)

    def get_ship_agent(self, agent_id, headers):
        return self._request("GET", f"/chandlery/ship-agents/{agent_id}", headers=headers)

    def list_agent_vessel_calls(self, agent_id, headers, params=None):
        return self._request(
            "GET", f"/chandlery/ship-agents/{agent_id}/vessel-calls",
            headers=headers, params=params,
        )

    def list_agent_orders(self, agent_id, headers, params=None):
        return self._request(
            "GET", f"/chandlery/ship-agents/{agent_id}/orders",
            headers=headers, params=params,
        )

    # --- VesselCall ---
    def create_vessel_call(self, payload, headers):
        return self._request("POST", "/chandlery/vessel-calls", payload, headers)

    def get_vessel_call(self, vessel_call_id, headers):
        return self._request("GET", f"/chandlery/vessel-calls/{vessel_call_id}", headers=headers)

    def arrive_vessel_call(self, vessel_call_id, headers):
        return self._request(
            "POST", f"/chandlery/vessel-calls/{vessel_call_id}/arrive", headers=headers,
        )

    def depart_vessel_call(self, vessel_call_id, headers):
        return self._request(
            "POST", f"/chandlery/vessel-calls/{vessel_call_id}/depart", headers=headers,
        )

    def cancel_vessel_call(self, vessel_call_id, headers):
        return self._request(
            "POST", f"/chandlery/vessel-calls/{vessel_call_id}/cancel", headers=headers,
        )

    def customs_clearance(self, vessel_call_id, payload, headers):
        return self._request(
            "POST", f"/chandlery/vessel-calls/{vessel_call_id}/customs-clearance",
            payload, headers,
        )

    # --- CatalogItem & StockLot ---
    def create_catalog_item(self, payload, headers):
        return self._request("POST", "/chandlery/catalog-items", payload, headers)

    def list_catalog_items(self, headers, params=None):
        return self._request("GET", "/chandlery/catalog-items", headers=headers, params=params)

    def create_stock_lot(self, payload, headers):
        return self._request("POST", "/chandlery/stock-lots", payload, headers)

    def list_stock_lots(self, headers, params=None):
        return self._request("GET", "/chandlery/stock-lots", headers=headers, params=params)

    def get_stock_lot(self, lot_id, headers):
        return self._request("GET", f"/chandlery/stock-lots/{lot_id}", headers=headers)

    def create_stock_adjustment(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/chandlery/stock-lots/{lot_id}/adjustments", payload, headers,
        )

    # --- Requisition ---
    def create_requisition(self, vessel_call_id, payload, headers):
        return self._request(
            "POST", f"/chandlery/vessel-calls/{vessel_call_id}/requisitions",
            payload, headers,
        )

    def list_requisitions(self, vessel_call_id, headers, params=None):
        return self._request(
            "GET", f"/chandlery/vessel-calls/{vessel_call_id}/requisitions",
            headers=headers, params=params,
        )

    def get_requisition(self, requisition_id, headers):
        return self._request("GET", f"/chandlery/requisitions/{requisition_id}", headers=headers)

    def submit_requisition(self, requisition_id, headers):
        return self._request(
            "POST", f"/chandlery/requisitions/{requisition_id}/submit", headers=headers,
        )

    def recall_requisition(self, requisition_id, headers):
        return self._request(
            "POST", f"/chandlery/requisitions/{requisition_id}/recall", headers=headers,
        )

    # --- Quotation ---
    def create_quotation(self, requisition_id, payload, headers):
        return self._request(
            "POST", f"/chandlery/requisitions/{requisition_id}/quotations",
            payload, headers,
        )

    def list_quotations(self, requisition_id, headers, params=None):
        return self._request(
            "GET", f"/chandlery/requisitions/{requisition_id}/quotations",
            headers=headers, params=params,
        )

    def get_quotation(self, quotation_id, headers):
        return self._request("GET", f"/chandlery/quotations/{quotation_id}", headers=headers)

    def send_quotation(self, quotation_id, headers):
        return self._request(
            "POST", f"/chandlery/quotations/{quotation_id}/send", headers=headers,
        )

    def revise_quotation(self, quotation_id, payload, headers):
        return self._request(
            "POST", f"/chandlery/quotations/{quotation_id}/revise", payload, headers,
        )

    def accept_quotation(self, quotation_id, headers):
        return self._request(
            "POST", f"/chandlery/quotations/{quotation_id}/accept", headers=headers,
        )

    def withdraw_quotation(self, quotation_id, headers):
        return self._request(
            "POST", f"/chandlery/quotations/{quotation_id}/withdraw", headers=headers,
        )

    def list_quotation_orders(self, quotation_id, headers):
        return self._request(
            "GET", f"/chandlery/quotations/{quotation_id}/orders", headers=headers,
        )

    # --- Order ---
    def get_order(self, order_id, headers):
        return self._request("GET", f"/chandlery/orders/{order_id}", headers=headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/chandlery/orders/{order_id}/cancel", headers=headers)

    # --- Delivery ---
    def create_delivery(self, order_id, payload, headers):
        return self._request(
            "POST", f"/chandlery/orders/{order_id}/deliveries", payload, headers,
        )

    def list_deliveries(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/chandlery/orders/{order_id}/deliveries",
            headers=headers, params=params,
        )

    def get_delivery(self, delivery_id, headers):
        return self._request("GET", f"/chandlery/deliveries/{delivery_id}", headers=headers)

    def dispatch_delivery(self, delivery_id, headers):
        return self._request(
            "POST", f"/chandlery/deliveries/{delivery_id}/dispatch", headers=headers,
        )

    def confirm_delivery(self, delivery_id, payload, headers):
        return self._request(
            "POST", f"/chandlery/deliveries/{delivery_id}/confirm", payload, headers,
        )

    # --- Invoice & Payment ---
    def create_invoice(self, order_id, payload, headers):
        return self._request(
            "POST", f"/chandlery/orders/{order_id}/invoices", payload, headers,
        )

    def list_order_invoices(self, order_id, headers):
        return self._request(
            "GET", f"/chandlery/orders/{order_id}/invoices", headers=headers,
        )

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/chandlery/invoices/{invoice_id}", headers=headers)

    def create_payment(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/chandlery/invoices/{invoice_id}/payments", payload, headers,
        )

    def list_payments(self, invoice_id, headers):
        return self._request(
            "GET", f"/chandlery/invoices/{invoice_id}/payments", headers=headers,
        )

    # --- QualityComplaint & CreditNote ---
    def create_complaint(self, delivery_id, payload, headers):
        return self._request(
            "POST", f"/chandlery/deliveries/{delivery_id}/complaints", payload, headers,
        )

    def list_complaints(self, delivery_id, headers, params=None):
        return self._request(
            "GET", f"/chandlery/deliveries/{delivery_id}/complaints",
            headers=headers, params=params,
        )

    def accept_complaint(self, complaint_id, headers):
        return self._request(
            "POST", f"/chandlery/complaints/{complaint_id}/accept", headers=headers,
        )

    def reject_complaint(self, complaint_id, headers):
        return self._request(
            "POST", f"/chandlery/complaints/{complaint_id}/reject", headers=headers,
        )

    def reopen_complaint(self, complaint_id, headers):
        return self._request(
            "POST", f"/chandlery/complaints/{complaint_id}/reopen", headers=headers,
        )

    def list_credit_notes(self, headers, params=None):
        return self._request("GET", "/chandlery/credit-notes", headers=headers, params=params)

    def get_credit_note(self, credit_note_id, headers):
        return self._request("GET", f"/chandlery/credit-notes/{credit_note_id}", headers=headers)

    def revoke_credit_note(self, credit_note_id, headers):
        return self._request(
            "POST", f"/chandlery/credit-notes/{credit_note_id}/revoke", headers=headers,
        )


api_client = ApiClient()
