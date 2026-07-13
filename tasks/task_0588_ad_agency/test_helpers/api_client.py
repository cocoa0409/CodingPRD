"""API client: one method per endpoint defined in the PRD (§4)."""

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def __init__(self, base_url=None):
        super().__init__(base_url)
        # Per-test-server isolation kills and relaunches the server on the SAME
        # port before every test, while this module-level client (and its
        # requests.Session connection pool) lives for the whole pytest process.
        # A pooled keep-alive socket opened against a prior boot points at a
        # now-dead server; reusing it surfaces as an intermittent
        # ConnectionError/BadStatusLine. Asking the server to close each socket
        # after responding minimizes pooling. Transport-only — this changes no
        # payload, header identity or assertion the PRD speaks about.
        self.session.headers["Connection"] = "close"

    def _request(self, method, path, payload=None, headers=None, params=None):
        # The runner hands out server ports from the OS ephemeral range and
        # kill -9's / rebinds that port before every test. During the unbound
        # window a loopback connect can be handed its own port as the source
        # port, producing a TCP self-connect whose "response" is the client's
        # own request line (BadStatusLine('POST /invoices HTTP/1.1')). Such a
        # request provably never reached a server, so retrying it once on a
        # fresh connection is safe and deterministic. Only genuine transport
        # drops are retried: a real server-side fault answers with an HTTP
        # 4xx/5xx response, not a ConnectionError, so this can never mask an
        # implementation bug.
        try:
            return super()._request(method, path, payload, headers, params)
        except requests.exceptions.ConnectionError:
            self.session.close()  # discard any stale / self-connected sockets
            return super()._request(method, path, payload, headers, params)

    # --- Logical clock ----------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Client -----------------------------------------------------------
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    # --- RateCard ---------------------------------------------------------
    def create_rate_card(self, payload, headers):
        return self._request("POST", "/rate-cards", payload, headers)

    def update_rate_card(self, rate_card_id, payload, headers):
        return self._request("PATCH", f"/rate-cards/{rate_card_id}", payload, headers)

    # --- StaffMember ------------------------------------------------------
    def create_staff_member(self, payload, headers):
        return self._request("POST", "/staff-members", payload, headers)

    def get_staff_utilization(self, staff_id, headers, params=None):
        return self._request(
            "GET", f"/staff-members/{staff_id}/utilization", headers=headers, params=params
        )

    # --- MediaPlacement ---------------------------------------------------
    def create_media_placement(self, payload, headers):
        return self._request("POST", "/media-placements", payload, headers)

    # --- Retainer ---------------------------------------------------------
    def create_retainer(self, payload, headers):
        return self._request("POST", "/retainers", payload, headers)

    def get_retainer(self, retainer_id, headers):
        return self._request("GET", f"/retainers/{retainer_id}", headers=headers)

    def list_retainers(self, headers, params=None):
        return self._request("GET", "/retainers", headers=headers, params=params)

    def fund_retainer(self, retainer_id, payload, headers):
        return self._request("POST", f"/retainers/{retainer_id}/fund", payload, headers)

    # --- SOW --------------------------------------------------------------
    def create_sow(self, payload, headers):
        return self._request("POST", "/sows", payload, headers)

    def get_sow(self, sow_id, headers):
        return self._request("GET", f"/sows/{sow_id}", headers=headers)

    def list_sows(self, headers, params=None):
        return self._request("GET", "/sows", headers=headers, params=params)

    def countersign_sow(self, sow_id, headers):
        return self._request("POST", f"/sows/{sow_id}/countersign", {}, headers)

    # --- Campaign ---------------------------------------------------------
    def create_campaign(self, payload, headers):
        return self._request("POST", "/campaigns", payload, headers)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/campaigns/{campaign_id}", headers=headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", "/campaigns", headers=headers, params=params)

    def launch_campaign(self, campaign_id, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/launch", {}, headers)

    def list_campaign_deliverables(self, campaign_id, headers, params=None):
        return self._request(
            "GET", f"/campaigns/{campaign_id}/deliverables", headers=headers, params=params
        )

    def list_campaign_vendor_costs(self, campaign_id, headers, params=None):
        return self._request(
            "GET", f"/campaigns/{campaign_id}/vendor-costs", headers=headers, params=params
        )

    def get_campaign_performance_report(self, campaign_id, headers):
        return self._request(
            "GET", f"/campaigns/{campaign_id}/performance-report", headers=headers
        )

    # --- Deliverable ------------------------------------------------------
    def create_deliverable(self, payload, headers):
        return self._request("POST", "/deliverables", payload, headers)

    def submit_deliverable(self, deliverable_id, headers):
        return self._request("POST", f"/deliverables/{deliverable_id}/submit", {}, headers)

    def request_changes_deliverable(self, deliverable_id, payload, headers):
        return self._request(
            "POST", f"/deliverables/{deliverable_id}/request-changes", payload, headers
        )

    def approve_deliverable(self, deliverable_id, headers):
        return self._request("POST", f"/deliverables/{deliverable_id}/approve", {}, headers)

    # --- TimeEntry --------------------------------------------------------
    def create_time_entry(self, payload, headers):
        return self._request("POST", "/time-entries", payload, headers)

    def get_time_entry(self, time_entry_id, headers):
        return self._request("GET", f"/time-entries/{time_entry_id}", headers=headers)

    def list_time_entries(self, headers, params=None):
        return self._request("GET", "/time-entries", headers=headers, params=params)

    def approve_time_entry(self, time_entry_id, headers):
        return self._request("POST", f"/time-entries/{time_entry_id}/approve", {}, headers)

    # --- VendorCost -------------------------------------------------------
    def create_vendor_cost(self, payload, headers):
        return self._request("POST", "/vendor-costs", payload, headers)

    def approve_vendor_cost(self, vendor_cost_id, payload, headers):
        return self._request(
            "POST", f"/vendor-costs/{vendor_cost_id}/approve", payload, headers
        )

    # --- MediaPlan --------------------------------------------------------
    def create_media_plan(self, payload, headers):
        return self._request("POST", "/media-plans", payload, headers)

    def get_media_plan(self, media_plan_id, headers):
        return self._request("GET", f"/media-plans/{media_plan_id}", headers=headers)

    def list_media_plans(self, headers, params=None):
        return self._request("GET", "/media-plans", headers=headers, params=params)

    def approve_media_plan(self, media_plan_id, headers):
        return self._request("POST", f"/media-plans/{media_plan_id}/approve", {}, headers)

    # --- InsertionOrder ---------------------------------------------------
    def create_insertion_order(self, payload, headers):
        return self._request("POST", "/insertion-orders", payload, headers)

    def get_insertion_order(self, insertion_order_id, headers):
        return self._request(
            "GET", f"/insertion-orders/{insertion_order_id}", headers=headers
        )

    def list_insertion_orders(self, headers, params=None):
        return self._request("GET", "/insertion-orders", headers=headers, params=params)

    def place_insertion_order(self, insertion_order_id, headers):
        return self._request(
            "POST", f"/insertion-orders/{insertion_order_id}/place", {}, headers
        )

    def cancel_insertion_order(self, insertion_order_id, headers):
        return self._request(
            "POST", f"/insertion-orders/{insertion_order_id}/cancel", {}, headers
        )

    def deliver_insertion_order(self, insertion_order_id, payload, headers):
        return self._request(
            "POST", f"/insertion-orders/{insertion_order_id}/deliver", payload, headers
        )

    # --- Invoice ----------------------------------------------------------
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def issue_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/issue", payload, headers)

    def void_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", payload, headers)

    def pay_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/payments", payload, headers)


api_client = ApiClient()
