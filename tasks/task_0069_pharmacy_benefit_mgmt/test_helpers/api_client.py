"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/pbm"


class ApiClient(GenericApiClient):
    # ---- Clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", f"{PREFIX}/_clock/set", {"to_iso8601": to_iso8601}, headers)

    # ---- BenefitPlan ----
    def create_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"{PREFIX}/plans/{plan_id}", headers=headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/plans", headers=headers, params=params)

    def archive_plan(self, plan_id, headers):
        return self._request("POST", f"{PREFIX}/plans/{plan_id}/archive", {}, headers)

    def finalize_rebates(self, plan_id, payload, headers):
        return self._request("POST", f"{PREFIX}/plans/{plan_id}/finalize-rebates", payload, headers)

    # ---- FormularyDrug ----
    def create_formulary_drug(self, payload, headers):
        return self._request("POST", f"{PREFIX}/formulary-drugs", payload, headers)

    def get_formulary_drug(self, drug_id, headers):
        return self._request("GET", f"{PREFIX}/formulary-drugs/{drug_id}", headers=headers)

    def list_formulary_drugs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/formulary-drugs", headers=headers, params=params)

    def delist_formulary_drug(self, drug_id, headers):
        return self._request("POST", f"{PREFIX}/formulary-drugs/{drug_id}/delist", {}, headers)

    # ---- StepTherapyProtocol ----
    def create_step_therapy_protocol(self, payload, headers):
        return self._request("POST", f"{PREFIX}/step-therapy-protocols", payload, headers)

    def get_step_therapy_protocol(self, proto_id, headers):
        return self._request("GET", f"{PREFIX}/step-therapy-protocols/{proto_id}", headers=headers)

    def list_step_therapy_protocols(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/step-therapy-protocols", headers=headers, params=params)

    # ---- Member ----
    def create_member(self, payload, headers):
        return self._request("POST", f"{PREFIX}/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"{PREFIX}/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/members", headers=headers, params=params)

    def terminate_member(self, member_id, headers):
        return self._request("POST", f"{PREFIX}/members/{member_id}/terminate", {}, headers)

    # ---- PriorAuthorization ----
    def create_prior_authorization(self, payload, headers):
        return self._request("POST", f"{PREFIX}/prior-authorizations", payload, headers)

    def get_prior_authorization(self, pa_id, headers):
        return self._request("GET", f"{PREFIX}/prior-authorizations/{pa_id}", headers=headers)

    def list_prior_authorizations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/prior-authorizations", headers=headers, params=params)

    def decide_prior_authorization(self, pa_id, payload, headers):
        return self._request("POST", f"{PREFIX}/prior-authorizations/{pa_id}/decide", payload, headers)

    def appeal_prior_authorization(self, pa_id, headers):
        return self._request("POST", f"{PREFIX}/prior-authorizations/{pa_id}/appeal", {}, headers)

    # ---- Claim ----
    def create_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/claims", headers=headers, params=params)

    def reverse_claim(self, claim_id, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/reverse", {}, headers)

    # ---- CopayCard ----
    def create_copay_card(self, payload, headers):
        return self._request("POST", f"{PREFIX}/copay-cards", payload, headers)

    def get_copay_card(self, card_id, headers):
        return self._request("GET", f"{PREFIX}/copay-cards/{card_id}", headers=headers)

    def list_copay_cards(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/copay-cards", headers=headers, params=params)

    # ---- RebateAgreement ----
    def create_rebate_agreement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/rebate-agreements", payload, headers)

    def get_rebate_agreement(self, agreement_id, headers):
        return self._request("GET", f"{PREFIX}/rebate-agreements/{agreement_id}", headers=headers)

    def list_rebate_agreements(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/rebate-agreements", headers=headers, params=params)

    # ---- RebateAccrual ----
    def get_rebate_accrual(self, accrual_id, headers):
        return self._request("GET", f"{PREFIX}/rebate-accruals/{accrual_id}", headers=headers)

    def list_rebate_accruals(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/rebate-accruals", headers=headers, params=params)


api_client = ApiClient()
