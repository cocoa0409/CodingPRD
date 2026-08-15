"""API client: one method per endpoint defined in the PRD.

Every path is mounted under the /campus prefix except the logical clock,
which lives at the server root (/_clock/set_current_utc).
"""

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/campus"


class ApiClient(GenericApiClient):
    # ---- logical clock -------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- organizations ---------------------------------------------------
    def create_organization(self, payload, headers):
        return self._request("POST", f"{BASE}/organizations", payload, headers)

    def get_organization(self, org_id, headers):
        return self._request("GET", f"{BASE}/organizations/{org_id}", headers=headers)

    def update_organization(self, org_id, payload, headers):
        return self._request("PATCH", f"{BASE}/organizations/{org_id}", payload, headers)

    def reinstate_organization(self, org_id, headers):
        return self._request(
            "POST", f"{BASE}/organizations/{org_id}/reinstate", {}, headers
        )

    # ---- rooms -----------------------------------------------------------
    def create_room(self, payload, headers):
        return self._request("POST", f"{BASE}/rooms", payload, headers)

    def get_room(self, room_id, headers):
        return self._request("GET", f"{BASE}/rooms/{room_id}", headers=headers)

    def update_room(self, room_id, payload, headers):
        return self._request("PATCH", f"{BASE}/rooms/{room_id}", payload, headers)

    def room_out_of_service(self, room_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/rooms/{room_id}/out-of-service", payload, headers
        )

    def get_room_utilization(self, room_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/rooms/{room_id}/utilization", headers=headers, params=params
        )

    # ---- terms -----------------------------------------------------------
    def create_term(self, payload, headers):
        return self._request("POST", f"{BASE}/terms", payload, headers)

    def get_term(self, term_id, headers):
        return self._request("GET", f"{BASE}/terms/{term_id}", headers=headers)

    # ---- academic blocks ---------------------------------------------------
    def create_academic_block(self, payload, headers):
        return self._request("POST", f"{BASE}/academic-blocks", payload, headers)

    def get_academic_block(self, block_id, headers):
        return self._request("GET", f"{BASE}/academic-blocks/{block_id}", headers=headers)

    def list_academic_blocks(self, headers, params=None):
        return self._request("GET", f"{BASE}/academic-blocks", headers=headers, params=params)

    def unplace_academic_block(self, block_id, headers):
        return self._request(
            "POST", f"{BASE}/academic-blocks/{block_id}/unplace", {}, headers
        )

    # ---- scheduling runs ---------------------------------------------------
    def create_scheduling_run(self, payload, headers):
        return self._request("POST", f"{BASE}/scheduling-runs", payload, headers)

    def get_scheduling_run(self, run_id, headers):
        return self._request("GET", f"{BASE}/scheduling-runs/{run_id}", headers=headers)

    def list_scheduling_runs(self, headers, params=None):
        return self._request("GET", f"{BASE}/scheduling-runs", headers=headers, params=params)

    def finalize_scheduling_run(self, run_id, headers):
        return self._request(
            "POST", f"{BASE}/scheduling-runs/{run_id}/finalize", {}, headers
        )

    # ---- event reservations ------------------------------------------------
    def create_event_reservation(self, payload, headers):
        return self._request("POST", f"{BASE}/event-reservations", payload, headers)

    def get_event_reservation(self, event_id, headers):
        return self._request(
            "GET", f"{BASE}/event-reservations/{event_id}", headers=headers
        )

    def list_event_reservations(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/event-reservations", headers=headers, params=params
        )

    def approve_event(self, event_id, headers):
        return self._request(
            "POST", f"{BASE}/event-reservations/{event_id}/approve", {}, headers
        )

    def decline_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/event-reservations/{event_id}/decline", payload, headers
        )

    def confirm_event(self, event_id, headers):
        return self._request(
            "POST", f"{BASE}/event-reservations/{event_id}/confirm", {}, headers
        )

    def cancel_event(self, event_id, headers):
        return self._request(
            "POST", f"{BASE}/event-reservations/{event_id}/cancel", {}, headers
        )

    def rebook_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/event-reservations/{event_id}/rebook", payload, headers
        )

    def check_in_event(self, event_id, headers):
        return self._request(
            "POST", f"{BASE}/event-reservations/{event_id}/check-in", {}, headers
        )

    # ---- service orders ----------------------------------------------------
    def create_service_order(self, payload, headers):
        return self._request("POST", f"{BASE}/service-orders", payload, headers)

    def get_service_order(self, order_id, headers):
        return self._request("GET", f"{BASE}/service-orders/{order_id}", headers=headers)

    def list_service_orders(self, headers, params=None):
        return self._request("GET", f"{BASE}/service-orders", headers=headers, params=params)

    def quote_service_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/service-orders/{order_id}/quote", payload, headers
        )

    def approve_service_order(self, order_id, headers):
        return self._request(
            "POST", f"{BASE}/service-orders/{order_id}/approve", {}, headers
        )

    def request_service_order_revision(self, order_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/service-orders/{order_id}/request-revision",
            payload,
            headers,
        )

    def schedule_service_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/service-orders/{order_id}/schedule", payload, headers
        )

    def fulfill_service_order(self, order_id, headers):
        return self._request(
            "POST", f"{BASE}/service-orders/{order_id}/fulfill", {}, headers
        )

    def cancel_service_order(self, order_id, headers):
        return self._request(
            "POST", f"{BASE}/service-orders/{order_id}/cancel", {}, headers
        )

    # ---- service crews -----------------------------------------------------
    def create_service_crew(self, payload, headers):
        return self._request("POST", f"{BASE}/service-crews", payload, headers)

    # ---- invoices ----------------------------------------------------------
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"{BASE}/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", f"{BASE}/invoices", headers=headers, params=params)

    def pay_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"{BASE}/invoices/{invoice_id}/pay", payload, headers)

    def waive_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/invoices/{invoice_id}/waive", payload, headers
        )

    def refund_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/invoices/{invoice_id}/refund", payload, headers
        )

    # ---- access grants -----------------------------------------------------
    def create_access_grant(self, payload, headers):
        return self._request("POST", f"{BASE}/access-grants", payload, headers)

    def get_access_grant(self, grant_id, headers):
        return self._request("GET", f"{BASE}/access-grants/{grant_id}", headers=headers)

    def list_access_grants(self, headers, params=None):
        return self._request("GET", f"{BASE}/access-grants", headers=headers, params=params)

    def issue_access_grant(self, grant_id, headers):
        return self._request(
            "POST", f"{BASE}/access-grants/{grant_id}/issue", {}, headers
        )

    def return_access_grant(self, grant_id, headers):
        return self._request(
            "POST", f"{BASE}/access-grants/{grant_id}/return", {}, headers
        )

    def mark_lost_access_grant(self, grant_id, headers):
        return self._request(
            "POST", f"{BASE}/access-grants/{grant_id}/mark-lost", {}, headers
        )

    # ---- ops ---------------------------------------------------------------
    def daily_close(self, headers):
        return self._request("POST", f"{BASE}/ops/daily-close", {}, headers)


api_client = ApiClient()
