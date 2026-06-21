"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Test-driving clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Resort ----
    def create_resort(self, payload, headers):
        return self._request("POST", "/resorts", payload, headers)

    def list_resorts(self, headers, params=None):
        return self._request("GET", "/resorts", headers=headers, params=params)

    def get_resort(self, resort_id, headers):
        return self._request("GET", f"/resorts/{resort_id}", headers=headers)

    def suspend_resort(self, resort_id, headers):
        return self._request("POST", f"/resorts/{resort_id}/suspend", {}, headers)

    # ---- PassProduct ----
    def create_pass_product(self, payload, headers):
        return self._request("POST", "/pass-products", payload, headers)

    def list_pass_products(self, headers, params=None):
        return self._request("GET", "/pass-products", headers=headers, params=params)

    def get_pass_product(self, product_id, headers):
        return self._request("GET", f"/pass-products/{product_id}", headers=headers)

    # ---- Pass ----
    def create_pass(self, payload, headers):
        return self._request("POST", "/passes", payload, headers)

    def list_passes(self, headers, params=None):
        return self._request("GET", "/passes", headers=headers, params=params)

    def get_pass(self, pass_id, headers):
        return self._request("GET", f"/passes/{pass_id}", headers=headers)

    def activate_pass(self, pass_id, headers):
        return self._request("POST", f"/passes/{pass_id}/activate", {}, headers)

    def suspend_pass(self, pass_id, headers):
        return self._request("POST", f"/passes/{pass_id}/suspend", {}, headers)

    def scan_pass(self, pass_id, payload, headers):
        return self._request("POST", f"/passes/{pass_id}/scan", payload, headers)

    # ---- BuddyTicket ----
    def create_buddy_ticket(self, payload, headers):
        return self._request("POST", "/buddy-tickets", payload, headers)

    def list_buddy_tickets(self, headers, params=None):
        return self._request("GET", "/buddy-tickets", headers=headers, params=params)

    def get_buddy_ticket(self, ticket_id, headers):
        return self._request("GET", f"/buddy-tickets/{ticket_id}", headers=headers)

    def redeem_buddy_ticket(self, ticket_id, headers):
        return self._request("POST", f"/buddy-tickets/{ticket_id}/redeem", {}, headers)

    def cancel_buddy_ticket(self, ticket_id, headers):
        return self._request("POST", f"/buddy-tickets/{ticket_id}/cancel", {}, headers)

    # ---- RefundRequest ----
    def create_refund_request(self, payload, headers):
        return self._request("POST", "/refund-requests", payload, headers)

    def list_refund_requests(self, headers, params=None):
        return self._request("GET", "/refund-requests", headers=headers, params=params)

    def get_refund_request(self, rr_id, headers):
        return self._request("GET", f"/refund-requests/{rr_id}", headers=headers)

    def approve_refund_request(self, rr_id, payload, headers):
        return self._request(
            "POST", f"/refund-requests/{rr_id}/approve", payload, headers
        )

    def reject_refund_request(self, rr_id, headers):
        return self._request("POST", f"/refund-requests/{rr_id}/reject", {}, headers)

    # ---- InterchangeAgreement ----
    def create_interchange_agreement(self, payload, headers):
        return self._request("POST", "/interchange-agreements", payload, headers)

    def list_interchange_agreements(self, headers, params=None):
        return self._request(
            "GET", "/interchange-agreements", headers=headers, params=params
        )

    def get_interchange_agreement(self, agr_id, headers):
        return self._request(
            "GET", f"/interchange-agreements/{agr_id}", headers=headers
        )

    def terminate_interchange_agreement(self, agr_id, headers):
        return self._request(
            "POST", f"/interchange-agreements/{agr_id}/terminate", {}, headers
        )

    # ---- FK reverse-reachability GETs ----
    def list_pass_lift_scans(self, pass_id, headers, params=None):
        return self._request(
            "GET", f"/passes/{pass_id}/lift-scans", headers=headers, params=params
        )

    def list_resort_lift_scans(self, resort_id, headers, params=None):
        return self._request(
            "GET", f"/resorts/{resort_id}/lift-scans", headers=headers, params=params
        )

    def list_pass_buddy_tickets(self, pass_id, headers, params=None):
        return self._request(
            "GET", f"/passes/{pass_id}/buddy-tickets", headers=headers, params=params
        )

    def list_resort_buddy_tickets(self, resort_id, headers, params=None):
        return self._request(
            "GET", f"/resorts/{resort_id}/buddy-tickets", headers=headers, params=params
        )

    def list_pass_refund_requests(self, pass_id, headers, params=None):
        return self._request(
            "GET", f"/passes/{pass_id}/refund-requests", headers=headers, params=params
        )

    def list_resort_interchange_agreements(self, resort_id, headers, params=None):
        return self._request(
            "GET",
            f"/resorts/{resort_id}/interchange-agreements",
            headers=headers,
            params=params,
        )

    # ---- Generic raw helpers (for header-omission / malformed tests) ----
    def raw_get(self, path, headers):
        return self._request("GET", path, headers=headers)

    def raw_post(self, path, payload, headers):
        return self._request("POST", path, payload, headers)


api_client = ApiClient()
