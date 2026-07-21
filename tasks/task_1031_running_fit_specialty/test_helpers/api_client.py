"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Member ----
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def adjust_loyalty(self, member_id, payload, headers):
        return self._request(
            "POST", f"/members/{member_id}/loyalty-adjustments", payload, headers
        )

    # ---- Product ----
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def restock_product(self, product_id, payload, headers):
        return self._request(
            "POST", f"/products/{product_id}/restock", payload, headers
        )

    # ---- Order ----
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def apply_redemption(self, order_id, payload, headers):
        return self._request(
            "POST", f"/orders/{order_id}/apply-redemption", payload, headers
        )

    def authorize_payment(self, order_id, headers):
        return self._request(
            "POST", f"/orders/{order_id}/authorize-payment", {}, headers
        )

    def capture_payment(self, order_id, headers):
        return self._request(
            "POST", f"/orders/{order_id}/capture-payment", {}, headers
        )

    def reserve_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/reserve", {}, headers)

    def fulfill_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/fulfill", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers)

    def price_override(self, order_id, payload, headers):
        return self._request(
            "POST", f"/orders/{order_id}/price-overrides", payload, headers
        )

    # ---- OrderLine ----
    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/order-lines/{line_id}", headers=headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    # ---- WearReturn ----
    def create_return(self, payload, headers):
        return self._request("POST", "/returns", payload, headers)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/returns/{return_id}", headers=headers)

    def list_returns(self, headers, params=None):
        return self._request("GET", "/returns", headers=headers, params=params)

    def start_inspection(self, return_id, headers):
        return self._request(
            "POST", f"/returns/{return_id}/start-inspection", {}, headers
        )

    def approve_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/approve", {}, headers)

    def reject_return(self, return_id, payload, headers):
        return self._request("POST", f"/returns/{return_id}/reject", payload, headers)

    def resubmit_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/resubmit", {}, headers)

    def withdraw_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/withdraw", {}, headers)

    # ---- Subscription ----
    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request(
            "GET", f"/subscriptions/{subscription_id}", headers=headers
        )

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def mark_past_due(self, subscription_id, headers):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/mark-past-due", {}, headers
        )

    def reactivate_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/reactivate", {}, headers
        )

    def cancel_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/cancel", {}, headers
        )

    # ---- RunningShoe ----
    def get_running_shoe(self, shoe_id, headers):
        return self._request("GET", f"/running-shoes/{shoe_id}", headers=headers)

    def list_running_shoes(self, headers, params=None):
        return self._request("GET", "/running-shoes", headers=headers, params=params)

    def log_mileage(self, shoe_id, payload, headers):
        return self._request(
            "POST", f"/running-shoes/{shoe_id}/log-mileage", payload, headers
        )

    def retire_shoe(self, shoe_id, headers):
        return self._request("POST", f"/running-shoes/{shoe_id}/retire", {}, headers)

    # ---- Fitter ----
    def create_fitter(self, payload, headers):
        return self._request("POST", "/fitters", payload, headers)

    def get_fitter(self, fitter_id, headers):
        return self._request("GET", f"/fitters/{fitter_id}", headers=headers)

    # ---- FitmentSession ----
    def create_fitment_session(self, payload, headers):
        return self._request("POST", "/fitment-sessions", payload, headers)

    def get_fitment_session(self, session_id, headers):
        return self._request(
            "GET", f"/fitment-sessions/{session_id}", headers=headers
        )

    def list_fitment_sessions(self, headers, params=None):
        return self._request(
            "GET", "/fitment-sessions", headers=headers, params=params
        )

    def checkin_fitment(self, session_id, headers):
        return self._request(
            "POST", f"/fitment-sessions/{session_id}/check-in", {}, headers
        )

    def complete_fitment(self, session_id, payload, headers):
        return self._request(
            "POST", f"/fitment-sessions/{session_id}/complete", payload, headers
        )

    def cancel_fitment(self, session_id, headers):
        return self._request(
            "POST", f"/fitment-sessions/{session_id}/cancel", {}, headers
        )

    # ---- TrainingSession ----
    def create_training_session(self, payload, headers):
        return self._request("POST", "/training-sessions", payload, headers)

    def get_training_session(self, session_id, headers):
        return self._request(
            "GET", f"/training-sessions/{session_id}", headers=headers
        )

    def list_training_sessions(self, headers, params=None):
        return self._request(
            "GET", "/training-sessions", headers=headers, params=params
        )

    # ---- TrainingBooking ----
    def create_training_booking(self, payload, headers):
        return self._request("POST", "/training-bookings", payload, headers)

    def get_training_booking(self, booking_id, headers):
        return self._request(
            "GET", f"/training-bookings/{booking_id}", headers=headers
        )

    def list_training_bookings(self, headers, params=None):
        return self._request(
            "GET", "/training-bookings", headers=headers, params=params
        )

    def cancel_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/training-bookings/{booking_id}/cancel", {}, headers
        )

    def mark_attended(self, booking_id, headers):
        return self._request(
            "POST", f"/training-bookings/{booking_id}/mark-attended", {}, headers
        )


api_client = ApiClient()
