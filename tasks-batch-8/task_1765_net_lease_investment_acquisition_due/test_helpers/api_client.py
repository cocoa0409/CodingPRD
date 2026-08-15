"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Deals
    # ------------------------------------------------------------------
    def create_deal(self, payload, headers):
        return self._request("POST", "/acquisition-deals/deals", payload, headers)

    def list_deals(self, headers, params=None):
        return self._request("GET", "/acquisition-deals/deals",
                             headers=headers, params=params)

    def get_deal(self, deal_id, headers):
        return self._request("GET", f"/acquisition-deals/deals/{deal_id}",
                             headers=headers)

    def submit_for_psa(self, deal_id, headers):
        return self._request("POST",
                             f"/acquisition-deals/deals/{deal_id}/submit-for-psa",
                             {}, headers)

    def certify_clear_to_close(self, deal_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/certify-clear-to-close",
            {}, headers)

    def close_deal(self, deal_id, headers):
        return self._request("POST", f"/acquisition-deals/deals/{deal_id}/close",
                             {}, headers)

    def terminate_deal(self, deal_id, termination_reason, headers):
        return self._request("POST",
                             f"/acquisition-deals/deals/{deal_id}/terminate",
                             {"termination_reason": termination_reason}, headers)

    # ------------------------------------------------------------------
    # Tenants
    # ------------------------------------------------------------------
    def create_tenant(self, payload, headers):
        return self._request("POST", "/tenants", payload, headers)

    def list_tenants(self, headers, params=None):
        return self._request("GET", "/tenants", headers=headers, params=params)

    def get_tenant(self, tenant_id, headers):
        return self._request("GET", f"/tenants/{tenant_id}", headers=headers)

    def analyze_credit(self, tenant_id, headers):
        return self._request("POST", f"/tenants/{tenant_id}/analyze-credit",
                             {}, headers)

    def approve_credit(self, tenant_id, headers):
        return self._request("POST", f"/tenants/{tenant_id}/approve-credit",
                             {}, headers)

    def reject_credit(self, tenant_id, headers):
        return self._request("POST", f"/tenants/{tenant_id}/reject-credit",
                             {}, headers)

    # ------------------------------------------------------------------
    # Properties (nested + flat)
    # ------------------------------------------------------------------
    def create_property(self, deal_id, payload, headers):
        return self._request("POST",
                             f"/acquisition-deals/deals/{deal_id}/properties",
                             payload, headers)

    def list_properties(self, deal_id, headers, params=None):
        return self._request("GET",
                             f"/acquisition-deals/deals/{deal_id}/properties",
                             headers=headers, params=params)

    def get_property(self, deal_id, property_id, headers):
        return self._request(
            "GET",
            f"/acquisition-deals/deals/{deal_id}/properties/{property_id}",
            headers=headers)

    def mark_property_surveyed(self, deal_id, property_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/properties/{property_id}/mark-surveyed",
            {}, headers)

    def clear_property(self, deal_id, property_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/properties/{property_id}/clear",
            {}, headers)

    def flag_property(self, deal_id, property_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/properties/{property_id}/flag",
            {}, headers)

    def get_property_flat(self, property_id, headers):
        return self._request("GET",
                             f"/acquisition-deals/properties/{property_id}",
                             headers=headers)

    def list_properties_flat(self, headers, params=None):
        return self._request("GET", "/acquisition-deals/properties",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Leases (nested + flat)
    # ------------------------------------------------------------------
    def create_lease(self, deal_id, property_id, payload, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/properties/{property_id}/leases",
            payload, headers)

    def list_leases(self, deal_id, property_id, headers, params=None):
        return self._request(
            "GET",
            f"/acquisition-deals/deals/{deal_id}/properties/{property_id}/leases",
            headers=headers, params=params)

    def get_lease(self, deal_id, property_id, lease_id, headers):
        return self._request(
            "GET",
            f"/acquisition-deals/deals/{deal_id}/properties/{property_id}/leases/{lease_id}",
            headers=headers)

    def verify_lease(self, deal_id, property_id, lease_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/properties/{property_id}/leases/{lease_id}/verify",
            {}, headers)

    def get_lease_flat(self, lease_id, headers):
        return self._request("GET", f"/acquisition-deals/leases/{lease_id}",
                             headers=headers)

    def list_leases_flat(self, headers, params=None):
        return self._request("GET", "/acquisition-deals/leases",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Underwriting models (nested + flat)
    # ------------------------------------------------------------------
    def create_underwriting_model(self, deal_id, payload, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/underwriting-models",
            payload, headers)

    def list_underwriting_models(self, deal_id, headers, params=None):
        return self._request(
            "GET",
            f"/acquisition-deals/deals/{deal_id}/underwriting-models",
            headers=headers, params=params)

    def get_underwriting_model(self, deal_id, model_id, headers):
        return self._request(
            "GET",
            f"/acquisition-deals/deals/{deal_id}/underwriting-models/{model_id}",
            headers=headers)

    def submit_underwriting_model(self, deal_id, model_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/underwriting-models/{model_id}/submit",
            {}, headers)

    def approve_underwriting_model(self, deal_id, model_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/underwriting-models/{model_id}/approve",
            {}, headers)

    def reject_underwriting_model(self, deal_id, model_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/underwriting-models/{model_id}/reject",
            {}, headers)

    def get_underwriting_model_flat(self, model_id, headers):
        return self._request(
            "GET", f"/acquisition-deals/underwriting-models/{model_id}",
            headers=headers)

    def list_underwriting_models_flat(self, headers, params=None):
        return self._request("GET", "/acquisition-deals/underwriting-models",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Purchase agreements
    # ------------------------------------------------------------------
    def create_purchase_agreement(self, deal_id, payload, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/purchase-agreements",
            payload, headers)

    def list_purchase_agreements(self, deal_id, headers, params=None):
        return self._request(
            "GET",
            f"/acquisition-deals/deals/{deal_id}/purchase-agreements",
            headers=headers, params=params)

    def get_purchase_agreement(self, deal_id, psa_id, headers):
        return self._request(
            "GET",
            f"/acquisition-deals/deals/{deal_id}/purchase-agreements/{psa_id}",
            headers=headers)

    def execute_purchase_agreement(self, deal_id, psa_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/purchase-agreements/{psa_id}/execute",
            {}, headers)

    def amend_purchase_agreement(self, deal_id, psa_id, payload, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/purchase-agreements/{psa_id}/amend",
            payload, headers)

    # ------------------------------------------------------------------
    # Diligence milestones
    # ------------------------------------------------------------------
    def list_milestones(self, deal_id, headers, params=None):
        return self._request("GET",
                             f"/acquisition-deals/deals/{deal_id}/milestones",
                             headers=headers, params=params)

    def get_milestone(self, deal_id, milestone_id, headers):
        return self._request(
            "GET",
            f"/acquisition-deals/deals/{deal_id}/milestones/{milestone_id}",
            headers=headers)

    def start_milestone(self, deal_id, milestone_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/milestones/{milestone_id}/start",
            {}, headers)

    def complete_milestone(self, deal_id, milestone_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/milestones/{milestone_id}/complete",
            {}, headers)

    def waive_milestone(self, deal_id, milestone_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/milestones/{milestone_id}/waive",
            {}, headers)

    # ------------------------------------------------------------------
    # Title reviews (nested + flat)
    # ------------------------------------------------------------------
    def create_title_review(self, deal_id, payload, headers):
        return self._request("POST",
                             f"/acquisition-deals/deals/{deal_id}/title-reviews",
                             payload, headers)

    def list_title_reviews(self, deal_id, headers, params=None):
        return self._request("GET",
                             f"/acquisition-deals/deals/{deal_id}/title-reviews",
                             headers=headers, params=params)

    def get_title_review(self, deal_id, review_id, headers):
        return self._request(
            "GET",
            f"/acquisition-deals/deals/{deal_id}/title-reviews/{review_id}",
            headers=headers)

    def begin_title_review(self, deal_id, review_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/title-reviews/{review_id}/begin-review",
            {}, headers)

    def clear_title_review(self, deal_id, review_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/title-reviews/{review_id}/clear",
            {}, headers)

    def reject_title_review(self, deal_id, review_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/title-reviews/{review_id}/reject",
            {}, headers)

    def get_title_review_flat(self, review_id, headers):
        return self._request("GET",
                             f"/acquisition-deals/title-reviews/{review_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Title exceptions (nested + flat)
    # ------------------------------------------------------------------
    def create_title_exception(self, deal_id, review_id, payload, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/title-reviews/{review_id}/exceptions",
            payload, headers)

    def list_title_exceptions(self, deal_id, review_id, headers, params=None):
        return self._request(
            "GET",
            f"/acquisition-deals/deals/{deal_id}/title-reviews/{review_id}/exceptions",
            headers=headers, params=params)

    def get_title_exception(self, deal_id, review_id, exception_id, headers):
        return self._request(
            "GET",
            f"/acquisition-deals/deals/{deal_id}/title-reviews/{review_id}/exceptions/{exception_id}",
            headers=headers)

    def propose_cure(self, deal_id, review_id, exception_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/title-reviews/{review_id}/exceptions/{exception_id}/propose-cure",
            {}, headers)

    def confirm_cure(self, deal_id, review_id, exception_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/title-reviews/{review_id}/exceptions/{exception_id}/confirm-cure",
            {}, headers)

    def waive_exception(self, deal_id, review_id, exception_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/title-reviews/{review_id}/exceptions/{exception_id}/waive",
            {}, headers)

    def get_title_exception_flat(self, exception_id, headers):
        return self._request(
            "GET", f"/acquisition-deals/title-exceptions/{exception_id}",
            headers=headers)

    def list_title_exceptions_flat(self, headers, params=None):
        return self._request("GET", "/acquisition-deals/title-exceptions",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Environmental assessments
    # ------------------------------------------------------------------
    def create_environmental_assessment(self, deal_id, payload, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/environmental-assessments",
            payload, headers)

    def list_environmental_assessments(self, deal_id, headers, params=None):
        return self._request(
            "GET",
            f"/acquisition-deals/deals/{deal_id}/environmental-assessments",
            headers=headers, params=params)

    def get_environmental_assessment(self, deal_id, ea_id, headers):
        return self._request(
            "GET",
            f"/acquisition-deals/deals/{deal_id}/environmental-assessments/{ea_id}",
            headers=headers)

    def receive_environmental_assessment(self, deal_id, ea_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/environmental-assessments/{ea_id}/receive",
            {}, headers)

    def clear_environmental_assessment(self, deal_id, ea_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/environmental-assessments/{ea_id}/clear",
            {}, headers)

    def mark_environmental_conditional(self, deal_id, ea_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/environmental-assessments/{ea_id}/mark-conditional",
            {}, headers)

    def fail_environmental_assessment(self, deal_id, ea_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/environmental-assessments/{ea_id}/fail",
            {}, headers)

    # ------------------------------------------------------------------
    # Property condition assessments
    # ------------------------------------------------------------------
    def create_pca(self, deal_id, payload, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/property-condition-assessments",
            payload, headers)

    def list_pcas(self, deal_id, headers, params=None):
        return self._request(
            "GET",
            f"/acquisition-deals/deals/{deal_id}/property-condition-assessments",
            headers=headers, params=params)

    def get_pca(self, deal_id, pca_id, headers):
        return self._request(
            "GET",
            f"/acquisition-deals/deals/{deal_id}/property-condition-assessments/{pca_id}",
            headers=headers)

    def receive_pca(self, deal_id, pca_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/property-condition-assessments/{pca_id}/receive",
            {}, headers)

    def accept_pca(self, deal_id, pca_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/property-condition-assessments/{pca_id}/accept",
            {}, headers)

    def reject_pca(self, deal_id, pca_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/property-condition-assessments/{pca_id}/reject",
            {}, headers)

    # ------------------------------------------------------------------
    # Estoppel certificates (nested + flat)
    # ------------------------------------------------------------------
    def create_estoppel(self, deal_id, payload, headers):
        return self._request("POST",
                             f"/acquisition-deals/deals/{deal_id}/estoppels",
                             payload, headers)

    def list_estoppels(self, deal_id, headers, params=None):
        return self._request("GET",
                             f"/acquisition-deals/deals/{deal_id}/estoppels",
                             headers=headers, params=params)

    def get_estoppel(self, deal_id, estoppel_id, headers):
        return self._request(
            "GET",
            f"/acquisition-deals/deals/{deal_id}/estoppels/{estoppel_id}",
            headers=headers)

    def receive_estoppel(self, deal_id, estoppel_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/estoppels/{estoppel_id}/receive",
            {}, headers)

    def certify_estoppel(self, deal_id, estoppel_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/estoppels/{estoppel_id}/certify",
            {}, headers)

    def get_estoppel_flat(self, estoppel_id, headers):
        return self._request("GET",
                             f"/acquisition-deals/estoppels/{estoppel_id}",
                             headers=headers)

    def list_estoppels_flat(self, headers, params=None):
        return self._request("GET", "/acquisition-deals/estoppels",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # SNDAs (nested + flat)
    # ------------------------------------------------------------------
    def create_snda(self, deal_id, payload, headers):
        return self._request("POST", f"/acquisition-deals/deals/{deal_id}/sndas",
                             payload, headers)

    def list_sndas(self, deal_id, headers, params=None):
        return self._request("GET",
                             f"/acquisition-deals/deals/{deal_id}/sndas",
                             headers=headers, params=params)

    def get_snda(self, deal_id, snda_id, headers):
        return self._request(
            "GET", f"/acquisition-deals/deals/{deal_id}/sndas/{snda_id}",
            headers=headers)

    def receive_snda(self, deal_id, snda_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/sndas/{snda_id}/receive",
            {}, headers)

    def certify_snda(self, deal_id, snda_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/sndas/{snda_id}/certify",
            {}, headers)

    def reject_snda(self, deal_id, snda_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/sndas/{snda_id}/reject",
            {}, headers)

    def get_snda_flat(self, snda_id, headers):
        return self._request("GET", f"/acquisition-deals/sndas/{snda_id}",
                             headers=headers)

    def list_sndas_flat(self, headers, params=None):
        return self._request("GET", "/acquisition-deals/sndas",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Financing applications
    # ------------------------------------------------------------------
    def create_financing_application(self, deal_id, payload, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/financing-applications",
            payload, headers)

    def list_financing_applications(self, deal_id, headers, params=None):
        return self._request(
            "GET",
            f"/acquisition-deals/deals/{deal_id}/financing-applications",
            headers=headers, params=params)

    def get_financing_application(self, deal_id, app_id, headers):
        return self._request(
            "GET",
            f"/acquisition-deals/deals/{deal_id}/financing-applications/{app_id}",
            headers=headers)

    def submit_financing_application(self, deal_id, app_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/financing-applications/{app_id}/submit",
            {}, headers)

    def commit_financing_application(self, deal_id, app_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/financing-applications/{app_id}/commit",
            {}, headers)

    def decline_financing_application(self, deal_id, app_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/financing-applications/{app_id}/decline",
            {}, headers)

    def withdraw_financing_application(self, deal_id, app_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/financing-applications/{app_id}/withdraw",
            {}, headers)

    # ------------------------------------------------------------------
    # Closing statements (nested + flat)
    # ------------------------------------------------------------------
    def list_closing_statements(self, deal_id, headers, params=None):
        return self._request(
            "GET",
            f"/acquisition-deals/deals/{deal_id}/closing-statements",
            headers=headers, params=params)

    def get_closing_statement(self, deal_id, stmt_id, headers):
        return self._request(
            "GET",
            f"/acquisition-deals/deals/{deal_id}/closing-statements/{stmt_id}",
            headers=headers)

    def issue_closing_statement(self, deal_id, stmt_id, payload, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/closing-statements/{stmt_id}/issue",
            payload, headers)

    def acknowledge_closing_statement(self, deal_id, stmt_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/closing-statements/{stmt_id}/acknowledge",
            {}, headers)

    def reissue_closing_statement(self, deal_id, stmt_id, payload, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/closing-statements/{stmt_id}/reissue",
            payload, headers)

    def finalize_true_up(self, deal_id, stmt_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/closing-statements/{stmt_id}/finalize-true-up",
            {}, headers)

    def get_closing_statement_flat(self, stmt_id, headers):
        return self._request(
            "GET", f"/acquisition-deals/closing-statements/{stmt_id}",
            headers=headers)

    def list_closing_statements_flat(self, headers, params=None):
        return self._request("GET", "/acquisition-deals/closing-statements",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Proration lines (read-only; nested + flat)
    # ------------------------------------------------------------------
    def list_prorations(self, deal_id, stmt_id, headers, params=None):
        return self._request(
            "GET",
            f"/acquisition-deals/deals/{deal_id}/closing-statements/{stmt_id}/prorations",
            headers=headers, params=params)

    def get_proration(self, deal_id, stmt_id, proration_id, headers):
        return self._request(
            "GET",
            f"/acquisition-deals/deals/{deal_id}/closing-statements/{stmt_id}/prorations/{proration_id}",
            headers=headers)

    def get_proration_flat(self, proration_id, headers):
        return self._request("GET",
                             f"/acquisition-deals/prorations/{proration_id}",
                             headers=headers)

    def list_prorations_flat(self, headers, params=None):
        return self._request("GET", "/acquisition-deals/prorations",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # True-up adjustments (nested + flat)
    # ------------------------------------------------------------------
    def create_true_up(self, deal_id, stmt_id, payload, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/closing-statements/{stmt_id}/true-ups",
            payload, headers)

    def list_true_ups(self, deal_id, stmt_id, headers, params=None):
        return self._request(
            "GET",
            f"/acquisition-deals/deals/{deal_id}/closing-statements/{stmt_id}/true-ups",
            headers=headers, params=params)

    def get_true_up(self, deal_id, stmt_id, adj_id, headers):
        return self._request(
            "GET",
            f"/acquisition-deals/deals/{deal_id}/closing-statements/{stmt_id}/true-ups/{adj_id}",
            headers=headers)

    def escrow_approve_true_up(self, deal_id, stmt_id, adj_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/closing-statements/{stmt_id}/true-ups/{adj_id}/escrow-approve",
            {}, headers)

    def asset_manager_approve_true_up(self, deal_id, stmt_id, adj_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/closing-statements/{stmt_id}/true-ups/{adj_id}/asset-manager-approve",
            {}, headers)

    def reject_true_up(self, deal_id, stmt_id, adj_id, headers):
        return self._request(
            "POST",
            f"/acquisition-deals/deals/{deal_id}/closing-statements/{stmt_id}/true-ups/{adj_id}/reject",
            {}, headers)

    def get_true_up_flat(self, adj_id, headers):
        return self._request(
            "GET", f"/acquisition-deals/true-up-adjustments/{adj_id}",
            headers=headers)

    def list_true_ups_flat(self, headers, params=None):
        return self._request("GET", "/acquisition-deals/true-up-adjustments",
                             headers=headers, params=params)


api_client = ApiClient()

# Per-test-server isolation SIGKILLs and respawns the API server before every
# test. A pooled keep-alive connection from the previous test can then be
# reused before the kernel delivers the old server's RST/FIN, surfacing as
# intermittent "Remote end closed connection without response" /
# "Connection reset by peer" failures on a test's first request. Sending
# Connection: close makes every request open a fresh TCP connection, so no
# request can ever ride a connection orphaned by a server restart. This is
# transport-level only and does not change any request semantics.
api_client.session.headers["Connection"] = "close"
