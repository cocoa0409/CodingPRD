"""API client: one method per endpoint defined in the PRD (Ghost Kitchen Platform)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Stall ──────────────────────────────────────────────────────────────
    def create_stall(self, payload, headers):
        return self._request("POST", "/stalls", payload, headers)

    def get_stall(self, stall_id, headers):
        return self._request("GET", f"/stalls/{stall_id}", headers=headers)

    def list_stalls(self, headers, params=None):
        return self._request("GET", "/stalls", headers=headers, params=params)

    def open_stall(self, stall_id, headers):
        return self._request("POST", f"/stalls/{stall_id}/open", headers=headers)

    def close_stall(self, stall_id, headers):
        return self._request("POST", f"/stalls/{stall_id}/close", headers=headers)

    def list_stall_equipment(self, stall_id, headers, params=None):
        return self._request("GET", f"/stalls/{stall_id}/equipment", headers=headers, params=params)

    def list_stall_ingredient_lots(self, stall_id, headers, params=None):
        return self._request("GET", f"/stalls/{stall_id}/ingredient-lots", headers=headers, params=params)

    # ── VirtualBrand ───────────────────────────────────────────────────────
    def create_brand(self, payload, headers):
        return self._request("POST", "/brands", payload, headers)

    def get_brand(self, brand_id, headers):
        return self._request("GET", f"/brands/{brand_id}", headers=headers)

    def list_brands(self, headers, params=None):
        return self._request("GET", "/brands", headers=headers, params=params)

    def list_brand_availability(self, brand_id, headers):
        return self._request("POST", f"/brands/{brand_id}/list", headers=headers)

    def pause_brand(self, brand_id, headers):
        return self._request("POST", f"/brands/{brand_id}/pause", headers=headers)

    def deactivate_brand(self, brand_id, headers):
        return self._request("POST", f"/brands/{brand_id}/deactivate", headers=headers)

    def list_brand_menu_items(self, brand_id, headers, params=None):
        return self._request("GET", f"/brands/{brand_id}/menu-items", headers=headers, params=params)

    def get_brand_performance(self, brand_id, headers):
        return self._request("GET", f"/brands/{brand_id}/performance", headers=headers)

    # ── KitchenLease ───────────────────────────────────────────────────────
    def create_lease(self, payload, headers):
        return self._request("POST", "/leases", payload, headers)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/leases/{lease_id}", headers=headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", "/leases", headers=headers, params=params)

    def activate_lease(self, lease_id, headers):
        return self._request("POST", f"/leases/{lease_id}/activate", headers=headers)

    def suspend_lease(self, lease_id, headers):
        return self._request("POST", f"/leases/{lease_id}/suspend", headers=headers)

    def reinstate_lease(self, lease_id, headers):
        return self._request("POST", f"/leases/{lease_id}/reinstate", headers=headers)

    def terminate_lease(self, lease_id, headers):
        return self._request("POST", f"/leases/{lease_id}/terminate", headers=headers)

    # ── Equipment ──────────────────────────────────────────────────────────
    def create_equipment(self, payload, headers):
        return self._request("POST", "/equipment", payload, headers)

    def get_equipment(self, equipment_id, headers):
        return self._request("GET", f"/equipment/{equipment_id}", headers=headers)

    def maintenance_equipment(self, equipment_id, headers):
        return self._request("POST", f"/equipment/{equipment_id}/maintenance", headers=headers)

    def restore_equipment(self, equipment_id, headers):
        return self._request("POST", f"/equipment/{equipment_id}/restore", headers=headers)

    def retire_equipment(self, equipment_id, headers):
        return self._request("POST", f"/equipment/{equipment_id}/retire", headers=headers)

    def list_equipment_bookings(self, equipment_id, headers, params=None):
        return self._request("GET", f"/equipment/{equipment_id}/bookings", headers=headers, params=params)

    # ── EquipmentBooking (maintenance holds) ───────────────────────────────
    def create_booking(self, payload, headers):
        return self._request("POST", "/equipment-bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/equipment-bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/equipment-bookings", headers=headers, params=params)

    def release_booking(self, booking_id, headers):
        return self._request("POST", f"/equipment-bookings/{booking_id}/release", headers=headers)

    # ── MenuItem + RecipeComponent ─────────────────────────────────────────
    def create_menu_item(self, payload, headers):
        return self._request("POST", "/menu-items", payload, headers)

    def get_menu_item(self, menu_item_id, headers):
        return self._request("GET", f"/menu-items/{menu_item_id}", headers=headers)

    def create_recipe_component(self, menu_item_id, payload, headers):
        return self._request("POST", f"/menu-items/{menu_item_id}/recipe-components", payload, headers)

    def list_recipe_components(self, menu_item_id, headers, params=None):
        return self._request("GET", f"/menu-items/{menu_item_id}/recipe-components", headers=headers, params=params)

    # ── IngredientLot ──────────────────────────────────────────────────────
    def create_ingredient_lot(self, payload, headers):
        return self._request("POST", "/ingredient-lots", payload, headers)

    def get_ingredient_lot(self, lot_id, headers):
        return self._request("GET", f"/ingredient-lots/{lot_id}", headers=headers)

    # ── AggregatorOrder ────────────────────────────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def route_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/route", headers=headers)

    def reject_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/reject", headers=headers)

    def start_prep_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/start-prep", headers=headers)

    def fulfill_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/fulfill", headers=headers)

    def cancel_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", payload, headers)

    # ── Test-driving logical clock ─────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
