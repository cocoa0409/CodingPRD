"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Config (Admin) ---
    def create_membership_plan(self, payload, headers):
        return self._request("POST", "/membership-plans", payload, headers)

    def list_membership_plans(self, headers, params=None):
        return self._request("GET", "/membership-plans", headers=headers, params=params)

    def patch_membership_plan(self, plan_id, payload, headers):
        return self._request("PATCH", f"/membership-plans/{plan_id}", payload, headers)

    def create_party_package(self, payload, headers):
        return self._request("POST", "/party-packages", payload, headers)

    def list_party_packages(self, headers, params=None):
        return self._request("GET", "/party-packages", headers=headers, params=params)

    def patch_party_package(self, package_id, payload, headers):
        return self._request("PATCH", f"/party-packages/{package_id}", payload, headers)

    def create_party_room(self, payload, headers):
        return self._request("POST", "/party-rooms", payload, headers)

    def list_party_rooms(self, headers, params=None):
        return self._request("GET", "/party-rooms", headers=headers, params=params)

    def get_party_room(self, room_id, headers):
        return self._request("GET", f"/party-rooms/{room_id}", headers=headers)

    def patch_party_room(self, room_id, payload, headers):
        return self._request("PATCH", f"/party-rooms/{room_id}", payload, headers)

    def create_cafe_menu_item(self, payload, headers):
        return self._request("POST", "/cafe-menu-items", payload, headers)

    def list_cafe_menu_items(self, headers, params=None):
        return self._request("GET", "/cafe-menu-items", headers=headers, params=params)

    def patch_cafe_menu_item(self, item_id, payload, headers):
        return self._request("PATCH", f"/cafe-menu-items/{item_id}", payload, headers)

    def create_staff_member(self, payload, headers):
        return self._request("POST", "/staff-members", payload, headers)

    def get_staff_member(self, staff_id, headers):
        return self._request("GET", f"/staff-members/{staff_id}", headers=headers)

    def patch_staff_member(self, staff_id, payload, headers):
        return self._request("PATCH", f"/staff-members/{staff_id}", payload, headers)

    # --- Guardians / children / waivers / membership / loyalty ---
    def create_guardian(self, payload, headers):
        return self._request("POST", "/guardians", payload, headers)

    def list_guardians(self, headers, params=None):
        return self._request("GET", "/guardians", headers=headers, params=params)

    def get_guardian(self, guardian_id, headers):
        return self._request("GET", f"/guardians/{guardian_id}", headers=headers)

    def create_child(self, guardian_id, payload, headers):
        return self._request("POST", f"/guardians/{guardian_id}/children", payload, headers)

    def list_children(self, guardian_id, headers, params=None):
        return self._request("GET", f"/guardians/{guardian_id}/children", headers=headers, params=params)

    def get_child(self, child_id, headers):
        return self._request("GET", f"/children/{child_id}", headers=headers)

    def list_child_visits(self, child_id, headers, params=None):
        return self._request("GET", f"/children/{child_id}/visits", headers=headers, params=params)

    def create_waiver(self, guardian_id, payload, headers):
        return self._request("POST", f"/guardians/{guardian_id}/waivers", payload, headers)

    def list_waivers(self, guardian_id, headers, params=None):
        return self._request("GET", f"/guardians/{guardian_id}/waivers", headers=headers, params=params)

    def enroll_membership(self, guardian_id, payload, headers):
        return self._request("POST", f"/guardians/{guardian_id}/membership", payload, headers)

    def cancel_membership(self, guardian_id, headers):
        return self._request("POST", f"/guardians/{guardian_id}/membership/cancel", {}, headers)

    def list_guardian_visits(self, guardian_id, headers, params=None):
        return self._request("GET", f"/guardians/{guardian_id}/visits", headers=headers, params=params)

    def list_guardian_cafe_orders(self, guardian_id, headers, params=None):
        return self._request("GET", f"/guardians/{guardian_id}/cafe-orders", headers=headers, params=params)

    def list_guardian_party_bookings(self, guardian_id, headers, params=None):
        return self._request("GET", f"/guardians/{guardian_id}/party-bookings", headers=headers, params=params)

    def list_loyalty_ledger(self, guardian_id, headers, params=None):
        return self._request("GET", f"/guardians/{guardian_id}/loyalty-ledger", headers=headers, params=params)

    def create_loyalty_adjustment(self, guardian_id, payload, headers):
        return self._request("POST", f"/guardians/{guardian_id}/loyalty-adjustments", payload, headers)

    # --- Session slots / visits ---
    def create_session_slot(self, payload, headers):
        return self._request("POST", "/session-slots", payload, headers)

    def list_session_slots(self, headers, params=None):
        return self._request("GET", "/session-slots", headers=headers, params=params)

    def get_session_slot(self, slot_id, headers):
        return self._request("GET", f"/session-slots/{slot_id}", headers=headers)

    def patch_session_slot(self, slot_id, payload, headers):
        return self._request("PATCH", f"/session-slots/{slot_id}", payload, headers)

    def open_session_slot(self, slot_id, headers):
        return self._request("POST", f"/session-slots/{slot_id}/open", {}, headers)

    def close_session_slot(self, slot_id, payload, headers):
        return self._request("POST", f"/session-slots/{slot_id}/close", payload, headers)

    def list_slot_visits(self, slot_id, headers, params=None):
        return self._request("GET", f"/session-slots/{slot_id}/visits", headers=headers, params=params)

    def create_visit(self, payload, headers):
        return self._request("POST", "/visits", payload, headers)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/visits/{visit_id}", headers=headers)

    def pay_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/pay", {}, headers)

    def check_in_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/check-in", payload, headers)

    def check_out_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/check-out", {}, headers)

    def cancel_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/cancel", {}, headers)

    def list_visit_cafe_orders(self, visit_id, headers, params=None):
        return self._request("GET", f"/visits/{visit_id}/cafe-orders", headers=headers, params=params)

    def list_visit_incidents(self, visit_id, headers, params=None):
        return self._request("GET", f"/visits/{visit_id}/incidents", headers=headers, params=params)

    # --- Party bookings ---
    def create_party_booking(self, payload, headers):
        return self._request("POST", "/party-bookings", payload, headers)

    def list_party_bookings(self, headers, params=None):
        return self._request("GET", "/party-bookings", headers=headers, params=params)

    def get_party_booking(self, booking_id, headers):
        return self._request("GET", f"/party-bookings/{booking_id}", headers=headers)

    def confirm_party_booking(self, booking_id, headers):
        return self._request("POST", f"/party-bookings/{booking_id}/confirm", {}, headers)

    def request_reschedule(self, booking_id, payload, headers):
        return self._request("POST", f"/party-bookings/{booking_id}/request-reschedule", payload, headers)

    def approve_reschedule(self, booking_id, headers):
        return self._request("POST", f"/party-bookings/{booking_id}/approve-reschedule", {}, headers)

    def cancel_party_booking(self, booking_id, headers):
        return self._request("POST", f"/party-bookings/{booking_id}/cancel", {}, headers)

    def complete_party_booking(self, booking_id, headers):
        return self._request("POST", f"/party-bookings/{booking_id}/complete", {}, headers)

    def list_party_booking_cafe_orders(self, booking_id, headers, params=None):
        return self._request("GET", f"/party-bookings/{booking_id}/cafe-orders", headers=headers, params=params)

    def list_room_party_bookings(self, room_id, headers, params=None):
        return self._request("GET", f"/party-rooms/{room_id}/party-bookings", headers=headers, params=params)

    def list_room_sanitation_tasks(self, room_id, headers, params=None):
        return self._request("GET", f"/party-rooms/{room_id}/sanitation-tasks", headers=headers, params=params)

    # --- Cafe orders ---
    def create_cafe_order(self, payload, headers):
        return self._request("POST", "/cafe-orders", payload, headers)

    def get_cafe_order(self, order_id, headers):
        return self._request("GET", f"/cafe-orders/{order_id}", headers=headers)

    def start_preparing_cafe_order(self, order_id, headers):
        return self._request("POST", f"/cafe-orders/{order_id}/start-preparing", {}, headers)

    def serve_cafe_order(self, order_id, headers):
        return self._request("POST", f"/cafe-orders/{order_id}/serve", {}, headers)

    def cancel_cafe_order(self, order_id, headers):
        return self._request("POST", f"/cafe-orders/{order_id}/cancel", {}, headers)

    # --- Sanitation ---
    def create_sanitation_task(self, payload, headers):
        return self._request("POST", "/sanitation-tasks", payload, headers)

    def start_sanitation_task(self, task_id, headers):
        return self._request("POST", f"/sanitation-tasks/{task_id}/start", {}, headers)

    def complete_sanitation_task(self, task_id, payload, headers):
        return self._request("POST", f"/sanitation-tasks/{task_id}/complete", payload, headers)

    # --- Incidents ---
    def create_incident(self, payload, headers):
        return self._request("POST", "/incidents", payload, headers)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/incidents/{incident_id}", headers=headers)

    def triage_incident(self, incident_id, headers):
        return self._request("POST", f"/incidents/{incident_id}/triage", {}, headers)

    def resolve_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/incidents/{incident_id}/resolve", payload, headers)

    def reopen_incident(self, incident_id, headers):
        return self._request("POST", f"/incidents/{incident_id}/reopen", {}, headers)

    def close_incident(self, incident_id, headers):
        return self._request("POST", f"/incidents/{incident_id}/close", {}, headers)

    # --- Ops ---
    def run_ops(self, headers):
        return self._request("POST", "/ops-runs", {}, headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
