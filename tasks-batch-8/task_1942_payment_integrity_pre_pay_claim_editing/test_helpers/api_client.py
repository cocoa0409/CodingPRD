"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/payment-integrity/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Providers
    # ------------------------------------------------------------------
    def create_provider(self, payload, headers):
        return self._request("POST", "/payment-integrity/providers", payload, headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", "/payment-integrity/providers",
                             headers=headers, params=params)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/payment-integrity/providers/{provider_id}",
                             headers=headers)

    def patch_provider(self, provider_id, payload, headers):
        return self._request("PATCH", f"/payment-integrity/providers/{provider_id}",
                             payload, headers)

    # ------------------------------------------------------------------
    # Edit rules and versions
    # ------------------------------------------------------------------
    def create_edit_rule(self, payload, headers):
        return self._request("POST", "/payment-integrity/edit-rules", payload, headers)

    def list_edit_rules(self, headers, params=None):
        return self._request("GET", "/payment-integrity/edit-rules",
                             headers=headers, params=params)

    def get_edit_rule(self, rule_id, headers):
        return self._request("GET", f"/payment-integrity/edit-rules/{rule_id}",
                             headers=headers)

    def create_edit_version(self, rule_id, payload, headers):
        return self._request("POST",
                             f"/payment-integrity/edit-rules/{rule_id}/versions",
                             payload, headers)

    def list_rule_versions(self, rule_id, headers, params=None):
        return self._request("GET",
                             f"/payment-integrity/edit-rules/{rule_id}/versions",
                             headers=headers, params=params)

    def get_edit_version(self, version_id, headers):
        return self._request("GET", f"/payment-integrity/edit-versions/{version_id}",
                             headers=headers)

    def list_edit_versions(self, headers, params=None):
        return self._request("GET", "/payment-integrity/edit-versions",
                             headers=headers, params=params)

    def submit_edit_version(self, version_id, headers):
        return self._request("POST",
                             f"/payment-integrity/edit-versions/{version_id}/submit",
                             {}, headers)

    def approve_edit_version(self, version_id, payload, headers):
        return self._request("POST",
                             f"/payment-integrity/edit-versions/{version_id}/approve",
                             payload, headers)

    def reject_edit_version(self, version_id, payload, headers):
        return self._request("POST",
                             f"/payment-integrity/edit-versions/{version_id}/reject",
                             payload, headers)

    def suspend_edit_version(self, version_id, payload, headers):
        return self._request("POST",
                             f"/payment-integrity/edit-versions/{version_id}/suspend",
                             payload, headers)

    def reactivate_edit_version(self, version_id, headers):
        return self._request("POST",
                             f"/payment-integrity/edit-versions/{version_id}/reactivate",
                             {}, headers)

    def retire_edit_version(self, version_id, headers):
        return self._request("POST",
                             f"/payment-integrity/edit-versions/{version_id}/retire",
                             {}, headers)

    # ------------------------------------------------------------------
    # Vendor edits
    # ------------------------------------------------------------------
    def create_vendor_edit(self, payload, headers):
        return self._request("POST", "/payment-integrity/vendor-edits", payload, headers)

    def list_vendor_edits(self, headers, params=None):
        return self._request("GET", "/payment-integrity/vendor-edits",
                             headers=headers, params=params)

    def get_vendor_edit(self, vendor_edit_id, headers):
        return self._request("GET",
                             f"/payment-integrity/vendor-edits/{vendor_edit_id}",
                             headers=headers)

    def map_vendor_edit(self, vendor_edit_id, payload, headers):
        return self._request("POST",
                             f"/payment-integrity/vendor-edits/{vendor_edit_id}/map",
                             payload, headers)

    # ------------------------------------------------------------------
    # Claims
    # ------------------------------------------------------------------
    def create_claim(self, payload, headers):
        return self._request("POST", "/payment-integrity/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/payment-integrity/claims",
                             headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/payment-integrity/claims/{claim_id}",
                             headers=headers)

    def add_claim_line(self, claim_id, payload, headers):
        return self._request("POST", f"/payment-integrity/claims/{claim_id}/lines",
                             payload, headers)

    def list_claim_lines(self, claim_id, headers, params=None):
        return self._request("GET", f"/payment-integrity/claims/{claim_id}/lines",
                             headers=headers, params=params)

    def list_claim_edit_hits(self, claim_id, headers, params=None):
        return self._request("GET",
                             f"/payment-integrity/claims/{claim_id}/edit-hits",
                             headers=headers, params=params)

    def run_edits(self, claim_id, headers):
        return self._request("POST",
                             f"/payment-integrity/claims/{claim_id}/run-edits",
                             {}, headers)

    def pay_claim(self, claim_id, headers):
        return self._request("POST", f"/payment-integrity/claims/{claim_id}/pay",
                             {}, headers)

    # ------------------------------------------------------------------
    # Edit hits
    # ------------------------------------------------------------------
    def list_edit_hits(self, headers, params=None):
        return self._request("GET", "/payment-integrity/edit-hits",
                             headers=headers, params=params)

    def get_edit_hit(self, hit_id, headers):
        return self._request("GET", f"/payment-integrity/edit-hits/{hit_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Review tasks
    # ------------------------------------------------------------------
    def list_review_tasks(self, headers, params=None):
        return self._request("GET", "/payment-integrity/review-tasks",
                             headers=headers, params=params)

    def get_review_task(self, task_id, headers):
        return self._request("GET", f"/payment-integrity/review-tasks/{task_id}",
                             headers=headers)

    def assign_review_task(self, task_id, payload, headers):
        return self._request("POST",
                             f"/payment-integrity/review-tasks/{task_id}/assign",
                             payload, headers)

    def decide_review_task(self, task_id, payload, headers):
        return self._request("POST",
                             f"/payment-integrity/review-tasks/{task_id}/decide",
                             payload, headers)

    def escalate_review_task(self, task_id, payload, headers):
        return self._request("POST",
                             f"/payment-integrity/review-tasks/{task_id}/escalate",
                             payload, headers)

    # ------------------------------------------------------------------
    # Disputes
    # ------------------------------------------------------------------
    def create_dispute(self, claim_id, payload, headers):
        return self._request("POST", f"/payment-integrity/claims/{claim_id}/disputes",
                             payload, headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/payment-integrity/disputes",
                             headers=headers, params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/payment-integrity/disputes/{dispute_id}",
                             headers=headers)

    def start_dispute_review(self, dispute_id, headers):
        return self._request("POST",
                             f"/payment-integrity/disputes/{dispute_id}/start-review",
                             {}, headers)

    def request_dispute_info(self, dispute_id, payload, headers):
        return self._request("POST",
                             f"/payment-integrity/disputes/{dispute_id}/request-info",
                             payload, headers)

    def submit_dispute_info(self, dispute_id, payload, headers):
        return self._request("POST",
                             f"/payment-integrity/disputes/{dispute_id}/submit-info",
                             payload, headers)

    def decide_dispute(self, dispute_id, payload, headers):
        return self._request("POST",
                             f"/payment-integrity/disputes/{dispute_id}/decide",
                             payload, headers)

    # ------------------------------------------------------------------
    # Itemized bill reviews
    # ------------------------------------------------------------------
    def create_ibr(self, claim_id, headers):
        return self._request("POST",
                             f"/payment-integrity/claims/{claim_id}/itemized-bill-reviews",
                             {}, headers)

    def list_ibrs(self, headers, params=None):
        return self._request("GET", "/payment-integrity/itemized-bill-reviews",
                             headers=headers, params=params)

    def get_ibr(self, ibr_id, headers):
        return self._request("GET",
                             f"/payment-integrity/itemized-bill-reviews/{ibr_id}",
                             headers=headers)

    def receive_ibr_documents(self, ibr_id, headers):
        return self._request(
            "POST",
            f"/payment-integrity/itemized-bill-reviews/{ibr_id}/receive-documents",
            {}, headers)

    def start_ibr_audit(self, ibr_id, headers):
        return self._request(
            "POST",
            f"/payment-integrity/itemized-bill-reviews/{ibr_id}/start-audit",
            {}, headers)

    def complete_ibr(self, ibr_id, payload, headers):
        return self._request(
            "POST", f"/payment-integrity/itemized-bill-reviews/{ibr_id}/complete",
            payload, headers)

    def expire_ibr(self, ibr_id, headers):
        return self._request(
            "POST", f"/payment-integrity/itemized-bill-reviews/{ibr_id}/expire",
            {}, headers)

    # ------------------------------------------------------------------
    # Inpatient reviews
    # ------------------------------------------------------------------
    def list_inpatient_reviews(self, headers, params=None):
        return self._request("GET", "/payment-integrity/inpatient-reviews",
                             headers=headers, params=params)

    def get_inpatient_review(self, review_id, headers):
        return self._request("GET",
                             f"/payment-integrity/inpatient-reviews/{review_id}",
                             headers=headers)

    def record_inpatient_findings(self, review_id, payload, headers):
        return self._request(
            "POST",
            f"/payment-integrity/inpatient-reviews/{review_id}/record-findings",
            payload, headers)

    def decide_inpatient_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/payment-integrity/inpatient-reviews/{review_id}/decide",
            payload, headers)

    # ------------------------------------------------------------------
    # Abrasion profiles
    # ------------------------------------------------------------------
    def list_abrasion_profiles(self, headers, params=None):
        return self._request("GET", "/payment-integrity/abrasion-profiles",
                             headers=headers, params=params)

    def get_abrasion_profile(self, profile_id, headers):
        return self._request("GET",
                             f"/payment-integrity/abrasion-profiles/{profile_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Savings periods
    # ------------------------------------------------------------------
    def create_savings_period(self, payload, headers):
        return self._request("POST", "/payment-integrity/savings-periods",
                             payload, headers)

    def list_savings_periods(self, headers, params=None):
        return self._request("GET", "/payment-integrity/savings-periods",
                             headers=headers, params=params)

    def get_savings_period(self, period_id, headers):
        return self._request("GET",
                             f"/payment-integrity/savings-periods/{period_id}",
                             headers=headers)

    def begin_reconciliation(self, period_id, headers):
        return self._request(
            "POST",
            f"/payment-integrity/savings-periods/{period_id}/begin-reconciliation",
            {}, headers)

    def finalize_savings_period(self, period_id, headers):
        return self._request(
            "POST", f"/payment-integrity/savings-periods/{period_id}/finalize",
            {}, headers)


api_client = ApiClient()
