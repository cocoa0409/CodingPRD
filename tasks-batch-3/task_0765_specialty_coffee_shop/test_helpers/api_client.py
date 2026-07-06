"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- BeanLot ----------------
    def create_bean_lot(self, payload, headers):
        return self._request("POST", "/bean-lots", payload, headers)

    def get_bean_lot(self, lot_id, headers):
        return self._request("GET", f"/bean-lots/{lot_id}", headers=headers)

    def list_bean_lots(self, headers, params=None):
        return self._request("GET", "/bean-lots", headers=headers, params=params)

    def activate_bean_lot(self, lot_id, headers):
        return self._request("POST", f"/bean-lots/{lot_id}/activate", {}, headers)

    def log_waste(self, lot_id, payload, headers):
        return self._request("POST", f"/bean-lots/{lot_id}/log-waste", payload, headers)

    # ---------------- Modifier ----------------
    def create_modifier(self, payload, headers):
        return self._request("POST", "/modifiers", payload, headers)

    def list_modifiers(self, headers, params=None):
        return self._request("GET", "/modifiers", headers=headers, params=params)

    # ---------------- MenuItem ----------------
    def create_menu_item(self, payload, headers):
        return self._request("POST", "/menu-items", payload, headers)

    def get_menu_item(self, item_id, headers):
        return self._request("GET", f"/menu-items/{item_id}", headers=headers)

    # ---------------- Equipment ----------------
    def create_equipment(self, payload, headers):
        return self._request("POST", "/equipment", payload, headers)

    def get_equipment(self, equipment_id, headers):
        return self._request("GET", f"/equipment/{equipment_id}", headers=headers)

    def calibrate_equipment(self, equipment_id, headers):
        return self._request("POST", f"/equipment/{equipment_id}/calibrate", {}, headers)

    # ---------------- MaintenanceWindow ----------------
    def create_maintenance_window(self, payload, headers):
        return self._request("POST", "/maintenance-windows", payload, headers)

    def get_maintenance_window(self, window_id, headers):
        return self._request("GET", f"/maintenance-windows/{window_id}", headers=headers)

    def list_maintenance_windows(self, headers, params=None):
        return self._request("GET", "/maintenance-windows", headers=headers, params=params)

    def complete_maintenance_window(self, window_id, headers):
        return self._request("POST", f"/maintenance-windows/{window_id}/complete", {}, headers)

    def cancel_maintenance_window(self, window_id, headers):
        return self._request("POST", f"/maintenance-windows/{window_id}/cancel", {}, headers)

    # ---------------- Barista ----------------
    def create_barista(self, payload, headers):
        return self._request("POST", "/baristas", payload, headers)

    def get_barista(self, barista_id, headers):
        return self._request("GET", f"/baristas/{barista_id}", headers=headers)

    # ---------------- Member ----------------
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def adjust_member_points(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/point-adjustments", payload, headers)

    # ---------------- Order ----------------
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def pay_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/pay", {}, headers)

    def fulfill_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/fulfill", {}, headers)

    def void_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/void", {}, headers)

    # ---------------- Subscription ----------------
    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscriptions", payload, headers)

    def get_subscription(self, sub_id, headers):
        return self._request("GET", f"/subscriptions/{sub_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def cancel_subscription(self, sub_id, headers):
        return self._request("POST", f"/subscriptions/{sub_id}/cancel", {}, headers)

    # ---------------- CateringEvent ----------------
    def create_catering_event(self, payload, headers):
        return self._request("POST", "/catering-events", payload, headers)

    def get_catering_event(self, event_id, headers):
        return self._request("GET", f"/catering-events/{event_id}", headers=headers)

    def list_catering_events(self, headers, params=None):
        return self._request("GET", "/catering-events", headers=headers, params=params)

    def confirm_catering_event(self, event_id, headers):
        return self._request("POST", f"/catering-events/{event_id}/confirm", {}, headers)

    def cancel_catering_event(self, event_id, headers):
        return self._request("POST", f"/catering-events/{event_id}/cancel", {}, headers)

    # ---------------- DailyReconciliation ----------------
    def create_reconciliation(self, payload, headers):
        return self._request("POST", "/daily-reconciliations", payload, headers)

    def get_reconciliation(self, recon_id, headers):
        return self._request("GET", f"/daily-reconciliations/{recon_id}", headers=headers)

    def list_reconciliations(self, headers, params=None):
        return self._request("GET", "/daily-reconciliations", headers=headers, params=params)

    def submit_count(self, recon_id, payload, headers):
        return self._request("POST", f"/daily-reconciliations/{recon_id}/submit-count", payload, headers)

    def close_reconciliation(self, recon_id, headers):
        return self._request("POST", f"/daily-reconciliations/{recon_id}/close", {}, headers)


api_client = ApiClient()
