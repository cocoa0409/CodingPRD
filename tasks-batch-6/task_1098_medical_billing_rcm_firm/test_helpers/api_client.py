"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock (test-driving) ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- Practice ----
    def create_practice(self, payload, headers):
        return self._request("POST", "/rcm/practices", payload, headers)

    def get_practice(self, practice_id, headers):
        return self._request("GET", f"/rcm/practices/{practice_id}", headers=headers)

    def list_practices(self, headers, params=None):
        return self._request("GET", "/rcm/practices", headers=headers, params=params)

    def activate_practice(self, practice_id, payload, headers):
        return self._request("POST", f"/rcm/practices/{practice_id}/activate", payload, headers)

    def get_practice_kpi(self, practice_id, headers):
        return self._request("GET", f"/rcm/practices/{practice_id}/kpi", headers=headers)

    def get_practice_billing_fee(self, practice_id, headers):
        return self._request("GET", f"/rcm/practices/{practice_id}/billing-fee", headers=headers)

    def list_practice_providers(self, practice_id, headers, params=None):
        return self._request("GET", f"/rcm/practices/{practice_id}/providers", headers=headers, params=params)

    def list_practice_fee_schedules(self, practice_id, headers, params=None):
        return self._request("GET", f"/rcm/practices/{practice_id}/fee-schedules", headers=headers, params=params)

    def list_practice_claims(self, practice_id, headers, params=None):
        return self._request("GET", f"/rcm/practices/{practice_id}/claims", headers=headers, params=params)

    def list_practice_statements(self, practice_id, headers, params=None):
        return self._request("GET", f"/rcm/practices/{practice_id}/statements", headers=headers, params=params)

    # ---- Payer ----
    def create_payer(self, payload, headers):
        return self._request("POST", "/rcm/payers", payload, headers)

    def get_payer(self, payer_id, headers):
        return self._request("GET", f"/rcm/payers/{payer_id}", headers=headers)

    def list_payer_enrollments(self, payer_id, headers, params=None):
        return self._request("GET", f"/rcm/payers/{payer_id}/enrollments", headers=headers, params=params)

    def list_payer_remittances(self, payer_id, headers, params=None):
        return self._request("GET", f"/rcm/payers/{payer_id}/remittances", headers=headers, params=params)

    def list_payer_claims(self, payer_id, headers, params=None):
        return self._request("GET", f"/rcm/payers/{payer_id}/claims", headers=headers, params=params)

    # ---- Provider / credentialing ----
    def create_provider(self, payload, headers):
        return self._request("POST", "/rcm/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/rcm/providers/{provider_id}", headers=headers)

    def list_provider_enrollments(self, provider_id, headers, params=None):
        return self._request("GET", f"/rcm/providers/{provider_id}/enrollments", headers=headers, params=params)

    def list_provider_claims(self, provider_id, headers, params=None):
        return self._request("GET", f"/rcm/providers/{provider_id}/claims", headers=headers, params=params)

    def submit_credentialing(self, provider_id, headers):
        return self._request("POST", f"/rcm/providers/{provider_id}/credentialing/submit", {}, headers)

    def decide_credentialing(self, provider_id, payload, headers):
        return self._request("POST", f"/rcm/providers/{provider_id}/credentialing/decision", payload, headers)

    # ---- PayerEnrollment ----
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/rcm/payer-enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/rcm/payer-enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/rcm/payer-enrollments", headers=headers, params=params)

    def activate_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/rcm/payer-enrollments/{enrollment_id}/activate", {}, headers)

    def terminate_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/rcm/payer-enrollments/{enrollment_id}/terminate", payload, headers)

    # ---- FeeSchedule ----
    def create_fee_schedule(self, payload, headers):
        return self._request("POST", "/rcm/fee-schedules", payload, headers)

    def get_fee_schedule(self, fee_schedule_id, headers):
        return self._request("GET", f"/rcm/fee-schedules/{fee_schedule_id}", headers=headers)

    def add_fee_schedule_line(self, fee_schedule_id, payload, headers):
        return self._request("POST", f"/rcm/fee-schedules/{fee_schedule_id}/lines", payload, headers)

    def list_fee_schedule_lines(self, fee_schedule_id, headers, params=None):
        return self._request("GET", f"/rcm/fee-schedules/{fee_schedule_id}/lines", headers=headers, params=params)

    def activate_fee_schedule(self, fee_schedule_id, payload, headers):
        return self._request("POST", f"/rcm/fee-schedules/{fee_schedule_id}/activate", payload, headers)

    # ---- Claim ----
    def create_claim(self, payload, headers):
        return self._request("POST", "/rcm/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/rcm/claims/{claim_id}", headers=headers)

    def add_claim_line(self, claim_id, payload, headers):
        return self._request("POST", f"/rcm/claims/{claim_id}/lines", payload, headers)

    def list_claim_lines(self, claim_id, headers, params=None):
        return self._request("GET", f"/rcm/claims/{claim_id}/lines", headers=headers, params=params)

    def list_claim_denials(self, claim_id, headers, params=None):
        return self._request("GET", f"/rcm/claims/{claim_id}/denials", headers=headers, params=params)

    def list_claim_postings(self, claim_id, headers, params=None):
        return self._request("GET", f"/rcm/claims/{claim_id}/postings", headers=headers, params=params)

    def list_claim_statements(self, claim_id, headers, params=None):
        return self._request("GET", f"/rcm/claims/{claim_id}/statements", headers=headers, params=params)

    def scrub_claim(self, claim_id, headers):
        return self._request("POST", f"/rcm/claims/{claim_id}/scrub", {}, headers)

    def submit_claim(self, claim_id, headers):
        return self._request("POST", f"/rcm/claims/{claim_id}/submit", {}, headers)

    def accept_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/rcm/claims/{claim_id}/accept", payload or {}, headers)

    def close_claim(self, claim_id, headers):
        return self._request("POST", f"/rcm/claims/{claim_id}/close", {}, headers)

    # ---- Denial ----
    def create_denial(self, claim_id, payload, headers):
        return self._request("POST", f"/rcm/claims/{claim_id}/denials", payload, headers)

    def get_denial(self, denial_id, headers):
        return self._request("GET", f"/rcm/denials/{denial_id}", headers=headers)

    def list_denial_appeals(self, denial_id, headers, params=None):
        return self._request("GET", f"/rcm/denials/{denial_id}/appeals", headers=headers, params=params)

    # ---- Appeal ----
    def create_appeal(self, denial_id, payload, headers):
        return self._request("POST", f"/rcm/denials/{denial_id}/appeals", payload, headers)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/rcm/appeals/{appeal_id}", headers=headers)

    def submit_appeal(self, appeal_id, headers):
        return self._request("POST", f"/rcm/appeals/{appeal_id}/submit", {}, headers)

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/rcm/appeals/{appeal_id}/decision", payload, headers)

    # ---- Remittance / posting ----
    def create_remittance(self, payload, headers):
        return self._request("POST", "/rcm/remittances", payload, headers)

    def get_remittance(self, remittance_id, headers):
        return self._request("GET", f"/rcm/remittances/{remittance_id}", headers=headers)

    def create_posting(self, remittance_id, payload, headers):
        return self._request("POST", f"/rcm/remittances/{remittance_id}/postings", payload, headers)

    def list_remittance_postings(self, remittance_id, headers, params=None):
        return self._request("GET", f"/rcm/remittances/{remittance_id}/postings", headers=headers, params=params)

    def finalize_remittance(self, remittance_id, headers):
        return self._request("POST", f"/rcm/remittances/{remittance_id}/finalize", {}, headers)

    def get_posting(self, posting_id, headers):
        return self._request("GET", f"/rcm/payment-postings/{posting_id}", headers=headers)

    def reverse_posting(self, posting_id, payload, headers):
        return self._request("POST", f"/rcm/payment-postings/{posting_id}/reverse", payload, headers)

    # ---- Patient statement ----
    def create_statement(self, payload, headers):
        return self._request("POST", "/rcm/patient-statements", payload, headers)

    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/rcm/patient-statements/{statement_id}", headers=headers)

    def send_statement(self, statement_id, headers):
        return self._request("POST", f"/rcm/patient-statements/{statement_id}/send", {}, headers)

    def record_statement_payment(self, statement_id, payload, headers):
        return self._request("POST", f"/rcm/patient-statements/{statement_id}/record-payment", payload, headers)

    def statement_collections(self, statement_id, headers):
        return self._request("POST", f"/rcm/patient-statements/{statement_id}/collections", {}, headers)

    def writeoff_statement(self, statement_id, headers):
        return self._request("POST", f"/rcm/patient-statements/{statement_id}/write-off", {}, headers)


api_client = ApiClient()
