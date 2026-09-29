"""Domain API client: one method per endpoint of PRD §4.

Every method returns the raw ``requests.Response`` so that tests can assert on
status codes as well as bodies.
"""

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


class DtcApiClient(GenericApiClient):
    """Client for the Winery DTC Shipping Compliance API mounted under /dtc."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc, headers=None):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ------------------------------------------------------------------
    # Wineries
    # ------------------------------------------------------------------
    def create_winery(self, payload, headers=None):
        return self._request("POST", f"{API_PREFIX}/wineries", payload, headers)

    def get_winery(self, winery_id, headers=None):
        return self._request("GET", f"{API_PREFIX}/wineries/{winery_id}", None, headers)

    def list_wineries(self, headers=None, params=None):
        return self._request("GET", f"{API_PREFIX}/wineries", params, headers)

    def set_winery_status(self, winery_id, payload, headers=None):
        return self._request(
            "POST", f"{API_PREFIX}/wineries/{winery_id}/status", payload, headers
        )

    # ------------------------------------------------------------------
    # State rules and prohibited ZIPs
    # ------------------------------------------------------------------
    def create_state_rule(self, payload, headers=None):
        return self._request("POST", f"{API_PREFIX}/state-rules", payload, headers)

    def get_state_rule(self, state_rule_id, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/state-rules/{state_rule_id}", None, headers
        )

    def list_state_rules(self, headers=None, params=None):
        return self._request("GET", f"{API_PREFIX}/state-rules", params, headers)

    def create_prohibited_zip(self, state_rule_id, payload, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/state-rules/{state_rule_id}/prohibited-zips",
            payload,
            headers,
        )

    def list_prohibited_zips(self, state_rule_id, headers=None, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/state-rules/{state_rule_id}/prohibited-zips",
            params,
            headers,
        )

    # ------------------------------------------------------------------
    # State permits
    # ------------------------------------------------------------------
    def create_state_permit(self, payload, headers=None):
        return self._request("POST", f"{API_PREFIX}/state-permits", payload, headers)

    def get_state_permit(self, permit_id, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/state-permits/{permit_id}", None, headers
        )

    def list_state_permits(self, headers=None, params=None):
        return self._request("GET", f"{API_PREFIX}/state-permits", params, headers)

    def activate_state_permit(self, permit_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/state-permits/{permit_id}/activate",
            payload if payload is not None else {},
            headers,
        )

    def file_permit_renewal(self, permit_id, payload, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/state-permits/{permit_id}/file-renewal",
            payload,
            headers,
        )

    def approve_permit_renewal(self, permit_id, payload, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/state-permits/{permit_id}/approve-renewal",
            payload,
            headers,
        )

    def revoke_state_permit(self, permit_id, payload, headers=None):
        return self._request(
            "POST", f"{API_PREFIX}/state-permits/{permit_id}/revoke", payload, headers
        )

    # ------------------------------------------------------------------
    # Carrier programs and enrollments
    # ------------------------------------------------------------------
    def create_carrier_program(self, payload, headers=None):
        return self._request("POST", f"{API_PREFIX}/carrier-programs", payload, headers)

    def get_carrier_program(self, program_id, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/carrier-programs/{program_id}", None, headers
        )

    def list_carrier_programs(self, headers=None, params=None):
        return self._request("GET", f"{API_PREFIX}/carrier-programs", params, headers)

    def create_carrier_enrollment(self, payload, headers=None):
        return self._request(
            "POST", f"{API_PREFIX}/carrier-enrollments", payload, headers
        )

    def get_carrier_enrollment(self, enrollment_id, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/carrier-enrollments/{enrollment_id}", None, headers
        )

    def list_carrier_enrollments(self, headers=None, params=None):
        return self._request("GET", f"{API_PREFIX}/carrier-enrollments", params, headers)

    def decide_carrier_enrollment(self, enrollment_id, payload, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/carrier-enrollments/{enrollment_id}/decision",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Consumers
    # ------------------------------------------------------------------
    def create_consumer(self, payload, headers=None):
        return self._request("POST", f"{API_PREFIX}/consumers", payload, headers)

    def get_consumer(self, consumer_id, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/consumers/{consumer_id}", None, headers
        )

    def list_consumers(self, headers=None, params=None):
        return self._request("GET", f"{API_PREFIX}/consumers", params, headers)

    def verify_consumer_id(self, consumer_id, payload, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/consumers/{consumer_id}/id-verification",
            payload,
            headers,
        )

    def get_volume_summary(self, consumer_id, headers=None, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/consumers/{consumer_id}/volume-summary",
            params,
            headers,
        )

    # ------------------------------------------------------------------
    # Club subscriptions and runs
    # ------------------------------------------------------------------
    def create_club_subscription(self, payload, headers=None):
        return self._request(
            "POST", f"{API_PREFIX}/club-subscriptions", payload, headers
        )

    def get_club_subscription(self, subscription_id, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/club-subscriptions/{subscription_id}", None, headers
        )

    def list_club_subscriptions(self, headers=None, params=None):
        return self._request("GET", f"{API_PREFIX}/club-subscriptions", params, headers)

    def place_weather_hold(self, subscription_id, payload, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/club-subscriptions/{subscription_id}/weather-hold",
            payload,
            headers,
        )

    def release_hold(self, subscription_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/club-subscriptions/{subscription_id}/release-hold",
            payload if payload is not None else {},
            headers,
        )

    def create_club_run(self, payload, headers=None):
        return self._request("POST", f"{API_PREFIX}/club-runs", payload, headers)

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------
    def create_order(self, payload, headers=None):
        return self._request("POST", f"{API_PREFIX}/orders", payload, headers)

    def get_order(self, order_id, headers=None):
        return self._request("GET", f"{API_PREFIX}/orders/{order_id}", None, headers)

    def list_orders(self, headers=None, params=None):
        return self._request("GET", f"{API_PREFIX}/orders", params, headers)

    def list_order_lines(self, order_id, headers=None, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/orders/{order_id}/lines", params, headers
        )

    def screen_order(self, order_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/orders/{order_id}/screen",
            payload if payload is not None else {},
            headers,
        )

    def raise_compliance_exception(self, order_id, payload, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/orders/{order_id}/compliance-exceptions",
            payload,
            headers,
        )

    def list_order_compliance_exceptions(self, order_id, headers=None, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/orders/{order_id}/compliance-exceptions",
            params,
            headers,
        )

    def get_compliance_exception(self, exception_id, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/compliance-exceptions/{exception_id}", None, headers
        )

    def decide_compliance_exception(self, exception_id, payload, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/compliance-exceptions/{exception_id}/decision",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Shipments
    # ------------------------------------------------------------------
    def create_shipment(self, payload, headers=None):
        return self._request("POST", f"{API_PREFIX}/shipments", payload, headers)

    def get_shipment(self, shipment_id, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/shipments/{shipment_id}", None, headers
        )

    def list_shipments(self, headers=None, params=None):
        return self._request("GET", f"{API_PREFIX}/shipments", params, headers)

    def scan_shipment(self, shipment_id, payload, headers=None):
        return self._request(
            "POST", f"{API_PREFIX}/shipments/{shipment_id}/scan", payload, headers
        )

    # ------------------------------------------------------------------
    # Volume ledger
    # ------------------------------------------------------------------
    def create_volume_ledger_entry(self, payload, headers=None):
        return self._request(
            "POST", f"{API_PREFIX}/volume-ledger-entries", payload, headers
        )

    def get_volume_ledger_entry(self, entry_id, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/volume-ledger-entries/{entry_id}", None, headers
        )

    def list_volume_ledger_entries(self, headers=None, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/volume-ledger-entries", params, headers
        )

    # ------------------------------------------------------------------
    # Remittances and the renewal calendar
    # ------------------------------------------------------------------
    def create_remittance(self, payload, headers=None):
        return self._request("POST", f"{API_PREFIX}/remittances", payload, headers)

    def get_remittance(self, remittance_id, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/remittances/{remittance_id}", None, headers
        )

    def list_remittances(self, headers=None, params=None):
        return self._request("GET", f"{API_PREFIX}/remittances", params, headers)

    def file_remittance(self, remittance_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/remittances/{remittance_id}/file",
            payload if payload is not None else {},
            headers,
        )

    def remit_remittance(self, remittance_id, payload, headers=None):
        return self._request(
            "POST", f"{API_PREFIX}/remittances/{remittance_id}/remit", payload, headers
        )

    def get_renewal_calendar(self, headers=None, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/renewal-calendar", params, headers
        )


# Backwards-compatible alias used by some tests.
ApiClient = DtcApiClient
