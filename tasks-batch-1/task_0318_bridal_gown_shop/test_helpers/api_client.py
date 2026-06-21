"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Stylists ──────────────────────────────────────────────────────────
    def create_stylist(self, payload, headers):
        return self._request("POST", "/stylists", payload, headers)

    def list_stylists(self, headers, params=None):
        return self._request("GET", "/stylists", headers=headers, params=params)

    def get_stylist(self, stylist_id, headers):
        return self._request("GET", f"/stylists/{stylist_id}", headers=headers)

    def update_stylist(self, stylist_id, payload, headers):
        return self._request("PATCH", f"/stylists/{stylist_id}", payload, headers)

    # ─── Fitting rooms ─────────────────────────────────────────────────────
    def create_fitting_room(self, payload, headers):
        return self._request("POST", "/fitting-rooms", payload, headers)

    def list_fitting_rooms(self, headers, params=None):
        return self._request("GET", "/fitting-rooms", headers=headers, params=params)

    def get_fitting_room(self, room_id, headers):
        return self._request("GET", f"/fitting-rooms/{room_id}", headers=headers)

    # ─── Bridal parties ────────────────────────────────────────────────────
    def create_bridal_party(self, payload, headers):
        return self._request("POST", "/bridal-parties", payload, headers)

    def list_bridal_parties(self, headers, params=None):
        return self._request("GET", "/bridal-parties", headers=headers, params=params)

    def get_bridal_party(self, party_id, headers):
        return self._request("GET", f"/bridal-parties/{party_id}", headers=headers)

    def update_bridal_party(self, party_id, payload, headers):
        return self._request("PATCH", f"/bridal-parties/{party_id}", payload, headers)

    def lock_bridal_party(self, party_id, headers):
        return self._request("POST", f"/bridal-parties/{party_id}/lock", {}, headers)

    # ─── Appointments ──────────────────────────────────────────────────────
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def check_in_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/check-in", {}, headers)

    def revert_check_in_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/revert-check-in", {}, headers)

    def complete_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/complete", {}, headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/cancel", {}, headers)

    def mark_no_show_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/mark-no-show", {}, headers)

    # ─── Fitting-room bookings ─────────────────────────────────────────────
    def create_fitting_room_booking(self, payload, headers):
        return self._request("POST", "/fitting-room-bookings", payload, headers)

    def list_fitting_room_bookings(self, headers, params=None):
        return self._request("GET", "/fitting-room-bookings", headers=headers, params=params)

    def get_fitting_room_booking(self, booking_id, headers):
        return self._request("GET", f"/fitting-room-bookings/{booking_id}", headers=headers)

    def release_fitting_room_booking(self, booking_id, headers):
        return self._request("POST", f"/fitting-room-bookings/{booking_id}/release", {}, headers)

    # ─── Gown orders ───────────────────────────────────────────────────────
    def create_gown_order(self, payload, headers):
        return self._request("POST", "/gown-orders", payload, headers)

    def list_gown_orders(self, headers, params=None):
        return self._request("GET", "/gown-orders", headers=headers, params=params)

    def get_gown_order(self, order_id, headers):
        return self._request("GET", f"/gown-orders/{order_id}", headers=headers)

    def submit_gown_order(self, order_id, headers):
        return self._request("POST", f"/gown-orders/{order_id}/submit", {}, headers)

    def receive_gown_order(self, order_id, headers):
        return self._request("POST", f"/gown-orders/{order_id}/receive", {}, headers)

    def mark_ready_gown_order(self, order_id, headers):
        return self._request("POST", f"/gown-orders/{order_id}/mark-ready", {}, headers)

    def pickup_gown_order(self, order_id, payload, headers):
        return self._request("POST", f"/gown-orders/{order_id}/pickup", payload, headers)

    def cancel_gown_order(self, order_id, headers):
        return self._request("POST", f"/gown-orders/{order_id}/cancel", {}, headers)

    # ─── Accessory add-ons ─────────────────────────────────────────────────
    def create_accessory_addon(self, payload, headers):
        return self._request("POST", "/accessory-addons", payload, headers)

    def list_accessory_addons(self, headers, params=None):
        return self._request("GET", "/accessory-addons", headers=headers, params=params)

    def get_accessory_addon(self, accessory_id, headers):
        return self._request("GET", f"/accessory-addons/{accessory_id}", headers=headers)

    def remove_accessory_addon(self, accessory_id, headers):
        return self._request("POST", f"/accessory-addons/{accessory_id}/remove", {}, headers)

    # ─── Alteration jobs ───────────────────────────────────────────────────
    def create_alteration_job(self, payload, headers):
        return self._request("POST", "/alteration-jobs", payload, headers)

    def list_alteration_jobs(self, headers, params=None):
        return self._request("GET", "/alteration-jobs", headers=headers, params=params)

    def get_alteration_job(self, job_id, headers):
        return self._request("GET", f"/alteration-jobs/{job_id}", headers=headers)

    def start_fitting_alteration_job(self, job_id, headers):
        return self._request("POST", f"/alteration-jobs/{job_id}/start-fitting", {}, headers)

    def request_adjustment_alteration_job(self, job_id, headers):
        return self._request("POST", f"/alteration-jobs/{job_id}/request-adjustment", {}, headers)

    def log_labor_alteration_job(self, job_id, payload, headers):
        return self._request("POST", f"/alteration-jobs/{job_id}/log-labor", payload, headers)

    def complete_alteration_job(self, job_id, headers):
        return self._request("POST", f"/alteration-jobs/{job_id}/complete", {}, headers)

    def cancel_alteration_job(self, job_id, headers):
        return self._request("POST", f"/alteration-jobs/{job_id}/cancel", {}, headers)

    # ─── Payment plans / payments / refunds ────────────────────────────────
    def create_payment_plan(self, payload, headers):
        return self._request("POST", "/payment-plans", payload, headers)

    def list_payment_plans(self, headers, params=None):
        return self._request("GET", "/payment-plans", headers=headers, params=params)

    def get_payment_plan(self, plan_id, headers):
        return self._request("GET", f"/payment-plans/{plan_id}", headers=headers)

    def post_payment(self, plan_id, payload, headers):
        return self._request("POST", f"/payment-plans/{plan_id}/payments", payload, headers)

    def list_payments(self, plan_id, headers, params=None):
        return self._request("GET", f"/payment-plans/{plan_id}/payments", headers=headers, params=params)

    def refund_payment_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/payment-plans/{plan_id}/refund", payload, headers)


api_client = ApiClient()
