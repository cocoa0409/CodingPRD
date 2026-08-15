"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock (PRD §2.4) ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Publications ---
    def create_publication(self, payload, headers):
        return self._request("POST", "/publications", payload, headers)

    def list_publications(self, headers, params=None):
        return self._request("GET", "/publications", headers=headers, params=params)

    def get_publication(self, publication_id, headers):
        return self._request("GET", f"/publications/{publication_id}", headers=headers)

    def suspend_publication(self, publication_id, headers):
        return self._request("POST", f"/publications/{publication_id}/suspend", {}, headers)

    def resume_publication(self, publication_id, headers):
        return self._request("POST", f"/publications/{publication_id}/resume", {}, headers)

    def cease_publication(self, publication_id, headers):
        return self._request("POST", f"/publications/{publication_id}/cease", {}, headers)

    # --- Issues ---
    def create_issue(self, publication_id, payload, headers):
        return self._request("POST", f"/publications/{publication_id}/issues", payload, headers)

    def list_issues(self, publication_id, headers, params=None):
        return self._request("GET", f"/publications/{publication_id}/issues", headers=headers, params=params)

    def get_issue(self, publication_id, issue_id, headers):
        return self._request("GET", f"/publications/{publication_id}/issues/{issue_id}", headers=headers)

    def get_issue_flat(self, issue_id, headers):
        return self._request("GET", f"/issues/{issue_id}", headers=headers)

    def close_editorial(self, publication_id, issue_id, headers):
        return self._request("POST", f"/publications/{publication_id}/issues/{issue_id}/close-editorial", {}, headers)

    def close_ads(self, publication_id, issue_id, payload, headers):
        return self._request("POST", f"/publications/{publication_id}/issues/{issue_id}/close-ads", payload, headers)

    def reopen_ads(self, publication_id, issue_id, headers):
        return self._request("POST", f"/publications/{publication_id}/issues/{issue_id}/reopen-ads", {}, headers)

    def ship_to_printer(self, publication_id, issue_id, headers):
        return self._request("POST", f"/publications/{publication_id}/issues/{issue_id}/ship-to-printer", {}, headers)

    def mark_mailed(self, publication_id, issue_id, headers):
        return self._request("POST", f"/publications/{publication_id}/issues/{issue_id}/mark-mailed", {}, headers)

    def finalize_issue(self, publication_id, issue_id, headers):
        return self._request("POST", f"/publications/{publication_id}/issues/{issue_id}/finalize", {}, headers)

    # --- Subscribers ---
    def create_subscriber(self, payload, headers):
        return self._request("POST", "/subscribers", payload, headers)

    def list_subscribers(self, headers, params=None):
        return self._request("GET", "/subscribers", headers=headers, params=params)

    def get_subscriber(self, subscriber_id, headers):
        return self._request("GET", f"/subscribers/{subscriber_id}", headers=headers)

    def update_subscriber(self, subscriber_id, payload, headers):
        return self._request("PATCH", f"/subscribers/{subscriber_id}", payload, headers)

    # --- Subscriptions ---
    def create_subscription(self, publication_id, subscriber_id, payload, headers):
        return self._request(
            "POST",
            f"/publications/{publication_id}/subscribers/{subscriber_id}/subscriptions",
            payload,
            headers,
        )

    def list_subscriptions(self, publication_id, headers, params=None):
        return self._request("GET", f"/publications/{publication_id}/subscriptions", headers=headers, params=params)

    def get_subscription(self, publication_id, subscription_id, headers):
        return self._request(
            "GET", f"/publications/{publication_id}/subscriptions/{subscription_id}", headers=headers
        )

    def get_subscription_flat(self, subscription_id, headers):
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def list_subscriber_subscriptions(self, subscriber_id, headers, params=None):
        return self._request("GET", f"/subscribers/{subscriber_id}/subscriptions", headers=headers, params=params)

    def activate_subscription(self, publication_id, subscription_id, headers):
        return self._request(
            "POST", f"/publications/{publication_id}/subscriptions/{subscription_id}/activate", {}, headers
        )

    def suspend_subscription(self, publication_id, subscription_id, headers):
        return self._request(
            "POST", f"/publications/{publication_id}/subscriptions/{subscription_id}/suspend", {}, headers
        )

    def resume_subscription(self, publication_id, subscription_id, headers):
        return self._request(
            "POST", f"/publications/{publication_id}/subscriptions/{subscription_id}/resume", {}, headers
        )

    def renew_subscription(self, publication_id, subscription_id, payload, headers):
        return self._request(
            "POST", f"/publications/{publication_id}/subscriptions/{subscription_id}/renew", payload, headers
        )

    def cancel_subscription(self, publication_id, subscription_id, headers):
        return self._request(
            "POST", f"/publications/{publication_id}/subscriptions/{subscription_id}/cancel", {}, headers
        )

    # --- SubscriptionTerms (read-only views) ---
    def list_subscription_terms(self, publication_id, subscription_id, headers, params=None):
        return self._request(
            "GET", f"/publications/{publication_id}/subscriptions/{subscription_id}/terms",
            headers=headers, params=params,
        )

    def get_subscription_term(self, publication_id, subscription_id, term_id, headers):
        return self._request(
            "GET",
            f"/publications/{publication_id}/subscriptions/{subscription_id}/terms/{term_id}",
            headers=headers,
        )

    def get_subscription_term_flat(self, term_id, headers):
        return self._request("GET", f"/subscription-terms/{term_id}", headers=headers)

    def list_term_revenue_entries(self, publication_id, subscription_id, term_id, headers, params=None):
        return self._request(
            "GET",
            f"/publications/{publication_id}/subscriptions/{subscription_id}/terms/{term_id}/revenue-entries",
            headers=headers, params=params,
        )

    def list_term_revenue_entries_flat(self, term_id, headers, params=None):
        return self._request(
            "GET", f"/subscription-terms/{term_id}/deferred-revenue-entries", headers=headers, params=params
        )

    def get_deferred_revenue_entry_flat(self, entry_id, headers):
        return self._request("GET", f"/deferred-revenue-entries/{entry_id}", headers=headers)

    # --- RenewalSeries ---
    def create_renewal_series(self, publication_id, payload, headers):
        return self._request("POST", f"/publications/{publication_id}/renewal-series", payload, headers)

    def list_renewal_series(self, publication_id, headers, params=None):
        return self._request("GET", f"/publications/{publication_id}/renewal-series", headers=headers, params=params)

    def get_renewal_series(self, publication_id, series_id, headers):
        return self._request("GET", f"/publications/{publication_id}/renewal-series/{series_id}", headers=headers)

    def get_renewal_series_flat(self, series_id, headers):
        return self._request("GET", f"/renewal-series/{series_id}", headers=headers)

    # --- RenewalEvents ---
    def list_renewal_events(self, publication_id, subscription_id, headers, params=None):
        return self._request(
            "GET",
            f"/publications/{publication_id}/subscriptions/{subscription_id}/renewal-events",
            headers=headers, params=params,
        )

    def get_renewal_event(self, publication_id, subscription_id, event_id, headers):
        return self._request(
            "GET",
            f"/publications/{publication_id}/subscriptions/{subscription_id}/renewal-events/{event_id}",
            headers=headers,
        )

    def get_renewal_event_flat(self, event_id, headers):
        return self._request("GET", f"/renewal-events/{event_id}", headers=headers)

    def fire_next_renewal_event(self, publication_id, subscription_id, headers):
        return self._request(
            "POST",
            f"/publications/{publication_id}/subscriptions/{subscription_id}/renewal-events/fire-next",
            {}, headers,
        )

    def decline_renewal_event(self, publication_id, subscription_id, event_id, headers):
        return self._request(
            "POST",
            f"/publications/{publication_id}/subscriptions/{subscription_id}/renewal-events/{event_id}/decline",
            {}, headers,
        )

    # --- MailingBatches ---
    def create_mailing_batch(self, publication_id, issue_id, payload, headers):
        return self._request(
            "POST", f"/publications/{publication_id}/issues/{issue_id}/mailing-batches", payload, headers
        )

    def list_mailing_batches(self, publication_id, issue_id, headers, params=None):
        return self._request(
            "GET", f"/publications/{publication_id}/issues/{issue_id}/mailing-batches",
            headers=headers, params=params,
        )

    def get_mailing_batch(self, publication_id, issue_id, batch_id, headers):
        return self._request(
            "GET",
            f"/publications/{publication_id}/issues/{issue_id}/mailing-batches/{batch_id}",
            headers=headers,
        )

    def get_mailing_batch_flat(self, batch_id, headers):
        return self._request("GET", f"/mailing-batches/{batch_id}", headers=headers)

    def generate_labels(self, publication_id, issue_id, batch_id, payload, headers):
        return self._request(
            "POST",
            f"/publications/{publication_id}/issues/{issue_id}/mailing-batches/{batch_id}/generate-labels",
            payload, headers,
        )

    def verify_postal(self, publication_id, issue_id, batch_id, headers):
        return self._request(
            "POST",
            f"/publications/{publication_id}/issues/{issue_id}/mailing-batches/{batch_id}/verify-postal",
            {}, headers,
        )

    def tender_batch(self, publication_id, issue_id, batch_id, headers):
        return self._request(
            "POST",
            f"/publications/{publication_id}/issues/{issue_id}/mailing-batches/{batch_id}/tender",
            {}, headers,
        )

    def confirm_batch(self, publication_id, issue_id, batch_id, headers):
        return self._request(
            "POST",
            f"/publications/{publication_id}/issues/{issue_id}/mailing-batches/{batch_id}/confirm",
            {}, headers,
        )

    # --- MailingLabels ---
    def list_mailing_labels(self, publication_id, issue_id, batch_id, headers, params=None):
        return self._request(
            "GET",
            f"/publications/{publication_id}/issues/{issue_id}/mailing-batches/{batch_id}/labels",
            headers=headers, params=params,
        )

    def get_mailing_label(self, publication_id, issue_id, batch_id, label_id, headers):
        return self._request(
            "GET",
            f"/publications/{publication_id}/issues/{issue_id}/mailing-batches/{batch_id}/labels/{label_id}",
            headers=headers,
        )

    def get_mailing_label_flat(self, label_id, headers):
        return self._request("GET", f"/mailing-labels/{label_id}", headers=headers)

    # --- PostalStatements ---
    def list_postal_statements(self, publication_id, issue_id, batch_id, headers, params=None):
        return self._request(
            "GET",
            f"/publications/{publication_id}/issues/{issue_id}/mailing-batches/{batch_id}/postal-statements",
            headers=headers, params=params,
        )

    def get_postal_statement_flat(self, statement_id, headers):
        return self._request("GET", f"/postal-statements/{statement_id}", headers=headers)

    # --- BackIssueOrders ---
    def create_back_issue_order(self, publication_id, subscriber_id, payload, headers):
        return self._request(
            "POST",
            f"/publications/{publication_id}/subscribers/{subscriber_id}/back-issue-orders",
            payload, headers,
        )

    def list_back_issue_orders(self, publication_id, headers, params=None):
        return self._request(
            "GET", f"/publications/{publication_id}/back-issue-orders", headers=headers, params=params
        )

    def list_subscriber_back_issue_orders(self, subscriber_id, headers, params=None):
        return self._request(
            "GET", f"/subscribers/{subscriber_id}/back-issue-orders", headers=headers, params=params
        )

    def get_back_issue_order(self, publication_id, order_id, headers):
        return self._request(
            "GET", f"/publications/{publication_id}/back-issue-orders/{order_id}", headers=headers
        )

    def get_back_issue_order_flat(self, order_id, headers):
        return self._request("GET", f"/back-issue-orders/{order_id}", headers=headers)

    def fulfill_back_issue_order(self, publication_id, order_id, headers):
        return self._request(
            "POST", f"/publications/{publication_id}/back-issue-orders/{order_id}/fulfill", {}, headers
        )

    def ship_back_issue_order(self, publication_id, order_id, headers):
        return self._request(
            "POST", f"/publications/{publication_id}/back-issue-orders/{order_id}/ship", {}, headers
        )

    def deliver_back_issue_order(self, publication_id, order_id, headers):
        return self._request(
            "POST", f"/publications/{publication_id}/back-issue-orders/{order_id}/deliver", {}, headers
        )

    def cancel_back_issue_order(self, publication_id, order_id, headers):
        return self._request(
            "POST", f"/publications/{publication_id}/back-issue-orders/{order_id}/cancel", {}, headers
        )

    def refund_back_issue_order(self, publication_id, order_id, headers):
        return self._request(
            "POST", f"/publications/{publication_id}/back-issue-orders/{order_id}/refund", {}, headers
        )

    # --- DigitalEntitlements ---
    def list_digital_entitlements(self, publication_id, subscription_id, headers, params=None):
        return self._request(
            "GET",
            f"/publications/{publication_id}/subscriptions/{subscription_id}/entitlements",
            headers=headers, params=params,
        )

    def get_digital_entitlement(self, publication_id, subscription_id, entitlement_id, headers):
        return self._request(
            "GET",
            f"/publications/{publication_id}/subscriptions/{subscription_id}/entitlements/{entitlement_id}",
            headers=headers,
        )

    def get_digital_entitlement_flat(self, entitlement_id, headers):
        return self._request("GET", f"/digital-entitlements/{entitlement_id}", headers=headers)

    def revoke_digital_entitlement(self, publication_id, subscription_id, entitlement_id, payload, headers):
        return self._request(
            "POST",
            f"/publications/{publication_id}/subscriptions/{subscription_id}/entitlements/{entitlement_id}/revoke",
            payload, headers,
        )

    # --- CirculationAuditRecords ---
    def create_circulation_audit(self, publication_id, payload, headers):
        return self._request("POST", f"/publications/{publication_id}/circulation-audits", payload, headers)

    def list_circulation_audits(self, publication_id, headers, params=None):
        return self._request(
            "GET", f"/publications/{publication_id}/circulation-audits", headers=headers, params=params
        )

    def get_circulation_audit(self, publication_id, audit_id, headers):
        return self._request(
            "GET", f"/publications/{publication_id}/circulation-audits/{audit_id}", headers=headers
        )

    def get_circulation_audit_flat(self, audit_id, headers):
        return self._request("GET", f"/circulation-audits/{audit_id}", headers=headers)

    def file_circulation_audit(self, publication_id, audit_id, headers):
        return self._request(
            "POST", f"/publications/{publication_id}/circulation-audits/{audit_id}/file", {}, headers
        )

    def pass_circulation_audit(self, publication_id, audit_id, headers):
        return self._request(
            "POST", f"/publications/{publication_id}/circulation-audits/{audit_id}/pass", {}, headers
        )

    def fail_circulation_audit(self, publication_id, audit_id, headers):
        return self._request(
            "POST", f"/publications/{publication_id}/circulation-audits/{audit_id}/fail", {}, headers
        )

    # --- Flat-alias reverse-reachability list endpoints (PRD §4) ---
    def list_issue_mailing_batches_flat(self, issue_id, headers, params=None):
        return self._request("GET", f"/issues/{issue_id}/mailing-batches", headers=headers, params=params)

    def list_issue_subscriptions(self, issue_id, headers, params=None):
        return self._request("GET", f"/issues/{issue_id}/subscriptions", headers=headers, params=params)

    def list_issue_subscription_terms(self, issue_id, headers, params=None):
        return self._request("GET", f"/issues/{issue_id}/subscription-terms", headers=headers, params=params)

    def list_issue_back_issue_orders(self, issue_id, headers, params=None):
        return self._request("GET", f"/issues/{issue_id}/back-issue-orders", headers=headers, params=params)

    def list_issue_digital_entitlements(self, issue_id, headers, params=None):
        return self._request("GET", f"/issues/{issue_id}/digital-entitlements", headers=headers, params=params)

    def list_issue_deferred_revenue_entries(self, issue_id, headers, params=None):
        return self._request(
            "GET", f"/issues/{issue_id}/deferred-revenue-entries", headers=headers, params=params
        )

    def list_subscription_terms_flat(self, subscription_id, headers, params=None):
        return self._request(
            "GET", f"/subscriptions/{subscription_id}/subscription-terms", headers=headers, params=params
        )

    def list_subscription_renewal_events_flat(self, subscription_id, headers, params=None):
        return self._request(
            "GET", f"/subscriptions/{subscription_id}/renewal-events", headers=headers, params=params
        )

    def list_subscription_digital_entitlements_flat(self, subscription_id, headers, params=None):
        return self._request(
            "GET", f"/subscriptions/{subscription_id}/digital-entitlements", headers=headers, params=params
        )

    def list_subscription_mailing_labels(self, subscription_id, headers, params=None):
        return self._request(
            "GET", f"/subscriptions/{subscription_id}/mailing-labels", headers=headers, params=params
        )

    def list_subscriber_mailing_labels(self, subscriber_id, headers, params=None):
        return self._request("GET", f"/subscribers/{subscriber_id}/mailing-labels", headers=headers, params=params)

    def list_batch_mailing_labels_flat(self, batch_id, headers, params=None):
        return self._request("GET", f"/mailing-batches/{batch_id}/mailing-labels", headers=headers, params=params)

    def list_batch_postal_statements_flat(self, batch_id, headers, params=None):
        return self._request(
            "GET", f"/mailing-batches/{batch_id}/postal-statements", headers=headers, params=params
        )


api_client = ApiClient()
