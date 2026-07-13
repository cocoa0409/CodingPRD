"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base `_request()` handles the
HTTP call, response envelope, and auth headers. All paths are mounted under the
`/v1` prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Platform / utilities ------------------------------------------
    def create_plan_catalog(self, payload, headers):
        return self._request("POST", "/v1/plan-catalog", payload, headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/v1/_clock/set_current_utc", payload, headers)

    def simulate_payment(self, payload, headers):
        return self._request("POST", "/v1/_payments/simulate", payload, headers)

    # --- Members --------------------------------------------------------
    def create_member(self, payload, headers=None):
        return self._request("POST", "/v1/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/v1/members/{member_id}", headers=headers)

    def list_member_subscriptions(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/v1/members/{member_id}/subscriptions", headers=headers, params=params
        )

    # --- Subscriptions --------------------------------------------------
    def create_subscription(self, payload, headers):
        return self._request("POST", "/v1/subscriptions", payload, headers)

    def get_subscription(self, sub_id, headers):
        return self._request("GET", f"/v1/subscriptions/{sub_id}", headers=headers)

    def change_plan(self, sub_id, payload, headers):
        return self._request("POST", f"/v1/subscriptions/{sub_id}/change-plan", payload, headers)

    def cancel_subscription(self, sub_id, headers):
        return self._request("POST", f"/v1/subscriptions/{sub_id}/cancel", None, headers)

    def renew_subscription(self, sub_id, headers):
        return self._request("POST", f"/v1/subscriptions/{sub_id}/renew", None, headers)

    def list_subscription_questionnaires(self, sub_id, headers, params=None):
        return self._request(
            "GET", f"/v1/subscriptions/{sub_id}/questionnaires", headers=headers, params=params
        )

    def list_subscription_documents(self, sub_id, headers, params=None):
        return self._request(
            "GET", f"/v1/subscriptions/{sub_id}/documents", headers=headers, params=params
        )

    def list_subscription_beneficiaries(self, sub_id, headers, params=None):
        return self._request(
            "GET", f"/v1/subscriptions/{sub_id}/beneficiaries", headers=headers, params=params
        )

    def list_subscription_assets(self, sub_id, headers, params=None):
        return self._request(
            "GET", f"/v1/subscriptions/{sub_id}/assets", headers=headers, params=params
        )

    def list_subscription_executors(self, sub_id, headers, params=None):
        return self._request(
            "GET", f"/v1/subscriptions/{sub_id}/executors", headers=headers, params=params
        )

    def get_estate_summary(self, sub_id, headers):
        return self._request("GET", f"/v1/subscriptions/{sub_id}/estate-summary", headers=headers)

    # --- Questionnaires -------------------------------------------------
    def create_questionnaire(self, payload, headers):
        return self._request("POST", "/v1/questionnaires", payload, headers)

    def get_questionnaire(self, q_id, headers):
        return self._request("GET", f"/v1/questionnaires/{q_id}", headers=headers)

    def submit_answers(self, q_id, payload, headers):
        return self._request("POST", f"/v1/questionnaires/{q_id}/answers", payload, headers)

    def list_questionnaire_documents(self, q_id, headers, params=None):
        return self._request(
            "GET", f"/v1/questionnaires/{q_id}/documents", headers=headers, params=params
        )

    # --- Documents ------------------------------------------------------
    def create_document(self, payload, headers):
        return self._request("POST", "/v1/documents", payload, headers)

    def get_document(self, doc_id, headers):
        return self._request("GET", f"/v1/documents/{doc_id}", headers=headers)

    def submit_review(self, doc_id, headers):
        return self._request("POST", f"/v1/documents/{doc_id}/submit-review", None, headers)

    def execute_document(self, doc_id, payload, headers):
        return self._request("POST", f"/v1/documents/{doc_id}/execute", payload, headers)

    def list_document_share_grants(self, doc_id, headers, params=None):
        return self._request(
            "GET", f"/v1/documents/{doc_id}/share-grants", headers=headers, params=params
        )

    def list_document_attorney_reviews(self, doc_id, headers, params=None):
        return self._request(
            "GET", f"/v1/documents/{doc_id}/attorney-reviews", headers=headers, params=params
        )

    # --- Attorney reviews -----------------------------------------------
    def review_decision(self, review_id, payload, headers):
        return self._request("POST", f"/v1/attorney-reviews/{review_id}/decision", payload, headers)

    # --- Beneficiaries --------------------------------------------------
    def create_beneficiary(self, payload, headers):
        return self._request("POST", "/v1/beneficiaries", payload, headers)

    def get_beneficiary(self, ben_id, headers):
        return self._request("GET", f"/v1/beneficiaries/{ben_id}", headers=headers)

    def list_beneficiary_assets(self, ben_id, headers, params=None):
        return self._request(
            "GET", f"/v1/beneficiaries/{ben_id}/assets", headers=headers, params=params
        )

    # --- Assets ---------------------------------------------------------
    def create_asset(self, payload, headers):
        return self._request("POST", "/v1/assets", payload, headers)

    def assign_beneficiary(self, asset_id, payload, headers):
        return self._request("POST", f"/v1/assets/{asset_id}/assign-beneficiary", payload, headers)

    # --- Executors ------------------------------------------------------
    def create_executor(self, payload, headers):
        return self._request("POST", "/v1/executors", payload, headers)

    def respond_executor(self, ex_id, payload, headers):
        return self._request("POST", f"/v1/executors/{ex_id}/respond", payload, headers)

    # --- Share grants ---------------------------------------------------
    def create_share_grant(self, payload, headers):
        return self._request("POST", "/v1/share-grants", payload, headers)

    def revoke_share_grant(self, grant_id, headers):
        return self._request("POST", f"/v1/share-grants/{grant_id}/revoke", None, headers)


api_client = ApiClient()
