"""API client: one method per endpoint defined in the wire service PRD.

All resources are mounted under the /wire prefix. Transition endpoints with no
request body send an empty JSON object so implementations parsing JSON bodies
never see a missing body.
"""
from prd_bench_local_runner.testing import GenericApiClient

_EMPTY = {}


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving) ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/wire/_clock/set_current_utc", payload, headers)

    # --- ContentPackage ---
    def create_package(self, payload, headers):
        return self._request("POST", "/wire/packages", payload, headers)

    def list_packages(self, headers, params=None):
        return self._request("GET", "/wire/packages", headers=headers, params=params)

    def get_package(self, package_id, headers):
        return self._request("GET", f"/wire/packages/{package_id}", headers=headers)

    def retire_package(self, package_id, headers):
        return self._request("POST", f"/wire/packages/{package_id}/retire", _EMPTY, headers)

    # --- SubscriberTier ---
    def create_tier(self, payload, headers):
        return self._request("POST", "/wire/tiers", payload, headers)

    def list_tiers(self, headers, params=None):
        return self._request("GET", "/wire/tiers", headers=headers, params=params)

    def get_tier(self, tier_id, headers):
        return self._request("GET", f"/wire/tiers/{tier_id}", headers=headers)

    def retire_tier(self, tier_id, headers):
        return self._request("POST", f"/wire/tiers/{tier_id}/retire", _EMPTY, headers)

    # --- Feed ---
    def create_feed(self, payload, headers):
        return self._request("POST", "/wire/feeds", payload, headers)

    def list_feeds(self, headers, params=None):
        return self._request("GET", "/wire/feeds", headers=headers, params=params)

    def get_feed(self, feed_id, headers):
        return self._request("GET", f"/wire/feeds/{feed_id}", headers=headers)

    # --- Subscriber ---
    def create_subscriber(self, payload, headers):
        return self._request("POST", "/wire/subscribers", payload, headers)

    def list_subscribers(self, headers, params=None):
        return self._request("GET", "/wire/subscribers", headers=headers, params=params)

    def get_subscriber(self, subscriber_id, headers):
        return self._request("GET", f"/wire/subscribers/{subscriber_id}", headers=headers)

    def suspend_subscriber(self, subscriber_id, headers):
        return self._request("POST", f"/wire/subscribers/{subscriber_id}/suspend", _EMPTY, headers)

    def reinstate_subscriber(self, subscriber_id, headers):
        return self._request("POST", f"/wire/subscribers/{subscriber_id}/reinstate", _EMPTY, headers)

    def give_termination_notice(self, subscriber_id, headers):
        return self._request(
            "POST", f"/wire/subscribers/{subscriber_id}/give-termination-notice", _EMPTY, headers
        )

    def terminate_subscriber(self, subscriber_id, headers):
        return self._request("POST", f"/wire/subscribers/{subscriber_id}/terminate", _EMPTY, headers)

    # --- Subscription ---
    def create_subscription(self, subscriber_id, payload, headers):
        return self._request("POST", f"/wire/subscribers/{subscriber_id}/subscriptions", payload, headers)

    def list_subscriber_subscriptions(self, subscriber_id, headers, params=None):
        return self._request(
            "GET", f"/wire/subscribers/{subscriber_id}/subscriptions", headers=headers, params=params
        )

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/wire/subscriptions", headers=headers, params=params)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/wire/subscriptions/{subscription_id}", headers=headers)

    def activate_subscription(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/wire/subscriptions/{subscription_id}/activate", payload, headers
        )

    def suspend_subscription(self, subscription_id, headers):
        return self._request("POST", f"/wire/subscriptions/{subscription_id}/suspend", _EMPTY, headers)

    def reinstate_subscription(self, subscription_id, headers):
        return self._request("POST", f"/wire/subscriptions/{subscription_id}/reinstate", _EMPTY, headers)

    def cancel_subscription(self, subscription_id, headers):
        return self._request("POST", f"/wire/subscriptions/{subscription_id}/cancel", _EMPTY, headers)

    def renew_subscription(self, subscription_id, headers):
        return self._request("POST", f"/wire/subscriptions/{subscription_id}/renew", _EMPTY, headers)

    def send_renewal_notice(self, subscription_id, headers):
        return self._request(
            "POST", f"/wire/subscriptions/{subscription_id}/send-renewal-notice", _EMPTY, headers
        )

    # --- Entitlement ---
    def create_entitlement(self, subscription_id, payload, headers):
        return self._request("POST", f"/wire/subscriptions/{subscription_id}/entitlements", payload, headers)

    def list_subscription_entitlements(self, subscription_id, headers, params=None):
        return self._request(
            "GET", f"/wire/subscriptions/{subscription_id}/entitlements", headers=headers, params=params
        )

    def list_entitlements(self, headers, params=None):
        return self._request("GET", "/wire/entitlements", headers=headers, params=params)

    def get_entitlement(self, entitlement_id, headers):
        return self._request("GET", f"/wire/entitlements/{entitlement_id}", headers=headers)

    def revoke_entitlement(self, entitlement_id, headers):
        return self._request("POST", f"/wire/entitlements/{entitlement_id}/revoke", _EMPTY, headers)

    # --- Article ---
    def create_article(self, payload, headers):
        return self._request("POST", "/wire/articles", payload, headers)

    def list_articles(self, headers, params=None):
        return self._request("GET", "/wire/articles", headers=headers, params=params)

    def get_article(self, article_id, headers):
        return self._request("GET", f"/wire/articles/{article_id}", headers=headers)

    def publish_article(self, article_id, headers):
        return self._request("POST", f"/wire/articles/{article_id}/publish", _EMPTY, headers)

    def extend_embargo(self, article_id, payload, headers):
        return self._request("POST", f"/wire/articles/{article_id}/embargo", payload, headers)

    def lift_embargo(self, article_id, headers):
        return self._request("POST", f"/wire/articles/{article_id}/lift-embargo", _EMPTY, headers)

    def withdraw_article(self, article_id, headers):
        return self._request("POST", f"/wire/articles/{article_id}/withdraw", _EMPTY, headers)

    def republish_article(self, article_id, payload, headers):
        return self._request("POST", f"/wire/articles/{article_id}/republish", payload, headers)

    def takedown_article(self, article_id, headers):
        return self._request("POST", f"/wire/articles/{article_id}/takedown", _EMPTY, headers)

    # --- Asset ---
    def create_asset(self, article_id, payload, headers):
        return self._request("POST", f"/wire/articles/{article_id}/assets", payload, headers)

    def list_article_assets(self, article_id, headers, params=None):
        return self._request(
            "GET", f"/wire/articles/{article_id}/assets", headers=headers, params=params
        )

    def list_assets(self, headers, params=None):
        return self._request("GET", "/wire/assets", headers=headers, params=params)

    # --- Publication (republication event) ---
    def create_publication(self, payload, headers):
        return self._request("POST", "/wire/publications", payload, headers)

    def list_publications(self, headers, params=None):
        return self._request("GET", "/wire/publications", headers=headers, params=params)

    def get_publication(self, publication_id, headers):
        return self._request("GET", f"/wire/publications/{publication_id}", headers=headers)

    def flag_publication(self, publication_id, headers):
        return self._request("POST", f"/wire/publications/{publication_id}/flag", _EMPTY, headers)

    def dismiss_publication(self, publication_id, headers):
        return self._request("POST", f"/wire/publications/{publication_id}/dismiss", _EMPTY, headers)

    # --- Invoice ---
    def create_invoice(self, subscription_id, payload, headers):
        return self._request("POST", f"/wire/subscriptions/{subscription_id}/invoices", payload, headers)

    def list_subscription_invoices(self, subscription_id, headers, params=None):
        return self._request(
            "GET", f"/wire/subscriptions/{subscription_id}/invoices", headers=headers, params=params
        )

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/wire/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/wire/invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/wire/invoices/{invoice_id}/issue", _EMPTY, headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/wire/invoices/{invoice_id}/pay", _EMPTY, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/wire/invoices/{invoice_id}/void", _EMPTY, headers)


api_client = ApiClient()
