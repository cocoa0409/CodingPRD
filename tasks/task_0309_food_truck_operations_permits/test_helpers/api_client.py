"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() is inherited and
handles the response envelope, base URL, and header injection.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Commissary ────────────────────────────────────────────────────
    def create_commissary(self, payload, headers):
        return self._request("POST", "/commissaries", payload, headers)

    def list_commissaries(self, headers, params=None):
        return self._request("GET", "/commissaries", headers=headers, params=params)

    def get_commissary(self, commissary_id, headers):
        return self._request("GET", f"/commissaries/{commissary_id}", headers=headers)

    def suspend_commissary(self, commissary_id, headers):
        return self._request("POST", f"/commissaries/{commissary_id}/suspend", headers=headers)

    def reinstate_commissary(self, commissary_id, headers):
        return self._request("POST", f"/commissaries/{commissary_id}/reinstate", headers=headers)

    # ─── OperatorTruck ─────────────────────────────────────────────────
    def create_truck(self, payload, headers):
        return self._request("POST", "/trucks", payload, headers)

    def list_trucks(self, headers, params=None):
        return self._request("GET", "/trucks", headers=headers, params=params)

    def get_truck(self, truck_id, headers):
        return self._request("GET", f"/trucks/{truck_id}", headers=headers)

    # ─── HealthPermit ──────────────────────────────────────────────────
    def issue_health_permit(self, payload, headers):
        return self._request("POST", "/health-permits", payload, headers)

    def list_health_permits(self, headers, params=None):
        return self._request("GET", "/health-permits", headers=headers, params=params)

    def get_health_permit(self, permit_id, headers):
        return self._request("GET", f"/health-permits/{permit_id}", headers=headers)

    def revoke_health_permit(self, permit_id, headers):
        return self._request("POST", f"/health-permits/{permit_id}/revoke", headers=headers)

    # ─── Spot ──────────────────────────────────────────────────────────
    def create_spot(self, payload, headers):
        return self._request("POST", "/spots", payload, headers)

    def list_spots(self, headers, params=None):
        return self._request("GET", "/spots", headers=headers, params=params)

    def get_spot(self, spot_id, headers):
        return self._request("GET", f"/spots/{spot_id}", headers=headers)

    # ─── Event ─────────────────────────────────────────────────────────
    def create_event(self, payload, headers):
        return self._request("POST", "/events", payload, headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/events", headers=headers, params=params)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}", headers=headers)

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/cancel", headers=headers)

    def get_sales_report(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}/sales-report", headers=headers)

    # ─── Booking ───────────────────────────────────────────────────────
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def arrive_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/arrive", headers=headers)

    def depart_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/depart", headers=headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", headers=headers)

    # ─── MenuItem ──────────────────────────────────────────────────────
    def create_menu_item(self, payload, headers):
        return self._request("POST", "/menu-items", payload, headers)

    def list_menu_items(self, headers, params=None):
        return self._request("GET", "/menu-items", headers=headers, params=params)

    def get_menu_item(self, menu_item_id, headers):
        return self._request("GET", f"/menu-items/{menu_item_id}", headers=headers)

    def unlist_menu_item(self, menu_item_id, headers):
        return self._request("POST", f"/menu-items/{menu_item_id}/unlist", headers=headers)

    # ─── PrepBatch ─────────────────────────────────────────────────────
    def create_prep_batch(self, payload, headers):
        return self._request("POST", "/prep-batches", payload, headers)

    def list_prep_batches(self, headers, params=None):
        return self._request("GET", "/prep-batches", headers=headers, params=params)

    def get_prep_batch(self, batch_id, headers):
        return self._request("GET", f"/prep-batches/{batch_id}", headers=headers)

    def discard_prep_batch(self, batch_id, headers):
        return self._request("POST", f"/prep-batches/{batch_id}/discard", headers=headers)

    # ─── StaffShift ────────────────────────────────────────────────────
    def create_staff_shift(self, payload, headers):
        return self._request("POST", "/staff-shifts", payload, headers)

    def list_staff_shifts(self, headers, params=None):
        return self._request("GET", "/staff-shifts", headers=headers, params=params)

    def get_staff_shift(self, shift_id, headers):
        return self._request("GET", f"/staff-shifts/{shift_id}", headers=headers)

    def cancel_staff_shift(self, shift_id, headers):
        return self._request("POST", f"/staff-shifts/{shift_id}/cancel", headers=headers)

    # ─── UtilityLog ────────────────────────────────────────────────────
    def create_utility_log(self, payload, headers):
        return self._request("POST", "/utility-logs", payload, headers)

    def list_utility_logs(self, headers, params=None):
        return self._request("GET", "/utility-logs", headers=headers, params=params)

    def get_utility_log(self, log_id, headers):
        return self._request("GET", f"/utility-logs/{log_id}", headers=headers)

    # ─── Order + OrderLine (POS / cashless) ────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def create_order_line(self, payload, headers):
        return self._request("POST", "/order-lines", payload, headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/order-lines/{line_id}", headers=headers)

    def authorize_payment(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/authorize-payment", headers=headers)

    def capture_payment(self, order_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/capture-payment", payload or {}, headers)

    def settle_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/settle", payload or {}, headers)

    def void_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/void", headers=headers)

    # ─── Test-driving clock ────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
