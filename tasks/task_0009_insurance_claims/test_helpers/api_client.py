"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Policies ─────────────────────────────────────────────────
    def create_policy(self, payload, headers):
        return self._request("POST", "/policies", payload, headers)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/policies/{policy_id}", headers=headers)

    def patch_policy(self, policy_id, payload, headers):
        return self._request("PATCH", f"/policies/{policy_id}", payload, headers)

    # ─── Adjusters ────────────────────────────────────────────────
    def create_adjuster(self, payload, headers):
        return self._request("POST", "/adjusters", payload, headers)

    def list_adjusters(self, headers, params=None):
        return self._request("GET", "/adjusters", headers=headers, params=params)

    def patch_adjuster(self, adjuster_id, payload, headers):
        return self._request("PATCH", f"/adjusters/{adjuster_id}", payload, headers)

    # ─── Repair Shops ─────────────────────────────────────────────
    def create_repair_shop(self, payload, headers):
        return self._request("POST", "/repair-shops", payload, headers)

    def get_repair_shop(self, shop_id, headers, params=None):
        return self._request("GET", f"/repair-shops/{shop_id}", headers=headers, params=params)

    def patch_repair_shop(self, shop_id, payload, headers):
        return self._request("PATCH", f"/repair-shops/{shop_id}", payload, headers)

    # ─── Claims ───────────────────────────────────────────────────
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def get_claim_estimate(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}/estimate", headers=headers)

    # ─── Investigations ───────────────────────────────────────────
    def create_investigation(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/investigations", payload, headers)

    def patch_investigation(self, claim_id, inv_id, payload, headers):
        return self._request("PATCH", f"/claims/{claim_id}/investigations/{inv_id}", payload, headers)

    def create_estimate_line_item(self, claim_id, inv_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/investigations/{inv_id}/estimates", payload, headers)

    def reject_investigation(self, claim_id, inv_id, headers):
        return self._request("POST", f"/claims/{claim_id}/investigations/{inv_id}/reject", headers=headers)

    def submit_for_review(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/submit-for-review", headers=headers)

    # ─── Reviews ──────────────────────────────────────────────────
    def create_decision(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/decisions", payload, headers)

    # ─── Payouts & Subrogations ───────────────────────────────────
    def create_payout(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/payouts", headers=headers)

    def get_payout(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}/payouts", headers=headers)

    def create_subrogation(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/subrogations", payload, headers)

    # ─── Appeals ──────────────────────────────────────────────────
    def create_appeal(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/appeals", payload, headers)

    def withdraw_appeal(self, claim_id, appeal_id, headers):
        return self._request("DELETE", f"/claims/{claim_id}/appeals/{appeal_id}", headers=headers)

    def create_appeal_decision(self, claim_id, appeal_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/appeals/{appeal_id}/decisions", payload, headers)

    # ─── Fraud flags & audit ──────────────────────────────────────
    def create_fraud_flag(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/fraud-flags", payload, headers)

    def get_audit_log(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/audit-log", headers=headers, params=params)

    # ─── Test-driving control endpoints ───────────────────────────
    def advance_clock(self, payload, headers):
        return self._request("POST", "/_clock/advance", payload, headers)

    def bank_settle(self, payload, headers):
        return self._request("POST", "/_events/bank-settle", payload, headers)

    def bank_fail(self, payload, headers):
        return self._request("POST", "/_events/bank-fail", payload, headers)


api_client = ApiClient()
