"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() method
(signature: _request(method, path, json=None, headers=None, params=None))
is inherited. All endpoint methods take an explicit `headers` argument so
tests can thread the correct role (and, for entity-backed Customers, the
correct owning identity).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Restaurant ──────────────────────────────────────────────────────
    def create_restaurant(self, payload, headers):
        return self._request("POST", "/restaurants", payload, headers)

    def get_restaurant(self, restaurant_id, headers):
        return self._request("GET", f"/restaurants/{restaurant_id}", headers=headers)

    def close_restaurant(self, restaurant_id, headers):
        return self._request("POST", f"/restaurants/{restaurant_id}/close", {}, headers)

    def open_restaurant(self, restaurant_id, headers):
        return self._request("POST", f"/restaurants/{restaurant_id}/open", {}, headers)

    # ─── DiningArea ──────────────────────────────────────────────────────
    def create_dining_area(self, payload, headers):
        return self._request("POST", "/dining-areas", payload, headers)

    def get_dining_area(self, area_id, headers):
        return self._request("GET", f"/dining-areas/{area_id}", headers=headers)

    def list_dining_areas(self, headers, params=None):
        return self._request("GET", "/dining-areas", headers=headers, params=params)

    # ─── Table ───────────────────────────────────────────────────────────
    def create_table(self, payload, headers):
        return self._request("POST", "/tables", payload, headers)

    def get_table(self, table_id, headers):
        return self._request("GET", f"/tables/{table_id}", headers=headers)

    def list_tables(self, headers, params=None):
        return self._request("GET", "/tables", headers=headers, params=params)

    def table_out_of_service(self, table_id, headers):
        return self._request("POST", f"/tables/{table_id}/out-of-service", {}, headers)

    def table_return_to_service(self, table_id, headers):
        return self._request("POST", f"/tables/{table_id}/return-to-service", {}, headers)

    def bus_table(self, table_id, headers):
        return self._request("POST", f"/tables/{table_id}/bus", {}, headers)

    # ─── ServicePeriod ───────────────────────────────────────────────────
    def create_service_period(self, payload, headers):
        return self._request("POST", "/service-periods", payload, headers)

    def get_service_period(self, period_id, headers):
        return self._request("GET", f"/service-periods/{period_id}", headers=headers)

    def list_service_periods(self, headers, params=None):
        return self._request("GET", "/service-periods", headers=headers, params=params)

    # ─── Customer ────────────────────────────────────────────────────────
    def create_customer(self, payload, headers=None):
        # Self-registration: no auth required.
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def get_customer_reliability(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/customers/{customer_id}/reliability", headers=headers, params=params
        )

    def block_customer(self, customer_id, headers):
        return self._request("POST", f"/customers/{customer_id}/block", {}, headers)

    def unblock_customer(self, customer_id, headers):
        return self._request("POST", f"/customers/{customer_id}/unblock", {}, headers)

    # ─── Reservation ─────────────────────────────────────────────────────
    def create_reservation(self, payload, headers):
        return self._request("POST", "/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/reservations", headers=headers, params=params)

    def place_deposit_hold(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/deposit-holds", payload, headers
        )

    def confirm_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/confirm", {}, headers)

    def reschedule_reservation(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/reschedule", payload, headers
        )

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/cancel", {}, headers)

    def seat_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/seat", {}, headers)

    def no_show_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/no-show", {}, headers)

    def complete_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/complete", {}, headers)

    # ─── DepositHold ─────────────────────────────────────────────────────
    def get_deposit_hold(self, hold_id, headers):
        return self._request("GET", f"/deposit-holds/{hold_id}", headers=headers)

    def list_deposit_holds(self, headers, params=None):
        return self._request("GET", "/deposit-holds", headers=headers, params=params)

    def capture_deposit_hold(self, hold_id, headers):
        return self._request("POST", f"/deposit-holds/{hold_id}/capture", {}, headers)

    def release_deposit_hold(self, hold_id, headers):
        return self._request("POST", f"/deposit-holds/{hold_id}/release", {}, headers)

    # ─── WaitlistEntry ───────────────────────────────────────────────────
    def create_waitlist_entry(self, payload, headers):
        return self._request("POST", "/waitlist-entries", payload, headers)

    def get_waitlist_entry(self, entry_id, headers):
        return self._request("GET", f"/waitlist-entries/{entry_id}", headers=headers)

    def list_waitlist_entries(self, headers, params=None):
        return self._request("GET", "/waitlist-entries", headers=headers, params=params)

    def notify_waitlist_entry(self, entry_id, headers):
        return self._request("POST", f"/waitlist-entries/{entry_id}/notify", {}, headers)

    def convert_waitlist_entry(self, entry_id, payload, headers):
        return self._request(
            "POST", f"/waitlist-entries/{entry_id}/convert", payload, headers
        )

    def requeue_waitlist_entry(self, entry_id, headers):
        return self._request("POST", f"/waitlist-entries/{entry_id}/requeue", {}, headers)

    def cancel_waitlist_entry(self, entry_id, headers):
        return self._request("POST", f"/waitlist-entries/{entry_id}/cancel", {}, headers)

    # ─── SpecialRequest ──────────────────────────────────────────────────
    def create_special_request(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/special-requests", payload, headers
        )

    def list_special_requests(self, reservation_id, headers, params=None):
        return self._request(
            "GET", f"/reservations/{reservation_id}/special-requests",
            headers=headers, params=params,
        )

    def acknowledge_special_request(self, special_request_id, headers):
        return self._request(
            "POST", f"/special-requests/{special_request_id}/acknowledge", {}, headers
        )

    # ─── Notification ────────────────────────────────────────────────────
    def get_notification(self, notification_id, headers):
        return self._request("GET", f"/notifications/{notification_id}", headers=headers)

    def list_notifications(self, headers, params=None):
        return self._request("GET", "/notifications", headers=headers, params=params)

    # ─── PrivateDiningEvent ──────────────────────────────────────────────
    def create_private_dining_event(self, payload, headers):
        return self._request("POST", "/private-dining-events", payload, headers)

    def get_private_dining_event(self, event_id, headers):
        return self._request("GET", f"/private-dining-events/{event_id}", headers=headers)

    def list_private_dining_events(self, headers, params=None):
        return self._request("GET", "/private-dining-events", headers=headers, params=params)

    def propose_private_dining_event(self, event_id, headers):
        return self._request(
            "POST", f"/private-dining-events/{event_id}/propose", {}, headers
        )

    def revise_private_dining_event(self, event_id, headers):
        return self._request(
            "POST", f"/private-dining-events/{event_id}/revise", {}, headers
        )

    def confirm_private_dining_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"/private-dining-events/{event_id}/confirm", payload, headers
        )

    def complete_private_dining_event(self, event_id, headers):
        return self._request(
            "POST", f"/private-dining-events/{event_id}/complete", {}, headers
        )

    def cancel_private_dining_event(self, event_id, headers):
        return self._request(
            "POST", f"/private-dining-events/{event_id}/cancel", {}, headers
        )

    # ─── Test clock (Manager-only, auth-exempt) ──────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
