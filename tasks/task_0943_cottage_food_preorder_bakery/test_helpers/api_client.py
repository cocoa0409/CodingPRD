"""API client: one method per endpoint the PRD declares under /bakery."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/bakery"


class ApiClient(GenericApiClient):
    # ── Baker ────────────────────────────────────────────────────────────────
    def create_baker(self, payload, headers):
        return self._request("POST", f"{PREFIX}/bakers", payload, headers)

    def set_permit_status(self, baker_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/bakers/{baker_id}/permit-status", payload, headers
        )

    def get_baker(self, baker_id, headers):
        return self._request("GET", f"{PREFIX}/bakers/{baker_id}", headers=headers)

    def list_bakers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/bakers", headers=headers, params=params)

    def get_baker_compliance(self, baker_id, headers):
        return self._request(
            "GET", f"{PREFIX}/bakers/{baker_id}/compliance", headers=headers
        )

    # ── Customer ─────────────────────────────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"{PREFIX}/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/customers", headers=headers, params=params
        )

    # ── Recipe / components ──────────────────────────────────────────────────
    def create_recipe(self, payload, headers):
        return self._request("POST", f"{PREFIX}/recipes", payload, headers)

    def add_recipe_component(self, recipe_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/recipes/{recipe_id}/components", payload, headers
        )

    def publish_recipe(self, recipe_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/recipes/{recipe_id}/publish", payload or {}, headers
        )

    def set_recipe_lifecycle(self, recipe_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/recipes/{recipe_id}/lifecycle", payload, headers
        )

    def get_recipe(self, recipe_id, headers):
        return self._request("GET", f"{PREFIX}/recipes/{recipe_id}", headers=headers)

    def list_recipes(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/recipes", headers=headers, params=params)

    def get_allergen_profile(self, recipe_id, headers):
        return self._request(
            "GET", f"{PREFIX}/recipes/{recipe_id}/allergen-profile", headers=headers
        )

    def get_recipe_component(self, recipe_component_id, headers):
        return self._request(
            "GET", f"{PREFIX}/recipe-components/{recipe_component_id}", headers=headers
        )

    def list_recipe_components(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/recipe-components", headers=headers, params=params
        )

    # ── IngredientLot ────────────────────────────────────────────────────────
    def create_ingredient_lot(self, payload, headers):
        return self._request("POST", f"{PREFIX}/ingredient-lots", payload, headers)

    def release_ingredient_lot(self, ingredient_lot_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/ingredient-lots/{ingredient_lot_id}/release",
            payload or {},
            headers,
        )

    def recall_ingredient_lot(self, ingredient_lot_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/ingredient-lots/{ingredient_lot_id}/recall",
            payload,
            headers,
        )

    def get_ingredient_lot(self, ingredient_lot_id, headers):
        return self._request(
            "GET", f"{PREFIX}/ingredient-lots/{ingredient_lot_id}", headers=headers
        )

    def list_ingredient_lots(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/ingredient-lots", headers=headers, params=params
        )

    # ── MenuItem ─────────────────────────────────────────────────────────────
    def create_menu_item(self, payload, headers):
        return self._request("POST", f"{PREFIX}/menu-items", payload, headers)

    def set_listing_status(self, menu_item_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/menu-items/{menu_item_id}/listing-status", payload, headers
        )

    def get_menu_item(self, menu_item_id, headers):
        return self._request(
            "GET", f"{PREFIX}/menu-items/{menu_item_id}", headers=headers
        )

    def list_menu_items(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/menu-items", headers=headers, params=params
        )

    # ── OfferWindow ──────────────────────────────────────────────────────────
    def create_offer_window(self, payload, headers):
        return self._request("POST", f"{PREFIX}/offer-windows", payload, headers)

    def lock_offer_window(self, offer_window_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/offer-windows/{offer_window_id}/lock", payload or {}, headers
        )

    def extend_cutoff(self, offer_window_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/offer-windows/{offer_window_id}/extend-cutoff",
            payload or {},
            headers,
        )

    def advance_offer_window(self, offer_window_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/offer-windows/{offer_window_id}/advance", payload, headers
        )

    def plan_offer_window(self, offer_window_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/offer-windows/{offer_window_id}/plan", payload, headers
        )

    def get_offer_window(self, offer_window_id, headers):
        return self._request(
            "GET", f"{PREFIX}/offer-windows/{offer_window_id}", headers=headers
        )

    def list_offer_windows(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/offer-windows", headers=headers, params=params
        )

    def get_offer_window_capacity(self, offer_window_id, headers):
        return self._request(
            "GET", f"{PREFIX}/offer-windows/{offer_window_id}/capacity", headers=headers
        )

    # ── Order / OrderLine ────────────────────────────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/orders", payload, headers)

    def add_order_line(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/orders/{order_id}/lines", payload, headers
        )

    def patch_order_line(self, order_id, order_line_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/orders/{order_id}/lines/{order_line_id}", payload, headers
        )

    def confirm_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/orders/{order_id}/confirm", payload or {}, headers
        )

    def cancel_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/orders/{order_id}/cancel", payload or {}, headers
        )

    def schedule_handoff(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/orders/{order_id}/schedule-handoff", payload or {}, headers
        )

    def record_handoff_outcome(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/orders/{order_id}/handoff-outcome", payload, headers
        )

    def get_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/orders", headers=headers, params=params)

    def get_order_quote(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/orders/{order_id}/quote", headers=headers)

    def get_order_line(self, order_line_id, headers):
        return self._request(
            "GET", f"{PREFIX}/order-lines/{order_line_id}", headers=headers
        )

    def list_order_lines(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/order-lines", headers=headers, params=params
        )

    # ── Batch / Label ────────────────────────────────────────────────────────
    def advance_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/batches/{batch_id}/advance", payload, headers
        )

    def confirm_yield(self, batch_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/batches/{batch_id}/confirm-yield", payload, headers
        )

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"{PREFIX}/batches/{batch_id}", headers=headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/batches", headers=headers, params=params)

    def create_label(self, payload, headers):
        return self._request("POST", f"{PREFIX}/labels", payload, headers)

    def get_label(self, label_id, headers):
        return self._request("GET", f"{PREFIX}/labels/{label_id}", headers=headers)

    def list_labels(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/labels", headers=headers, params=params)

    # ── Subscription / cycles ────────────────────────────────────────────────
    def create_subscription(self, payload, headers):
        return self._request("POST", f"{PREFIX}/subscriptions", payload, headers)

    def set_subscription_status(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/subscriptions/{subscription_id}/status", payload, headers
        )

    def generate_cycle(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/subscriptions/{subscription_id}/cycles", payload, headers
        )

    def skip_cycle(self, subscription_cycle_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/subscription-cycles/{subscription_cycle_id}/skip",
            payload or {},
            headers,
        )

    def confirm_cycle(self, subscription_cycle_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/subscription-cycles/{subscription_cycle_id}/confirm",
            payload,
            headers,
        )

    def get_subscription(self, subscription_id, headers):
        return self._request(
            "GET", f"{PREFIX}/subscriptions/{subscription_id}", headers=headers
        )

    def list_subscriptions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/subscriptions", headers=headers, params=params
        )

    def get_subscription_cycle(self, subscription_cycle_id, headers):
        return self._request(
            "GET",
            f"{PREFIX}/subscription-cycles/{subscription_cycle_id}",
            headers=headers,
        )

    def list_subscription_cycles(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/subscription-cycles", headers=headers, params=params
        )

    # ── Payment / money ──────────────────────────────────────────────────────
    def create_payment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/payments", payload, headers)

    def capture_payment(self, payment_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/payments/{payment_id}/capture", payload or {}, headers
        )

    def create_refund(self, payment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/payments/{payment_id}/refunds", payload, headers
        )

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"{PREFIX}/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/payments", headers=headers, params=params)

    def get_money_movement(self, money_movement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/money-movements/{money_movement_id}", headers=headers
        )

    def list_money_movements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/money-movements", headers=headers, params=params
        )

    # ── DeliveryRoute ────────────────────────────────────────────────────────
    def create_delivery_route(self, payload, headers):
        return self._request("POST", f"{PREFIX}/delivery-routes", payload, headers)

    def set_route_status(self, delivery_route_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/delivery-routes/{delivery_route_id}/status",
            payload,
            headers,
        )

    def get_delivery_route(self, delivery_route_id, headers):
        return self._request(
            "GET", f"{PREFIX}/delivery-routes/{delivery_route_id}", headers=headers
        )

    def list_delivery_routes(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/delivery-routes", headers=headers, params=params
        )

    # ── Review ───────────────────────────────────────────────────────────────
    def create_review(self, payload, headers):
        return self._request("POST", f"{PREFIX}/reviews", payload, headers)

    def respond_to_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/reviews/{review_id}/respond", payload, headers
        )

    def moderate_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/reviews/{review_id}/moderation", payload, headers
        )

    def get_review(self, review_id, headers):
        return self._request("GET", f"{PREFIX}/reviews/{review_id}", headers=headers)

    def list_reviews(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/reviews", headers=headers, params=params)

    # ── Test-driving capabilities ────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", payload, headers
        )

    def expire_due_holds(self, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/_holds/expire-due", payload or {}, headers
        )

    # ── Raw helper for header-omission tests ─────────────────────────────────
    def raw_get(self, path, headers=None, params=None):
        return self._request("GET", f"{PREFIX}{path}", headers=headers, params=params)


api_client = ApiClient()
