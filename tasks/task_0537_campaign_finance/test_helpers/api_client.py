"""API client: one method per endpoint defined in the PRD (mounted under /disclosure)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/disclosure/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ---- Committee ----
    def create_committee(self, payload, headers):
        return self._request("POST", "/disclosure/committees", payload, headers)

    def get_committee(self, committee_id, headers):
        return self._request("GET", f"/disclosure/committees/{committee_id}", headers=headers)

    def list_committees(self, headers, params=None):
        return self._request("GET", "/disclosure/committees", headers=headers, params=params)

    def approve_committee(self, committee_id, headers):
        return self._request("POST", f"/disclosure/committees/{committee_id}/approve", {}, headers)

    def suspend_committee(self, committee_id, headers):
        return self._request("POST", f"/disclosure/committees/{committee_id}/suspend", {}, headers)

    def terminate_committee(self, committee_id, headers):
        return self._request("POST", f"/disclosure/committees/{committee_id}/terminate", {}, headers)

    # ---- Contribution ----
    def create_contribution(self, committee_id, payload, headers):
        return self._request("POST", f"/disclosure/committees/{committee_id}/contributions", payload, headers)

    def list_committee_contributions(self, committee_id, headers, params=None):
        return self._request("GET", f"/disclosure/committees/{committee_id}/contributions", headers=headers, params=params)

    def search_contributions(self, headers, params=None):
        return self._request("GET", "/disclosure/contributions", headers=headers, params=params)

    def get_contribution(self, contribution_id, headers):
        return self._request("GET", f"/disclosure/contributions/{contribution_id}", headers=headers)

    def deposit_contribution(self, contribution_id, headers):
        return self._request("POST", f"/disclosure/contributions/{contribution_id}/deposit", {}, headers)

    def refund_contribution(self, contribution_id, headers):
        return self._request("POST", f"/disclosure/contributions/{contribution_id}/refund", {}, headers)

    def void_contribution(self, contribution_id, headers):
        return self._request("POST", f"/disclosure/contributions/{contribution_id}/void", {}, headers)

    def flag_contribution(self, contribution_id, headers):
        return self._request("POST", f"/disclosure/contributions/{contribution_id}/flag", {}, headers)

    def clear_contribution(self, contribution_id, headers):
        return self._request("POST", f"/disclosure/contributions/{contribution_id}/clear", {}, headers)

    # ---- Expenditure ----
    def create_expenditure(self, committee_id, payload, headers):
        return self._request("POST", f"/disclosure/committees/{committee_id}/expenditures", payload, headers)

    def list_expenditures(self, committee_id, headers, params=None):
        return self._request("GET", f"/disclosure/committees/{committee_id}/expenditures", headers=headers, params=params)

    # ---- ReportingPeriod ----
    def create_reporting_period(self, payload, headers):
        return self._request("POST", "/disclosure/reporting-periods", payload, headers)

    def get_reporting_period(self, period_id, headers):
        return self._request("GET", f"/disclosure/reporting-periods/{period_id}", headers=headers)

    def close_reporting_period(self, period_id, headers):
        return self._request("POST", f"/disclosure/reporting-periods/{period_id}/close", {}, headers)

    # ---- Report ----
    def create_report(self, committee_id, payload, headers):
        return self._request("POST", f"/disclosure/committees/{committee_id}/reports", payload, headers)

    def list_committee_reports(self, committee_id, headers, params=None):
        return self._request("GET", f"/disclosure/committees/{committee_id}/reports", headers=headers, params=params)

    def list_period_reports(self, period_id, headers, params=None):
        return self._request("GET", f"/disclosure/reporting-periods/{period_id}/reports", headers=headers, params=params)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/disclosure/reports/{report_id}", headers=headers)

    def list_report_revisions(self, report_id, headers, params=None):
        return self._request("GET", f"/disclosure/reports/{report_id}/revisions", headers=headers, params=params)

    def file_report(self, report_id, headers):
        return self._request("POST", f"/disclosure/reports/{report_id}/file", {}, headers)

    def amend_report(self, report_id, headers):
        return self._request("POST", f"/disclosure/reports/{report_id}/amend", {}, headers)

    def audit_open_report(self, report_id, headers):
        return self._request("POST", f"/disclosure/reports/{report_id}/audit-open", {}, headers)

    def audit_close_report(self, report_id, headers):
        return self._request("POST", f"/disclosure/reports/{report_id}/audit-close", {}, headers)

    def waive_penalty(self, report_id, headers):
        return self._request("POST", f"/disclosure/reports/{report_id}/penalty/waive", {}, headers)

    # ---- LobbyingRegistrant ----
    def create_registrant(self, payload, headers):
        return self._request("POST", "/disclosure/registrants", payload, headers)

    def get_registrant(self, registrant_id, headers):
        return self._request("GET", f"/disclosure/registrants/{registrant_id}", headers=headers)

    def terminate_registrant(self, registrant_id, headers):
        return self._request("POST", f"/disclosure/registrants/{registrant_id}/terminate", {}, headers)

    # ---- Client ----
    def create_client(self, registrant_id, payload, headers):
        return self._request("POST", f"/disclosure/registrants/{registrant_id}/clients", payload, headers)

    def list_clients(self, registrant_id, headers, params=None):
        return self._request("GET", f"/disclosure/registrants/{registrant_id}/clients", headers=headers, params=params)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/disclosure/clients/{client_id}", headers=headers)

    def deactivate_client(self, client_id, headers):
        return self._request("POST", f"/disclosure/clients/{client_id}/deactivate", {}, headers)

    # ---- LobbyingReportingPeriod ----
    def create_lobbying_period(self, payload, headers):
        return self._request("POST", "/disclosure/lobbying-periods", payload, headers)

    def get_lobbying_period(self, period_id, headers):
        return self._request("GET", f"/disclosure/lobbying-periods/{period_id}", headers=headers)

    def close_lobbying_period(self, period_id, headers):
        return self._request("POST", f"/disclosure/lobbying-periods/{period_id}/close", {}, headers)

    # ---- LobbyingActivity ----
    def create_activity(self, registrant_id, payload, headers):
        return self._request("POST", f"/disclosure/registrants/{registrant_id}/activities", payload, headers)

    def list_registrant_activities(self, registrant_id, headers, params=None):
        return self._request("GET", f"/disclosure/registrants/{registrant_id}/activities", headers=headers, params=params)

    def list_client_activities(self, client_id, headers, params=None):
        return self._request("GET", f"/disclosure/clients/{client_id}/activities", headers=headers, params=params)

    def list_period_activities(self, period_id, headers, params=None):
        return self._request("GET", f"/disclosure/lobbying-periods/{period_id}/activities", headers=headers, params=params)

    def get_activity(self, activity_id, headers):
        return self._request("GET", f"/disclosure/activities/{activity_id}", headers=headers)

    def search_activities(self, headers, params=None):
        return self._request("GET", "/disclosure/activities", headers=headers, params=params)

    def void_activity(self, activity_id, headers):
        return self._request("POST", f"/disclosure/activities/{activity_id}/void", {}, headers)


api_client = ApiClient()
