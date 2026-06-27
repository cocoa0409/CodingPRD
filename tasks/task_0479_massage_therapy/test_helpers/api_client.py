"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # ---- Modality ----
    def create_modality(self, payload, headers):
        return self._request("POST", "/practice/modalities", payload, headers)

    def get_modality(self, modality_id, headers):
        return self._request("GET", f"/practice/modalities/{modality_id}", headers=headers)

    def list_modalities(self, headers, params=None):
        return self._request("GET", "/practice/modalities", headers=headers, params=params)

    # ---- Therapist ----
    def create_therapist(self, payload, headers):
        return self._request("POST", "/practice/therapists", payload, headers)

    def get_therapist(self, therapist_id, headers):
        return self._request("GET", f"/practice/therapists/{therapist_id}", headers=headers)

    def list_therapists(self, headers, params=None):
        return self._request("GET", "/practice/therapists", headers=headers, params=params)

    def reset_commission(self, therapist_id, headers):
        return self._request("POST", f"/practice/therapists/{therapist_id}/reset-commission", {}, headers)

    # ---- TherapistCertification ----
    def create_certification(self, payload, headers):
        return self._request("POST", "/practice/certifications", payload, headers)

    def get_certification(self, cert_id, headers):
        return self._request("GET", f"/practice/certifications/{cert_id}", headers=headers)

    def list_certifications(self, headers, params=None):
        return self._request("GET", "/practice/certifications", headers=headers, params=params)

    # ---- Table ----
    def create_table(self, payload, headers):
        return self._request("POST", "/practice/tables", payload, headers)

    def get_table(self, table_id, headers):
        return self._request("GET", f"/practice/tables/{table_id}", headers=headers)

    def list_tables(self, headers, params=None):
        return self._request("GET", "/practice/tables", headers=headers, params=params)

    # ---- Client ----
    def create_client(self, payload, headers):
        return self._request("POST", "/practice/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/practice/clients/{client_id}", headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/practice/clients", headers=headers, params=params)

    def adjust_wallet(self, client_id, payload, headers):
        return self._request("POST", f"/practice/clients/{client_id}/wallet-adjustments", payload, headers)

    # ---- Intake ----
    def create_intake(self, payload, headers):
        return self._request("POST", "/practice/intakes", payload, headers)

    def get_intake(self, intake_id, headers):
        return self._request("GET", f"/practice/intakes/{intake_id}", headers=headers)

    def list_intakes(self, headers, params=None):
        return self._request("GET", "/practice/intakes", headers=headers, params=params)

    def sign_intake(self, intake_id, headers):
        return self._request("POST", f"/practice/intakes/{intake_id}/sign", {}, headers)

    # ---- ConsentRecord ----
    def create_consent(self, payload, headers):
        return self._request("POST", "/practice/consent-records", payload, headers)

    def get_consent(self, consent_id, headers):
        return self._request("GET", f"/practice/consent-records/{consent_id}", headers=headers)

    def list_consents(self, headers, params=None):
        return self._request("GET", "/practice/consent-records", headers=headers, params=params)

    def revoke_consent(self, consent_id, headers):
        return self._request("POST", f"/practice/consent-records/{consent_id}/revoke", {}, headers)

    # ---- MembershipPlan ----
    def create_plan(self, payload, headers):
        return self._request("POST", "/practice/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/practice/plans/{plan_id}", headers=headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/practice/plans", headers=headers, params=params)

    # ---- Package ----
    def create_package(self, payload, headers):
        return self._request("POST", "/practice/packages", payload, headers)

    def get_package(self, package_id, headers):
        return self._request("GET", f"/practice/packages/{package_id}", headers=headers)

    def list_packages(self, headers, params=None):
        return self._request("GET", "/practice/packages", headers=headers, params=params)

    def get_package_ledger(self, package_id, headers, params=None):
        return self._request("GET", f"/practice/packages/{package_id}/ledger", headers=headers, params=params)

    def renew_package(self, package_id, headers):
        return self._request("POST", f"/practice/packages/{package_id}/renew", {}, headers)

    def suspend_package(self, package_id, headers):
        return self._request("POST", f"/practice/packages/{package_id}/suspend", {}, headers)

    def resume_package(self, package_id, headers):
        return self._request("POST", f"/practice/packages/{package_id}/resume", {}, headers)

    def cancel_membership(self, package_id, headers):
        return self._request("POST", f"/practice/packages/{package_id}/cancel-membership", {}, headers)

    # ---- CommissionTier ----
    def create_commission_tier(self, payload, headers):
        return self._request("POST", "/practice/commission-tiers", payload, headers)

    def list_commission_tiers(self, headers, params=None):
        return self._request("GET", "/practice/commission-tiers", headers=headers, params=params)

    # ---- Appointment ----
    def create_appointment(self, payload, headers):
        return self._request("POST", "/practice/appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/practice/appointments/{appointment_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/practice/appointments", headers=headers, params=params)

    def check_in_appointment(self, appointment_id, headers):
        return self._request("POST", f"/practice/appointments/{appointment_id}/check-in", {}, headers)

    def complete_appointment(self, appointment_id, headers):
        return self._request("POST", f"/practice/appointments/{appointment_id}/complete", {}, headers)

    def cancel_appointment(self, appointment_id, payload, headers):
        return self._request("POST", f"/practice/appointments/{appointment_id}/cancel", payload, headers)

    def no_show_appointment(self, appointment_id, headers):
        return self._request("POST", f"/practice/appointments/{appointment_id}/no-show", {}, headers)

    def waive_no_show(self, appointment_id, headers):
        return self._request("POST", f"/practice/appointments/{appointment_id}/waive-no-show", {}, headers)

    def price_appointment(self, appointment_id, headers):
        return self._request("POST", f"/practice/appointments/{appointment_id}/price", {}, headers)

    def pay_appointment(self, appointment_id, payload, headers):
        return self._request("POST", f"/practice/appointments/{appointment_id}/pay", payload, headers)

    def void_appointment(self, appointment_id, headers):
        return self._request("POST", f"/practice/appointments/{appointment_id}/void", {}, headers)

    # ---- SoapNote ----
    def create_soap_note(self, payload, headers):
        return self._request("POST", "/practice/soap-notes", payload, headers)

    def get_soap_note(self, note_id, headers):
        return self._request("GET", f"/practice/soap-notes/{note_id}", headers=headers)

    def list_soap_notes(self, headers, params=None):
        return self._request("GET", "/practice/soap-notes", headers=headers, params=params)

    def edit_soap_note(self, note_id, payload, headers):
        return self._request("PATCH", f"/practice/soap-notes/{note_id}", payload, headers)

    def finalize_soap_note(self, note_id, headers):
        return self._request("POST", f"/practice/soap-notes/{note_id}/finalize", {}, headers)

    def reopen_soap_note(self, note_id, headers):
        return self._request("POST", f"/practice/soap-notes/{note_id}/reopen", {}, headers)

    # ---- Superbill ----
    def create_superbill(self, payload, headers):
        return self._request("POST", "/practice/superbills", payload, headers)

    def get_superbill(self, superbill_id, headers):
        return self._request("GET", f"/practice/superbills/{superbill_id}", headers=headers)

    def list_superbills(self, headers, params=None):
        return self._request("GET", "/practice/superbills", headers=headers, params=params)

    def void_superbill(self, superbill_id, headers):
        return self._request("POST", f"/practice/superbills/{superbill_id}/void", {}, headers)


api_client = ApiClient()
