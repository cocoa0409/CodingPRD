"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Applicants ────────────────────────────────────────────────────
    def create_applicant(self, payload, headers):
        return self._request("POST", "/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/applicants/{applicant_id}", headers=headers)

    def list_applicants(self, headers, params=None):
        return self._request("GET", "/applicants", headers=headers, params=params)

    # ─── Applications ──────────────────────────────────────────────────
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def docket_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/docket", {}, headers)

    def pay_issue_fee(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/pay-issue-fee",
                             payload, headers)

    def convert_provisional(self, application_id, payload, headers):
        return self._request("POST",
                             f"/applications/{application_id}/convert-provisional-to-utility",
                             payload, headers)

    # ─── Office Actions ────────────────────────────────────────────────
    def create_office_action(self, payload, headers):
        return self._request("POST", "/office-actions", payload, headers)

    def get_office_action(self, oa_id, headers):
        return self._request("GET", f"/office-actions/{oa_id}", headers=headers)

    def list_office_actions(self, headers, params=None):
        return self._request("GET", "/office-actions", headers=headers, params=params)

    def create_office_action_response(self, payload, headers):
        return self._request("POST", "/office-action-responses", payload, headers)

    def get_office_action_response(self, oar_id, headers):
        return self._request("GET", f"/office-action-responses/{oar_id}", headers=headers)

    def list_office_action_responses(self, headers, params=None):
        return self._request("GET", "/office-action-responses", headers=headers, params=params)

    # ─── Maintenance Fees ──────────────────────────────────────────────
    def get_maintenance_fee(self, mf_id, headers):
        return self._request("GET", f"/maintenance-fees/{mf_id}", headers=headers)

    def list_maintenance_fees(self, headers, params=None):
        return self._request("GET", "/maintenance-fees", headers=headers, params=params)

    # ─── Fee Payments ──────────────────────────────────────────────────
    def create_fee_payment(self, payload, headers):
        return self._request("POST", "/fee-payments", payload, headers)

    def get_fee_payment(self, fp_id, headers):
        return self._request("GET", f"/fee-payments/{fp_id}", headers=headers)

    def list_fee_payments(self, headers, params=None):
        return self._request("GET", "/fee-payments", headers=headers, params=params)

    # ─── PCT Phase Entries ─────────────────────────────────────────────
    def create_pct_phase_entry(self, payload, headers):
        return self._request("POST", "/pct-phase-entries", payload, headers)

    def get_pct_phase_entry(self, pce_id, headers):
        return self._request("GET", f"/pct-phase-entries/{pce_id}", headers=headers)

    def list_pct_phase_entries(self, headers, params=None):
        return self._request("GET", "/pct-phase-entries", headers=headers, params=params)

    # ─── Test-driving endpoints ────────────────────────────────────────
    def set_current_utc(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def sweep_deadlines(self, headers):
        return self._request("POST", "/_jobs/sweep-deadlines", {}, headers)


api_client = ApiClient()
