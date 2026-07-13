"""API client: one method per endpoint defined in the PRD.

Subclasses the framework GenericApiClient, which supplies the inherited
_request(method, path, json_body=None, headers=None, params=None).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Reports ----
    def create_report(self, payload, headers):
        return self._request("POST", "/reports", payload, headers)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/reports/{report_id}", headers=headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/reports", headers=headers, params=params)

    def screen_report(self, report_id, payload, headers):
        return self._request("POST", f"/reports/{report_id}/screen", payload, headers)

    # ---- Clients ----
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def capacity_determination(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/capacity-determination", payload, headers)

    def create_risk_assessment(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/risk-assessments", payload, headers)

    # ---- Financial accounts ----
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    # ---- Facilities ----
    def create_facility(self, payload, headers):
        return self._request("POST", "/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/facilities/{facility_id}", headers=headers)

    # ---- Cases ----
    def get_case(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/cases", headers=headers, params=params)

    def close_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/close", payload, headers)

    def cross_report_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/cross-report", payload, headers)

    def recover_funds(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/recover-funds", payload, headers)

    def refer_guardianship(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/refer-guardianship", payload, headers)

    def create_service_plan(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/service-plan", payload, headers)

    # ---- Investigations ----
    def create_investigation(self, payload, headers):
        return self._request("POST", "/investigations", payload, headers)

    def get_investigation(self, investigation_id, headers):
        return self._request("GET", f"/investigations/{investigation_id}", headers=headers)

    def list_investigations(self, headers, params=None):
        return self._request("GET", "/investigations", headers=headers, params=params)

    def submit_findings(self, investigation_id, payload, headers):
        return self._request("POST", f"/investigations/{investigation_id}/submit-findings", payload, headers)

    def return_findings(self, investigation_id, payload, headers):
        return self._request("POST", f"/investigations/{investigation_id}/return", payload, headers)

    def dispose_investigation(self, investigation_id, payload, headers):
        return self._request("POST", f"/investigations/{investigation_id}/dispose", payload, headers)

    # ---- Placements ----
    def create_placement(self, payload, headers):
        return self._request("POST", "/placements", payload, headers)

    def get_placement(self, placement_id, headers):
        return self._request("GET", f"/placements/{placement_id}", headers=headers)

    def list_placements(self, headers, params=None):
        return self._request("GET", "/placements", headers=headers, params=params)

    def discharge_placement(self, placement_id, headers):
        return self._request("POST", f"/placements/{placement_id}/discharge", {}, headers)

    def review_placement(self, placement_id, headers):
        return self._request("POST", f"/placements/{placement_id}/review", {}, headers)

    # ---- Freezes ----
    def create_freeze(self, payload, headers):
        return self._request("POST", "/freezes", payload, headers)

    def get_freeze(self, freeze_id, headers):
        return self._request("GET", f"/freezes/{freeze_id}", headers=headers)

    def list_freezes(self, headers, params=None):
        return self._request("GET", "/freezes", headers=headers, params=params)

    def lift_freeze(self, freeze_id, headers):
        return self._request("POST", f"/freezes/{freeze_id}/lift", {}, headers)

    # ---- Clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
