"""API client: one method per endpoint defined in the PRD (all under /legal)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Customer ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/legal/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/legal/customers/{customer_id}", headers=headers)

    # ---- SubscriptionPlan ----
    def create_subscription_plan(self, payload, headers):
        return self._request("POST", "/legal/subscription-plans", payload, headers)

    def get_subscription_plan(self, plan_id, headers):
        return self._request("GET", f"/legal/subscription-plans/{plan_id}", headers=headers)

    # ---- Subscription ----
    def create_subscription(self, payload, headers):
        return self._request("POST", "/legal/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/legal/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/legal/subscriptions", headers=headers, params=params)

    def transition_subscription(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/legal/subscriptions/{subscription_id}/transition", payload, headers
        )

    # ---- ClauseTemplate ----
    def create_clause_template(self, payload, headers):
        return self._request("POST", "/legal/clause-templates", payload, headers)

    def get_clause_template(self, template_id, headers):
        return self._request("GET", f"/legal/clause-templates/{template_id}", headers=headers)

    def list_clause_templates(self, headers, params=None):
        return self._request("GET", "/legal/clause-templates", headers=headers, params=params)

    # ---- DocumentProject ----
    def create_document_project(self, payload, headers):
        return self._request("POST", "/legal/document-projects", payload, headers)

    def get_document_project(self, project_id, headers):
        return self._request("GET", f"/legal/document-projects/{project_id}", headers=headers)

    def list_document_projects(self, headers, params=None):
        return self._request("GET", "/legal/document-projects", headers=headers, params=params)

    def upsert_questionnaire(self, project_id, payload, headers):
        return self._request(
            "PUT", f"/legal/document-projects/{project_id}/questionnaire", payload, headers
        )

    def get_questionnaire(self, project_id, headers):
        return self._request(
            "GET", f"/legal/document-projects/{project_id}/questionnaire", headers=headers
        )

    def assemble_document_project(self, project_id, headers):
        return self._request(
            "POST", f"/legal/document-projects/{project_id}/assemble", {}, headers
        )

    def transition_document_project(self, project_id, payload, headers):
        return self._request(
            "POST", f"/legal/document-projects/{project_id}/transition", payload, headers
        )

    # ---- AssembledClause ----
    def get_assembled_clause(self, clause_id, headers):
        return self._request("GET", f"/legal/assembled-clauses/{clause_id}", headers=headers)

    def list_assembled_clauses(self, headers, params=None):
        return self._request("GET", "/legal/assembled-clauses", headers=headers, params=params)

    # ---- DocumentRevision ----
    def create_document_revision(self, payload, headers):
        return self._request("POST", "/legal/document-revisions", payload, headers)

    def get_document_revision(self, revision_id, headers):
        return self._request("GET", f"/legal/document-revisions/{revision_id}", headers=headers)

    def list_document_revisions(self, headers, params=None):
        return self._request("GET", "/legal/document-revisions", headers=headers, params=params)

    # ---- Attorney ----
    def create_attorney(self, payload, headers):
        return self._request("POST", "/legal/attorneys", payload, headers)

    def get_attorney(self, attorney_id, headers):
        return self._request("GET", f"/legal/attorneys/{attorney_id}", headers=headers)

    # ---- AttorneyReview ----
    def create_attorney_review(self, payload, headers):
        return self._request("POST", "/legal/attorney-reviews", payload, headers)

    def get_attorney_review(self, review_id, headers):
        return self._request("GET", f"/legal/attorney-reviews/{review_id}", headers=headers)

    def list_attorney_reviews(self, headers, params=None):
        return self._request("GET", "/legal/attorney-reviews", headers=headers, params=params)

    def transition_attorney_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/legal/attorney-reviews/{review_id}/transition", payload, headers
        )

    # ---- SignatureRequest ----
    def create_signature_request(self, payload, headers):
        return self._request("POST", "/legal/signature-requests", payload, headers)

    def get_signature_request(self, request_id, headers):
        return self._request("GET", f"/legal/signature-requests/{request_id}", headers=headers)

    def list_signature_requests(self, headers, params=None):
        return self._request("GET", "/legal/signature-requests", headers=headers, params=params)

    def transition_signature_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/legal/signature-requests/{request_id}/transition", payload, headers
        )

    def sign_signature_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/legal/signature-requests/{request_id}/sign", payload, headers
        )

    # ---- NotaryReferral ----
    def create_notary_referral(self, payload, headers):
        return self._request("POST", "/legal/notary-referrals", payload, headers)

    def get_notary_referral(self, referral_id, headers):
        return self._request("GET", f"/legal/notary-referrals/{referral_id}", headers=headers)

    def list_notary_referrals(self, headers, params=None):
        return self._request("GET", "/legal/notary-referrals", headers=headers, params=params)

    # ---- Order ----
    def get_order(self, order_id, headers):
        return self._request("GET", f"/legal/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/legal/orders", headers=headers, params=params)

    # ---- UpdateReminder ----
    def get_update_reminder(self, reminder_id, headers):
        return self._request("GET", f"/legal/update-reminders/{reminder_id}", headers=headers)

    def list_update_reminders(self, headers, params=None):
        return self._request("GET", "/legal/update-reminders", headers=headers, params=params)

    # ---- Test-driving endpoints ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/legal/_clock/set", payload, headers)

    def dispatch_due_reminders(self, headers):
        return self._request("POST", "/legal/_reminders/dispatch_due", {}, headers)


api_client = ApiClient()
