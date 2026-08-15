"""API client: one method per endpoint declared in PRD section 4."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Community Kitchen Meal Program API."""

    # --- Logical clock ------------------------------------------------------
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/kitchen/_clock/set_current_utc", payload, headers)

    # --- Sites --------------------------------------------------------------
    def create_site(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/kitchen/sites", payload, headers)

    def list_sites(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/kitchen/sites", headers=headers, params=params)

    def get_site(self, site_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/kitchen/sites/{site_id}", headers=headers)

    def list_site_equipment_assets(
        self, site_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/kitchen/sites/{site_id}/equipment-assets",
            headers=headers, params=params,
        )

    def list_site_food_batches(
        self, site_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/kitchen/sites/{site_id}/food-batches",
            headers=headers, params=params,
        )

    def list_site_volunteer_shifts(
        self, site_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/kitchen/sites/{site_id}/volunteer-shifts",
            headers=headers, params=params,
        )

    # --- Menu days ----------------------------------------------------------
    def create_menu_day(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/kitchen/menu-days", payload, headers)

    def list_menu_days(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/kitchen/menu-days", headers=headers, params=params)

    def get_menu_day(self, menu_day_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/kitchen/menu-days/{menu_day_id}", headers=headers
        )

    def get_menu_day_summary(self, menu_day_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/kitchen/menu-days/{menu_day_id}/summary", headers=headers
        )

    def list_menu_day_items(
        self, menu_day_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/kitchen/menu-days/{menu_day_id}/menu-items",
            headers=headers, params=params,
        )

    def list_menu_day_services(
        self, menu_day_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/kitchen/menu-days/{menu_day_id}/meal-services",
            headers=headers, params=params,
        )

    def list_menu_day_waste_logs(
        self, menu_day_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/kitchen/menu-days/{menu_day_id}/waste-logs",
            headers=headers, params=params,
        )

    def list_menu_day_volunteer_shifts(
        self, menu_day_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/kitchen/menu-days/{menu_day_id}/volunteer-shifts",
            headers=headers, params=params,
        )

    def lock_forecast(self, menu_day_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/kitchen/menu-days/{menu_day_id}/lock-forecast", payload, headers
        )

    def start_production(self, menu_day_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/kitchen/menu-days/{menu_day_id}/start-production", {}, headers
        )

    def reconcile_menu_day(self, menu_day_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/kitchen/menu-days/{menu_day_id}/reconcile", {}, headers
        )

    def cancel_menu_day(self, menu_day_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/kitchen/menu-days/{menu_day_id}/cancel", {}, headers
        )

    # --- Menu items ---------------------------------------------------------
    def create_menu_item(self, menu_day_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/kitchen/menu-days/{menu_day_id}/menu-items", payload, headers
        )

    def get_menu_item(self, menu_item_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/kitchen/menu-items/{menu_item_id}", headers=headers
        )

    def list_item_allocations(
        self, menu_item_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/kitchen/menu-items/{menu_item_id}/batch-allocations",
            headers=headers, params=params,
        )

    def list_item_orders(
        self, menu_item_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/kitchen/menu-items/{menu_item_id}/meal-orders",
            headers=headers, params=params,
        )

    def create_allocation(self, menu_item_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/kitchen/menu-items/{menu_item_id}/allocations", payload, headers
        )

    def confirm_menu_item(self, menu_item_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/kitchen/menu-items/{menu_item_id}/confirm", {}, headers
        )

    def mark_item_unavailable(self, menu_item_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/kitchen/menu-items/{menu_item_id}/mark-unavailable", {}, headers
        )

    # --- Food batches -------------------------------------------------------
    def create_food_batch(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/kitchen/food-batches", payload, headers)

    def get_food_batch(self, batch_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/kitchen/food-batches/{batch_id}", headers=headers)

    def list_batch_allocations(
        self, batch_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/kitchen/food-batches/{batch_id}/batch-allocations",
            headers=headers, params=params,
        )

    def list_batch_waste_logs(
        self, batch_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/kitchen/food-batches/{batch_id}/waste-logs",
            headers=headers, params=params,
        )

    def begin_inspection(self, batch_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/kitchen/food-batches/{batch_id}/begin-inspection", {}, headers
        )

    def record_inspection(self, batch_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/kitchen/food-batches/{batch_id}/record-inspection", payload, headers
        )

    def reject_batch(self, batch_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/kitchen/food-batches/{batch_id}/reject", {}, headers
        )

    # --- Volunteers ---------------------------------------------------------
    def create_volunteer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/kitchen/volunteers", payload, headers)

    def list_volunteers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/kitchen/volunteers", headers=headers, params=params)

    def get_volunteer(self, volunteer_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/kitchen/volunteers/{volunteer_id}", headers=headers
        )

    def list_volunteer_shifts_of_volunteer(
        self, volunteer_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/kitchen/volunteers/{volunteer_id}/volunteer-shifts",
            headers=headers, params=params,
        )

    def suspend_volunteer(self, volunteer_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/kitchen/volunteers/{volunteer_id}/suspend", {}, headers
        )

    def reinstate_volunteer(self, volunteer_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/kitchen/volunteers/{volunteer_id}/reinstate", {}, headers
        )

    # --- Volunteer shifts ---------------------------------------------------
    def create_volunteer_shift(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/kitchen/volunteer-shifts", payload, headers)

    def get_volunteer_shift(self, shift_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/kitchen/volunteer-shifts/{shift_id}", headers=headers
        )

    def check_in_shift(self, shift_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/kitchen/volunteer-shifts/{shift_id}/check-in", {}, headers
        )

    def complete_shift(self, shift_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/kitchen/volunteer-shifts/{shift_id}/complete", payload, headers
        )

    def reassign_shift(self, shift_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/kitchen/volunteer-shifts/{shift_id}/reassign", payload, headers
        )

    def cancel_shift(self, shift_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/kitchen/volunteer-shifts/{shift_id}/cancel", payload, headers
        )

    def mark_no_show(self, shift_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/kitchen/volunteer-shifts/{shift_id}/mark-no-show", {}, headers
        )

    # --- Guests -------------------------------------------------------------
    def create_guest(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/kitchen/guests", payload, headers)

    def get_guest(self, guest_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/kitchen/guests/{guest_id}", headers=headers)

    def list_guest_orders(
        self, guest_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/kitchen/guests/{guest_id}/meal-orders",
            headers=headers, params=params,
        )

    def flag_guest(self, guest_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/kitchen/guests/{guest_id}/flag", {}, headers)

    def unflag_guest(self, guest_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/kitchen/guests/{guest_id}/unflag", {}, headers)

    def deactivate_guest(self, guest_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/kitchen/guests/{guest_id}/deactivate", {}, headers
        )

    # --- Meal services ------------------------------------------------------
    def create_meal_service(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/kitchen/meal-services", payload, headers)

    def get_meal_service(self, service_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/kitchen/meal-services/{service_id}", headers=headers
        )

    def list_service_orders(
        self, service_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/kitchen/meal-services/{service_id}/meal-orders",
            headers=headers, params=params,
        )

    def open_service(self, service_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/kitchen/meal-services/{service_id}/open", payload, headers
        )

    def pause_service(self, service_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/kitchen/meal-services/{service_id}/pause", {}, headers
        )

    def resume_service(self, service_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/kitchen/meal-services/{service_id}/resume", {}, headers
        )

    def close_service(self, service_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/kitchen/meal-services/{service_id}/close", {}, headers
        )

    def abort_service(self, service_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/kitchen/meal-services/{service_id}/abort", {}, headers
        )

    # --- Meal orders --------------------------------------------------------
    def create_meal_order(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/kitchen/meal-orders", payload, headers)

    def get_meal_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/kitchen/meal-orders/{order_id}", headers=headers)

    def start_prep(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/kitchen/meal-orders/{order_id}/start-prep", {}, headers
        )

    def mark_ready(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/kitchen/meal-orders/{order_id}/mark-ready", {}, headers
        )

    def rework_order(self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/kitchen/meal-orders/{order_id}/rework", payload, headers
        )

    def serve_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/kitchen/meal-orders/{order_id}/serve", {}, headers
        )

    def deliver_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/kitchen/meal-orders/{order_id}/deliver", {}, headers
        )

    def release_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/kitchen/meal-orders/{order_id}/release", {}, headers
        )

    # --- Equipment assets ---------------------------------------------------
    def create_equipment_asset(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/kitchen/equipment-assets", payload, headers)

    def get_equipment_asset(self, asset_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/kitchen/equipment-assets/{asset_id}", headers=headers
        )

    def schedule_maintenance(self, asset_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/kitchen/equipment-assets/{asset_id}/schedule-maintenance",
            payload, headers,
        )

    def complete_maintenance(self, asset_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/kitchen/equipment-assets/{asset_id}/complete-maintenance",
            {}, headers,
        )

    def report_fault(self, asset_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/kitchen/equipment-assets/{asset_id}/report-fault", {}, headers
        )

    def complete_repair(self, asset_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/kitchen/equipment-assets/{asset_id}/complete-repair",
            payload, headers,
        )

    def decommission_asset(self, asset_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/kitchen/equipment-assets/{asset_id}/decommission", {}, headers
        )

    # --- Waste logs ---------------------------------------------------------
    def create_waste_log(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/kitchen/waste-logs", payload, headers)

    def get_waste_log(self, waste_log_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/kitchen/waste-logs/{waste_log_id}", headers=headers
        )


api_client = ApiClient()
