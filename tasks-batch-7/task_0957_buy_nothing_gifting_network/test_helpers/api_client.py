"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Members ---
    def create_member(self, payload, headers):
        return self._request("POST", "/v1/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/v1/members/{member_id}", headers=headers)

    def list_reputation_events_of_member(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/v1/members/{member_id}/reputation-events", headers=headers, params=params
        )

    # --- Groups ---
    def create_group(self, payload, headers):
        return self._request("POST", "/v1/groups", payload, headers)

    def get_group(self, group_id, headers):
        return self._request("GET", f"/v1/groups/{group_id}", headers=headers)

    def update_group(self, group_id, payload, headers):
        return self._request("PUT", f"/v1/groups/{group_id}", payload, headers)

    # --- Memberships ---
    def create_membership(self, payload, headers):
        return self._request("POST", "/v1/memberships", payload, headers)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/v1/memberships/{membership_id}", headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/v1/memberships", headers=headers, params=params)

    def approve_membership(self, membership_id, headers, payload=None):
        return self._request("POST", f"/v1/memberships/{membership_id}/approve", payload, headers)

    def reject_membership(self, membership_id, headers):
        return self._request("POST", f"/v1/memberships/{membership_id}/reject", headers=headers)

    def leave_membership(self, membership_id, headers):
        return self._request("POST", f"/v1/memberships/{membership_id}/leave", headers=headers)

    def remove_membership(self, membership_id, headers):
        return self._request("POST", f"/v1/memberships/{membership_id}/remove", headers=headers)

    # --- Gift posts ---
    def create_gift_post(self, payload, headers):
        return self._request("POST", "/v1/gift-posts", payload, headers)

    def get_gift_post(self, post_id, headers):
        return self._request("GET", f"/v1/gift-posts/{post_id}", headers=headers)

    def list_gift_posts(self, headers, params=None):
        return self._request("GET", "/v1/gift-posts", headers=headers, params=params)

    def update_gift_post(self, post_id, payload, headers):
        return self._request("PUT", f"/v1/gift-posts/{post_id}", payload, headers)

    def publish_gift_post(self, post_id, headers):
        return self._request("POST", f"/v1/gift-posts/{post_id}/publish", headers=headers)

    def withdraw_gift_post(self, post_id, headers):
        return self._request("POST", f"/v1/gift-posts/{post_id}/withdraw", headers=headers)

    def offer_gift_post(self, post_id, payload, headers):
        return self._request("POST", f"/v1/gift-posts/{post_id}/offer", payload, headers)

    # --- Claims ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/v1/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/v1/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/v1/claims", headers=headers, params=params)

    def accept_claim(self, claim_id, headers):
        return self._request("POST", f"/v1/claims/{claim_id}/accept", headers=headers)

    def decline_claim(self, claim_id, headers):
        return self._request("POST", f"/v1/claims/{claim_id}/decline", headers=headers)

    def withdraw_claim(self, claim_id, headers):
        return self._request("POST", f"/v1/claims/{claim_id}/withdraw", headers=headers)

    # --- Pickup plans ---
    def create_pickup_plan(self, payload, headers):
        return self._request("POST", "/v1/pickup-plans", payload, headers)

    def get_pickup_plan(self, plan_id, headers):
        return self._request("GET", f"/v1/pickup-plans/{plan_id}", headers=headers)

    def list_pickup_plans(self, headers, params=None):
        return self._request("GET", "/v1/pickup-plans", headers=headers, params=params)

    def counter_pickup_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/v1/pickup-plans/{plan_id}/counter", payload, headers)

    def confirm_pickup_plan(self, plan_id, headers):
        return self._request("POST", f"/v1/pickup-plans/{plan_id}/confirm", headers=headers)

    def cancel_pickup_plan(self, plan_id, headers):
        return self._request("POST", f"/v1/pickup-plans/{plan_id}/cancel", headers=headers)

    def complete_pickup_plan(self, plan_id, headers):
        return self._request("POST", f"/v1/pickup-plans/{plan_id}/complete", headers=headers)

    def miss_pickup_plan(self, plan_id, headers):
        return self._request("POST", f"/v1/pickup-plans/{plan_id}/miss", headers=headers)

    # --- Wishlists ---
    def create_wishlist(self, payload, headers):
        return self._request("POST", "/v1/wishlists", payload, headers)

    def get_wishlist(self, wishlist_id, headers):
        return self._request("GET", f"/v1/wishlists/{wishlist_id}", headers=headers)

    def list_wishlists(self, headers, params=None):
        return self._request("GET", "/v1/wishlists", headers=headers, params=params)

    def cancel_wishlist(self, wishlist_id, headers):
        return self._request("POST", f"/v1/wishlists/{wishlist_id}/cancel", headers=headers)

    # --- Curb alerts ---
    def create_curb_alert(self, payload, headers):
        return self._request("POST", "/v1/curb-alerts", payload, headers)

    def get_curb_alert(self, alert_id, headers):
        return self._request("GET", f"/v1/curb-alerts/{alert_id}", headers=headers)

    def list_curb_alerts(self, headers, params=None):
        return self._request("GET", "/v1/curb-alerts", headers=headers, params=params)

    def cancel_curb_alert(self, alert_id, headers):
        return self._request("POST", f"/v1/curb-alerts/{alert_id}/cancel", headers=headers)

    # --- Reports ---
    def create_report(self, payload, headers):
        return self._request("POST", "/v1/reports", payload, headers)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/v1/reports/{report_id}", headers=headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/v1/reports", headers=headers, params=params)

    def start_review_report(self, report_id, headers):
        return self._request("POST", f"/v1/reports/{report_id}/start-review", headers=headers)

    def resolve_report(self, report_id, payload, headers):
        return self._request("POST", f"/v1/reports/{report_id}/resolve", payload, headers)

    # --- Moderation actions ---
    def get_moderation_action(self, action_id, headers):
        return self._request("GET", f"/v1/moderation-actions/{action_id}", headers=headers)

    def list_moderation_actions(self, headers, params=None):
        return self._request("GET", "/v1/moderation-actions", headers=headers, params=params)

    def overturn_moderation_action(self, action_id, headers):
        return self._request("POST", f"/v1/moderation-actions/{action_id}/overturn", headers=headers)

    # --- Reputation events ---
    def get_reputation_event(self, event_id, headers):
        return self._request("GET", f"/v1/reputation-events/{event_id}", headers=headers)

    # --- Logical clock (test-driving, PlatformAdmin only) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/v1/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
