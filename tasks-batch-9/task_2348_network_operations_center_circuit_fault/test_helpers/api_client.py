"""API client: one method per endpoint defined in PRD Section 4."""

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed façade over the network-operations API under test."""

    def __init__(self, base_url: Optional[str] = None):
        super().__init__(base_url)
        # The harness restarts the service between tests, so a pooled
        # keep-alive socket from the previous process is already dead by the
        # time the next test reuses it. Closing each connection keeps every
        # request on a freshly opened socket.
        self.session.headers["Connection"] = "close"

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, payload: dict, headers: dict):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Carriers
    # ------------------------------------------------------------------
    def create_carrier(self, payload: dict, headers: dict):
        return self._request("POST", "/carriers", payload, headers)

    def get_carrier(self, carrier_id: str, headers: dict):
        return self._request("GET", f"/carriers/{carrier_id}", headers=headers)

    def list_carrier_circuits(
        self, carrier_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/carriers/{carrier_id}/circuits", headers=headers, params=params
        )

    def list_carrier_vendor_reviews(
        self, carrier_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"/carriers/{carrier_id}/vendor-reviews",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Circuits
    # ------------------------------------------------------------------
    def create_circuit(self, payload: dict, headers: dict):
        return self._request("POST", "/circuits", payload, headers)

    def get_circuit(self, circuit_id: str, headers: dict):
        return self._request("GET", f"/circuits/{circuit_id}", headers=headers)

    def list_circuit_devices(
        self, circuit_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/circuits/{circuit_id}/devices", headers=headers, params=params
        )

    def create_capacity_reading(self, circuit_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/circuits/{circuit_id}/capacity-readings", payload, headers
        )

    def list_capacity_readings(
        self, circuit_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"/circuits/{circuit_id}/capacity-readings",
            headers=headers,
            params=params,
        )

    def list_circuit_upgrade_orders(
        self, circuit_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"/circuits/{circuit_id}/upgrade-orders",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Devices
    # ------------------------------------------------------------------
    def create_device(self, payload: dict, headers: dict):
        return self._request("POST", "/devices", payload, headers)

    def get_device(self, device_id: str, headers: dict):
        return self._request("GET", f"/devices/{device_id}", headers=headers)

    # ------------------------------------------------------------------
    # Application paths
    # ------------------------------------------------------------------
    def create_application_path(self, payload: dict, headers: dict):
        return self._request("POST", "/application-paths", payload, headers)

    def get_application_path(self, path_id: str, headers: dict):
        return self._request("GET", f"/application-paths/{path_id}", headers=headers)

    def get_path_availability(
        self, path_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"/application-paths/{path_id}/availability",
            headers=headers,
            params=params,
        )

    def list_path_failover_tests(
        self, path_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"/application-paths/{path_id}/failover-tests",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Path segments
    # ------------------------------------------------------------------
    def create_path_segment(self, payload: dict, headers: dict):
        return self._request("POST", "/path-segments", payload, headers)

    def get_path_segment(self, segment_id: str, headers: dict):
        return self._request("GET", f"/path-segments/{segment_id}", headers=headers)

    def list_path_segments(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/path-segments", headers=headers, params=params)

    def delete_path_segment(self, segment_id: str, headers: dict):
        return self._request("DELETE", f"/path-segments/{segment_id}", headers=headers)

    # ------------------------------------------------------------------
    # Alarms
    # ------------------------------------------------------------------
    def create_alarm(self, payload: dict, headers: dict):
        return self._request("POST", "/alarms", payload, headers)

    def clear_alarm(self, alarm_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/alarms/{alarm_id}/clear", payload, headers)

    def get_alarm(self, alarm_id: str, headers: dict):
        return self._request("GET", f"/alarms/{alarm_id}", headers=headers)

    def list_alarms(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/alarms", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Incidents
    # ------------------------------------------------------------------
    def get_incident(self, incident_id: str, headers: dict):
        return self._request("GET", f"/incidents/{incident_id}", headers=headers)

    def list_incidents(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/incidents", headers=headers, params=params)

    def advance_incident_response(self, incident_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/incidents/{incident_id}/response", payload, headers
        )

    def escalate_incident(self, incident_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/incidents/{incident_id}/escalate", payload, headers
        )

    def resolve_incident(self, incident_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/incidents/{incident_id}/resolve", payload, headers
        )

    # ------------------------------------------------------------------
    # Carrier tickets
    # ------------------------------------------------------------------
    def create_carrier_ticket(self, payload: dict, headers: dict):
        return self._request("POST", "/carrier-tickets", payload, headers)

    def get_carrier_ticket(self, ticket_id: str, headers: dict):
        return self._request("GET", f"/carrier-tickets/{ticket_id}", headers=headers)

    def list_carrier_tickets(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/carrier-tickets", headers=headers, params=params)

    def create_test_result(self, ticket_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/carrier-tickets/{ticket_id}/test-results", payload, headers
        )

    def list_test_results(
        self, ticket_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"/carrier-tickets/{ticket_id}/test-results",
            headers=headers,
            params=params,
        )

    def escalate_carrier_ticket(self, ticket_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/carrier-tickets/{ticket_id}/escalate", payload, headers
        )

    def carrier_update_ticket(self, ticket_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/carrier-tickets/{ticket_id}/carrier-update", payload, headers
        )

    def confirm_restoration(self, ticket_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/carrier-tickets/{ticket_id}/confirm-restoration",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # SLA credit claims
    # ------------------------------------------------------------------
    def create_sla_credit_claim(self, payload: dict, headers: dict):
        return self._request("POST", "/sla-credit-claims", payload, headers)

    def get_sla_credit_claim(self, claim_id: str, headers: dict):
        return self._request("GET", f"/sla-credit-claims/{claim_id}", headers=headers)

    def list_sla_credit_claims(self, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", "/sla-credit-claims", headers=headers, params=params
        )

    def submit_sla_credit_claim(self, claim_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/sla-credit-claims/{claim_id}/submit", payload, headers
        )

    def carrier_respond_to_claim(self, claim_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/sla-credit-claims/{claim_id}/carrier-response", payload, headers
        )

    def settle_sla_credit_claim(self, claim_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/sla-credit-claims/{claim_id}/settle", payload, headers
        )

    def withdraw_sla_credit_claim(self, claim_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/sla-credit-claims/{claim_id}/withdraw", payload, headers
        )

    # ------------------------------------------------------------------
    # Maintenance windows
    # ------------------------------------------------------------------
    def create_maintenance_window(self, payload: dict, headers: dict):
        return self._request("POST", "/maintenance-windows", payload, headers)

    def get_maintenance_window(self, window_id: str, headers: dict):
        return self._request(
            "GET", f"/maintenance-windows/{window_id}", headers=headers
        )

    def list_maintenance_windows(self, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", "/maintenance-windows", headers=headers, params=params
        )

    def review_maintenance_window(self, window_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/maintenance-windows/{window_id}/review", payload, headers
        )

    def set_maintenance_window_state(
        self, window_id: str, payload: dict, headers: dict
    ):
        return self._request(
            "POST", f"/maintenance-windows/{window_id}/state", payload, headers
        )

    # ------------------------------------------------------------------
    # Failover tests
    # ------------------------------------------------------------------
    def create_failover_test(self, payload: dict, headers: dict):
        return self._request("POST", "/failover-tests", payload, headers)

    def start_failover_test(self, test_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/failover-tests/{test_id}/start", payload, headers
        )

    def record_failover_result(self, test_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/failover-tests/{test_id}/record-result", payload, headers
        )

    # ------------------------------------------------------------------
    # Upgrade orders
    # ------------------------------------------------------------------
    def create_upgrade_order(self, payload: dict, headers: dict):
        return self._request("POST", "/upgrade-orders", payload, headers)

    def submit_upgrade_order(self, order_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/upgrade-orders/{order_id}/submit", payload, headers
        )

    def approve_upgrade_order(self, order_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/upgrade-orders/{order_id}/approve", payload, headers
        )

    def set_upgrade_order_state(self, order_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/upgrade-orders/{order_id}/state", payload, headers
        )

    def cancel_upgrade_order(self, order_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/upgrade-orders/{order_id}/cancel", payload, headers
        )

    # ------------------------------------------------------------------
    # Vendor reviews
    # ------------------------------------------------------------------
    def create_vendor_review(self, payload: dict, headers: dict):
        return self._request("POST", "/vendor-reviews", payload, headers)

    def decide_vendor_review(self, review_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/vendor-reviews/{review_id}/decide", payload, headers
        )


api_client = ApiClient()
