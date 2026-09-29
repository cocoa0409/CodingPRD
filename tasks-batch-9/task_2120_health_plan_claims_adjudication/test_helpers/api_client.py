"""API client: one method per endpoint defined in the PRD (all rooted at /adjudication)."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/adjudication"


class ApiClient(GenericApiClient):
    # ─── Benefit plans ────────────────────────────────────────────────────────
    def create_benefit_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/benefit-plans", payload, headers)

    def get_benefit_plan(self, plan_id, headers):
        return self._request("GET", f"{PREFIX}/benefit-plans/{plan_id}", headers=headers)

    # ─── Fee schedule rates ───────────────────────────────────────────────────
    def create_fee_schedule_rate(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/benefit-plans/{plan_id}/fee-schedule-rates", payload, headers
        )

    def list_fee_schedule_rates(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/benefit-plans/{plan_id}/fee-schedule-rates",
            headers=headers, params=params,
        )

    # ─── Members ──────────────────────────────────────────────────────────────
    def create_member(self, payload, headers):
        return self._request("POST", f"{PREFIX}/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"{PREFIX}/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/members", headers=headers, params=params)

    # ─── Coverage segments ────────────────────────────────────────────────────
    def create_coverage(self, member_id, payload, headers):
        return self._request("POST", f"{PREFIX}/members/{member_id}/coverages", payload, headers)

    def list_coverages(self, member_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/members/{member_id}/coverages", headers=headers, params=params
        )

    def terminate_coverage(self, coverage_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/coverages/{coverage_id}/terminate", payload, headers
        )

    # ─── Benefit accumulators ─────────────────────────────────────────────────
    def list_accumulators(self, member_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/members/{member_id}/accumulators", headers=headers, params=params
        )

    def adjust_accumulator(self, accumulator_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/accumulators/{accumulator_id}/adjustments", payload, headers
        )

    # ─── Providers ────────────────────────────────────────────────────────────
    def create_provider(self, payload, headers):
        return self._request("POST", f"{PREFIX}/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"{PREFIX}/providers/{provider_id}", headers=headers)

    # ─── Provider contracts ───────────────────────────────────────────────────
    def create_contract(self, payload, headers):
        return self._request("POST", f"{PREFIX}/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"{PREFIX}/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/contracts", headers=headers, params=params)

    def activate_contract(self, contract_id, headers):
        return self._request("POST", f"{PREFIX}/contracts/{contract_id}/activate", {}, headers)

    def terminate_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/contracts/{contract_id}/terminate", payload, headers
        )

    # ─── Edit rules ───────────────────────────────────────────────────────────
    def create_edit_rule(self, payload, headers):
        return self._request("POST", f"{PREFIX}/edit-rules", payload, headers)

    # ─── Authorizations ───────────────────────────────────────────────────────
    def create_authorization(self, payload, headers):
        return self._request("POST", f"{PREFIX}/authorizations", payload, headers)

    def get_authorization(self, authorization_id, headers):
        return self._request(
            "GET", f"{PREFIX}/authorizations/{authorization_id}", headers=headers
        )

    def list_authorizations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/authorizations", headers=headers, params=params)

    def revoke_authorization(self, authorization_id, headers):
        return self._request(
            "POST", f"{PREFIX}/authorizations/{authorization_id}/revoke", {}, headers
        )

    # ─── Claims ───────────────────────────────────────────────────────────────
    def create_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/claims", headers=headers, params=params)

    def adjudicate_claim(self, claim_id, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/adjudicate", {}, headers)

    def override_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/override", payload, headers)

    def finalize_claim(self, claim_id, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/finalize", {}, headers)

    def void_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/void", payload, headers)

    def create_adjustment(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/adjustments", payload, headers)

    def post_other_payer_payment(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/claims/{claim_id}/other-payer-payment", payload, headers
        )

    # ─── Claim lines ──────────────────────────────────────────────────────────
    def get_claim_line(self, claim_line_id, headers):
        return self._request("GET", f"{PREFIX}/claim-lines/{claim_line_id}", headers=headers)

    def list_claim_lines(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/claim-lines", headers=headers, params=params)

    # ─── Remittance advices ───────────────────────────────────────────────────
    def list_remittances(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/claims/{claim_id}/remittances", headers=headers, params=params
        )

    # ─── Adjudication events ──────────────────────────────────────────────────
    def list_events(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/claims/{claim_id}/events", headers=headers, params=params
        )

    # ─── Logical clock ────────────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
