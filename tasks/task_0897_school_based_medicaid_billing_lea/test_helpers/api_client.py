"""API client: one method per endpoint of the School-Based Medicaid Billing API."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- Students ----
    def create_student(self, payload, headers):
        return self._request("POST", "/sbmb/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/sbmb/students/{student_id}", headers=headers)

    def withdraw_student(self, student_id, headers):
        return self._request("POST", f"/sbmb/students/{student_id}/withdraw", {}, headers)

    # ---- Providers ----
    def create_provider(self, payload, headers):
        return self._request("POST", "/sbmb/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/sbmb/providers/{provider_id}", headers=headers)

    # ---- Provider credentials ----
    def create_credential(self, payload, headers):
        return self._request("POST", "/sbmb/provider-credentials", payload, headers)

    def get_credential(self, credential_id, headers):
        return self._request("GET", f"/sbmb/provider-credentials/{credential_id}", headers=headers)

    def list_credentials(self, headers, params=None):
        return self._request("GET", "/sbmb/provider-credentials", headers=headers, params=params)

    def activate_credential(self, credential_id, headers):
        return self._request("POST", f"/sbmb/provider-credentials/{credential_id}/activate", {}, headers)

    def suspend_credential(self, credential_id, payload, headers):
        return self._request("POST", f"/sbmb/provider-credentials/{credential_id}/suspend", payload, headers)

    # ---- IEP authorizations ----
    def create_authorization(self, payload, headers):
        return self._request("POST", "/sbmb/iep-authorizations", payload, headers)

    def get_authorization(self, authorization_id, headers):
        return self._request("GET", f"/sbmb/iep-authorizations/{authorization_id}", headers=headers)

    def list_authorizations(self, headers, params=None):
        return self._request("GET", "/sbmb/iep-authorizations", headers=headers, params=params)

    def activate_authorization(self, authorization_id, headers):
        return self._request("POST", f"/sbmb/iep-authorizations/{authorization_id}/activate", {}, headers)

    def discontinue_authorization(self, authorization_id, headers):
        return self._request("POST", f"/sbmb/iep-authorizations/{authorization_id}/discontinue", {}, headers)

    # ---- Parental consents ----
    def create_consent(self, payload, headers):
        return self._request("POST", "/sbmb/parental-consents", payload, headers)

    def get_consent(self, consent_id, headers):
        return self._request("GET", f"/sbmb/parental-consents/{consent_id}", headers=headers)

    def list_consents(self, headers, params=None):
        return self._request("GET", "/sbmb/parental-consents", headers=headers, params=params)

    def grant_consent(self, consent_id, headers):
        return self._request("POST", f"/sbmb/parental-consents/{consent_id}/grant", {}, headers)

    def revoke_consent(self, consent_id, headers):
        return self._request("POST", f"/sbmb/parental-consents/{consent_id}/revoke", {}, headers)

    # ---- Service logs ----
    def create_service_log(self, payload, headers):
        return self._request("POST", "/sbmb/service-logs", payload, headers)

    def get_service_log(self, service_log_id, headers):
        return self._request("GET", f"/sbmb/service-logs/{service_log_id}", headers=headers)

    def list_service_logs(self, headers, params=None):
        return self._request("GET", "/sbmb/service-logs", headers=headers, params=params)

    def document_service_log(self, service_log_id, payload, headers):
        return self._request("POST", f"/sbmb/service-logs/{service_log_id}/document", payload, headers)

    def verify_service_log(self, service_log_id, headers):
        return self._request("POST", f"/sbmb/service-logs/{service_log_id}/verify", {}, headers)

    def return_service_log(self, service_log_id, payload, headers):
        return self._request("POST", f"/sbmb/service-logs/{service_log_id}/return", payload, headers)

    def void_service_log(self, service_log_id, headers):
        return self._request("POST", f"/sbmb/service-logs/{service_log_id}/void", {}, headers)

    # ---- Claims ----
    def create_claim(self, payload, headers):
        return self._request("POST", "/sbmb/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/sbmb/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/sbmb/claims", headers=headers, params=params)

    def attach_log(self, claim_id, payload, headers):
        return self._request("POST", f"/sbmb/claims/{claim_id}/attach", payload, headers)

    def submit_claim(self, claim_id, headers):
        return self._request("POST", f"/sbmb/claims/{claim_id}/submit", {}, headers)

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/sbmb/claims/{claim_id}/adjudicate", payload, headers)

    def void_claim(self, claim_id, headers):
        return self._request("POST", f"/sbmb/claims/{claim_id}/void", {}, headers)

    # ---- RMTS quarters ----
    def create_quarter(self, payload, headers):
        return self._request("POST", "/sbmb/rmts-quarters", payload, headers)

    def get_quarter(self, quarter_id, headers):
        return self._request("GET", f"/sbmb/rmts-quarters/{quarter_id}", headers=headers)

    def close_quarter(self, quarter_id, headers):
        return self._request("POST", f"/sbmb/rmts-quarters/{quarter_id}/close", {}, headers)

    # ---- RMTS moments ----
    def create_moment(self, payload, headers):
        return self._request("POST", "/sbmb/rmts-moments", payload, headers)

    def get_moment(self, moment_id, headers):
        return self._request("GET", f"/sbmb/rmts-moments/{moment_id}", headers=headers)

    def list_moments(self, headers, params=None):
        return self._request("GET", "/sbmb/rmts-moments", headers=headers, params=params)

    def respond_moment(self, moment_id, payload, headers):
        return self._request("POST", f"/sbmb/rmts-moments/{moment_id}/respond", payload, headers)

    def code_moment(self, moment_id, payload, headers):
        return self._request("POST", f"/sbmb/rmts-moments/{moment_id}/code", payload, headers)

    # ---- Cost settlements ----
    def create_settlement(self, payload, headers):
        return self._request("POST", "/sbmb/cost-settlements", payload, headers)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/sbmb/cost-settlements/{settlement_id}", headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/sbmb/cost-settlements", headers=headers, params=params)

    def certify_settlement(self, settlement_id, headers):
        return self._request("POST", f"/sbmb/cost-settlements/{settlement_id}/certify", {}, headers)

    def settle_settlement(self, settlement_id, headers):
        return self._request("POST", f"/sbmb/cost-settlements/{settlement_id}/settle", {}, headers)


api_client = ApiClient()
