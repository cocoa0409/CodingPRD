"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock / reference data ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def create_per_diem_locality(self, payload, headers):
        return self._request("POST", "/per-diem-localities", payload, headers)

    def create_facility(self, payload, headers):
        return self._request("POST", "/facilities", payload, headers)

    # --- Clinician ---
    def create_clinician(self, payload, headers):
        return self._request("POST", "/clinicians", payload, headers)

    def get_clinician(self, clinician_id, headers):
        return self._request("GET", f"/clinicians/{clinician_id}", headers=headers)

    def list_clinician_licenses(self, clinician_id, headers, params=None):
        return self._request("GET", f"/clinicians/{clinician_id}/licenses", headers=headers, params=params)

    # --- License ---
    def create_license(self, payload, headers):
        return self._request("POST", "/licenses", payload, headers)

    def transition_license(self, license_id, to, headers):
        return self._request("POST", f"/licenses/{license_id}/transition", {"to": to}, headers)

    # --- Assignment ---
    def create_assignment(self, payload, headers):
        return self._request("POST", "/assignments", payload, headers)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def activate_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/activate", headers=headers)

    def cancel_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/assignments/{assignment_id}/cancel", payload, headers)

    def list_assignment_contracts(self, assignment_id, headers, params=None):
        return self._request("GET", f"/assignments/{assignment_id}/contracts", headers=headers, params=params)

    def list_assignment_credential_packets(self, assignment_id, headers, params=None):
        return self._request("GET", f"/assignments/{assignment_id}/credential-packets", headers=headers, params=params)

    def list_assignment_timesheets(self, assignment_id, headers, params=None):
        return self._request("GET", f"/assignments/{assignment_id}/timesheets", headers=headers, params=params)

    def list_assignment_extensions(self, assignment_id, headers, params=None):
        return self._request("GET", f"/assignments/{assignment_id}/extensions", headers=headers, params=params)

    # --- Contract ---
    def transition_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/transition", payload, headers)

    def revise_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/revise", payload, headers)

    # --- Credential packet / item ---
    def get_credential_packet(self, packet_id, headers):
        return self._request("GET", f"/credential-packets/{packet_id}", headers=headers)

    def list_credential_packet_items(self, packet_id, headers, params=None):
        return self._request("GET", f"/credential-packets/{packet_id}/items", headers=headers, params=params)

    def create_credential_item(self, packet_id, payload, headers):
        return self._request("POST", f"/credential-packets/{packet_id}/items", payload, headers)

    def transition_credential_packet(self, packet_id, to, headers):
        return self._request("POST", f"/credential-packets/{packet_id}/transition", {"to": to}, headers)

    def transition_credential_item(self, item_id, to, headers):
        return self._request("POST", f"/credential-items/{item_id}/transition", {"to": to}, headers)

    # --- Timesheet ---
    def create_timesheet(self, payload, headers):
        return self._request("POST", "/timesheets", payload, headers)

    def transition_timesheet(self, timesheet_id, payload, headers):
        return self._request("POST", f"/timesheets/{timesheet_id}/transition", payload, headers)

    # --- Earnings statements ---
    def get_earnings_statement(self, statement_id, headers):
        return self._request("GET", f"/earnings-statements/{statement_id}", headers=headers)

    def list_earnings_statements(self, headers, params=None):
        return self._request("GET", "/earnings-statements", headers=headers, params=params)

    # --- Payroll runs ---
    def create_payroll_run(self, payload, headers):
        return self._request("POST", "/payroll-runs", payload, headers)

    def transition_payroll_run(self, run_id, to, headers):
        return self._request("POST", f"/payroll-runs/{run_id}/transition", {"to": to}, headers)

    # --- Extension negotiations ---
    def create_extension(self, assignment_id, payload, headers):
        return self._request("POST", f"/assignments/{assignment_id}/extensions", payload, headers)

    def respond_extension(self, extension_id, payload, headers):
        return self._request("POST", f"/extension-requests/{extension_id}/respond", payload, headers)


api_client = ApiClient()
