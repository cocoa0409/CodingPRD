"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock --------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/api/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- tax jurisdictions ----------------------------------------------
    def create_tax_jurisdiction(self, payload, headers):
        return self._request("POST", "/api/tax-jurisdictions", payload, headers)

    def list_tax_jurisdictions(self, headers, params=None):
        return self._request("GET", "/api/tax-jurisdictions", headers=headers, params=params)

    def get_tax_jurisdiction(self, tax_jurisdiction_id, headers):
        return self._request(
            "GET", f"/api/tax-jurisdictions/{tax_jurisdiction_id}", headers=headers
        )

    # ---- revenue share tiers --------------------------------------------
    def create_revenue_share_tier(self, payload, headers):
        return self._request("POST", "/api/revenue-share-tiers", payload, headers)

    def list_revenue_share_tiers(self, headers, params=None):
        return self._request("GET", "/api/revenue-share-tiers", headers=headers, params=params)

    def get_revenue_share_tier(self, revenue_share_tier_id, headers):
        return self._request(
            "GET", f"/api/revenue-share-tiers/{revenue_share_tier_id}", headers=headers
        )

    # ---- developers ------------------------------------------------------
    def create_developer(self, payload, headers):
        return self._request("POST", "/api/developers", payload, headers)

    def list_developers(self, headers, params=None):
        return self._request("GET", "/api/developers", headers=headers, params=params)

    def get_developer(self, developer_id, headers):
        return self._request("GET", f"/api/developers/{developer_id}", headers=headers)

    def verify_developer(self, developer_id, headers):
        return self._request("POST", f"/api/developers/{developer_id}/verify", {}, headers)

    def suspend_developer(self, developer_id, payload, headers):
        return self._request("POST", f"/api/developers/{developer_id}/suspend", payload, headers)

    def reinstate_developer(self, developer_id, payload, headers):
        return self._request("POST", f"/api/developers/{developer_id}/reinstate", payload, headers)

    def terminate_developer(self, developer_id, payload, headers):
        return self._request("POST", f"/api/developers/{developer_id}/terminate", payload, headers)

    def set_payout_hold(self, developer_id, payload, headers):
        return self._request(
            "POST", f"/api/developers/{developer_id}/payout-holds", payload, headers
        )

    def set_tax_profile(self, developer_id, payload, headers):
        return self._request(
            "POST", f"/api/developers/{developer_id}/tax-profile", payload, headers
        )

    def get_developer_summary(self, developer_id, headers):
        return self._request("GET", f"/api/developers/{developer_id}/summary", headers=headers)

    def list_developer_ledger_entries(self, developer_id, headers, params=None):
        return self._request(
            "GET", f"/api/developers/{developer_id}/ledger-entries", headers=headers, params=params
        )

    # ---- apps ------------------------------------------------------------
    def create_app(self, payload, headers):
        return self._request("POST", "/api/apps", payload, headers)

    def list_apps(self, headers, params=None):
        return self._request("GET", "/api/apps", headers=headers, params=params)

    def get_app(self, app_id, headers):
        return self._request("GET", f"/api/apps/{app_id}", headers=headers)

    def patch_app(self, app_id, payload, headers):
        return self._request("PATCH", f"/api/apps/{app_id}", payload, headers)

    def submit_app_for_review(self, app_id, payload, headers):
        return self._request("POST", f"/api/apps/{app_id}/submit-for-review", payload, headers)

    def publish_app(self, app_id, headers):
        return self._request("POST", f"/api/apps/{app_id}/publish", {}, headers)

    def suspend_app(self, app_id, payload, headers):
        return self._request("POST", f"/api/apps/{app_id}/suspend", payload, headers)

    def reinstate_app(self, app_id, payload, headers):
        return self._request("POST", f"/api/apps/{app_id}/reinstate", payload, headers)

    def delist_app(self, app_id, payload, headers):
        return self._request("POST", f"/api/apps/{app_id}/delist", payload, headers)

    def get_app_analytics(self, app_id, headers):
        return self._request("GET", f"/api/apps/{app_id}/analytics", headers=headers)

    def list_app_review_submissions(self, app_id, headers, params=None):
        return self._request(
            "GET", f"/api/apps/{app_id}/review-submissions", headers=headers, params=params
        )

    def list_app_pricing_plans(self, app_id, headers, params=None):
        return self._request(
            "GET", f"/api/apps/{app_id}/pricing-plans", headers=headers, params=params
        )

    def create_pricing_plan(self, app_id, payload, headers):
        return self._request("POST", f"/api/apps/{app_id}/pricing-plans", payload, headers)

    # ---- review submissions ---------------------------------------------
    def list_review_submissions(self, headers, params=None):
        return self._request("GET", "/api/review-submissions", headers=headers, params=params)

    def get_review_submission(self, review_submission_id, headers):
        return self._request(
            "GET", f"/api/review-submissions/{review_submission_id}", headers=headers
        )

    def triage_review_submission(self, review_submission_id, headers):
        return self._request(
            "POST", f"/api/review-submissions/{review_submission_id}/triage", {}, headers
        )

    def decide_review_submission(self, review_submission_id, payload, headers):
        return self._request(
            "POST", f"/api/review-submissions/{review_submission_id}/decision", payload, headers
        )

    # ---- pricing plans ---------------------------------------------------
    def list_pricing_plans(self, headers, params=None):
        return self._request("GET", "/api/pricing-plans", headers=headers, params=params)

    def get_pricing_plan(self, pricing_plan_id, headers):
        return self._request("GET", f"/api/pricing-plans/{pricing_plan_id}", headers=headers)

    def retire_pricing_plan(self, pricing_plan_id, headers):
        return self._request(
            "POST", f"/api/pricing-plans/{pricing_plan_id}/retire", {}, headers
        )

    # ---- purchases -------------------------------------------------------
    def create_purchase(self, payload, headers):
        return self._request("POST", "/api/purchases", payload, headers)

    def list_purchases(self, headers, params=None):
        return self._request("GET", "/api/purchases", headers=headers, params=params)

    def get_purchase(self, purchase_id, headers):
        return self._request("GET", f"/api/purchases/{purchase_id}", headers=headers)

    def capture_purchase(self, purchase_id, headers):
        return self._request("POST", f"/api/purchases/{purchase_id}/capture", {}, headers)

    def void_purchase(self, purchase_id, headers):
        return self._request("POST", f"/api/purchases/{purchase_id}/void", {}, headers)

    # ---- refunds ---------------------------------------------------------
    def request_refund(self, purchase_id, payload, headers):
        return self._request("POST", f"/api/purchases/{purchase_id}/refunds", payload, headers)

    def list_refunds(self, headers, params=None):
        return self._request("GET", "/api/refunds", headers=headers, params=params)

    def get_refund(self, refund_id, headers):
        return self._request("GET", f"/api/refunds/{refund_id}", headers=headers)

    def decide_refund(self, refund_id, payload, headers):
        return self._request("POST", f"/api/refunds/{refund_id}/decide", payload, headers)

    def execute_refund(self, refund_id, headers):
        return self._request("POST", f"/api/refunds/{refund_id}/execute", {}, headers)

    # ---- chargebacks -----------------------------------------------------
    def create_chargeback(self, purchase_id, payload, headers):
        return self._request("POST", f"/api/purchases/{purchase_id}/chargebacks", payload, headers)

    def list_chargebacks(self, headers, params=None):
        return self._request("GET", "/api/chargebacks", headers=headers, params=params)

    def get_chargeback(self, chargeback_id, headers):
        return self._request("GET", f"/api/chargebacks/{chargeback_id}", headers=headers)

    def represent_chargeback(self, chargeback_id, payload, headers):
        return self._request(
            "POST", f"/api/chargebacks/{chargeback_id}/represent", payload, headers
        )

    def resolve_chargeback(self, chargeback_id, payload, headers):
        return self._request("POST", f"/api/chargebacks/{chargeback_id}/resolve", payload, headers)

    def reverse_chargeback(self, chargeback_id, payload, headers):
        return self._request("POST", f"/api/chargebacks/{chargeback_id}/reverse", payload, headers)

    # ---- policy cases ----------------------------------------------------
    def create_policy_case(self, payload, headers):
        return self._request("POST", "/api/policy-cases", payload, headers)

    def list_policy_cases(self, headers, params=None):
        return self._request("GET", "/api/policy-cases", headers=headers, params=params)

    def get_policy_case(self, policy_case_id, headers):
        return self._request("GET", f"/api/policy-cases/{policy_case_id}", headers=headers)

    def investigate_policy_case(self, policy_case_id, headers):
        return self._request(
            "POST", f"/api/policy-cases/{policy_case_id}/investigate", {}, headers
        )

    def decide_policy_case(self, policy_case_id, payload, headers):
        return self._request(
            "POST", f"/api/policy-cases/{policy_case_id}/decide", payload, headers
        )

    def appeal_policy_case(self, policy_case_id, payload, headers):
        return self._request(
            "POST", f"/api/policy-cases/{policy_case_id}/appeal", payload, headers
        )

    def decide_policy_case_appeal(self, policy_case_id, payload, headers):
        return self._request(
            "POST", f"/api/policy-cases/{policy_case_id}/appeal-decision", payload, headers
        )

    # ---- payout batches / lines -----------------------------------------
    def create_payout_batch(self, payload, headers):
        return self._request("POST", "/api/payout-batches", payload, headers)

    def list_payout_batches(self, headers, params=None):
        return self._request("GET", "/api/payout-batches", headers=headers, params=params)

    def get_payout_batch(self, payout_batch_id, headers):
        return self._request("GET", f"/api/payout-batches/{payout_batch_id}", headers=headers)

    def calculate_payout_batch(self, payout_batch_id, headers):
        return self._request(
            "POST", f"/api/payout-batches/{payout_batch_id}/calculate", {}, headers
        )

    def submit_payout_batch(self, payout_batch_id, headers):
        return self._request("POST", f"/api/payout-batches/{payout_batch_id}/submit", {}, headers)

    def approve_payout_batch(self, payout_batch_id, headers):
        return self._request("POST", f"/api/payout-batches/{payout_batch_id}/approve", {}, headers)

    def pay_payout_batch(self, payout_batch_id, payload, headers):
        return self._request(
            "POST", f"/api/payout-batches/{payout_batch_id}/pay", payload, headers
        )

    def retry_payout_batch(self, payout_batch_id, headers):
        return self._request("POST", f"/api/payout-batches/{payout_batch_id}/retry", {}, headers)

    def list_payout_batch_lines(self, payout_batch_id, headers, params=None):
        return self._request(
            "GET", f"/api/payout-batches/{payout_batch_id}/lines", headers=headers, params=params
        )

    def list_payout_lines(self, headers, params=None):
        return self._request("GET", "/api/payout-lines", headers=headers, params=params)

    def get_payout_line(self, payout_line_id, headers):
        return self._request("GET", f"/api/payout-lines/{payout_line_id}", headers=headers)

    # ---- ledger and tax forms -------------------------------------------
    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/api/ledger-entries", headers=headers, params=params)

    def get_ledger_entry(self, ledger_entry_id, headers):
        return self._request("GET", f"/api/ledger-entries/{ledger_entry_id}", headers=headers)

    def create_tax_form(self, payload, headers):
        return self._request("POST", "/api/tax-forms", payload, headers)

    def list_tax_forms(self, headers, params=None):
        return self._request("GET", "/api/tax-forms", headers=headers, params=params)

    def get_tax_form(self, tax_form_id, headers):
        return self._request("GET", f"/api/tax-forms/{tax_form_id}", headers=headers)


api_client = ApiClient()
