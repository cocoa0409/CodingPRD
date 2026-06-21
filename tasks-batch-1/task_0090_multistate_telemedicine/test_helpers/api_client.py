"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; only the PRD-specific endpoint
methods are added here. Every method returns the raw requests.Response so tests
can assert status codes and envelope shape.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Physician registry ────────────────────────────
    def create_physician(self, payload, headers=None):
        return self._request("POST", "/physicians", payload, headers)

    def get_physician(self, physician_id, headers=None):
        return self._request("GET", f"/physicians/{physician_id}", headers=headers)

    def list_physicians(self, headers=None, params=None):
        return self._request("GET", "/physicians", headers=headers, params=params)

    def deactivate_physician(self, physician_id, headers=None):
        return self._request("POST", f"/physicians/{physician_id}/deactivate", headers=headers)

    # ── State licenses ────────────────────────────────
    def create_state_license(self, physician_id, payload, headers=None):
        return self._request("POST", f"/physicians/{physician_id}/state-licenses", payload, headers)

    def list_state_licenses(self, physician_id, headers=None, params=None):
        return self._request("GET", f"/physicians/{physician_id}/state-licenses", headers=headers, params=params)

    def get_state_license(self, license_id, headers=None):
        return self._request("GET", f"/state-licenses/{license_id}", headers=headers)

    def suspend_state_license(self, license_id, payload, headers=None):
        return self._request("POST", f"/state-licenses/{license_id}/suspend", payload, headers)

    def reinstate_state_license(self, license_id, headers=None):
        return self._request("POST", f"/state-licenses/{license_id}/reinstate", headers=headers)

    def revoke_state_license(self, license_id, headers=None):
        return self._request("POST", f"/state-licenses/{license_id}/revoke", headers=headers)

    # ── Patients ──────────────────────────────────────
    def create_patient(self, payload, headers=None):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers=None):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def list_patients(self, headers=None, params=None):
        return self._request("GET", "/patients", headers=headers, params=params)

    # ── Payers ────────────────────────────────────────
    def create_payer(self, payload, headers=None):
        return self._request("POST", "/payers", payload, headers)

    def get_payer(self, payer_id, headers=None):
        return self._request("GET", f"/payers/{payer_id}", headers=headers)

    # ── Visits ────────────────────────────────────────
    def create_visit(self, payload, headers=None):
        return self._request("POST", "/visits", payload, headers)

    def get_visit(self, visit_id, headers=None):
        return self._request("GET", f"/visits/{visit_id}", headers=headers)

    def list_visits(self, headers=None, params=None):
        return self._request("GET", "/visits", headers=headers, params=params)

    def run_compliance(self, visit_id, headers=None):
        return self._request("POST", f"/visits/{visit_id}/run-compliance", {}, headers)

    def override_compliance(self, visit_id, headers=None):
        return self._request("POST", f"/visits/{visit_id}/override-compliance", {}, headers)

    def approve_visit(self, visit_id, headers=None):
        return self._request("POST", f"/visits/{visit_id}/approve", {}, headers)

    def complete_visit(self, visit_id, headers=None):
        return self._request("POST", f"/visits/{visit_id}/complete", {}, headers)

    def cancel_visit(self, visit_id, headers=None):
        return self._request("POST", f"/visits/{visit_id}/cancel", {}, headers)

    def list_visit_compliance_checks(self, visit_id, headers=None, params=None):
        return self._request("GET", f"/visits/{visit_id}/compliance-checks", headers=headers, params=params)

    def list_license_compliance_checks(self, license_id, headers=None, params=None):
        return self._request("GET", f"/state-licenses/{license_id}/compliance-checks", headers=headers, params=params)

    # ── Prescriptions ─────────────────────────────────
    def create_prescription(self, visit_id, payload, headers=None):
        return self._request("POST", f"/visits/{visit_id}/prescriptions", payload, headers)

    def list_visit_prescriptions(self, visit_id, headers=None, params=None):
        return self._request("GET", f"/visits/{visit_id}/prescriptions", headers=headers, params=params)

    def get_prescription(self, prescription_id, headers=None):
        return self._request("GET", f"/prescriptions/{prescription_id}", headers=headers)

    # ── Claims ────────────────────────────────────────
    def list_visit_claims(self, visit_id, headers=None, params=None):
        return self._request("GET", f"/visits/{visit_id}/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers=None):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers=None, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def adjudicate_claim(self, claim_id, headers=None):
        return self._request("POST", f"/claims/{claim_id}/adjudicate", {}, headers)

    # ── Follow-ups ────────────────────────────────────
    def list_visit_follow_ups(self, visit_id, headers=None, params=None):
        return self._request("GET", f"/visits/{visit_id}/follow-ups", headers=headers, params=params)

    def get_follow_up(self, follow_up_id, headers=None):
        return self._request("GET", f"/follow-ups/{follow_up_id}", headers=headers)

    def list_follow_ups(self, headers=None, params=None):
        return self._request("GET", "/follow-ups", headers=headers, params=params)

    def fulfill_follow_up(self, follow_up_id, payload, headers=None):
        return self._request("POST", f"/follow-ups/{follow_up_id}/fulfill", payload, headers)

    def lapse_follow_up(self, follow_up_id, headers=None):
        return self._request("POST", f"/follow-ups/{follow_up_id}/lapse", {}, headers)

    # ── Test-driving clock ────────────────────────────
    def set_clock(self, payload, headers=None):
        return self._request("POST", "/_clock/set", payload, headers)

    def get_clock(self, headers=None):
        return self._request("GET", "/_clock", headers=headers)


api_client = ApiClient()
