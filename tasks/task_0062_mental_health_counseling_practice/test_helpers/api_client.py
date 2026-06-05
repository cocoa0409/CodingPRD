"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Therapist ---
    def create_therapist(self, payload, headers):
        return self._request("POST", "/therapists", payload, headers)

    def get_therapist(self, therapist_id, headers):
        return self._request("GET", f"/therapists/{therapist_id}", headers=headers)

    def list_therapists(self, headers, params=None):
        return self._request("GET", "/therapists", headers=headers, params=params)

    def promote_therapist(self, therapist_id, payload, headers):
        return self._request("POST", f"/therapists/{therapist_id}/promote", payload, headers)

    def suspend_therapist(self, therapist_id, payload, headers):
        return self._request("POST", f"/therapists/{therapist_id}/suspend", payload, headers)

    # --- StateLicense ---
    def create_state_license(self, payload, headers):
        return self._request("POST", "/state-licenses", payload, headers)

    def get_state_license(self, license_id, headers):
        return self._request("GET", f"/state-licenses/{license_id}", headers=headers)

    def list_state_licenses(self, headers, params=None):
        return self._request("GET", "/state-licenses", headers=headers, params=params)

    def revoke_state_license(self, license_id, headers):
        return self._request("POST", f"/state-licenses/{license_id}/revoke", {}, headers)

    # --- SupervisionLog ---
    def create_supervision_log(self, payload, headers):
        return self._request("POST", "/supervision-logs", payload, headers)

    def get_supervision_log(self, log_id, headers):
        return self._request("GET", f"/supervision-logs/{log_id}", headers=headers)

    def list_supervision_logs(self, headers, params=None):
        return self._request("GET", "/supervision-logs", headers=headers, params=params)

    def accept_supervision_log(self, log_id, headers):
        return self._request("POST", f"/supervision-logs/{log_id}/accept", {}, headers)

    def reject_supervision_log(self, log_id, headers):
        return self._request("POST", f"/supervision-logs/{log_id}/reject", {}, headers)

    # --- Patient ---
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/patients", headers=headers, params=params)

    def patch_patient_financials(self, patient_id, payload, headers):
        return self._request("PATCH", f"/patients/{patient_id}/financials", payload, headers)

    # --- InsurancePolicy ---
    def create_insurance_policy(self, payload, headers):
        return self._request("POST", "/insurance-policies", payload, headers)

    def get_insurance_policy(self, policy_id, headers):
        return self._request("GET", f"/insurance-policies/{policy_id}", headers=headers)

    def list_insurance_policies(self, headers, params=None):
        return self._request("GET", "/insurance-policies", headers=headers, params=params)

    # --- PayerContract ---
    def create_payer_contract(self, payload, headers):
        return self._request("POST", "/payer-contracts", payload, headers)

    def get_payer_contract(self, contract_id, headers):
        return self._request("GET", f"/payer-contracts/{contract_id}", headers=headers)

    # --- Appointment ---
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def render_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/render", {}, headers)

    def complete_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/complete", {}, headers)

    def write_off_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/write-off", {}, headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/cancel", {}, headers)

    # --- ClinicalNote ---
    def create_clinical_note(self, payload, headers):
        return self._request("POST", "/clinical-notes", payload, headers)

    def get_clinical_note(self, note_id, headers):
        return self._request("GET", f"/clinical-notes/{note_id}", headers=headers)

    def list_clinical_notes(self, headers, params=None):
        return self._request("GET", "/clinical-notes", headers=headers, params=params)

    def sign_clinical_note(self, note_id, headers):
        return self._request("POST", f"/clinical-notes/{note_id}/sign", {}, headers)

    def cosign_clinical_note(self, note_id, headers):
        return self._request("POST", f"/clinical-notes/{note_id}/cosign", {}, headers)

    # --- Claim ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/adjudicate", payload, headers)

    def deny_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/deny", payload, headers)

    def resubmit_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/resubmit", payload, headers)

    def void_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/void", payload, headers)

    # --- CrisisAssessment ---
    def create_crisis_assessment(self, payload, headers):
        return self._request("POST", "/crisis-assessments", payload, headers)

    def get_crisis_assessment(self, assessment_id, headers):
        return self._request("GET", f"/crisis-assessments/{assessment_id}", headers=headers)

    def list_crisis_assessments(self, headers, params=None):
        return self._request("GET", "/crisis-assessments", headers=headers, params=params)

    def resolve_crisis_assessment(self, assessment_id, headers):
        return self._request("POST", f"/crisis-assessments/{assessment_id}/resolve", {}, headers)

    # --- SafetyPlan ---
    def create_safety_plan(self, payload, headers):
        return self._request("POST", "/safety-plans", payload, headers)

    def get_safety_plan(self, plan_id, headers):
        return self._request("GET", f"/safety-plans/{plan_id}", headers=headers)

    def list_safety_plans(self, headers, params=None):
        return self._request("GET", "/safety-plans", headers=headers, params=params)

    # --- Test-driving endpoints ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def inject_therapist_hours(self, payload, headers):
        return self._request("POST", "/_inject/therapist_hours", payload, headers)


api_client = ApiClient()
