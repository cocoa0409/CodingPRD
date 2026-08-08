"""API client: one method per endpoint defined in the Cardiac & Pulmonary Rehab PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Patients ----
    def create_patient(self, payload, headers):
        return self._request("POST", "/rehab/patients", payload, headers=headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/rehab/patients/{patient_id}", headers=headers)

    # ---- Physicians ----
    def create_physician(self, payload, headers):
        return self._request("POST", "/rehab/physicians", payload, headers=headers)

    def get_physician(self, physician_id, headers):
        return self._request("GET", f"/rehab/physicians/{physician_id}", headers=headers)

    # ---- Clinicians ----
    def create_clinician(self, payload, headers):
        return self._request("POST", "/rehab/clinicians", payload, headers=headers)

    def get_clinician(self, clinician_id, headers):
        return self._request("GET", f"/rehab/clinicians/{clinician_id}", headers=headers)

    # ---- Monitoring stations ----
    def create_station(self, payload, headers):
        return self._request("POST", "/rehab/stations", payload, headers=headers)

    def get_station(self, station_id, headers):
        return self._request("GET", f"/rehab/stations/{station_id}", headers=headers)

    # ---- Referrals ----
    def create_referral(self, payload, headers):
        return self._request("POST", "/rehab/referrals", payload, headers=headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/rehab/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/rehab/referrals", headers=headers, params=params)

    def decide_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/rehab/referrals/{referral_id}/decision", payload, headers=headers)

    # ---- Programs ----
    def create_program(self, payload, headers):
        return self._request("POST", "/rehab/programs", payload, headers=headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/rehab/programs/{program_id}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/rehab/programs", headers=headers, params=params)

    def activate_program(self, program_id, headers, payload=None):
        return self._request("POST", f"/rehab/programs/{program_id}/activate", payload or {}, headers=headers)

    def hold_program(self, program_id, headers, payload=None):
        return self._request("POST", f"/rehab/programs/{program_id}/hold", payload or {}, headers=headers)

    def resume_program(self, program_id, headers, payload=None):
        return self._request("POST", f"/rehab/programs/{program_id}/resume", payload or {}, headers=headers)

    def discharge_program(self, program_id, headers, payload=None):
        return self._request("POST", f"/rehab/programs/{program_id}/discharge", payload or {}, headers=headers)

    def withdraw_program(self, program_id, headers, payload=None):
        return self._request("POST", f"/rehab/programs/{program_id}/withdraw", payload or {}, headers=headers)

    def get_statement(self, program_id, headers):
        return self._request("GET", f"/rehab/programs/{program_id}/statement", headers=headers)

    # ---- Insurance authorizations ----
    def create_authorization(self, payload, headers):
        return self._request("POST", "/rehab/authorizations", payload, headers=headers)

    def get_authorization(self, authorization_id, headers):
        return self._request("GET", f"/rehab/authorizations/{authorization_id}", headers=headers)

    def list_authorizations(self, headers, params=None):
        return self._request("GET", "/rehab/authorizations", headers=headers, params=params)

    def approve_authorization(self, authorization_id, headers, payload=None):
        return self._request("POST", f"/rehab/authorizations/{authorization_id}/approve", payload or {}, headers=headers)

    # ---- Sessions ----
    def create_session(self, payload, headers):
        return self._request("POST", "/rehab/sessions", payload, headers=headers)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/rehab/sessions/{session_id}", headers=headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/rehab/sessions", headers=headers, params=params)

    def complete_session(self, session_id, payload, headers):
        return self._request("POST", f"/rehab/sessions/{session_id}/complete", payload or {}, headers=headers)

    def mark_missed_session(self, session_id, headers, payload=None):
        return self._request("POST", f"/rehab/sessions/{session_id}/mark-missed", payload or {}, headers=headers)

    def reschedule_session(self, session_id, payload, headers):
        return self._request("POST", f"/rehab/sessions/{session_id}/reschedule", payload, headers=headers)

    def cancel_session(self, session_id, headers, payload=None):
        return self._request("POST", f"/rehab/sessions/{session_id}/cancel", payload or {}, headers=headers)

    def void_session(self, session_id, headers, payload=None):
        return self._request("POST", f"/rehab/sessions/{session_id}/void", payload or {}, headers=headers)

    # ---- Care plan items ----
    def create_care_plan_item(self, payload, headers):
        return self._request("POST", "/rehab/care-plan-items", payload, headers=headers)

    def get_care_plan_item(self, item_id, headers):
        return self._request("GET", f"/rehab/care-plan-items/{item_id}", headers=headers)

    def list_care_plan_items(self, headers, params=None):
        return self._request("GET", "/rehab/care-plan-items", headers=headers, params=params)

    def resolve_care_plan_item(self, item_id, payload, headers):
        return self._request("POST", f"/rehab/care-plan-items/{item_id}/resolve", payload, headers=headers)

    # ---- Outcome assessments ----
    def create_outcome(self, payload, headers):
        return self._request("POST", "/rehab/outcomes", payload, headers=headers)

    def get_outcome(self, outcome_id, headers):
        return self._request("GET", f"/rehab/outcomes/{outcome_id}", headers=headers)

    def list_outcomes(self, headers, params=None):
        return self._request("GET", "/rehab/outcomes", headers=headers, params=params)

    def finalize_outcome(self, outcome_id, payload, headers):
        return self._request("POST", f"/rehab/outcomes/{outcome_id}/finalize", payload or {}, headers=headers)

    # ---- Billing claims ----
    def create_claim(self, payload, headers):
        return self._request("POST", "/rehab/claims", payload, headers=headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/rehab/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/rehab/claims", headers=headers, params=params)

    def submit_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/rehab/claims/{claim_id}/submit", payload or {}, headers=headers)

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/rehab/claims/{claim_id}/adjudicate", payload, headers=headers)

    def resubmit_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/rehab/claims/{claim_id}/resubmit", payload or {}, headers=headers)

    def void_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/rehab/claims/{claim_id}/void", payload or {}, headers=headers)

    # ---- Maintenance programs ----
    def get_maintenance_program(self, maintenance_id, headers):
        return self._request("GET", f"/rehab/maintenance-programs/{maintenance_id}", headers=headers)

    def list_maintenance_programs(self, headers, params=None):
        return self._request("GET", "/rehab/maintenance-programs", headers=headers, params=params)

    def cancel_maintenance_program(self, maintenance_id, headers, payload=None):
        return self._request("POST", f"/rehab/maintenance-programs/{maintenance_id}/cancel", payload or {}, headers=headers)

    # ---- Test-driving: logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers=headers)


api_client = ApiClient()
