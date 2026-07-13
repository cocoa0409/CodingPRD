"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Publications ----
    def create_publication(self, payload, headers):
        return self._request("POST", "/publications", payload, headers=headers)

    def get_publication(self, pub_id, headers):
        return self._request("GET", f"/publications/{pub_id}", headers=headers)

    def suspend_publication(self, pub_id, headers):
        return self._request("POST", f"/publications/{pub_id}/suspend", headers=headers)

    def reset_deliverability(self, pub_id, headers):
        return self._request("POST", f"/publications/{pub_id}/deliverability-reset", headers=headers)

    def get_analytics(self, pub_id, headers):
        return self._request("GET", f"/publications/{pub_id}/analytics", headers=headers)

    # ---- Tiers ----
    def create_tier(self, pub_id, payload, headers):
        return self._request("POST", f"/publications/{pub_id}/tiers", payload, headers=headers)

    def list_tiers(self, pub_id, headers, params=None):
        return self._request("GET", f"/publications/{pub_id}/tiers", headers=headers, params=params)

    # ---- Members ----
    def create_member(self, pub_id, payload, headers):
        return self._request("POST", f"/publications/{pub_id}/members", payload, headers=headers)

    def list_members(self, pub_id, headers, params=None):
        return self._request("GET", f"/publications/{pub_id}/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def verify_member(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/verify", payload, headers=headers)

    # ---- Subscriptions ----
    def create_subscription(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/subscriptions", payload, headers=headers)

    def get_subscription(self, sub_id, headers):
        return self._request("GET", f"/subscriptions/{sub_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def change_tier(self, sub_id, payload, headers):
        return self._request("POST", f"/subscriptions/{sub_id}/change-tier", payload, headers=headers)

    def cancel_subscription(self, sub_id, payload, headers):
        return self._request("POST", f"/subscriptions/{sub_id}/cancel", payload, headers=headers)

    def reactivate_subscription(self, sub_id, headers):
        return self._request("POST", f"/subscriptions/{sub_id}/reactivate", headers=headers)

    def renew_subscription(self, sub_id, headers):
        return self._request("POST", f"/subscriptions/{sub_id}/renew", headers=headers)

    # ---- Invoices & payments ----
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def simulate_payment(self, payload, headers):
        return self._request("POST", "/_payments/simulate", payload, headers=headers)

    # ---- Posts / newsletters ----
    def create_post(self, pub_id, payload, headers):
        return self._request("POST", f"/publications/{pub_id}/posts", payload, headers=headers)

    def list_posts(self, pub_id, headers, params=None):
        return self._request("GET", f"/publications/{pub_id}/posts", headers=headers, params=params)

    def get_post_content(self, post_id, headers):
        return self._request("GET", f"/posts/{post_id}/content", headers=headers)

    def publish_post(self, post_id, headers):
        return self._request("POST", f"/posts/{post_id}/publish", headers=headers)

    def send_post(self, post_id, headers):
        return self._request("POST", f"/posts/{post_id}/send", headers=headers)

    # ---- Events ----
    def create_event(self, pub_id, payload, headers):
        return self._request("POST", f"/publications/{pub_id}/events", payload, headers=headers)

    def list_events(self, pub_id, headers, params=None):
        return self._request("GET", f"/publications/{pub_id}/events", headers=headers, params=params)

    def create_registration(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/registrations", payload, headers=headers)

    # ---- Registrations ----
    def get_registration(self, reg_id, headers):
        return self._request("GET", f"/registrations/{reg_id}", headers=headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/registrations", headers=headers, params=params)

    def cancel_registration(self, reg_id, headers):
        return self._request("POST", f"/registrations/{reg_id}/cancel", headers=headers)

    # ---- Comments ----
    def create_comment(self, post_id, payload, headers):
        return self._request("POST", f"/posts/{post_id}/comments", payload, headers=headers)

    def get_comment(self, comment_id, headers):
        return self._request("GET", f"/comments/{comment_id}", headers=headers)

    def list_comments(self, headers, params=None):
        return self._request("GET", "/comments", headers=headers, params=params)

    def moderate_comment(self, comment_id, payload, headers):
        return self._request("POST", f"/comments/{comment_id}/moderate", payload, headers=headers)

    # ---- Payouts ----
    def create_payout(self, pub_id, payload, headers):
        return self._request("POST", f"/publications/{pub_id}/payouts", payload, headers=headers)

    def list_payouts(self, pub_id, headers, params=None):
        return self._request("GET", f"/publications/{pub_id}/payouts", headers=headers, params=params)

    def settle_payout(self, payout_id, payload, headers):
        return self._request("POST", f"/payouts/{payout_id}/settle", payload, headers=headers)

    # ---- Test-driving ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers=headers)

    def record_bounce(self, payload, headers):
        return self._request("POST", "/_email/bounce", payload, headers=headers)


api_client = ApiClient()
