"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Test clock (§3.11) ───────────────────────────────────────────────
    def set_clock(self, now_utc, headers):
        return self._request("POST", "/_clock/set", {"now_utc": now_utc}, headers)

    # ─── Chef (§3.1) ──────────────────────────────────────────────────────
    def create_chef(self, payload, headers):
        return self._request("POST", "/chefs", payload, headers)

    def list_chefs(self, headers, params=None):
        return self._request("GET", "/chefs", headers=headers, params=params)

    def get_chef(self, chef_id, headers):
        return self._request("GET", f"/chefs/{chef_id}", headers=headers)

    def activate_chef(self, chef_id, headers):
        return self._request("POST", f"/chefs/{chef_id}/activate", headers=headers)

    def suspend_chef(self, chef_id, headers):
        return self._request("POST", f"/chefs/{chef_id}/suspend", headers=headers)

    # ─── MenuPackage (§3.2) ───────────────────────────────────────────────
    def create_menu(self, payload, headers):
        return self._request("POST", "/menus", payload, headers)

    def list_menus(self, headers, params=None):
        return self._request("GET", "/menus", headers=headers, params=params)

    def get_menu(self, menu_id, headers):
        return self._request("GET", f"/menus/{menu_id}", headers=headers)

    def publish_menu(self, menu_id, headers):
        return self._request("POST", f"/menus/{menu_id}/publish", headers=headers)

    # ─── TravelZone (§3.2) ────────────────────────────────────────────────
    def create_travel_zone(self, payload, headers):
        return self._request("POST", "/travel-zones", payload, headers)

    def list_travel_zones(self, headers, params=None):
        return self._request("GET", "/travel-zones", headers=headers, params=params)

    def get_travel_zone(self, zone_id, headers):
        return self._request("GET", f"/travel-zones/{zone_id}", headers=headers)

    # ─── AvailabilityBlock (§3.2) ─────────────────────────────────────────
    def create_availability_block(self, payload, headers):
        return self._request("POST", "/availability-blocks", payload, headers)

    def list_availability_blocks(self, headers, params=None):
        return self._request("GET", "/availability-blocks", headers=headers, params=params)

    def get_availability_block(self, block_id, headers):
        return self._request("GET", f"/availability-blocks/{block_id}", headers=headers)

    # ─── Client (§3.3) ────────────────────────────────────────────────────
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    # ─── Booking (§3.3, §3.6, §3.8) ───────────────────────────────────────
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def confirm_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/confirm", payload, headers)

    def decline_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/decline", headers=headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", headers=headers)

    def start_prep_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/start-prep", headers=headers)

    def complete_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/complete", headers=headers)

    # ─── Payment (§3.6) ───────────────────────────────────────────────────
    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    # ─── GroceryRun (§3.5) ────────────────────────────────────────────────
    def create_grocery_run(self, payload, headers):
        return self._request("POST", "/grocery-runs", payload, headers)

    def list_grocery_runs(self, headers, params=None):
        return self._request("GET", "/grocery-runs", headers=headers, params=params)

    def get_grocery_run(self, grocery_run_id, headers):
        return self._request("GET", f"/grocery-runs/{grocery_run_id}", headers=headers)

    def finalize_grocery_run(self, grocery_run_id, headers):
        return self._request("POST", f"/grocery-runs/{grocery_run_id}/finalize", headers=headers)

    # ─── RescheduleRequest (§3.9) ─────────────────────────────────────────
    def create_reschedule_request(self, payload, headers):
        return self._request("POST", "/reschedule-requests", payload, headers)

    def list_reschedule_requests(self, headers, params=None):
        return self._request("GET", "/reschedule-requests", headers=headers, params=params)

    def get_reschedule_request(self, request_id, headers):
        return self._request("GET", f"/reschedule-requests/{request_id}", headers=headers)

    def accept_reschedule_request(self, request_id, headers):
        return self._request("POST", f"/reschedule-requests/{request_id}/accept", headers=headers)

    def reject_reschedule_request(self, request_id, headers):
        return self._request("POST", f"/reschedule-requests/{request_id}/reject", headers=headers)

    def withdraw_reschedule_request(self, request_id, headers):
        return self._request("POST", f"/reschedule-requests/{request_id}/withdraw", headers=headers)

    # ─── RecurringPlan (§3.10) ────────────────────────────────────────────
    def create_recurring_plan(self, payload, headers):
        return self._request("POST", "/recurring-plans", payload, headers)

    def list_recurring_plans(self, headers, params=None):
        return self._request("GET", "/recurring-plans", headers=headers, params=params)

    def get_recurring_plan(self, plan_id, headers):
        return self._request("GET", f"/recurring-plans/{plan_id}", headers=headers)

    def generate_occurrence(self, plan_id, payload, headers):
        return self._request("POST", f"/recurring-plans/{plan_id}/generate-occurrence", payload, headers)

    def pause_recurring_plan(self, plan_id, headers):
        return self._request("POST", f"/recurring-plans/{plan_id}/pause", headers=headers)

    def resume_recurring_plan(self, plan_id, headers):
        return self._request("POST", f"/recurring-plans/{plan_id}/resume", headers=headers)

    def cancel_recurring_plan(self, plan_id, headers):
        return self._request("POST", f"/recurring-plans/{plan_id}/cancel", headers=headers)


api_client = ApiClient()
