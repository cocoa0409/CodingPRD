"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock ---
    def set_clock(self, to_iso8601: str, headers: dict):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # --- Customer ---
    def register_customer(self, payload: dict, headers: dict):
        return self._request("POST", "/customers/register", payload, headers)

    def get_customer(self, customer_id: str, headers: dict):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def get_customer_loyalty_ledger(self, customer_id: str, headers: dict, params: dict = None):
        return self._request("GET", f"/customers/{customer_id}/loyalty-ledger", headers=headers, params=params)

    def get_order_loyalty_ledger(self, order_id: str, headers: dict, params: dict = None):
        return self._request("GET", f"/orders/{order_id}/loyalty-ledger", headers=headers, params=params)

    # --- Plant / StockUnit / CareLog ---
    def create_plant(self, payload: dict, headers: dict):
        return self._request("POST", "/plants", payload, headers)

    def get_plant(self, plant_id: str, headers: dict):
        return self._request("GET", f"/plants/{plant_id}", headers=headers)

    def intake_stock_unit(self, plant_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/plants/{plant_id}/stock-units", payload, headers)

    def list_stock_units_for_plant(self, plant_id: str, headers: dict, params: dict = None):
        return self._request("GET", f"/plants/{plant_id}/stock-units", headers=headers, params=params)

    def get_stock_unit(self, stock_unit_id: str, headers: dict):
        return self._request("GET", f"/stock-units/{stock_unit_id}", headers=headers)

    def adjust_stock_unit(self, stock_unit_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/stock-units/{stock_unit_id}/adjust", payload, headers)

    def append_care_log(self, stock_unit_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/stock-units/{stock_unit_id}/care-log", payload, headers)

    def list_care_log(self, stock_unit_id: str, headers: dict, params: dict = None):
        return self._request("GET", f"/stock-units/{stock_unit_id}/care-log", headers=headers, params=params)

    # --- DeliveryDriver ---
    def create_delivery_driver(self, payload: dict, headers: dict):
        return self._request("POST", "/delivery-drivers", payload, headers)

    def get_delivery_driver(self, driver_id: str, headers: dict):
        return self._request("GET", f"/delivery-drivers/{driver_id}", headers=headers)

    # --- Order / OrderLine ---
    def create_order(self, payload: dict, headers: dict):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id: str, headers: dict):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers: dict, params: dict = None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def list_order_lines(self, headers: dict, params: dict = None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def get_order_line(self, orderline_id: str, headers: dict):
        return self._request("GET", f"/order-lines/{orderline_id}", headers=headers)

    def pay_order(self, order_id: str, headers: dict):
        return self._request("POST", f"/orders/{order_id}/pay", {}, headers)

    def dispatch_order(self, order_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/orders/{order_id}/dispatch", payload, headers)

    def cancel_order(self, order_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/orders/{order_id}/cancel", payload, headers)

    # --- Delivery ---
    def deliver_delivery(self, delivery_id: str, headers: dict):
        return self._request("POST", f"/deliveries/{delivery_id}/deliver", {}, headers)

    def list_deliveries(self, headers: dict, params: dict = None):
        return self._request("GET", "/deliveries", headers=headers, params=params)

    def get_delivery(self, delivery_id: str, headers: dict):
        return self._request("GET", f"/deliveries/{delivery_id}", headers=headers)

    # --- Subscription ---
    def create_subscription(self, payload: dict, headers: dict):
        return self._request("POST", "/subscriptions", payload, headers)

    def list_subscriptions(self, headers: dict, params: dict = None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def get_subscription(self, subscription_id: str, headers: dict):
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def pause_subscription(self, subscription_id: str, headers: dict):
        return self._request("POST", f"/subscriptions/{subscription_id}/pause", {}, headers)

    def resume_subscription(self, subscription_id: str, headers: dict):
        return self._request("POST", f"/subscriptions/{subscription_id}/resume", {}, headers)

    def cancel_subscription(self, subscription_id: str, headers: dict):
        return self._request("POST", f"/subscriptions/{subscription_id}/cancel", {}, headers)

    def scheduler_fulfill_subscriptions(self, headers: dict):
        return self._request("POST", "/_scheduler/fulfill-subscriptions", {}, headers)

    def list_care_reminders(self, headers: dict, params: dict = None):
        return self._request("GET", "/care-reminders", headers=headers, params=params)

    def get_care_reminder(self, reminder_id: str, headers: dict):
        return self._request("GET", f"/care-reminders/{reminder_id}", headers=headers)

    # --- Workshop ---
    def create_workshop(self, payload: dict, headers: dict):
        return self._request("POST", "/workshops", payload, headers)

    def get_workshop(self, workshop_id: str, headers: dict):
        return self._request("GET", f"/workshops/{workshop_id}", headers=headers)

    def register_workshop(self, workshop_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/workshops/{workshop_id}/register", payload, headers)

    def complete_workshop(self, workshop_id: str, headers: dict):
        return self._request("POST", f"/workshops/{workshop_id}/complete", {}, headers)

    def list_workshop_registrations(self, headers: dict, params: dict = None):
        return self._request("GET", "/workshop-registrations", headers=headers, params=params)

    def get_workshop_registration(self, registration_id: str, headers: dict):
        return self._request("GET", f"/workshop-registrations/{registration_id}", headers=headers)

    # --- Warranty ---
    def submit_warranty_claim(self, payload: dict, headers: dict):
        return self._request("POST", "/warranty-claims", payload, headers)

    def approve_warranty_claim(self, warranty_id: str, headers: dict):
        return self._request("POST", f"/warranty-claims/{warranty_id}/approve", {}, headers)

    def deny_warranty_claim(self, warranty_id: str, headers: dict):
        return self._request("POST", f"/warranty-claims/{warranty_id}/deny", {}, headers)

    def list_warranty_claims(self, headers: dict, params: dict = None):
        return self._request("GET", "/warranty-claims", headers=headers, params=params)

    def get_warranty_claim(self, warranty_id: str, headers: dict):
        return self._request("GET", f"/warranty-claims/{warranty_id}", headers=headers)

    # --- SpecialOrder ---
    def create_special_order(self, payload: dict, headers: dict):
        return self._request("POST", "/special-orders", payload, headers)

    def quote_special_order(self, special_order_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/special-orders/{special_order_id}/quote", payload, headers)

    def requote_special_order(self, special_order_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/special-orders/{special_order_id}/re-quote", payload, headers)

    def customer_approve_special_order(self, special_order_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/special-orders/{special_order_id}/customer-approve", payload, headers)

    def list_special_orders(self, headers: dict, params: dict = None):
        return self._request("GET", "/special-orders", headers=headers, params=params)

    def get_special_order(self, special_order_id: str, headers: dict):
        return self._request("GET", f"/special-orders/{special_order_id}", headers=headers)


api_client = ApiClient()
