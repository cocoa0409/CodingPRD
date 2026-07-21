"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/v1/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # --- Retreats ---
    def create_retreat(self, payload, headers):
        return self._request("POST", "/v1/retreats", payload, headers)

    def get_retreat(self, retreat_id, headers):
        return self._request("GET", f"/v1/retreats/{retreat_id}", headers=headers)

    def list_retreats(self, headers, params=None):
        return self._request("GET", "/v1/retreats", headers=headers, params=params)

    def publish_retreat(self, retreat_id, headers):
        return self._request("POST", f"/v1/retreats/{retreat_id}/publish", {}, headers)

    def cancel_retreat(self, retreat_id, headers):
        return self._request("POST", f"/v1/retreats/{retreat_id}/cancel", {}, headers)

    def complete_retreat(self, retreat_id, headers):
        return self._request("POST", f"/v1/retreats/{retreat_id}/complete", {}, headers)

    def list_retreat_rooms(self, retreat_id, headers, params=None):
        return self._request("GET", f"/v1/retreats/{retreat_id}/rooms", headers=headers, params=params)

    def list_retreat_shuttles(self, retreat_id, headers, params=None):
        return self._request("GET", f"/v1/retreats/{retreat_id}/shuttles", headers=headers, params=params)

    # --- Rooms ---
    def create_room(self, payload, headers):
        return self._request("POST", "/v1/rooms", payload, headers)

    # --- Guests ---
    def create_guest(self, payload, headers):
        return self._request("POST", "/v1/guests", payload, headers)

    def get_guest(self, guest_id, headers):
        return self._request("GET", f"/v1/guests/{guest_id}", headers=headers)

    # --- Facilitators ---
    def create_facilitator(self, payload, headers):
        return self._request("POST", "/v1/facilitators", payload, headers)

    def get_facilitator(self, facilitator_id, headers):
        return self._request("GET", f"/v1/facilitators/{facilitator_id}", headers=headers)

    def withdraw_facilitator(self, facilitator_id, headers):
        return self._request("POST", f"/v1/facilitators/{facilitator_id}/withdraw", {}, headers)

    # --- Bookings ---
    def create_booking(self, payload, headers):
        return self._request("POST", "/v1/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/v1/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/v1/bookings", headers=headers, params=params)

    def pay_deposit(self, booking_id, amount_cents, headers):
        return self._request("POST", f"/v1/bookings/{booking_id}/pay-deposit", {"amount_cents": amount_cents}, headers)

    def pay_balance(self, booking_id, amount_cents, headers):
        return self._request("POST", f"/v1/bookings/{booking_id}/pay-balance", {"amount_cents": amount_cents}, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/v1/bookings/{booking_id}/cancel", {}, headers)

    def check_in_booking(self, booking_id, headers):
        return self._request("POST", f"/v1/bookings/{booking_id}/check-in", {}, headers)

    def list_booking_payments(self, booking_id, headers, params=None):
        return self._request("GET", f"/v1/bookings/{booking_id}/payments", headers=headers, params=params)

    def list_booking_waiver(self, booking_id, headers, params=None):
        return self._request("GET", f"/v1/bookings/{booking_id}/waiver", headers=headers, params=params)

    # --- Waivers ---
    def create_waiver(self, payload, headers):
        return self._request("POST", "/v1/waivers", payload, headers)

    def sign_waiver(self, waiver_id, signature_name, headers):
        return self._request("POST", f"/v1/waivers/{waiver_id}/sign", {"signature_name": signature_name}, headers)

    def review_waiver(self, waiver_id, decision, headers):
        return self._request("POST", f"/v1/waivers/{waiver_id}/review", {"decision": decision}, headers)

    # --- Activity slots ---
    def create_activity_slot(self, payload, headers):
        return self._request("POST", "/v1/activity-slots", payload, headers)

    def get_activity_slot(self, slot_id, headers):
        return self._request("GET", f"/v1/activity-slots/{slot_id}", headers=headers)

    def list_activity_slots(self, headers, params=None):
        return self._request("GET", "/v1/activity-slots", headers=headers, params=params)

    def cancel_activity_slot(self, slot_id, headers):
        return self._request("POST", f"/v1/activity-slots/{slot_id}/cancel", {}, headers)

    # --- Shuttles ---
    def create_shuttle(self, payload, headers):
        return self._request("POST", "/v1/shuttles", payload, headers)

    # --- Transport segments ---
    def create_transport_segment(self, payload, headers):
        return self._request("POST", "/v1/transport-segments", payload, headers)

    def get_transport_segment(self, segment_id, headers):
        return self._request("GET", f"/v1/transport-segments/{segment_id}", headers=headers)

    def list_transport_segments(self, headers, params=None):
        return self._request("GET", "/v1/transport-segments", headers=headers, params=params)

    # --- Add-ons ---
    def create_addon(self, payload, headers):
        return self._request("POST", "/v1/addons", payload, headers)

    def get_addon(self, addon_id, headers):
        return self._request("GET", f"/v1/addons/{addon_id}", headers=headers)

    # --- Booking add-ons ---
    def create_booking_addon(self, payload, headers):
        return self._request("POST", "/v1/booking-addons", payload, headers)

    def get_booking_addon(self, booking_addon_id, headers):
        return self._request("GET", f"/v1/booking-addons/{booking_addon_id}", headers=headers)

    def list_booking_addons(self, headers, params=None):
        return self._request("GET", "/v1/booking-addons", headers=headers, params=params)


api_client = ApiClient()
