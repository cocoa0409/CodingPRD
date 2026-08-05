"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Inmate ---
    def create_inmate(self, payload, headers):
        return self._request("POST", "/inmates", payload, headers)

    def get_inmate(self, inmate_id, headers):
        return self._request("GET", f"/inmates/{inmate_id}", headers=headers)

    def list_inmate_bookings(self, inmate_id, headers, params=None):
        return self._request("GET", f"/inmates/{inmate_id}/bookings", headers=headers, params=params)

    def list_inmate_visitors(self, inmate_id, headers, params=None):
        return self._request("GET", f"/inmates/{inmate_id}/visitors", headers=headers, params=params)

    def register_visitor(self, inmate_id, payload, headers):
        return self._request("POST", f"/inmates/{inmate_id}/visitors", payload, headers)

    # --- Booking ---
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def get_release_projection(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}/release-projection", headers=headers)

    def create_classification(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/classifications", payload, headers)

    def list_classifications(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/classifications", headers=headers, params=params)

    def release_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/release", payload, headers)

    # --- Housing ---
    def create_housing_unit(self, payload, headers):
        return self._request("POST", "/housing-units", payload, headers)

    def get_housing_unit(self, unit_id, headers):
        return self._request("GET", f"/housing-units/{unit_id}", headers=headers)

    def create_bed(self, unit_id, payload, headers):
        return self._request("POST", f"/housing-units/{unit_id}/beds", payload, headers)

    def list_beds(self, unit_id, headers, params=None):
        return self._request("GET", f"/housing-units/{unit_id}/beds", headers=headers, params=params)

    def create_housing_assignment(self, payload, headers):
        return self._request("POST", "/housing-assignments", payload, headers)

    def get_housing_assignment(self, assignment_id, headers):
        return self._request("GET", f"/housing-assignments/{assignment_id}", headers=headers)

    def list_housing_assignments(self, headers, params=None):
        return self._request("GET", "/housing-assignments", headers=headers, params=params)

    def end_housing_assignment(self, assignment_id, headers):
        return self._request("POST", f"/housing-assignments/{assignment_id}/end", None, headers)

    # --- Commissary ---
    def get_commissary_account(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}/commissary-account", headers=headers)

    def get_commissary_account_by_id(self, account_id, headers):
        return self._request("GET", f"/commissary-accounts/{account_id}", headers=headers)

    def deposit(self, account_id, payload, headers):
        return self._request("POST", f"/commissary-accounts/{account_id}/deposits", payload, headers)

    def create_order(self, account_id, payload, headers):
        return self._request("POST", f"/commissary-accounts/{account_id}/orders", payload, headers)

    def list_orders(self, account_id, headers, params=None):
        return self._request("GET", f"/commissary-accounts/{account_id}/orders", headers=headers, params=params)

    def fulfill_order(self, order_id, headers):
        return self._request("POST", f"/commissary-orders/{order_id}/fulfill", None, headers)

    def refund_order(self, order_id, headers):
        return self._request("POST", f"/commissary-orders/{order_id}/refund", None, headers)

    # --- Court ---
    def create_court_event(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/court-events", payload, headers)

    def list_court_events(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/court-events", headers=headers, params=params)

    def continue_court_event(self, event_id, payload, headers):
        return self._request("POST", f"/court-events/{event_id}/continue", payload, headers)

    def attend_court_event(self, event_id, headers):
        return self._request("POST", f"/court-events/{event_id}/attend", None, headers)

    # --- Visitation ---
    def approve_visitor(self, visitor_id, headers):
        return self._request("POST", f"/visitors/{visitor_id}/approve", None, headers)

    def create_visit(self, payload, headers):
        return self._request("POST", "/visits", payload, headers)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/visits/{visit_id}", headers=headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", "/visits", headers=headers, params=params)

    def approve_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/approve", None, headers)

    def cancel_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/cancel", None, headers)

    # --- Medical / Grievance ---
    def create_request(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/requests", payload, headers)

    def list_requests(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/requests", headers=headers, params=params)

    def review_request(self, request_id, headers):
        return self._request("POST", f"/requests/{request_id}/review", None, headers)

    def deny_request(self, request_id, headers):
        return self._request("POST", f"/requests/{request_id}/deny", None, headers)

    def appeal_request(self, request_id, headers):
        return self._request("POST", f"/requests/{request_id}/appeal", None, headers)

    def resolve_request(self, request_id, headers):
        return self._request("POST", f"/requests/{request_id}/resolve", None, headers)

    # --- Disciplinary ---
    def create_infraction(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/infractions", payload, headers)

    def list_infractions(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/infractions", headers=headers, params=params)

    def uphold_infraction(self, infraction_id, headers):
        return self._request("POST", f"/infractions/{infraction_id}/uphold", None, headers)

    # --- Property ---
    def create_property(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/property", payload, headers)

    def list_property(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/property", headers=headers, params=params)

    def release_property(self, item_id, headers):
        return self._request("POST", f"/property-items/{item_id}/release", None, headers)

    # --- Test-driving clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
