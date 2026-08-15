"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def __init__(self, base_url=None):
        super().__init__(base_url)
        # "Connection: close" makes every request open a fresh connection to
        # whichever server instance is currently bound to the port. Without it,
        # urllib3 may reuse a keep-alive socket whose server was SIGKILLed by the
        # per-test-server restart, flaking with RemoteDisconnected /
        # ConnectionResetError on the first request of the next test.
        self.session.headers["Connection"] = "close"

    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Stations
    # ------------------------------------------------------------------
    def create_station(self, payload, headers):
        return self._request("POST", "/baggage/stations", payload, headers)

    def get_station(self, station_id, headers):
        return self._request("GET", f"/baggage/stations/{station_id}", headers=headers)

    def list_stations(self, headers, params=None):
        return self._request("GET", "/baggage/stations", headers=headers, params=params)

    def get_station_irregularity_summary(self, station_id, headers):
        return self._request("GET", f"/baggage/stations/{station_id}/irregularity-summary",
                             headers=headers)

    # ------------------------------------------------------------------
    # Carriers
    # ------------------------------------------------------------------
    def create_carrier(self, payload, headers):
        return self._request("POST", "/baggage/carriers", payload, headers)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"/baggage/carriers/{carrier_id}", headers=headers)

    # ------------------------------------------------------------------
    # Courier services
    # ------------------------------------------------------------------
    def create_courier_service(self, payload, headers):
        return self._request("POST", "/baggage/courier-services", payload, headers)

    def get_courier_service(self, courier_id, headers):
        return self._request("GET", f"/baggage/courier-services/{courier_id}", headers=headers)

    def list_courier_services(self, headers, params=None):
        return self._request("GET", "/baggage/courier-services", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Repair vendors
    # ------------------------------------------------------------------
    def create_repair_vendor(self, payload, headers):
        return self._request("POST", "/baggage/repair-vendors", payload, headers)

    def get_repair_vendor(self, vendor_id, headers):
        return self._request("GET", f"/baggage/repair-vendors/{vendor_id}", headers=headers)

    # ------------------------------------------------------------------
    # Passengers
    # ------------------------------------------------------------------
    def create_passenger(self, payload, headers):
        return self._request("POST", "/baggage/passengers", payload, headers)

    def get_passenger(self, passenger_id, headers):
        return self._request("GET", f"/baggage/passengers/{passenger_id}", headers=headers)

    # ------------------------------------------------------------------
    # Bag tags
    # ------------------------------------------------------------------
    def create_bag_tag(self, payload, headers):
        return self._request("POST", "/baggage/bag-tags", payload, headers)

    def get_bag_tag(self, bag_tag_id, headers):
        return self._request("GET", f"/baggage/bag-tags/{bag_tag_id}", headers=headers)

    def list_bag_tags(self, headers, params=None):
        return self._request("GET", "/baggage/bag-tags", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Irregularity reports
    # ------------------------------------------------------------------
    def create_report(self, payload, headers):
        return self._request("POST", "/baggage/reports", payload, headers)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/baggage/reports/{report_id}", headers=headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/baggage/reports", headers=headers, params=params)

    def record_tracing_event(self, report_id, payload, headers):
        return self._request("POST", f"/baggage/reports/{report_id}/tracing-events",
                             payload, headers)

    def assess_loss(self, report_id, payload, headers):
        return self._request("POST", f"/baggage/reports/{report_id}/assess-loss",
                             payload, headers)

    def assess_damage(self, report_id, payload, headers):
        return self._request("POST", f"/baggage/reports/{report_id}/assess-damage",
                             payload, headers)

    def open_claim_review(self, report_id, headers):
        return self._request("POST", f"/baggage/reports/{report_id}/open-claim-review",
                             {}, headers)

    def offer_settlement(self, report_id, payload, headers):
        return self._request("POST", f"/baggage/reports/{report_id}/offer-settlement",
                             payload, headers)

    def accept_settlement(self, report_id, headers):
        return self._request("POST", f"/baggage/reports/{report_id}/accept-settlement",
                             {}, headers)

    def reject_settlement(self, report_id, headers):
        return self._request("POST", f"/baggage/reports/{report_id}/reject-settlement",
                             {}, headers)

    def create_settlement_payment(self, report_id, payload, headers):
        return self._request("POST", f"/baggage/reports/{report_id}/settlement-payments",
                             payload, headers)

    # ------------------------------------------------------------------
    # Settlement payments
    # ------------------------------------------------------------------
    def get_settlement_payment(self, payment_id, headers):
        return self._request("GET", f"/baggage/settlement-payments/{payment_id}", headers=headers)

    def list_settlement_payments(self, headers, params=None):
        return self._request("GET", "/baggage/settlement-payments", headers=headers, params=params)

    def mark_payment_paid(self, payment_id, headers):
        return self._request("POST", f"/baggage/settlement-payments/{payment_id}/mark-paid",
                             {}, headers)

    def void_payment(self, payment_id, headers):
        return self._request("POST", f"/baggage/settlement-payments/{payment_id}/void",
                             {}, headers)

    # ------------------------------------------------------------------
    # Tracing events (read side)
    # ------------------------------------------------------------------
    def get_tracing_event(self, event_id, headers):
        return self._request("GET", f"/baggage/tracing-events/{event_id}", headers=headers)

    def list_tracing_events(self, headers, params=None):
        return self._request("GET", "/baggage/tracing-events", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Delivery dispatches
    # ------------------------------------------------------------------
    def create_dispatch(self, payload, headers):
        return self._request("POST", "/baggage/dispatches", payload, headers)

    def get_dispatch(self, dispatch_id, headers):
        return self._request("GET", f"/baggage/dispatches/{dispatch_id}", headers=headers)

    def list_dispatches(self, headers, params=None):
        return self._request("GET", "/baggage/dispatches", headers=headers, params=params)

    def mark_dispatch_delivered(self, dispatch_id, headers):
        return self._request("POST", f"/baggage/dispatches/{dispatch_id}/mark-delivered",
                             {}, headers)

    def mark_dispatch_failed(self, dispatch_id, headers):
        return self._request("POST", f"/baggage/dispatches/{dispatch_id}/mark-failed",
                             {}, headers)

    def reschedule_dispatch(self, dispatch_id, payload, headers):
        return self._request("POST", f"/baggage/dispatches/{dispatch_id}/reschedule",
                             payload, headers)

    # ------------------------------------------------------------------
    # Repair orders
    # ------------------------------------------------------------------
    def create_repair_order(self, payload, headers):
        return self._request("POST", "/baggage/repair-orders", payload, headers)

    def get_repair_order(self, order_id, headers):
        return self._request("GET", f"/baggage/repair-orders/{order_id}", headers=headers)

    def list_repair_orders(self, headers, params=None):
        return self._request("GET", "/baggage/repair-orders", headers=headers, params=params)

    def decide_repair_order(self, order_id, headers):
        return self._request("POST", f"/baggage/repair-orders/{order_id}/decide", {}, headers)

    def complete_repair_order(self, order_id, headers):
        return self._request("POST", f"/baggage/repair-orders/{order_id}/complete", {}, headers)

    # ------------------------------------------------------------------
    # Expense claims
    # ------------------------------------------------------------------
    def create_expense_claim(self, payload, headers):
        return self._request("POST", "/baggage/expense-claims", payload, headers)

    def get_expense_claim(self, claim_id, headers):
        return self._request("GET", f"/baggage/expense-claims/{claim_id}", headers=headers)

    def list_expense_claims(self, headers, params=None):
        return self._request("GET", "/baggage/expense-claims", headers=headers, params=params)

    def adjudicate_expense_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/baggage/expense-claims/{claim_id}/adjudicate",
                             payload, headers)

    def pay_expense_claim(self, claim_id, headers):
        return self._request("POST", f"/baggage/expense-claims/{claim_id}/pay", {}, headers)


api_client = ApiClient()
