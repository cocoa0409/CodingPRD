"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() is inherited.
All paths are mounted under the /seller prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Shop ----
    def create_shop(self, payload, headers):
        return self._request("POST", "/seller/shops", payload, headers)

    def get_shop(self, shop_id, headers):
        return self._request("GET", f"/seller/shops/{shop_id}", headers=headers)

    def list_shops(self, headers, params=None):
        return self._request("GET", "/seller/shops", headers=headers, params=params)

    def enable_vacation(self, shop_id, headers, payload=None):
        return self._request("POST", f"/seller/shops/{shop_id}/enable-vacation",
                             payload if payload is not None else {}, headers)

    def return_from_vacation(self, shop_id, headers, payload=None):
        return self._request("POST", f"/seller/shops/{shop_id}/return-from-vacation",
                             payload if payload is not None else {}, headers)

    def suspend_shop(self, shop_id, headers, payload=None):
        return self._request("POST", f"/seller/shops/{shop_id}/suspend",
                             payload if payload is not None else {}, headers)

    def reinstate_shop(self, shop_id, headers, payload=None):
        return self._request("POST", f"/seller/shops/{shop_id}/reinstate",
                             payload if payload is not None else {}, headers)

    # ---- ShippingProfile ----
    def create_shipping_profile(self, payload, headers):
        return self._request("POST", "/seller/shipping-profiles", payload, headers)

    def get_shipping_profile(self, profile_id, headers):
        return self._request("GET", f"/seller/shipping-profiles/{profile_id}", headers=headers)

    def list_shipping_profiles(self, headers, params=None):
        return self._request("GET", "/seller/shipping-profiles", headers=headers, params=params)

    # ---- Material ----
    def create_material(self, payload, headers):
        return self._request("POST", "/seller/materials", payload, headers)

    def get_material(self, material_id, headers):
        return self._request("GET", f"/seller/materials/{material_id}", headers=headers)

    def list_materials(self, headers, params=None):
        return self._request("GET", "/seller/materials", headers=headers, params=params)

    def restock_material(self, material_id, headers, payload=None):
        return self._request("POST", f"/seller/materials/{material_id}/restock",
                             payload if payload is not None else {}, headers)

    # ---- Listing ----
    def create_listing(self, payload, headers):
        return self._request("POST", "/seller/listings", payload, headers)

    def get_listing(self, listing_id, headers):
        return self._request("GET", f"/seller/listings/{listing_id}", headers=headers)

    def list_listings(self, headers, params=None):
        return self._request("GET", "/seller/listings", headers=headers, params=params)

    def publish_listing(self, listing_id, headers, payload=None):
        return self._request("POST", f"/seller/listings/{listing_id}/publish",
                             payload if payload is not None else {}, headers)

    def deactivate_listing(self, listing_id, headers, payload=None):
        return self._request("POST", f"/seller/listings/{listing_id}/deactivate",
                             payload if payload is not None else {}, headers)

    def restock_listing(self, listing_id, headers, payload=None):
        return self._request("POST", f"/seller/listings/{listing_id}/restock",
                             payload if payload is not None else {}, headers)

    # ---- VacationPeriod ----
    def create_vacation_period(self, payload, headers):
        return self._request("POST", "/seller/vacation-periods", payload, headers)

    def get_vacation_period(self, period_id, headers):
        return self._request("GET", f"/seller/vacation-periods/{period_id}", headers=headers)

    def list_vacation_periods(self, headers, params=None):
        return self._request("GET", "/seller/vacation-periods", headers=headers, params=params)

    # ---- Order ----
    def create_order(self, payload, headers):
        return self._request("POST", "/seller/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/seller/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/seller/orders", headers=headers, params=params)

    def pay_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/seller/orders/{order_id}/pay",
                             payload if payload is not None else {}, headers)

    def ship_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/seller/orders/{order_id}/ship",
                             payload if payload is not None else {}, headers)

    def deliver_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/seller/orders/{order_id}/deliver",
                             payload if payload is not None else {}, headers)

    def complete_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/seller/orders/{order_id}/complete",
                             payload if payload is not None else {}, headers)

    def cancel_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/seller/orders/{order_id}/cancel",
                             payload if payload is not None else {}, headers)

    # ---- Review ----
    def create_review(self, payload, headers):
        return self._request("POST", "/seller/reviews", payload, headers)

    def get_review(self, review_id, headers):
        return self._request("GET", f"/seller/reviews/{review_id}", headers=headers)

    def list_reviews(self, headers, params=None):
        return self._request("GET", "/seller/reviews", headers=headers, params=params)

    def respond_review(self, review_id, headers, payload=None):
        return self._request("POST", f"/seller/reviews/{review_id}/respond",
                             payload if payload is not None else {}, headers)

    def hide_review(self, review_id, headers, payload=None):
        return self._request("POST", f"/seller/reviews/{review_id}/hide",
                             payload if payload is not None else {}, headers)

    # ---- Case ----
    def create_case(self, payload, headers):
        return self._request("POST", "/seller/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/seller/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/seller/cases", headers=headers, params=params)

    def respond_case(self, case_id, headers, payload=None):
        return self._request("POST", f"/seller/cases/{case_id}/respond",
                             payload if payload is not None else {}, headers)

    def escalate_case(self, case_id, headers, payload=None):
        return self._request("POST", f"/seller/cases/{case_id}/escalate",
                             payload if payload is not None else {}, headers)

    def resolve_case(self, case_id, headers, payload=None):
        return self._request("POST", f"/seller/cases/{case_id}/resolve",
                             payload if payload is not None else {}, headers)

    # ---- Payout ----
    def create_payout(self, payload, headers):
        return self._request("POST", "/seller/payouts", payload, headers)

    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/seller/payouts/{payout_id}", headers=headers)

    def list_payouts(self, headers, params=None):
        return self._request("GET", "/seller/payouts", headers=headers, params=params)

    def mark_paid_payout(self, payout_id, headers, payload=None):
        return self._request("POST", f"/seller/payouts/{payout_id}/mark-paid",
                             payload if payload is not None else {}, headers)

    def release_hold_payout(self, payout_id, headers, payload=None):
        return self._request("POST", f"/seller/payouts/{payout_id}/release-hold",
                             payload if payload is not None else {}, headers)

    # ---- Logical clock (test-driving) ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/seller/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
