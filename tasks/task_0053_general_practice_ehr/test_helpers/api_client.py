"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Providers ────────────────────────────────────────────────
    def create_provider(self, payload, headers):
        return self._request("POST", "/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/providers/{provider_id}", headers=headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", "/providers", headers=headers, params=params)

    def deactivate_provider(self, provider_id, headers):
        return self._request("POST", f"/providers/{provider_id}/deactivate", {}, headers)

    def bind_panel(self, provider_id, payload, headers):
        return self._request("POST", f"/providers/{provider_id}/panel", payload, headers)

    def list_provider_patients(self, provider_id, headers, params=None):
        return self._request("GET", f"/providers/{provider_id}/patients", headers=headers, params=params)

    def list_provider_referrals(self, provider_id, headers, params=None):
        return self._request("GET", f"/providers/{provider_id}/referrals", headers=headers, params=params)

    # ─── Patients ─────────────────────────────────────────────────
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/patients", headers=headers, params=params)

    def deactivate_patient(self, patient_id, headers):
        return self._request("POST", f"/patients/{patient_id}/deactivate", {}, headers)

    def record_payment(self, patient_id, payload, headers):
        return self._request("POST", f"/patients/{patient_id}/payments", payload, headers)

    def list_patient_visits(self, patient_id, headers, params=None):
        return self._request("GET", f"/patients/{patient_id}/visits", headers=headers, params=params)

    def list_patient_prescriptions(self, patient_id, headers, params=None):
        return self._request("GET", f"/patients/{patient_id}/prescriptions", headers=headers, params=params)

    def list_patient_referrals(self, patient_id, headers, params=None):
        return self._request("GET", f"/patients/{patient_id}/referrals", headers=headers, params=params)

    def list_patient_hedis_measures(self, patient_id, headers, params=None):
        return self._request("GET", f"/patients/{patient_id}/hedis-measures", headers=headers, params=params)

    def get_patient_portal_account(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}/portal-account", headers=headers)

    # ─── CPT codes ────────────────────────────────────────────────
    def create_cpt_code(self, payload, headers):
        return self._request("POST", "/cpt-codes", payload, headers)

    def get_cpt_code(self, cpt_id, headers):
        return self._request("GET", f"/cpt-codes/{cpt_id}", headers=headers)

    def list_cpt_codes(self, headers, params=None):
        return self._request("GET", "/cpt-codes", headers=headers, params=params)

    # ─── Visits ───────────────────────────────────────────────────
    def create_visit(self, payload, headers):
        return self._request("POST", "/visits", payload, headers)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/visits/{visit_id}", headers=headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", "/visits", headers=headers, params=params)

    def create_charge_line(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/charge-lines", payload, headers)

    def list_charge_lines(self, visit_id, headers, params=None):
        return self._request("GET", f"/visits/{visit_id}/charge-lines", headers=headers, params=params)

    def check_in_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/check-in", {}, headers)

    def start_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/start", {}, headers)

    def code_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/code", {}, headers)

    def reopen_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/reopen", {}, headers)

    def finalize_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/finalize", {}, headers)

    def cancel_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/cancel", {}, headers)

    def no_show_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/no-show", {}, headers)

    # ─── Prescriptions ────────────────────────────────────────────
    def create_prescription(self, payload, headers):
        return self._request("POST", "/prescriptions", payload, headers)

    def get_prescription(self, rx_id, headers):
        return self._request("GET", f"/prescriptions/{rx_id}", headers=headers)

    def list_prescriptions(self, headers, params=None):
        return self._request("GET", "/prescriptions", headers=headers, params=params)

    def submit_prescription(self, rx_id, headers):
        return self._request("POST", f"/prescriptions/{rx_id}/submit", {}, headers)

    def revise_prescription(self, rx_id, headers):
        return self._request("POST", f"/prescriptions/{rx_id}/revise", {}, headers)

    def sign_prescription(self, rx_id, payload, headers):
        return self._request("POST", f"/prescriptions/{rx_id}/sign", payload, headers)

    def transmit_prescription(self, rx_id, headers):
        return self._request("POST", f"/prescriptions/{rx_id}/transmit", {}, headers)

    def dispense_prescription(self, rx_id, headers):
        return self._request("POST", f"/prescriptions/{rx_id}/dispense", {}, headers)

    def void_prescription(self, rx_id, headers):
        return self._request("POST", f"/prescriptions/{rx_id}/void", {}, headers)

    # ─── Referrals ────────────────────────────────────────────────
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers)

    def get_referral(self, ref_id, headers):
        return self._request("GET", f"/referrals/{ref_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def authorize_referral(self, ref_id, headers):
        return self._request("POST", f"/referrals/{ref_id}/authorize", {}, headers)

    def deny_referral(self, ref_id, headers):
        return self._request("POST", f"/referrals/{ref_id}/deny", {}, headers)

    def schedule_referral(self, ref_id, headers):
        return self._request("POST", f"/referrals/{ref_id}/schedule", {}, headers)

    def expire_referral(self, ref_id, headers):
        return self._request("POST", f"/referrals/{ref_id}/expire", {}, headers)

    def complete_referral(self, ref_id, headers):
        return self._request("POST", f"/referrals/{ref_id}/complete", {}, headers)

    def cancel_referral(self, ref_id, headers):
        return self._request("POST", f"/referrals/{ref_id}/cancel", {}, headers)

    # ─── Portal accounts ──────────────────────────────────────────
    def create_portal_account(self, payload, headers):
        return self._request("POST", "/portal-accounts", payload, headers)

    def get_portal_account(self, pa_id, headers):
        return self._request("GET", f"/portal-accounts/{pa_id}", headers=headers)

    def activate_portal_account(self, pa_id, payload, headers):
        return self._request("POST", f"/portal-accounts/{pa_id}/activate", payload, headers)

    def suspend_portal_account(self, pa_id, headers):
        return self._request("POST", f"/portal-accounts/{pa_id}/suspend", {}, headers)

    def reinstate_portal_account(self, pa_id, headers):
        return self._request("POST", f"/portal-accounts/{pa_id}/reinstate", {}, headers)

    def deactivate_portal_account(self, pa_id, headers):
        return self._request("POST", f"/portal-accounts/{pa_id}/deactivate", {}, headers)

    # ─── HEDIS measures ───────────────────────────────────────────
    def create_hedis_measure(self, payload, headers):
        return self._request("POST", "/hedis-measures", payload, headers)

    def get_hedis_measure(self, hm_id, headers):
        return self._request("GET", f"/hedis-measures/{hm_id}", headers=headers)

    def exclude_hedis_measure(self, hm_id, headers):
        return self._request("POST", f"/hedis-measures/{hm_id}/exclude", {}, headers)

    def get_hedis_rate(self, headers, params=None):
        return self._request("GET", "/hedis/rate", headers=headers, params=params)

    # ─── Test-driving clock ───────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
