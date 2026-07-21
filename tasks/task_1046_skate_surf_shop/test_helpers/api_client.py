"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers=headers)

    # ---- Product ----
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers=headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def update_product(self, product_id, payload, headers):
        return self._request("PATCH", f"/products/{product_id}", payload, headers=headers)

    def restock_product(self, product_id, payload, headers):
        return self._request("POST", f"/products/{product_id}/restock", payload, headers=headers)

    # ---- Member ----
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers=headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def suspend_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/suspend", {}, headers=headers)

    def reinstate_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/reinstate", {}, headers=headers)

    # ---- Instructor ----
    def create_instructor(self, payload, headers):
        return self._request("POST", "/instructors", payload, headers=headers)

    def get_instructor(self, instructor_id, headers):
        return self._request("GET", f"/instructors/{instructor_id}", headers=headers)

    # ---- ServiceBay ----
    def create_service_bay(self, payload, headers):
        return self._request("POST", "/service-bays", payload, headers=headers)

    def get_service_bay(self, bay_id, headers):
        return self._request("GET", f"/service-bays/{bay_id}", headers=headers)

    # ---- RentalUnit ----
    def create_rental_unit(self, payload, headers):
        return self._request("POST", "/rental-units", payload, headers=headers)

    def get_rental_unit(self, unit_id, headers):
        return self._request("GET", f"/rental-units/{unit_id}", headers=headers)

    # ---- BoardBuild ----
    def create_board_build(self, payload, headers):
        return self._request("POST", "/board-builds", payload, headers=headers)

    def get_board_build(self, build_id, headers):
        return self._request("GET", f"/board-builds/{build_id}", headers=headers)

    def list_board_builds(self, headers, params=None):
        return self._request("GET", "/board-builds", headers=headers, params=params)

    def reserve_board_build(self, build_id, headers):
        return self._request("POST", f"/board-builds/{build_id}/reserve", {}, headers=headers)

    def assemble_board_build(self, build_id, headers):
        return self._request("POST", f"/board-builds/{build_id}/assemble", {}, headers=headers)

    def revise_board_build(self, build_id, headers):
        return self._request("POST", f"/board-builds/{build_id}/revise", {}, headers=headers)

    def setup_board_build(self, build_id, headers):
        return self._request("POST", f"/board-builds/{build_id}/setup", {}, headers=headers)

    def complete_board_build(self, build_id, headers, payload=None):
        return self._request("POST", f"/board-builds/{build_id}/complete", payload or {}, headers=headers)

    def cancel_board_build(self, build_id, headers):
        return self._request("POST", f"/board-builds/{build_id}/cancel", {}, headers=headers)

    # ---- ServiceOrder ----
    def create_service_order(self, payload, headers):
        return self._request("POST", "/service-orders", payload, headers=headers)

    def get_service_order(self, order_id, headers):
        return self._request("GET", f"/service-orders/{order_id}", headers=headers)

    def list_service_orders(self, headers, params=None):
        return self._request("GET", "/service-orders", headers=headers, params=params)

    def start_service_order(self, order_id, headers):
        return self._request("POST", f"/service-orders/{order_id}/start", {}, headers=headers)

    def complete_service_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/service-orders/{order_id}/complete", payload or {}, headers=headers)

    def cancel_service_order(self, order_id, headers):
        return self._request("POST", f"/service-orders/{order_id}/cancel", {}, headers=headers)

    # ---- Rental ----
    def create_rental(self, payload, headers):
        return self._request("POST", "/rentals", payload, headers=headers)

    def get_rental(self, rental_id, headers):
        return self._request("GET", f"/rentals/{rental_id}", headers=headers)

    def list_rentals(self, headers, params=None):
        return self._request("GET", "/rentals", headers=headers, params=params)

    def checkout_rental(self, rental_id, headers):
        return self._request("POST", f"/rentals/{rental_id}/checkout", {}, headers=headers)

    def return_rental(self, rental_id, headers, payload=None):
        return self._request("POST", f"/rentals/{rental_id}/return", payload or {}, headers=headers)

    def cancel_rental(self, rental_id, headers):
        return self._request("POST", f"/rentals/{rental_id}/cancel", {}, headers=headers)

    # ---- Lesson ----
    def create_lesson(self, payload, headers):
        return self._request("POST", "/lessons", payload, headers=headers)

    def get_lesson(self, lesson_id, headers):
        return self._request("GET", f"/lessons/{lesson_id}", headers=headers)

    def list_lessons(self, headers, params=None):
        return self._request("GET", "/lessons", headers=headers, params=params)

    def confirm_lesson(self, lesson_id, headers):
        return self._request("POST", f"/lessons/{lesson_id}/confirm", {}, headers=headers)

    def complete_lesson(self, lesson_id, headers, payload=None):
        return self._request("POST", f"/lessons/{lesson_id}/complete", payload or {}, headers=headers)

    def cancel_lesson(self, lesson_id, headers):
        return self._request("POST", f"/lessons/{lesson_id}/cancel", {}, headers=headers)

    # ---- TradeIn ----
    def create_trade_in(self, payload, headers):
        return self._request("POST", "/trade-ins", payload, headers=headers)

    def get_trade_in(self, trade_in_id, headers):
        return self._request("GET", f"/trade-ins/{trade_in_id}", headers=headers)

    def list_trade_ins(self, headers, params=None):
        return self._request("GET", "/trade-ins", headers=headers, params=params)

    def appraise_trade_in(self, trade_in_id, payload, headers):
        return self._request("POST", f"/trade-ins/{trade_in_id}/appraise", payload, headers=headers)

    def buyout_trade_in(self, trade_in_id, payload, headers):
        return self._request("POST", f"/trade-ins/{trade_in_id}/buyout", payload, headers=headers)

    def list_for_consignment(self, trade_in_id, payload, headers):
        return self._request("POST", f"/trade-ins/{trade_in_id}/list", payload, headers=headers)

    def sell_trade_in(self, trade_in_id, headers):
        return self._request("POST", f"/trade-ins/{trade_in_id}/sell", {}, headers=headers)

    def return_trade_in(self, trade_in_id, headers):
        return self._request("POST", f"/trade-ins/{trade_in_id}/return", {}, headers=headers)

    # ---- SpecialOrder ----
    def create_special_order(self, payload, headers):
        return self._request("POST", "/special-orders", payload, headers=headers)

    def get_special_order(self, order_id, headers):
        return self._request("GET", f"/special-orders/{order_id}", headers=headers)

    def list_special_orders(self, headers, params=None):
        return self._request("GET", "/special-orders", headers=headers, params=params)

    def quote_special_order(self, order_id, payload, headers):
        return self._request("POST", f"/special-orders/{order_id}/quote", payload, headers=headers)

    def deposit_special_order(self, order_id, payload, headers):
        return self._request("POST", f"/special-orders/{order_id}/deposit", payload, headers=headers)

    def fulfill_special_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/special-orders/{order_id}/fulfill", payload or {}, headers=headers)

    def cancel_special_order(self, order_id, headers):
        return self._request("POST", f"/special-orders/{order_id}/cancel", {}, headers=headers)

    # ---- Event & EventRegistration ----
    def create_event(self, payload, headers):
        return self._request("POST", "/events", payload, headers=headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}", headers=headers)

    def close_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/close", {}, headers=headers)

    def register_event(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/register", payload, headers=headers)

    def get_event_registration(self, registration_id, headers):
        return self._request("GET", f"/event-registrations/{registration_id}", headers=headers)

    def list_event_registrations(self, headers, params=None):
        return self._request("GET", "/event-registrations", headers=headers, params=params)

    def cancel_event_registration(self, registration_id, headers):
        return self._request("POST", f"/event-registrations/{registration_id}/cancel", {}, headers=headers)


api_client = ApiClient()
