"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----------------------------------------------------------------- Customer
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    # ----------------------------------------------------------------- Segment
    def create_segment(self, payload, headers):
        return self._request("POST", "/segments", payload, headers)

    def get_segment(self, segment_id, headers):
        return self._request("GET", f"/segments/{segment_id}", headers=headers)

    def add_member(self, segment_id, payload, headers):
        return self._request("POST", f"/segments/{segment_id}/members", payload, headers)

    def list_segment_members(self, segment_id, headers, params=None):
        return self._request("GET", f"/segments/{segment_id}/members", headers=headers, params=params)

    def revoke_member(self, segment_id, membership_id, headers):
        return self._request("DELETE", f"/segments/{segment_id}/members/{membership_id}", headers=headers)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/segment-memberships/{membership_id}", headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/segment-memberships", headers=headers, params=params)

    # ---------------------------------------------------------------- Promotion
    def create_promotion(self, payload, headers):
        return self._request("POST", "/promotions", payload, headers)

    def get_promotion(self, promotion_id, headers):
        return self._request("GET", f"/promotions/{promotion_id}", headers=headers)

    def list_promotions(self, headers, params=None):
        return self._request("GET", "/promotions", headers=headers, params=params)

    def activate_promotion(self, promotion_id, headers):
        return self._request("POST", f"/promotions/{promotion_id}/activate", headers=headers)

    def pause_promotion(self, promotion_id, headers):
        return self._request("POST", f"/promotions/{promotion_id}/pause", headers=headers)

    def archive_promotion(self, promotion_id, headers):
        return self._request("POST", f"/promotions/{promotion_id}/archive", headers=headers)

    # ------------------------------------------------------------------- Coupon
    def create_coupon(self, promotion_id, payload, headers):
        return self._request("POST", f"/promotions/{promotion_id}/coupons", payload, headers)

    def list_coupons(self, promotion_id, headers, params=None):
        return self._request("GET", f"/promotions/{promotion_id}/coupons", headers=headers, params=params)

    def get_coupon(self, promotion_id, coupon_id, headers):
        return self._request("GET", f"/promotions/{promotion_id}/coupons/{coupon_id}", headers=headers)

    def disable_coupon(self, promotion_id, coupon_id, headers):
        return self._request("POST", f"/promotions/{promotion_id}/coupons/{coupon_id}/disable", headers=headers)

    def enable_coupon(self, promotion_id, coupon_id, headers):
        return self._request("POST", f"/promotions/{promotion_id}/coupons/{coupon_id}/enable", headers=headers)

    # --------------------------------------------------------- BlackoutWindow
    def create_blackout(self, promotion_id, payload, headers):
        return self._request("POST", f"/promotions/{promotion_id}/blackouts", payload, headers)

    def list_blackouts(self, promotion_id, headers, params=None):
        return self._request("GET", f"/promotions/{promotion_id}/blackouts", headers=headers, params=params)

    # --------------------------------------------------------- ExclusionRule
    def create_exclusion_rule(self, payload, headers):
        return self._request("POST", "/exclusion-rules", payload, headers)

    def get_exclusion_rule(self, exclusion_rule_id, headers):
        return self._request("GET", f"/exclusion-rules/{exclusion_rule_id}", headers=headers)

    def list_exclusion_rules(self, headers, params=None):
        return self._request("GET", "/exclusion-rules", headers=headers, params=params)

    # ------------------------------------------------------------------- Cart
    def create_cart(self, payload, headers):
        return self._request("POST", "/carts", payload, headers)

    def get_cart(self, cart_id, headers):
        return self._request("GET", f"/carts/{cart_id}", headers=headers)

    def list_carts(self, headers, params=None):
        return self._request("GET", "/carts", headers=headers, params=params)

    def add_line(self, cart_id, payload, headers):
        return self._request("POST", f"/carts/{cart_id}/lines", payload, headers)

    def list_lines(self, cart_id, headers, params=None):
        return self._request("GET", f"/carts/{cart_id}/lines", headers=headers, params=params)

    def update_line(self, cart_id, line_id, payload, headers):
        return self._request("PATCH", f"/carts/{cart_id}/lines/{line_id}", payload, headers)

    def remove_line(self, cart_id, line_id, headers):
        return self._request("DELETE", f"/carts/{cart_id}/lines/{line_id}", headers=headers)

    def apply_coupon(self, cart_id, payload, headers):
        return self._request("POST", f"/carts/{cart_id}/applications", payload, headers)

    def list_applications(self, cart_id, headers, params=None):
        return self._request("GET", f"/carts/{cart_id}/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/cart-applications/{application_id}", headers=headers)

    def list_cart_applications(self, headers, params=None):
        return self._request("GET", "/cart-applications", headers=headers, params=params)

    def remove_application(self, cart_id, application_id, headers):
        return self._request("DELETE", f"/carts/{cart_id}/applications/{application_id}", headers=headers)

    def auto_apply(self, cart_id, headers):
        return self._request("POST", f"/carts/{cart_id}/auto-apply", headers=headers)

    def reprice(self, cart_id, headers):
        return self._request("POST", f"/carts/{cart_id}/reprice", headers=headers)

    def lock_cart(self, cart_id, headers):
        return self._request("POST", f"/carts/{cart_id}/lock", headers=headers)

    def unlock_cart(self, cart_id, headers):
        return self._request("POST", f"/carts/{cart_id}/unlock", headers=headers)

    def checkout_cart(self, cart_id, payload, headers):
        return self._request("POST", f"/carts/{cart_id}/checkout", payload, headers)

    def abandon_cart(self, cart_id, headers):
        return self._request("POST", f"/carts/{cart_id}/abandon", headers=headers)

    def list_cart_redemptions(self, cart_id, headers, params=None):
        return self._request("GET", f"/carts/{cart_id}/redemptions", headers=headers, params=params)

    def get_redemption(self, redemption_id, headers):
        return self._request("GET", f"/redemptions/{redemption_id}", headers=headers)

    def list_redemptions(self, headers, params=None):
        return self._request("GET", "/redemptions", headers=headers, params=params)

    # --------------------------------------------------- Clock (test-driving)
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)

    def advance_clock(self, payload, headers):
        return self._request("POST", "/_clock/advance", payload, headers)


api_client = ApiClient()
