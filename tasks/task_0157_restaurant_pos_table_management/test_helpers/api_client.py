"""API client: one method per endpoint defined in the Restaurant POS PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- bootstrap / config ----
    def create_restaurant(self, payload, headers):
        return self._request("POST", "/restaurants", payload, headers)

    def get_restaurant(self, restaurant_id, headers):
        return self._request("GET", f"/restaurants/{restaurant_id}", headers=headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- menu / 86 ----
    def create_menu_item(self, payload, headers):
        return self._request("POST", "/menu-items", payload, headers)

    def get_menu_item(self, menu_item_id, headers):
        return self._request("GET", f"/menu-items/{menu_item_id}", headers=headers)

    def list_menu_items(self, headers, params=None):
        return self._request("GET", "/menu-items", headers=headers, params=params)

    def create_happy_hour_window(self, payload, headers):
        return self._request("POST", "/happy-hour-windows", payload, headers)

    def get_happy_hour_window(self, window_id, headers):
        return self._request("GET", f"/happy-hour-windows/{window_id}", headers=headers)

    def list_happy_hour_windows(self, headers, params=None):
        return self._request("GET", "/happy-hour-windows", headers=headers, params=params)

    # ---- tables / waitlist / seatings ----
    def create_table(self, payload, headers):
        return self._request("POST", "/tables", payload, headers)

    def get_table(self, table_id, headers):
        return self._request("GET", f"/tables/{table_id}", headers=headers)

    def list_tables(self, headers, params=None):
        return self._request("GET", "/tables", headers=headers, params=params)

    def buss_table(self, table_id, payload, headers):
        return self._request("POST", f"/tables/{table_id}/buss", payload, headers)

    def create_waitlist_entry(self, payload, headers):
        return self._request("POST", "/waitlist", payload, headers)

    def get_waitlist_entry(self, waitlist_id, headers):
        return self._request("GET", f"/waitlist/{waitlist_id}", headers=headers)

    def list_waitlist(self, headers, params=None):
        return self._request("GET", "/waitlist", headers=headers, params=params)

    def cancel_waitlist_entry(self, waitlist_id, headers):
        return self._request("POST", f"/waitlist/{waitlist_id}/cancel", headers=headers)

    def create_seating(self, payload, headers):
        return self._request("POST", "/seatings", payload, headers)

    def get_seating(self, seating_id, headers):
        return self._request("GET", f"/seatings/{seating_id}", headers=headers)

    def list_seatings(self, headers, params=None):
        return self._request("GET", "/seatings", headers=headers, params=params)

    def clear_seating(self, seating_id, headers):
        return self._request("POST", f"/seatings/{seating_id}/clear", headers=headers)

    # ---- staff / shifts ----
    def create_staff_member(self, payload, headers):
        return self._request("POST", "/staff-members", payload, headers)

    def get_staff_member(self, staff_id, headers):
        return self._request("GET", f"/staff-members/{staff_id}", headers=headers)

    def list_staff_members(self, headers, params=None):
        return self._request("GET", "/staff-members", headers=headers, params=params)

    def create_staff_shift(self, payload, headers):
        return self._request("POST", "/staff-shifts", payload, headers)

    def get_staff_shift(self, shift_id, headers):
        return self._request("GET", f"/staff-shifts/{shift_id}", headers=headers)

    def list_staff_shifts(self, headers, params=None):
        return self._request("GET", "/staff-shifts", headers=headers, params=params)

    # ---- checks / courses / items / modifiers ----
    def create_check(self, payload, headers):
        return self._request("POST", "/checks", payload, headers)

    def get_check(self, check_id, headers):
        return self._request("GET", f"/checks/{check_id}", headers=headers)

    def list_checks(self, headers, params=None):
        return self._request("GET", "/checks", headers=headers, params=params)

    def present_check(self, check_id, headers):
        return self._request("POST", f"/checks/{check_id}/present", headers=headers)

    def reopen_check(self, check_id, headers):
        return self._request("POST", f"/checks/{check_id}/reopen", headers=headers)

    def close_check(self, check_id, headers):
        return self._request("POST", f"/checks/{check_id}/close", headers=headers)

    def void_check(self, check_id, headers):
        return self._request("POST", f"/checks/{check_id}/void", headers=headers)

    def split_check(self, check_id, payload, headers):
        return self._request("POST", f"/checks/{check_id}/split", payload, headers)

    def create_course(self, payload, headers):
        return self._request("POST", "/courses", payload, headers)

    def get_course(self, course_id, headers):
        return self._request("GET", f"/courses/{course_id}", headers=headers)

    def list_courses(self, headers, params=None):
        return self._request("GET", "/courses", headers=headers, params=params)

    def fire_course(self, course_id, headers):
        return self._request("POST", f"/courses/{course_id}/fire", headers=headers)

    def create_order_item(self, payload, headers):
        return self._request("POST", "/order-items", payload, headers)

    def get_order_item(self, order_item_id, headers):
        return self._request("GET", f"/order-items/{order_item_id}", headers=headers)

    def list_order_items(self, headers, params=None):
        return self._request("GET", "/order-items", headers=headers, params=params)

    def serve_order_item(self, order_item_id, headers):
        return self._request("POST", f"/order-items/{order_item_id}/serve", headers=headers)

    def void_order_item(self, order_item_id, headers):
        return self._request("POST", f"/order-items/{order_item_id}/void", headers=headers)

    def comp_order_item(self, order_item_id, headers):
        return self._request("POST", f"/order-items/{order_item_id}/comp", headers=headers)

    def create_item_modifier(self, payload, headers):
        return self._request("POST", "/item-modifiers", payload, headers)

    def get_item_modifier(self, modifier_id, headers):
        return self._request("GET", f"/item-modifiers/{modifier_id}", headers=headers)

    def list_item_modifiers(self, headers, params=None):
        return self._request("GET", "/item-modifiers", headers=headers, params=params)

    # ---- payments ----
    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def void_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/void", headers=headers)

    # ---- tip pools / allocations ----
    def create_tip_pool(self, payload, headers):
        return self._request("POST", "/tip-pools", payload, headers)

    def get_tip_pool(self, pool_id, headers):
        return self._request("GET", f"/tip-pools/{pool_id}", headers=headers)

    def list_tip_pools(self, headers, params=None):
        return self._request("GET", "/tip-pools", headers=headers, params=params)

    def distribute_tip_pool(self, pool_id, headers):
        return self._request("POST", f"/tip-pools/{pool_id}/distribute", headers=headers)

    def get_tip_allocation(self, allocation_id, headers):
        return self._request("GET", f"/tip-allocations/{allocation_id}", headers=headers)

    def list_tip_allocations(self, headers, params=None):
        return self._request("GET", "/tip-allocations", headers=headers, params=params)


api_client = ApiClient()
