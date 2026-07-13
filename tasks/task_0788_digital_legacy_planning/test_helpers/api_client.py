"""API client: one method per endpoint defined in the PRD (all under /legacy)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Plan ----
    def create_plan(self, payload, headers):
        return self._request("POST", "/legacy/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/legacy/plans/{plan_id}", headers=headers)

    def get_plan_completeness(self, plan_id, headers):
        return self._request("GET", f"/legacy/plans/{plan_id}/completeness", headers=headers)

    def set_life_status(self, plan_id, payload, headers):
        return self._request("POST", f"/legacy/plans/{plan_id}/life-status", payload, headers)

    # ---- VaultItem ----
    def create_vault_item(self, payload, headers):
        return self._request("POST", "/legacy/vault-items", payload, headers)

    def list_vault_items(self, headers, params=None):
        return self._request("GET", "/legacy/vault-items", headers=headers, params=params)

    def get_vault_item(self, item_id, headers):
        return self._request("GET", f"/legacy/vault-items/{item_id}", headers=headers)

    def seal_vault_item(self, item_id, headers):
        return self._request("POST", f"/legacy/vault-items/{item_id}/seal", {}, headers)

    def recall_vault_item(self, item_id, headers):
        return self._request("POST", f"/legacy/vault-items/{item_id}/recall", {}, headers)

    def archive_vault_item(self, item_id, headers):
        return self._request("POST", f"/legacy/vault-items/{item_id}/archive", {}, headers)

    # ---- Deputy ----
    def create_deputy(self, payload, headers):
        return self._request("POST", "/legacy/deputies", payload, headers)

    def list_deputies(self, headers, params=None):
        return self._request("GET", "/legacy/deputies", headers=headers, params=params)

    def get_deputy(self, deputy_id, headers):
        return self._request("GET", f"/legacy/deputies/{deputy_id}", headers=headers)

    def accept_deputy(self, deputy_id, headers):
        return self._request("POST", f"/legacy/deputies/{deputy_id}/accept", {}, headers)

    def revoke_deputy(self, deputy_id, headers):
        return self._request("POST", f"/legacy/deputies/{deputy_id}/revoke", {}, headers)

    # ---- Beneficiary ----
    def create_beneficiary(self, payload, headers):
        return self._request("POST", "/legacy/beneficiaries", payload, headers)

    def list_beneficiaries(self, headers, params=None):
        return self._request("GET", "/legacy/beneficiaries", headers=headers, params=params)

    def get_beneficiary(self, beneficiary_id, headers):
        return self._request("GET", f"/legacy/beneficiaries/{beneficiary_id}", headers=headers)

    def remove_beneficiary(self, beneficiary_id, headers):
        return self._request("POST", f"/legacy/beneficiaries/{beneficiary_id}/remove", {}, headers)

    # ---- Directive ----
    def create_directive(self, payload, headers):
        return self._request("POST", "/legacy/directives", payload, headers)

    def list_directives(self, headers, params=None):
        return self._request("GET", "/legacy/directives", headers=headers, params=params)

    def get_directive(self, directive_id, headers):
        return self._request("GET", f"/legacy/directives/{directive_id}", headers=headers)

    def activate_directive(self, directive_id, payload, headers):
        return self._request("POST", f"/legacy/directives/{directive_id}/activate", payload, headers)

    def revise_directive(self, directive_id, headers):
        return self._request("POST", f"/legacy/directives/{directive_id}/revise", {}, headers)

    def revoke_directive(self, directive_id, headers):
        return self._request("POST", f"/legacy/directives/{directive_id}/revoke", {}, headers)

    # ---- ReleaseRequest ----
    def create_release_request(self, payload, headers):
        return self._request("POST", "/legacy/release-requests", payload, headers)

    def list_release_requests(self, headers, params=None):
        return self._request("GET", "/legacy/release-requests", headers=headers, params=params)

    def get_release_request(self, release_request_id, headers):
        return self._request("GET", f"/legacy/release-requests/{release_request_id}", headers=headers)

    def verify_release_request(self, release_request_id, headers):
        return self._request("POST", f"/legacy/release-requests/{release_request_id}/verify", {}, headers)

    def approve_release_request(self, release_request_id, payload, headers):
        return self._request("POST", f"/legacy/release-requests/{release_request_id}/approve", payload, headers)

    def deny_release_request(self, release_request_id, headers):
        return self._request("POST", f"/legacy/release-requests/{release_request_id}/deny", {}, headers)

    def grant_release_request(self, release_request_id, headers):
        return self._request("POST", f"/legacy/release-requests/{release_request_id}/grant", {}, headers)

    # ---- Subscription ----
    def create_subscription(self, payload, headers):
        return self._request("POST", "/legacy/subscriptions", payload, headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/legacy/subscriptions", headers=headers, params=params)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/legacy/subscriptions/{subscription_id}", headers=headers)

    def cancel_subscription(self, subscription_id, headers):
        return self._request("POST", f"/legacy/subscriptions/{subscription_id}/cancel", {}, headers)

    def record_payment(self, subscription_id, payload, headers):
        return self._request("POST", f"/legacy/subscriptions/{subscription_id}/record-payment", payload, headers)

    # ---- Share ----
    def create_share(self, payload, headers):
        return self._request("POST", "/legacy/shares", payload, headers)

    def list_shares(self, headers, params=None):
        return self._request("GET", "/legacy/shares", headers=headers, params=params)

    def get_share(self, share_id, headers):
        return self._request("GET", f"/legacy/shares/{share_id}", headers=headers)

    def revoke_share(self, share_id, headers):
        return self._request("POST", f"/legacy/shares/{share_id}/revoke", {}, headers)

    # ---- Integration ----
    def create_integration(self, payload, headers):
        return self._request("POST", "/legacy/integrations", payload, headers)

    def list_integrations(self, headers, params=None):
        return self._request("GET", "/legacy/integrations", headers=headers, params=params)

    def get_integration(self, integration_id, headers):
        return self._request("GET", f"/legacy/integrations/{integration_id}", headers=headers)

    def sync_integration(self, integration_id, headers):
        return self._request("POST", f"/legacy/integrations/{integration_id}/sync", {}, headers)

    # ---- ReviewReminder ----
    def create_review_reminder(self, payload, headers):
        return self._request("POST", "/legacy/review-reminders", payload, headers)

    def list_review_reminders(self, headers, params=None):
        return self._request("GET", "/legacy/review-reminders", headers=headers, params=params)

    def get_review_reminder(self, reminder_id, headers):
        return self._request("GET", f"/legacy/review-reminders/{reminder_id}", headers=headers)

    def complete_review_reminder(self, reminder_id, headers):
        return self._request("POST", f"/legacy/review-reminders/{reminder_id}/complete", {}, headers)

    # ---- Ops / test-driving ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_review_sweep(self, payload, headers):
        return self._request("POST", "/_ops/run-review-sweep", payload, headers)


api_client = ApiClient()
