"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() is inherited.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- Customer ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ---- Technician ----
    def create_technician(self, payload, headers):
        return self._request("POST", "/technicians", payload, headers)

    # ---- RepairBay ----
    def create_repair_bay(self, payload, headers):
        return self._request("POST", "/repair-bays", payload, headers)

    # ---- Device ----
    def create_device(self, payload, headers):
        return self._request("POST", "/devices", payload, headers)

    def get_device(self, device_id, headers):
        return self._request("GET", f"/devices/{device_id}", headers=headers)

    def list_devices(self, headers, params=None):
        return self._request("GET", "/devices", headers=headers, params=params)

    # ---- RepairTicket ----
    def create_repair_ticket(self, payload, headers):
        return self._request("POST", "/repair-tickets", payload, headers)

    def get_repair_ticket(self, ticket_id, headers):
        return self._request("GET", f"/repair-tickets/{ticket_id}", headers=headers)

    def list_repair_tickets(self, headers, params=None):
        return self._request("GET", "/repair-tickets", headers=headers, params=params)

    def diagnose(self, ticket_id, payload, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/diagnose", payload, headers)

    def create_estimate(self, ticket_id, payload, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/estimates", payload, headers)

    def list_estimates(self, ticket_id, headers, params=None):
        return self._request("GET", f"/repair-tickets/{ticket_id}/estimates",
                             headers=headers, params=params)

    def get_estimate(self, ticket_id, estimate_id, headers):
        return self._request("GET", f"/repair-tickets/{ticket_id}/estimates/{estimate_id}",
                             headers=headers)

    def approve_estimate(self, ticket_id, estimate_id, headers):
        return self._request("POST",
                             f"/repair-tickets/{ticket_id}/estimates/{estimate_id}/approve",
                             {}, headers)

    def reject_estimate(self, ticket_id, estimate_id, headers):
        return self._request("POST",
                             f"/repair-tickets/{ticket_id}/estimates/{estimate_id}/reject",
                             {}, headers)

    def complete_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/complete", payload, headers)

    def cancel_ticket(self, ticket_id, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/cancel", {}, headers)

    def callback_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/callback", payload, headers)

    # ---- Part ----
    def create_part(self, payload, headers):
        return self._request("POST", "/parts", payload, headers)

    def get_part(self, part_id, headers):
        return self._request("GET", f"/parts/{part_id}", headers=headers)

    def receive_stock(self, part_id, payload, headers):
        return self._request("POST", f"/parts/{part_id}/receive-stock", payload, headers)

    # ---- PartOrder ----
    def create_part_order(self, ticket_id, payload, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/part-orders", payload, headers)

    def get_part_order(self, part_order_id, headers):
        return self._request("GET", f"/part-orders/{part_order_id}", headers=headers)

    def list_part_orders(self, headers, params=None):
        return self._request("GET", "/part-orders", headers=headers, params=params)

    def restock_part_order(self, part_order_id, headers):
        return self._request("POST", f"/part-orders/{part_order_id}/restock", {}, headers)

    # ---- TradeIn ----
    def create_trade_in(self, payload, headers):
        return self._request("POST", "/trade-ins", payload, headers)

    def get_trade_in(self, trade_in_id, headers):
        return self._request("GET", f"/trade-ins/{trade_in_id}", headers=headers)

    def list_trade_ins(self, headers, params=None):
        return self._request("GET", "/trade-ins", headers=headers, params=params)

    def offer_trade_in(self, trade_in_id, payload, headers):
        return self._request("POST", f"/trade-ins/{trade_in_id}/offer", payload, headers)

    def dispute_trade_in(self, trade_in_id, headers):
        return self._request("POST", f"/trade-ins/{trade_in_id}/dispute", {}, headers)

    def accept_trade_in(self, trade_in_id, headers):
        return self._request("POST", f"/trade-ins/{trade_in_id}/accept", {}, headers)

    def decline_trade_in(self, trade_in_id, headers):
        return self._request("POST", f"/trade-ins/{trade_in_id}/decline", {}, headers)

    def pay_trade_in(self, trade_in_id, headers):
        return self._request("POST", f"/trade-ins/{trade_in_id}/pay", {}, headers)

    def cancel_trade_in(self, trade_in_id, headers):
        return self._request("POST", f"/trade-ins/{trade_in_id}/cancel", {}, headers)

    # ---- DataWipeCertificate ----
    def create_data_wipe_certificate(self, payload, headers):
        return self._request("POST", "/data-wipe-certificates", payload, headers)

    def get_data_wipe_certificate(self, certificate_id, headers):
        return self._request("GET", f"/data-wipe-certificates/{certificate_id}", headers=headers)

    def list_data_wipe_certificates(self, headers, params=None):
        return self._request("GET", "/data-wipe-certificates", headers=headers, params=params)

    # ---- ProtectionPlanClaim ----
    def create_claim(self, payload, headers):
        return self._request("POST", "/protection-plan-claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/protection-plan-claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/protection-plan-claims", headers=headers, params=params)

    def route_claim(self, claim_id, headers):
        return self._request("POST", f"/protection-plan-claims/{claim_id}/route", {}, headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/protection-plan-claims/{claim_id}/approve", {}, headers)

    def deny_claim(self, claim_id, headers):
        return self._request("POST", f"/protection-plan-claims/{claim_id}/deny", {}, headers)


api_client = ApiClient()
