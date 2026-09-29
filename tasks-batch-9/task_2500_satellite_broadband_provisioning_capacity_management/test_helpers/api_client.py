"""API client: one method per endpoint defined in the PRD.

Every path is mounted under the `/satellite-broadband` service root.
"""

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/satellite-broadband"


class ApiClient(GenericApiClient):
    """Thin wrapper exposing one named method per PRD endpoint."""

    # ───────────────────────── logical clock ─────────────────────────

    def set_clock(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # ─────────────────────── spectrum licences ───────────────────────

    def create_spectrum_license(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/spectrum-licenses", payload, headers)

    def get_spectrum_license(self, license_id: str, headers: dict):
        return self._request("GET", f"{PREFIX}/spectrum-licenses/{license_id}", headers=headers)

    def record_coordination(self, license_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/spectrum-licenses/{license_id}/coordination", payload, headers
        )

    def enforcement_action(self, license_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/spectrum-licenses/{license_id}/enforcement-action", payload, headers
        )

    # ───────────────────────────── beams ─────────────────────────────

    def create_beam(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/beams", payload, headers)

    def get_beam(self, beam_id: str, headers: dict):
        return self._request("GET", f"{PREFIX}/beams/{beam_id}", headers=headers)

    def list_beams(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/beams", headers=headers, params=params)

    def write_capacity_policy(self, beam_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/beams/{beam_id}/capacity-policy", payload, headers
        )

    def close_billing_cycle(self, beam_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"{PREFIX}/beams/{beam_id}/billing-cycle-close", payload, headers
        )

    # ────────────────────────── service cells ────────────────────────

    def create_service_cell(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/service-cells", payload, headers)

    def get_service_cell(self, cell_id: str, headers: dict):
        return self._request("GET", f"{PREFIX}/service-cells/{cell_id}", headers=headers)

    def list_service_cells(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/service-cells", headers=headers, params=params)

    def get_cell_availability(self, cell_id: str, headers: dict):
        return self._request(
            "GET", f"{PREFIX}/service-cells/{cell_id}/availability", headers=headers
        )

    # ────────────────────────── service plans ────────────────────────

    def create_service_plan(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/service-plans", payload, headers)

    # ─────────────────────────── subscribers ─────────────────────────

    def create_subscriber(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/subscribers", payload, headers)

    def get_subscriber(self, subscriber_id: str, headers: dict):
        return self._request("GET", f"{PREFIX}/subscribers/{subscriber_id}", headers=headers)

    # ────────────────────────── service orders ───────────────────────

    def create_service_order(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/service-orders", payload, headers)

    def get_service_order(self, order_id: str, headers: dict):
        return self._request("GET", f"{PREFIX}/service-orders/{order_id}", headers=headers)

    def list_service_orders(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/service-orders", headers=headers, params=params)

    def cancel_service_order(self, order_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/service-orders/{order_id}/cancel", payload, headers
        )

    # ───────────────────────────── terminals ─────────────────────────

    def create_terminal(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/terminals", payload, headers)

    def get_terminal(self, terminal_id: str, headers: dict):
        return self._request("GET", f"{PREFIX}/terminals/{terminal_id}", headers=headers)

    def list_terminals(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/terminals", headers=headers, params=params)

    def deliver_terminal(self, terminal_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"{PREFIX}/terminals/{terminal_id}/deliver", payload, headers
        )

    def create_obstruction_scan(self, terminal_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/terminals/{terminal_id}/obstruction-scans", payload, headers
        )

    def list_obstruction_scans(
        self, terminal_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/terminals/{terminal_id}/obstruction-scans",
            headers=headers,
            params=params,
        )

    def install_terminal(self, terminal_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"{PREFIX}/terminals/{terminal_id}/install", payload, headers
        )

    def return_terminal(self, terminal_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/terminals/{terminal_id}/return", payload, headers
        )

    def warranty_replacement(self, terminal_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/terminals/{terminal_id}/warranty-replacement", payload, headers
        )

    def transfer_terminal(self, terminal_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/terminals/{terminal_id}/transfer", payload, headers
        )

    # ──────────────────────────── subscriptions ──────────────────────

    def create_subscription(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/subscriptions", payload, headers)

    def get_subscription(self, subscription_id: str, headers: dict):
        return self._request("GET", f"{PREFIX}/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/subscriptions", headers=headers, params=params)

    def acknowledge_disclosure(self, subscription_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{PREFIX}/subscriptions/{subscription_id}/disclosure-acknowledgement",
            payload,
            headers,
        )

    def authorize_subscription(self, subscription_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/subscriptions/{subscription_id}/authorize", payload, headers
        )

    def change_plan(self, subscription_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/subscriptions/{subscription_id}/plan-change", payload, headers
        )

    def suspend_subscription(self, subscription_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/subscriptions/{subscription_id}/suspend", payload, headers
        )

    def terminate_subscription(self, subscription_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/subscriptions/{subscription_id}/terminate", payload, headers
        )

    def create_usage_record(self, subscription_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/subscriptions/{subscription_id}/usage-records", payload, headers
        )

    def list_usage_records(
        self, subscription_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/subscriptions/{subscription_id}/usage-records",
            headers=headers,
            params=params,
        )

    # ───────────────────── roaming authorisations ────────────────────

    def create_roaming_authorization(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/roaming-authorizations", payload, headers)

    def get_roaming_authorization(self, authorization_id: str, headers: dict):
        return self._request(
            "GET", f"{PREFIX}/roaming-authorizations/{authorization_id}", headers=headers
        )

    def list_roaming_authorizations(self, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/roaming-authorizations", headers=headers, params=params
        )

    def request_roaming_info(self, authorization_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{PREFIX}/roaming-authorizations/{authorization_id}/request-info",
            payload,
            headers,
        )

    def resubmit_roaming_authorization(self, authorization_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{PREFIX}/roaming-authorizations/{authorization_id}/resubmit",
            payload,
            headers,
        )

    def decide_roaming_authorization(self, authorization_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{PREFIX}/roaming-authorizations/{authorization_id}/decide",
            payload,
            headers,
        )

    # ─────────────────────────── outage events ───────────────────────

    def create_outage_event(self, payload: dict, headers: dict):
        return self._request("POST", f"{PREFIX}/outage-events", payload, headers)

    def get_outage_event(self, event_id: str, headers: dict):
        return self._request("GET", f"{PREFIX}/outage-events/{event_id}", headers=headers)

    def list_outage_events(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/outage-events", headers=headers, params=params)

    def resolve_outage_event(self, event_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/outage-events/{event_id}/resolve", payload, headers
        )

    # ─────────────────────────── outage credits ──────────────────────

    def get_outage_credit(self, credit_id: str, headers: dict):
        return self._request("GET", f"{PREFIX}/outage-credits/{credit_id}", headers=headers)

    def list_outage_credits(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/outage-credits", headers=headers, params=params)

    def submit_outage_credit(self, credit_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"{PREFIX}/outage-credits/{credit_id}/submit", payload, headers
        )

    def decide_outage_credit(self, credit_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{PREFIX}/outage-credits/{credit_id}/decide", payload, headers
        )


api_client = ApiClient()
