"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Test clock ───────────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Plan ─────────────────────────────────────────────────────────────
    def create_plan(self, payload, headers):
        return self._request("POST", "/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/plans/{plan_id}", headers=headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/plans", headers=headers, params=params)

    def retire_plan(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/retire", headers=headers)

    # ─── Traveler ─────────────────────────────────────────────────────────
    def create_traveler(self, payload, headers):
        return self._request("POST", "/travelers", payload, headers)

    def get_traveler(self, traveler_id, headers):
        return self._request("GET", f"/travelers/{traveler_id}", headers=headers)

    # ─── Named Storm ──────────────────────────────────────────────────────
    def create_named_storm(self, payload, headers):
        return self._request("POST", "/named-storms", payload, headers)

    def get_named_storm(self, storm_id, headers):
        return self._request("GET", f"/named-storms/{storm_id}", headers=headers)

    def list_named_storms(self, headers, params=None):
        return self._request("GET", "/named-storms", headers=headers, params=params)

    def dissipate_named_storm(self, storm_id, headers):
        return self._request("POST", f"/named-storms/{storm_id}/dissipate", headers=headers)

    # ─── Policy ───────────────────────────────────────────────────────────
    def create_policy(self, payload, headers):
        return self._request("POST", "/policies", payload, headers)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/policies/{policy_id}", headers=headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/policies", headers=headers, params=params)

    def add_insured_traveler(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/insured-travelers", payload, headers)

    def list_policy_insured_travelers(self, policy_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/insured-travelers", headers=headers, params=params)

    def get_insured_traveler(self, insured_traveler_id, headers):
        return self._request("GET", f"/insured-travelers/{insured_traveler_id}", headers=headers)

    def list_insured_travelers(self, headers, params=None):
        return self._request("GET", "/insured-travelers", headers=headers, params=params)

    def record_payment(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/record-payment", payload, headers)

    def issue_policy(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/issue", headers=headers)

    def free_look_cancel_policy(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/free-look-cancel", headers=headers)

    def cancel_policy(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/cancel", headers=headers)

    # ─── Claim ────────────────────────────────────────────────────────────
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def add_expense(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/expenses", payload, headers)

    def list_expenses(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/expenses", headers=headers, params=params)

    def add_document(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/documents", payload, headers)

    def list_documents(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/documents", headers=headers, params=params)

    def start_review(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/start-review", headers=headers)

    def request_info(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/request-info", headers=headers)

    def resubmit_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/resubmit", headers=headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/approve", headers=headers)

    def deny_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/deny", payload, headers)

    # ─── Payout ───────────────────────────────────────────────────────────
    def create_payout(self, payload, headers):
        return self._request("POST", "/payouts", payload, headers)

    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/payouts/{payout_id}", headers=headers)

    def list_payouts(self, headers, params=None):
        return self._request("GET", "/payouts", headers=headers, params=params)

    def disburse_payout(self, payout_id, headers):
        return self._request("POST", f"/payouts/{payout_id}/disburse", headers=headers)

    def reverse_payout(self, payout_id, headers):
        return self._request("POST", f"/payouts/{payout_id}/reverse", headers=headers)

    # ─── Refund ───────────────────────────────────────────────────────────
    def get_refund(self, refund_id, headers):
        return self._request("GET", f"/refunds/{refund_id}", headers=headers)

    def list_refunds(self, headers, params=None):
        return self._request("GET", "/refunds", headers=headers, params=params)

    def complete_refund(self, refund_id, headers):
        return self._request("POST", f"/refunds/{refund_id}/complete", headers=headers)

    def void_refund(self, refund_id, headers):
        return self._request("POST", f"/refunds/{refund_id}/void", headers=headers)


api_client = ApiClient()
