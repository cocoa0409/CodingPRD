"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Test-driving endpoints (logical clock, SLA sweep)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/inbox/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def run_sla_sweep(self, headers):
        return self._request("POST", "/inbox/_sla/sweep", {}, headers)

    # ------------------------------------------------------------------
    # Patients
    # ------------------------------------------------------------------
    def create_patient(self, payload, headers):
        return self._request("POST", "/inbox/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/inbox/patients/{patient_id}", headers=headers)

    # ------------------------------------------------------------------
    # Staff
    # ------------------------------------------------------------------
    def create_staff(self, payload, headers):
        return self._request("POST", "/inbox/staff", payload, headers)

    def get_staff(self, staff_id, headers):
        return self._request("GET", f"/inbox/staff/{staff_id}", headers=headers)

    def get_burden_summary(self, staff_id, headers, params=None):
        return self._request("GET", f"/inbox/staff/{staff_id}/burden-summary",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Pools
    # ------------------------------------------------------------------
    def create_pool(self, payload, headers):
        return self._request("POST", "/inbox/pools", payload, headers)

    def get_pool(self, pool_id, headers):
        return self._request("GET", f"/inbox/pools/{pool_id}", headers=headers)

    # ------------------------------------------------------------------
    # Coverage windows
    # ------------------------------------------------------------------
    def create_coverage_window(self, payload, headers):
        return self._request("POST", "/inbox/coverage-windows", payload, headers)

    def list_coverage_windows(self, headers, params=None):
        return self._request("GET", "/inbox/coverage-windows", headers=headers,
                             params=params)

    def get_coverage_window(self, window_id, headers):
        return self._request("GET", f"/inbox/coverage-windows/{window_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # On-call shifts
    # ------------------------------------------------------------------
    def create_on_call_shift(self, payload, headers):
        return self._request("POST", "/inbox/on-call-shifts", payload, headers)

    def list_on_call_shifts(self, headers, params=None):
        return self._request("GET", "/inbox/on-call-shifts", headers=headers,
                             params=params)

    def get_on_call_shift(self, shift_id, headers):
        return self._request("GET", f"/inbox/on-call-shifts/{shift_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Delegation grants
    # ------------------------------------------------------------------
    def create_delegation_grant(self, payload, headers):
        return self._request("POST", "/inbox/delegation-grants", payload, headers)

    def list_delegation_grants(self, headers, params=None):
        return self._request("GET", "/inbox/delegation-grants", headers=headers,
                             params=params)

    def get_delegation_grant(self, grant_id, headers):
        return self._request("GET", f"/inbox/delegation-grants/{grant_id}",
                             headers=headers)

    def revoke_delegation_grant(self, grant_id, headers):
        return self._request("POST", f"/inbox/delegation-grants/{grant_id}/revoke",
                             {}, headers)

    # ------------------------------------------------------------------
    # Portal messages
    # ------------------------------------------------------------------
    def create_portal_message(self, payload, headers):
        return self._request("POST", "/inbox/portal-messages", payload, headers)

    def list_portal_messages(self, headers, params=None):
        return self._request("GET", "/inbox/portal-messages", headers=headers,
                             params=params)

    def get_portal_message(self, message_id, headers):
        return self._request("GET", f"/inbox/portal-messages/{message_id}",
                             headers=headers)

    def triage_message(self, message_id, payload, headers):
        return self._request("POST", f"/inbox/portal-messages/{message_id}/triage",
                             payload, headers)

    def assign_message(self, message_id, payload, headers):
        return self._request("POST", f"/inbox/portal-messages/{message_id}/assign",
                             payload, headers)

    def start_review(self, message_id, headers):
        return self._request("POST",
                             f"/inbox/portal-messages/{message_id}/start-review",
                             {}, headers)

    def reply_message(self, message_id, payload, headers):
        return self._request("POST", f"/inbox/portal-messages/{message_id}/reply",
                             payload, headers)

    def complete_message(self, message_id, payload, headers):
        return self._request("POST",
                             f"/inbox/portal-messages/{message_id}/complete",
                             payload, headers)

    def cosign_message(self, message_id, payload, headers):
        return self._request("POST", f"/inbox/portal-messages/{message_id}/cosign",
                             payload, headers)

    def escalate_message(self, message_id, payload, headers):
        return self._request("POST",
                             f"/inbox/portal-messages/{message_id}/escalate",
                             payload, headers)

    def determine_billing(self, message_id, payload, headers):
        return self._request("POST",
                             f"/inbox/portal-messages/{message_id}/determine-billing",
                             payload, headers)

    def close_message(self, message_id, headers):
        return self._request("POST", f"/inbox/portal-messages/{message_id}/close",
                             {}, headers)

    # ------------------------------------------------------------------
    # Time entries
    # ------------------------------------------------------------------
    def create_time_entry(self, payload, headers):
        return self._request("POST", "/inbox/time-entries", payload, headers)

    def list_time_entries(self, headers, params=None):
        return self._request("GET", "/inbox/time-entries", headers=headers,
                             params=params)

    def get_time_entry(self, entry_id, headers):
        return self._request("GET", f"/inbox/time-entries/{entry_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Education notices
    # ------------------------------------------------------------------
    def create_education_notice(self, payload, headers):
        return self._request("POST", "/inbox/education-notices", payload, headers)

    def list_education_notices(self, headers, params=None):
        return self._request("GET", "/inbox/education-notices", headers=headers,
                             params=params)

    def get_education_notice(self, notice_id, headers):
        return self._request("GET", f"/inbox/education-notices/{notice_id}",
                             headers=headers)

    def acknowledge_education_notice(self, notice_id, headers):
        return self._request("POST",
                             f"/inbox/education-notices/{notice_id}/acknowledge",
                             {}, headers)

    # ------------------------------------------------------------------
    # Consent records
    # ------------------------------------------------------------------
    def list_consent_records(self, headers, params=None):
        return self._request("GET", "/inbox/consent-records", headers=headers,
                             params=params)

    def get_consent_record(self, consent_id, headers):
        return self._request("GET", f"/inbox/consent-records/{consent_id}",
                             headers=headers)

    def respond_consent(self, consent_id, payload, headers):
        return self._request("POST",
                             f"/inbox/consent-records/{consent_id}/respond",
                             payload, headers)

    # ------------------------------------------------------------------
    # E-visit claims
    # ------------------------------------------------------------------
    def create_evisit_claim(self, payload, headers):
        return self._request("POST", "/inbox/e-visit-claims", payload, headers)

    def list_evisit_claims(self, headers, params=None):
        return self._request("GET", "/inbox/e-visit-claims", headers=headers,
                             params=params)

    def get_evisit_claim(self, claim_id, headers):
        return self._request("GET", f"/inbox/e-visit-claims/{claim_id}",
                             headers=headers)

    def submit_claim(self, claim_id, headers):
        return self._request("POST", f"/inbox/e-visit-claims/{claim_id}/submit",
                             {}, headers)

    def record_adjudication(self, claim_id, payload, headers):
        return self._request("POST",
                             f"/inbox/e-visit-claims/{claim_id}/record-adjudication",
                             payload, headers)

    def rework_claim(self, claim_id, headers):
        return self._request("POST", f"/inbox/e-visit-claims/{claim_id}/rework",
                             {}, headers)

    def void_claim(self, claim_id, headers):
        return self._request("POST", f"/inbox/e-visit-claims/{claim_id}/void",
                             {}, headers)

    # ------------------------------------------------------------------
    # Escalations
    # ------------------------------------------------------------------
    def list_escalations(self, headers, params=None):
        return self._request("GET", "/inbox/escalations", headers=headers,
                             params=params)

    def get_escalation(self, escalation_id, headers):
        return self._request("GET", f"/inbox/escalations/{escalation_id}",
                             headers=headers)

    def acknowledge_escalation(self, escalation_id, headers):
        return self._request("POST",
                             f"/inbox/escalations/{escalation_id}/acknowledge",
                             {}, headers)


api_client = ApiClient()
