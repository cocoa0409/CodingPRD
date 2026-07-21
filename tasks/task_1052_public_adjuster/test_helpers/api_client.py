"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------ logical clock
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/v1/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------ Adjuster
    def create_adjuster(self, payload, headers):
        return self._request("POST", "/v1/adjusters", payload, headers)

    def get_adjuster(self, adjuster_id, headers):
        return self._request("GET", f"/v1/adjusters/{adjuster_id}", headers=headers)

    # ------------------------------------------------------------------- License
    def create_license(self, payload, headers):
        return self._request("POST", "/v1/licenses", payload, headers)

    def get_license(self, license_id, headers):
        return self._request("GET", f"/v1/licenses/{license_id}", headers=headers)

    def list_licenses(self, headers, params=None):
        return self._request("GET", "/v1/licenses", headers=headers, params=params)

    def suspend_license(self, license_id, headers):
        return self._request("POST", f"/v1/licenses/{license_id}/suspend", headers=headers)

    def reinstate_license(self, license_id, headers):
        return self._request("POST", f"/v1/licenses/{license_id}/reinstate", headers=headers)

    def revoke_license(self, license_id, headers):
        return self._request("POST", f"/v1/licenses/{license_id}/revoke", headers=headers)

    # -------------------------------------------------------------------- Client
    def create_client(self, payload, headers):
        return self._request("POST", "/v1/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/v1/clients/{client_id}", headers=headers)

    # -------------------------------------------------------------------- Policy
    def create_policy(self, payload, headers):
        return self._request("POST", "/v1/policies", payload, headers)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/v1/policies/{policy_id}", headers=headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/v1/policies", headers=headers, params=params)

    def lapse_policy(self, policy_id, headers):
        return self._request("POST", f"/v1/policies/{policy_id}/lapse", headers=headers)

    def cancel_policy(self, policy_id, headers):
        return self._request("POST", f"/v1/policies/{policy_id}/cancel", headers=headers)

    # ------------------------------------------------------------------ Contract
    def create_contract(self, payload, headers):
        return self._request("POST", "/v1/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/v1/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/v1/contracts", headers=headers, params=params)

    def sign_contract(self, contract_id, headers):
        return self._request("POST", f"/v1/contracts/{contract_id}/sign", headers=headers)

    def activate_contract(self, contract_id, headers):
        return self._request("POST", f"/v1/contracts/{contract_id}/activate", headers=headers)

    def rescind_contract(self, contract_id, headers):
        return self._request("POST", f"/v1/contracts/{contract_id}/rescind", headers=headers)

    def cancel_contract(self, contract_id, headers):
        return self._request("POST", f"/v1/contracts/{contract_id}/cancel", headers=headers)

    # --------------------------------------------------------------------- Claim
    def create_claim(self, payload, headers):
        return self._request("POST", "/v1/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/v1/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/v1/claims", headers=headers, params=params)

    def file_claim(self, claim_id, headers):
        return self._request("POST", f"/v1/claims/{claim_id}/file", headers=headers)

    def schedule_inspection(self, claim_id, payload, headers):
        return self._request("POST", f"/v1/claims/{claim_id}/schedule-inspection", payload, headers)

    def record_offer(self, claim_id, payload, headers):
        return self._request("POST", f"/v1/claims/{claim_id}/record-offer", payload, headers)

    def counter_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/v1/claims/{claim_id}/counter", payload, headers)

    def accept_settlement(self, claim_id, headers):
        return self._request("POST", f"/v1/claims/{claim_id}/accept-settlement", headers=headers)

    def withdraw_claim(self, claim_id, headers):
        return self._request("POST", f"/v1/claims/{claim_id}/withdraw", headers=headers)

    # ---------------------------------------------------------------- Supplement
    def create_supplement(self, payload, headers):
        return self._request("POST", "/v1/supplements", payload, headers)

    def get_supplement(self, supplement_id, headers):
        return self._request("GET", f"/v1/supplements/{supplement_id}", headers=headers)

    def list_supplements(self, headers, params=None):
        return self._request("GET", "/v1/supplements", headers=headers, params=params)

    def submit_supplement(self, supplement_id, headers):
        return self._request("POST", f"/v1/supplements/{supplement_id}/submit", headers=headers)

    def decide_supplement(self, supplement_id, payload, headers):
        return self._request("POST", f"/v1/supplements/{supplement_id}/decide", payload, headers)

    # ----------------------------------------------------------------- Appraisal
    def create_appraisal(self, payload, headers):
        return self._request("POST", "/v1/appraisals", payload, headers)

    def get_appraisal(self, appraisal_id, headers):
        return self._request("GET", f"/v1/appraisals/{appraisal_id}", headers=headers)

    def list_appraisals(self, headers, params=None):
        return self._request("GET", "/v1/appraisals", headers=headers, params=params)

    def name_appraisers(self, appraisal_id, payload, headers):
        return self._request("POST", f"/v1/appraisals/{appraisal_id}/name-appraisers", payload, headers)

    def select_umpire(self, appraisal_id, payload, headers):
        return self._request("POST", f"/v1/appraisals/{appraisal_id}/select-umpire", payload, headers)

    def render_award(self, appraisal_id, payload, headers):
        return self._request("POST", f"/v1/appraisals/{appraisal_id}/render-award", payload, headers)

    def cancel_appraisal(self, appraisal_id, headers):
        return self._request("POST", f"/v1/appraisals/{appraisal_id}/cancel", headers=headers)

    # ------------------------------------------------------------------- Payment
    def create_payment(self, payload, headers):
        return self._request("POST", "/v1/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/v1/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/v1/payments", headers=headers, params=params)

    def clear_payment(self, payment_id, headers):
        return self._request("POST", f"/v1/payments/{payment_id}/clear", headers=headers)

    def reverse_payment(self, payment_id, headers):
        return self._request("POST", f"/v1/payments/{payment_id}/reverse", headers=headers)

    # -------------------------------------------------------------- Disbursement
    def get_disbursement(self, disbursement_id, headers):
        return self._request("GET", f"/v1/disbursements/{disbursement_id}", headers=headers)

    def list_disbursements(self, headers, params=None):
        return self._request("GET", "/v1/disbursements", headers=headers, params=params)

    def release_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/v1/disbursements/{disbursement_id}/release", headers=headers)

    def hold_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/v1/disbursements/{disbursement_id}/hold", headers=headers)

    def resume_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/v1/disbursements/{disbursement_id}/resume", headers=headers)

    # ------------------------------------------------------------------- Dispute
    def create_dispute(self, payload, headers):
        return self._request("POST", "/v1/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/v1/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/v1/disputes", headers=headers, params=params)

    def review_dispute(self, dispute_id, headers):
        return self._request("POST", f"/v1/disputes/{dispute_id}/review", headers=headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/v1/disputes/{dispute_id}/resolve", payload, headers)

    def withdraw_dispute(self, dispute_id, headers):
        return self._request("POST", f"/v1/disputes/{dispute_id}/withdraw", headers=headers)


api_client = ApiClient()
