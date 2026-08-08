"""API client: one method per endpoint in the Warranty-Claim & Recall Concierge API."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Households & Members ----
    def create_household(self, payload, headers):
        return self._request("POST", "/households", payload, headers)

    def create_member(self, household_id, payload, headers):
        return self._request("POST", f"/households/{household_id}/members", payload, headers)

    def get_household(self, household_id, headers):
        return self._request("GET", f"/households/{household_id}", headers=headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    # ---- Subscriptions ----
    def create_subscription(self, household_id, payload, headers):
        return self._request("POST", f"/households/{household_id}/subscriptions", payload, headers)

    def change_plan(self, subscription_id, payload, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/change-plan", payload, headers)

    def mark_past_due(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/mark-past-due", headers=headers)

    def reinstate_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/reinstate", headers=headers)

    def cancel_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/cancel", headers=headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    # ---- Manufacturers ----
    def create_manufacturer(self, payload, headers):
        return self._request("POST", "/manufacturers", payload, headers)

    def get_manufacturer(self, manufacturer_id, headers):
        return self._request("GET", f"/manufacturers/{manufacturer_id}", headers=headers)

    # ---- Products ----
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def archive_product(self, product_id, headers):
        return self._request("POST", f"/products/{product_id}/archive", headers=headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    # ---- Recall Notices ----
    def create_recall_notice(self, payload, headers):
        return self._request("POST", "/recall-notices", payload, headers)

    def publish_recall_notice(self, recall_notice_id, headers):
        return self._request("POST", f"/recall-notices/{recall_notice_id}/publish", headers=headers)

    def close_recall_notice(self, recall_notice_id, headers):
        return self._request("POST", f"/recall-notices/{recall_notice_id}/close", headers=headers)

    def get_recall_notice(self, recall_notice_id, headers):
        return self._request("GET", f"/recall-notices/{recall_notice_id}", headers=headers)

    def list_recall_notices(self, headers, params=None):
        return self._request("GET", "/recall-notices", headers=headers, params=params)

    # ---- Recall Matches ----
    def acknowledge_recall_match(self, recall_match_id, headers):
        return self._request("POST", f"/recall-matches/{recall_match_id}/acknowledge", headers=headers)

    def dismiss_recall_match(self, recall_match_id, headers):
        return self._request("POST", f"/recall-matches/{recall_match_id}/dismiss", headers=headers)

    def remedy_recall_match(self, recall_match_id, headers):
        return self._request("POST", f"/recall-matches/{recall_match_id}/remedy", headers=headers)

    def get_recall_match(self, recall_match_id, headers):
        return self._request("GET", f"/recall-matches/{recall_match_id}", headers=headers)

    def list_recall_matches(self, headers, params=None):
        return self._request("GET", "/recall-matches", headers=headers, params=params)

    # ---- Claims ----
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def submit_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/submit", headers=headers)

    def add_claim_document(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/documents", payload, headers)

    def review_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/review", headers=headers)

    def request_claim_docs(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/request-docs", headers=headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/approve", headers=headers)

    def reject_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/reject", headers=headers)

    def withdraw_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/withdraw", headers=headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def get_claim_document(self, doc_id, headers):
        return self._request("GET", f"/claim-documents/{doc_id}", headers=headers)

    def list_claim_documents(self, headers, params=None):
        return self._request("GET", "/claim-documents", headers=headers, params=params)

    # ---- Resolutions ----
    def request_rma(self, resolution_id, headers):
        return self._request("POST", f"/resolutions/{resolution_id}/request-rma", headers=headers)

    def authorize_rma(self, resolution_id, headers):
        return self._request("POST", f"/resolutions/{resolution_id}/authorize-rma", headers=headers)

    def dispatch_resolution(self, resolution_id, payload, headers):
        return self._request("POST", f"/resolutions/{resolution_id}/dispatch", payload, headers)

    def complete_resolution(self, resolution_id, headers):
        return self._request("POST", f"/resolutions/{resolution_id}/complete", headers=headers)

    def fail_resolution(self, resolution_id, headers):
        return self._request("POST", f"/resolutions/{resolution_id}/fail", headers=headers)

    def get_resolution(self, resolution_id, headers):
        return self._request("GET", f"/resolutions/{resolution_id}", headers=headers)

    def list_resolutions(self, headers, params=None):
        return self._request("GET", "/resolutions", headers=headers, params=params)

    # ---- Test-driving clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
