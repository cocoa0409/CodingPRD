"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Customers
    # ------------------------------------------------------------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/grow/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/grow/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/grow/customers/{customer_id}", headers=headers)

    # ------------------------------------------------------------------
    # Varieties
    # ------------------------------------------------------------------
    def create_variety(self, payload, headers):
        return self._request("POST", "/grow/varieties", payload, headers)

    def list_varieties(self, headers, params=None):
        return self._request("GET", "/grow/varieties", headers=headers, params=params)

    def get_variety(self, variety_id, headers):
        return self._request("GET", f"/grow/varieties/{variety_id}", headers=headers)

    def retire_variety(self, variety_id, headers):
        return self._request("POST", f"/grow/varieties/{variety_id}/retire", {}, headers)

    # ------------------------------------------------------------------
    # Variety trials
    # ------------------------------------------------------------------
    def create_variety_trial(self, payload, headers):
        return self._request("POST", "/grow/variety-trials", payload, headers)

    def list_variety_trials(self, headers, params=None):
        return self._request("GET", "/grow/variety-trials", headers=headers, params=params)

    def get_variety_trial(self, trial_id, headers):
        return self._request("GET", f"/grow/variety-trials/{trial_id}", headers=headers)

    def record_panel(self, trial_id, scores, headers):
        return self._request(
            "POST", f"/grow/variety-trials/{trial_id}/record-panel",
            {"scores": list(scores)}, headers)

    def decide_trial(self, trial_id, outcome, headers):
        return self._request(
            "POST", f"/grow/variety-trials/{trial_id}/decide",
            {"outcome": outcome}, headers)

    # ------------------------------------------------------------------
    # Seed lots / germination tests
    # ------------------------------------------------------------------
    def create_seed_lot(self, payload, headers):
        return self._request("POST", "/grow/seed-lots", payload, headers)

    def list_seed_lots(self, headers, params=None):
        return self._request("GET", "/grow/seed-lots", headers=headers, params=params)

    def get_seed_lot(self, seed_lot_id, headers):
        return self._request("GET", f"/grow/seed-lots/{seed_lot_id}", headers=headers)

    def create_germination_test(self, payload, headers):
        return self._request("POST", "/grow/germination-tests", payload, headers)

    def list_germination_tests(self, headers, params=None):
        return self._request("GET", "/grow/germination-tests", headers=headers, params=params)

    def get_germination_test(self, test_id, headers):
        return self._request("GET", f"/grow/germination-tests/{test_id}", headers=headers)

    def record_germination_result(self, test_id, germinated_count, headers):
        return self._request(
            "POST", f"/grow/germination-tests/{test_id}/record-result",
            {"germinated_count": germinated_count}, headers)

    # ------------------------------------------------------------------
    # Food safety plans / sanitation logs
    # ------------------------------------------------------------------
    def create_food_safety_plan(self, payload, headers):
        return self._request("POST", "/grow/food-safety-plans", payload, headers)

    def get_food_safety_plan(self, plan_id, headers):
        return self._request("GET", f"/grow/food-safety-plans/{plan_id}", headers=headers)

    def approve_food_safety_plan(self, plan_id, headers):
        return self._request("POST", f"/grow/food-safety-plans/{plan_id}/approve", {}, headers)

    def suspend_food_safety_plan(self, plan_id, headers):
        return self._request("POST", f"/grow/food-safety-plans/{plan_id}/suspend", {}, headers)

    def create_sanitation_log(self, payload, headers):
        return self._request("POST", "/grow/sanitation-logs", payload, headers)

    def list_sanitation_logs(self, headers, params=None):
        return self._request("GET", "/grow/sanitation-logs", headers=headers, params=params)

    def get_sanitation_log(self, log_id, headers):
        return self._request("GET", f"/grow/sanitation-logs/{log_id}", headers=headers)

    # ------------------------------------------------------------------
    # Crop plans / tray batches
    # ------------------------------------------------------------------
    def create_crop_plan(self, payload, headers):
        return self._request("POST", "/grow/crop-plans", payload, headers)

    def list_crop_plans(self, headers, params=None):
        return self._request("GET", "/grow/crop-plans", headers=headers, params=params)

    def get_crop_plan(self, plan_id, headers):
        return self._request("GET", f"/grow/crop-plans/{plan_id}", headers=headers)

    def sow_crop_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/grow/crop-plans/{plan_id}/sow", payload, headers)

    def cancel_crop_plan(self, plan_id, headers):
        return self._request("POST", f"/grow/crop-plans/{plan_id}/cancel", {}, headers)

    def list_tray_batches(self, headers, params=None):
        return self._request("GET", "/grow/tray-batches", headers=headers, params=params)

    def get_tray_batch(self, batch_id, headers):
        return self._request("GET", f"/grow/tray-batches/{batch_id}", headers=headers)

    def advance_tray_batch(self, batch_id, headers):
        return self._request("POST", f"/grow/tray-batches/{batch_id}/advance", {}, headers)

    def harvest_tray_batch(self, batch_id, harvested_kg, headers):
        return self._request(
            "POST", f"/grow/tray-batches/{batch_id}/harvest",
            {"harvested_kg": harvested_kg}, headers)

    # ------------------------------------------------------------------
    # Standing orders / order items
    # ------------------------------------------------------------------
    def create_standing_order(self, payload, headers):
        return self._request("POST", "/grow/standing-orders", payload, headers)

    def list_standing_orders(self, headers, params=None):
        return self._request("GET", "/grow/standing-orders", headers=headers, params=params)

    def get_standing_order(self, order_id, headers):
        return self._request("GET", f"/grow/standing-orders/{order_id}", headers=headers)

    def get_order_projection(self, order_id, headers):
        return self._request(
            "GET", f"/grow/standing-orders/{order_id}/projection", headers=headers)

    def add_order_line(self, order_id, payload, headers):
        return self._request(
            "POST", f"/grow/standing-orders/{order_id}/lines", payload, headers)

    def list_order_lines(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/grow/standing-orders/{order_id}/lines", headers=headers, params=params)

    def confirm_standing_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/grow/standing-orders/{order_id}/confirm", payload, headers)

    def cancel_standing_order(self, order_id, headers):
        return self._request(
            "POST", f"/grow/standing-orders/{order_id}/cancel", {}, headers)

    def list_order_items(self, headers, params=None):
        return self._request("GET", "/grow/order-items", headers=headers, params=params)

    def get_order_item(self, item_id, headers):
        return self._request("GET", f"/grow/order-items/{item_id}", headers=headers)

    # ------------------------------------------------------------------
    # Delivery routes / stops
    # ------------------------------------------------------------------
    def create_delivery_route(self, payload, headers):
        return self._request("POST", "/grow/delivery-routes", payload, headers)

    def list_delivery_routes(self, headers, params=None):
        return self._request("GET", "/grow/delivery-routes", headers=headers, params=params)

    def get_delivery_route(self, route_id, headers):
        return self._request("GET", f"/grow/delivery-routes/{route_id}", headers=headers)

    def add_delivery_stop(self, route_id, payload, headers):
        return self._request(
            "POST", f"/grow/delivery-routes/{route_id}/stops", payload, headers)

    def list_route_stops(self, route_id, headers, params=None):
        return self._request(
            "GET", f"/grow/delivery-routes/{route_id}/stops", headers=headers, params=params)

    def dispatch_route(self, route_id, headers):
        return self._request(
            "POST", f"/grow/delivery-routes/{route_id}/dispatch", {}, headers)

    def complete_route(self, route_id, headers):
        return self._request(
            "POST", f"/grow/delivery-routes/{route_id}/complete", {}, headers)

    def list_delivery_stops(self, headers, params=None):
        return self._request("GET", "/grow/delivery-stops", headers=headers, params=params)

    def get_delivery_stop(self, stop_id, headers):
        return self._request("GET", f"/grow/delivery-stops/{stop_id}", headers=headers)

    def deliver_stop(self, stop_id, headers):
        return self._request(
            "POST", f"/grow/delivery-stops/{stop_id}/deliver", {}, headers)

    def skip_stop(self, stop_id, headers):
        return self._request("POST", f"/grow/delivery-stops/{stop_id}/skip", {}, headers)

    # ------------------------------------------------------------------
    # Spoilage credits
    # ------------------------------------------------------------------
    def create_spoilage_credit(self, payload, headers):
        return self._request("POST", "/grow/spoilage-credits", payload, headers)

    def list_spoilage_credits(self, headers, params=None):
        return self._request("GET", "/grow/spoilage-credits", headers=headers, params=params)

    def get_spoilage_credit(self, credit_id, headers):
        return self._request("GET", f"/grow/spoilage-credits/{credit_id}", headers=headers)

    def approve_spoilage_credit(self, credit_id, headers):
        return self._request(
            "POST", f"/grow/spoilage-credits/{credit_id}/approve", {}, headers)

    def reject_spoilage_credit(self, credit_id, headers):
        return self._request(
            "POST", f"/grow/spoilage-credits/{credit_id}/reject", {}, headers)

    # ------------------------------------------------------------------
    # Surplus listings
    # ------------------------------------------------------------------
    def create_surplus_listing(self, payload, headers):
        return self._request("POST", "/grow/surplus-listings", payload, headers)

    def list_surplus_listings(self, headers, params=None):
        return self._request("GET", "/grow/surplus-listings", headers=headers, params=params)

    def get_surplus_listing(self, listing_id, headers):
        return self._request("GET", f"/grow/surplus-listings/{listing_id}", headers=headers)

    def sell_surplus_listing(self, listing_id, headers):
        return self._request(
            "POST", f"/grow/surplus-listings/{listing_id}/sell", {}, headers)

    def withdraw_surplus_listing(self, listing_id, headers):
        return self._request(
            "POST", f"/grow/surplus-listings/{listing_id}/withdraw", {}, headers)

    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint, PRD §2.5)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/grow/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
