"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Product ----
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def adjust_inventory(self, product_id, payload, headers):
        return self._request(
            "POST", f"/products/{product_id}/inventory-adjustments", payload, headers
        )

    def discontinue_product(self, product_id, headers):
        return self._request(
            "POST", f"/products/{product_id}/discontinue", {}, headers
        )

    # ---- Customer ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def loyalty_adjustment(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/customers/{customer_id}/loyalty-adjustments", payload, headers
        )

    # ---- Coach ----
    def create_coach(self, payload, headers):
        return self._request("POST", "/coaches", payload, headers)

    def list_coaches(self, headers, params=None):
        return self._request("GET", "/coaches", headers=headers, params=params)

    def get_coach(self, coach_id, headers):
        return self._request("GET", f"/coaches/{coach_id}", headers=headers)

    # ---- RentalAsset ----
    def create_rental_asset(self, payload, headers):
        return self._request("POST", "/rental-assets", payload, headers)

    def list_rental_assets(self, headers, params=None):
        return self._request("GET", "/rental-assets", headers=headers, params=params)

    def get_rental_asset(self, asset_id, headers):
        return self._request("GET", f"/rental-assets/{asset_id}", headers=headers)

    # ---- Lesson ----
    def create_lesson(self, payload, headers):
        return self._request("POST", "/lessons", payload, headers)

    def list_lessons(self, headers, params=None):
        return self._request("GET", "/lessons", headers=headers, params=params)

    def get_lesson(self, lesson_id, headers):
        return self._request("GET", f"/lessons/{lesson_id}", headers=headers)

    def complete_lesson(self, lesson_id, payload, headers):
        return self._request(
            "POST", f"/lessons/{lesson_id}/complete", payload, headers
        )

    def cancel_lesson(self, lesson_id, headers):
        return self._request("POST", f"/lessons/{lesson_id}/cancel", {}, headers)

    # ---- Rental ----
    def create_rental(self, payload, headers):
        return self._request("POST", "/rentals", payload, headers)

    def list_rentals(self, headers, params=None):
        return self._request("GET", "/rentals", headers=headers, params=params)

    def get_rental(self, rental_id, headers):
        return self._request("GET", f"/rentals/{rental_id}", headers=headers)

    def checkout_rental(self, rental_id, headers):
        return self._request("POST", f"/rentals/{rental_id}/checkout", {}, headers)

    def return_rental(self, rental_id, headers):
        return self._request("POST", f"/rentals/{rental_id}/return", {}, headers)

    def release_rental(self, rental_id, headers):
        return self._request("POST", f"/rentals/{rental_id}/release", {}, headers)

    # ---- BoardBuild ----
    def create_board_build(self, payload, headers):
        return self._request("POST", "/board-builds", payload, headers)

    def list_board_builds(self, headers, params=None):
        return self._request("GET", "/board-builds", headers=headers, params=params)

    def get_board_build(self, build_id, headers):
        return self._request("GET", f"/board-builds/{build_id}", headers=headers)

    def reserve_board_build(self, build_id, headers):
        return self._request("POST", f"/board-builds/{build_id}/reserve", {}, headers)

    def complete_board_build(self, build_id, headers):
        return self._request("POST", f"/board-builds/{build_id}/complete", {}, headers)

    def cancel_board_build(self, build_id, headers):
        return self._request("POST", f"/board-builds/{build_id}/cancel", {}, headers)

    # ---- ServiceTicket ----
    def create_service_ticket(self, payload, headers):
        return self._request("POST", "/service-tickets", payload, headers)

    def list_service_tickets(self, headers, params=None):
        return self._request("GET", "/service-tickets", headers=headers, params=params)

    def get_service_ticket(self, ticket_id, headers):
        return self._request("GET", f"/service-tickets/{ticket_id}", headers=headers)

    def ready_service_ticket(self, ticket_id, headers):
        return self._request("POST", f"/service-tickets/{ticket_id}/ready", {}, headers)

    def pickup_service_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/service-tickets/{ticket_id}/pickup", {}, headers
        )

    def cancel_service_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/service-tickets/{ticket_id}/cancel", {}, headers
        )

    # ---- TradeIn ----
    def create_trade_in(self, payload, headers):
        return self._request("POST", "/trade-ins", payload, headers)

    def list_trade_ins(self, headers, params=None):
        return self._request("GET", "/trade-ins", headers=headers, params=params)

    def get_trade_in(self, trade_in_id, headers):
        return self._request("GET", f"/trade-ins/{trade_in_id}", headers=headers)

    def appraise_trade_in(self, trade_in_id, payload, headers):
        return self._request(
            "POST", f"/trade-ins/{trade_in_id}/appraise", payload, headers
        )

    def accept_trade_in(self, trade_in_id, payload, headers):
        return self._request(
            "POST", f"/trade-ins/{trade_in_id}/accept", payload, headers
        )

    def reject_trade_in(self, trade_in_id, headers):
        return self._request("POST", f"/trade-ins/{trade_in_id}/reject", {}, headers)

    def sell_trade_in(self, trade_in_id, payload, headers):
        return self._request(
            "POST", f"/trade-ins/{trade_in_id}/sell", payload, headers
        )

    # ---- SpecialOrder ----
    def create_special_order(self, payload, headers):
        return self._request("POST", "/special-orders", payload, headers)

    def list_special_orders(self, headers, params=None):
        return self._request("GET", "/special-orders", headers=headers, params=params)

    def get_special_order(self, order_id, headers):
        return self._request("GET", f"/special-orders/{order_id}", headers=headers)

    def quote_special_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/special-orders/{order_id}/quote", payload, headers
        )

    def revise_special_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/special-orders/{order_id}/revise", payload, headers
        )

    def approve_special_order(self, order_id, headers):
        return self._request(
            "POST", f"/special-orders/{order_id}/approve", {}, headers
        )

    def fulfill_special_order(self, order_id, headers):
        return self._request(
            "POST", f"/special-orders/{order_id}/fulfill", {}, headers
        )

    def cancel_special_order(self, order_id, headers):
        return self._request(
            "POST", f"/special-orders/{order_id}/cancel", {}, headers
        )

    # ---- Event ----
    def create_event(self, payload, headers):
        return self._request("POST", "/events", payload, headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/events", headers=headers, params=params)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}", headers=headers)

    def publish_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/publish", {}, headers)

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/cancel", {}, headers)

    # ---- EventEntry ----
    def create_event_entry(self, payload, headers):
        return self._request("POST", "/event-entries", payload, headers)

    def list_event_entries(self, headers, params=None):
        return self._request("GET", "/event-entries", headers=headers, params=params)

    def get_event_entry(self, entry_id, headers):
        return self._request("GET", f"/event-entries/{entry_id}", headers=headers)

    def cancel_event_entry(self, entry_id, headers):
        return self._request("POST", f"/event-entries/{entry_id}/cancel", {}, headers)

    # ---- Logical clock (test-driving) ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
