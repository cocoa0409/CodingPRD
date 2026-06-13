"""API client: one method per endpoint defined in the CGL PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Insurer ---
    def create_insurer(self, payload, headers):
        return self._request("POST", "/insurers", payload, headers)

    def get_insurer(self, insurer_id, headers):
        return self._request("GET", f"/insurers/{insurer_id}", headers=headers)

    def advance_clock(self, insurer_id, payload, headers):
        return self._request("POST", f"/insurers/{insurer_id}/clock", payload, headers)

    # --- Insured ---
    def create_insured(self, payload, headers):
        return self._request("POST", "/insureds", payload, headers)

    def get_insured(self, insured_id, headers):
        return self._request("GET", f"/insureds/{insured_id}", headers=headers)

    def list_insureds(self, headers, params=None):
        return self._request("GET", "/insureds", headers=headers, params=params)

    # --- Certificate Holder ---
    def create_certificate_holder(self, payload, headers):
        return self._request("POST", "/certificate-holders", payload, headers)

    def get_certificate_holder(self, holder_id, headers):
        return self._request("GET", f"/certificate-holders/{holder_id}", headers=headers)

    def list_certificate_holders(self, headers, params=None):
        return self._request("GET", "/certificate-holders", headers=headers, params=params)

    # --- Policy ---
    def create_policy(self, payload, headers):
        return self._request("POST", "/policies", payload, headers)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/policies/{policy_id}", headers=headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/policies", headers=headers, params=params)

    def bind_policy(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/bind", {}, headers)

    def activate_policy(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/activate", {}, headers)

    def cancel_policy(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/cancel", {}, headers)

    # --- Additional Insured Endorsement ---
    def create_endorsement(self, payload, headers):
        return self._request("POST", "/endorsements", payload, headers)

    def get_endorsement(self, endorsement_id, headers):
        return self._request("GET", f"/endorsements/{endorsement_id}", headers=headers)

    def list_endorsements(self, headers, params=None):
        return self._request("GET", "/endorsements", headers=headers, params=params)

    def void_endorsement(self, endorsement_id, headers):
        return self._request("POST", f"/endorsements/{endorsement_id}/void", {}, headers)

    # --- Certificate of Insurance ---
    def create_certificate(self, payload, headers):
        return self._request("POST", "/certificates", payload, headers)

    def get_certificate(self, certificate_id, headers):
        return self._request("GET", f"/certificates/{certificate_id}", headers=headers)

    def list_certificates(self, headers, params=None):
        return self._request("GET", "/certificates", headers=headers, params=params)

    def issue_certificate(self, certificate_id, headers):
        return self._request("POST", f"/certificates/{certificate_id}/issue", {}, headers)

    def revoke_certificate(self, certificate_id, headers):
        return self._request("POST", f"/certificates/{certificate_id}/revoke", {}, headers)

    # --- Claim ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def post_transaction(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/transactions", payload, headers)

    def get_transaction(self, transaction_id, headers):
        return self._request("GET", f"/claim-transactions/{transaction_id}", headers=headers)

    def list_transactions(self, headers, params=None):
        return self._request("GET", "/claim-transactions", headers=headers, params=params)

    def close_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/close", {}, headers)

    def deny_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/deny", {}, headers)

    def reopen_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/reopen", {}, headers)

    # --- Premium Audit ---
    def create_audit(self, payload, headers):
        return self._request("POST", "/audits", payload, headers)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/audits/{audit_id}", headers=headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", "/audits", headers=headers, params=params)

    def start_audit(self, audit_id, headers):
        return self._request("POST", f"/audits/{audit_id}/start", {}, headers)

    def create_exposure_record(self, audit_id, payload, headers):
        return self._request("POST", f"/audits/{audit_id}/exposure-records", payload, headers)

    def get_exposure_record(self, exposure_record_id, headers):
        return self._request("GET", f"/exposure-records/{exposure_record_id}", headers=headers)

    def list_exposure_records(self, headers, params=None):
        return self._request("GET", "/exposure-records", headers=headers, params=params)

    def complete_audit(self, audit_id, headers):
        return self._request("POST", f"/audits/{audit_id}/complete", {}, headers)

    def dispute_audit(self, audit_id, headers):
        return self._request("POST", f"/audits/{audit_id}/dispute", {}, headers)

    def reopen_audit(self, audit_id, headers):
        return self._request("POST", f"/audits/{audit_id}/reopen", {}, headers)

    def finalize_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/audits/{audit_id}/finalize", payload, headers)

    # --- Loss Run ---
    def generate_loss_run(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/loss-runs", {}, headers)

    def get_loss_run(self, loss_run_id, headers):
        return self._request("GET", f"/loss-runs/{loss_run_id}", headers=headers)

    def list_loss_runs(self, headers, params=None):
        return self._request("GET", "/loss-runs", headers=headers, params=params)


api_client = ApiClient()
