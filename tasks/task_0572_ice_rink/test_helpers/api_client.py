"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Rinks ---
    def create_rink(self, payload, headers):
        return self._request("POST", "/rinks", payload, headers)

    def get_rink(self, rink_id, headers):
        return self._request("GET", f"/rinks/{rink_id}", headers=headers)

    # --- Skaters ---
    def create_skater(self, payload, headers):
        return self._request("POST", "/skaters", payload, headers)

    def get_skater(self, skater_id, headers):
        return self._request("GET", f"/skaters/{skater_id}", headers=headers)

    def adjust_wallet(self, skater_id, payload, headers):
        return self._request("POST", f"/skaters/{skater_id}/wallet/adjustments",
                             payload, headers)

    # --- Ice slots ---
    def create_ice_slot(self, payload, headers):
        return self._request("POST", "/ice-slots", payload, headers)

    def get_ice_slot(self, slot_id, headers):
        return self._request("GET", f"/ice-slots/{slot_id}", headers=headers)

    def list_ice_slots(self, headers, params=None):
        return self._request("GET", "/ice-slots", headers=headers, params=params)

    def publish_ice_slot(self, slot_id, headers):
        return self._request("POST", f"/ice-slots/{slot_id}/publish", {}, headers)

    def unpublish_ice_slot(self, slot_id, headers):
        return self._request("POST", f"/ice-slots/{slot_id}/unpublish", {}, headers)

    def cancel_ice_slot(self, slot_id, headers):
        return self._request("POST", f"/ice-slots/{slot_id}/cancel", {}, headers)

    def complete_ice_slot(self, slot_id, headers):
        return self._request("POST", f"/ice-slots/{slot_id}/complete", {}, headers)

    # --- Public-skate admissions ---
    def create_admission(self, slot_id, payload, headers):
        return self._request("POST", f"/ice-slots/{slot_id}/admissions",
                             payload, headers)

    def get_admission(self, admission_id, headers):
        return self._request("GET", f"/admissions/{admission_id}", headers=headers)

    def list_admissions(self, headers, params=None):
        return self._request("GET", "/admissions", headers=headers, params=params)

    def refund_admission(self, admission_id, headers):
        return self._request("POST", f"/admissions/{admission_id}/refund", {}, headers)

    # --- Learn-to-skate classes ---
    def create_class(self, payload, headers):
        return self._request("POST", "/learn-to-skate-classes", payload, headers)

    def get_class(self, class_id, headers):
        return self._request("GET", f"/learn-to-skate-classes/{class_id}",
                             headers=headers)

    def list_classes(self, headers, params=None):
        return self._request("GET", "/learn-to-skate-classes",
                             headers=headers, params=params)

    def create_enrollment(self, class_id, payload, headers):
        return self._request("POST", f"/learn-to-skate-classes/{class_id}/enrollments",
                             payload, headers)

    # --- Enrollments ---
    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def withdraw_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/withdraw", {}, headers)

    def complete_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/complete", {}, headers)

    # --- Tuition subscriptions ---
    def create_tuition_subscription(self, enrollment_id, payload, headers):
        return self._request("POST",
                             f"/enrollments/{enrollment_id}/tuition-subscriptions",
                             payload, headers)

    def get_tuition_subscription(self, sub_id, headers):
        return self._request("GET", f"/tuition-subscriptions/{sub_id}", headers=headers)

    def list_tuition_subscriptions(self, headers, params=None):
        return self._request("GET", "/tuition-subscriptions",
                             headers=headers, params=params)

    def advance_cycle(self, sub_id, headers):
        return self._request("POST", f"/tuition-subscriptions/{sub_id}/advance-cycle",
                             {}, headers)

    def pay_subscription(self, sub_id, headers):
        return self._request("POST", f"/tuition-subscriptions/{sub_id}/pay", {}, headers)

    def cancel_subscription(self, sub_id, headers):
        return self._request("POST", f"/tuition-subscriptions/{sub_id}/cancel", {}, headers)

    # --- Leagues ---
    def create_league(self, payload, headers):
        return self._request("POST", "/leagues", payload, headers)

    def get_league(self, league_id, headers):
        return self._request("GET", f"/leagues/{league_id}", headers=headers)

    def start_league(self, league_id, headers):
        return self._request("POST", f"/leagues/{league_id}/start", {}, headers)

    def cancel_league(self, league_id, headers):
        return self._request("POST", f"/leagues/{league_id}/cancel", {}, headers)

    def create_registration(self, league_id, payload, headers):
        return self._request("POST", f"/leagues/{league_id}/registrations",
                             payload, headers)

    def get_registration(self, reg_id, headers):
        return self._request("GET", f"/league-registrations/{reg_id}", headers=headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/league-registrations",
                             headers=headers, params=params)

    # --- Locker assignments ---
    def create_locker_assignment(self, rink_id, payload, headers):
        return self._request("POST", f"/rinks/{rink_id}/locker-assignments",
                             payload, headers)

    def get_locker_assignment(self, locker_id, headers):
        return self._request("GET", f"/locker-assignments/{locker_id}", headers=headers)

    def list_locker_assignments(self, headers, params=None):
        return self._request("GET", "/locker-assignments",
                             headers=headers, params=params)

    def release_locker(self, locker_id, headers):
        return self._request("POST", f"/locker-assignments/{locker_id}/release",
                             {}, headers)

    # --- Slot bookings ---
    def create_slot_booking(self, slot_id, payload, headers):
        return self._request("POST", f"/ice-slots/{slot_id}/slot-bookings",
                             payload, headers)

    def get_slot_booking(self, booking_id, headers):
        return self._request("GET", f"/slot-bookings/{booking_id}", headers=headers)

    def list_slot_bookings(self, headers, params=None):
        return self._request("GET", "/slot-bookings", headers=headers, params=params)

    def complete_slot_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/slot-bookings/{booking_id}/complete",
                             payload, headers)

    def cancel_slot_booking(self, booking_id, headers):
        return self._request("POST", f"/slot-bookings/{booking_id}/cancel", {}, headers)

    # --- Sharpening orders ---
    def create_sharpening_order(self, payload, headers):
        return self._request("POST", "/sharpening-orders", payload, headers)

    def get_sharpening_order(self, order_id, headers):
        return self._request("GET", f"/sharpening-orders/{order_id}", headers=headers)

    def list_sharpening_orders(self, headers, params=None):
        return self._request("GET", "/sharpening-orders", headers=headers, params=params)

    def advance_sharpening_order(self, order_id, headers):
        return self._request("POST", f"/sharpening-orders/{order_id}/advance", {}, headers)


api_client = ApiClient()
