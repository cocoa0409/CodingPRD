"""API client: one method per endpoint defined in PRD §4.

Each method delegates to GenericApiClient._request and returns the raw
Response object. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every call.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Organizations (PRD §3.1, §4)
    # =======================================================================
    def create_organization(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", "/organizations", payload, headers)

    def get_organization(self, org_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/organizations/{org_id}",
                             headers=headers)

    def update_organization(self, org_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("PATCH", f"/organizations/{org_id}",
                             payload, headers)

    # =======================================================================
    # Facilities (PRD §3.1, §4)
    # =======================================================================
    def create_facility(self, org_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", f"/organizations/{org_id}/facilities",
                             payload, headers)

    def update_facility(self, org_id: str, facility_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/organizations/{org_id}/facilities/{facility_id}",
            payload, headers,
        )

    def list_facilities(self, org_id: str, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/organizations/{org_id}/facilities",
            headers=headers, params=params,
        )

    # =======================================================================
    # Boundary changes (PRD §3.1, §4)
    # =======================================================================
    def create_boundary_change(self, org_id: str, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/organizations/{org_id}/boundary-changes",
            payload, headers,
        )

    def list_boundary_changes(self, org_id: str, headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/organizations/{org_id}/boundary-changes",
            headers=headers, params=params,
        )

    # =======================================================================
    # Reporting periods (PRD §3.2, §4)
    # =======================================================================
    def create_reporting_period(self, org_id: str, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/organizations/{org_id}/reporting-periods",
            payload, headers,
        )

    def update_reporting_period(self, org_id: str, period_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "PATCH",
            f"/organizations/{org_id}/reporting-periods/{period_id}",
            payload, headers,
        )

    def close_reporting_period(self, org_id: str, period_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/organizations/{org_id}/reporting-periods/{period_id}/close",
            payload or {}, headers,
        )

    def cancel_reporting_period(self, org_id: str, period_id: str,
                                headers: Dict[str, str],
                                payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/organizations/{org_id}/reporting-periods/{period_id}/cancel",
            payload or {}, headers,
        )

    # =======================================================================
    # Emission sources (PRD §3.3, §4)
    # =======================================================================
    def create_source(self, org_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/organizations/{org_id}/sources",
            payload, headers,
        )

    def update_source(self, org_id: str, source_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/organizations/{org_id}/sources/{source_id}",
            payload, headers,
        )

    def list_sources(self, org_id: str, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/organizations/{org_id}/sources",
            headers=headers, params=params,
        )

    def get_source(self, org_id: str, source_id: str,
                   headers: Dict[str, str]):
        # GET single source is not in the PRD directly, but the list endpoint
        # works for reads. Provide a list helper instead and look up by id.
        return self.list_sources(org_id, headers, params={"limit": 100})

    # =======================================================================
    # Emission factors (PRD §3.4, §4)
    # =======================================================================
    def create_factor(self, org_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/organizations/{org_id}/factors",
            payload, headers,
        )

    def approve_factor(self, org_id: str, factor_id: str,
                       headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/organizations/{org_id}/factors/{factor_id}/approve",
            payload or {}, headers,
        )

    def delete_factor(self, org_id: str, factor_id: str,
                      headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "DELETE", f"/organizations/{org_id}/factors/{factor_id}",
            headers=headers, params=params,
        )

    def list_factors(self, org_id: str, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/organizations/{org_id}/factors",
            headers=headers, params=params,
        )

    # =======================================================================
    # Activity data (PRD §3.5, §4)
    # =======================================================================
    def create_activity_data(self, org_id: str, period_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST",
            (f"/organizations/{org_id}/reporting-periods/"
             f"{period_id}/activity-data"),
            payload, headers,
        )

    def list_activity_data(self, org_id: str, period_id: str,
                           headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            (f"/organizations/{org_id}/reporting-periods/"
             f"{period_id}/activity-data"),
            headers=headers, params=params,
        )

    def list_emission_records(self, org_id: str, period_id: str,
                              headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            (f"/organizations/{org_id}/reporting-periods/"
             f"{period_id}/emission-records"),
            headers=headers, params=params,
        )

    # =======================================================================
    # Reduction projects (PRD §3.6, §4)
    # =======================================================================
    def create_project(self, org_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/organizations/{org_id}/projects",
            payload, headers,
        )

    def activate_project(self, org_id: str, project_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/organizations/{org_id}/projects/{project_id}/activate",
            payload or {}, headers,
        )

    def complete_project(self, org_id: str, project_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/organizations/{org_id}/projects/{project_id}/complete",
            payload or {}, headers,
        )

    def cancel_project(self, org_id: str, project_id: str,
                       headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/organizations/{org_id}/projects/{project_id}/cancel",
            payload or {}, headers,
        )

    # =======================================================================
    # Carbon credits (PRD §3.6, §4)
    # =======================================================================
    def create_credit(self, org_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/organizations/{org_id}/credits",
            payload, headers,
        )

    def retire_credit(self, org_id: str, credit_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/organizations/{org_id}/credits/{credit_id}/retire",
            payload, headers,
        )

    def transfer_credit(self, org_id: str, credit_id: str,
                        headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/organizations/{org_id}/credits/{credit_id}/transfer",
            payload or {}, headers,
        )

    # =======================================================================
    # Reports (PRD §3.7, §4)
    # =======================================================================
    def create_report(self, org_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/organizations/{org_id}/reports",
            payload, headers,
        )

    def compile_report(self, org_id: str, report_id: str,
                       headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/organizations/{org_id}/reports/{report_id}/compile",
            payload or {}, headers,
        )

    def verify_report(self, org_id: str, report_id: str,
                      headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/organizations/{org_id}/reports/{report_id}/verify",
            payload or {}, headers,
        )

    def request_revisions(self, org_id: str, report_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            (f"/organizations/{org_id}/reports/"
             f"{report_id}/request-revisions"),
            payload or {}, headers,
        )

    def reopen_report(self, org_id: str, report_id: str,
                      headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/organizations/{org_id}/reports/{report_id}/reopen",
            payload or {}, headers,
        )

    def publish_report(self, org_id: str, report_id: str,
                       headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/organizations/{org_id}/reports/{report_id}/publish",
            payload or {}, headers,
        )

    def get_report(self, org_id: str, report_id: str,
                   headers: Dict[str, str]):
        return self._request(
            "GET", f"/organizations/{org_id}/reports/{report_id}",
            headers=headers,
        )

    def get_report_dual_scope2(self, org_id: str, report_id: str,
                               headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/organizations/{org_id}/reports/{report_id}/dual-scope2",
            headers=headers,
        )

    # =======================================================================
    # Audit log (PRD §2.9, §4)
    # =======================================================================
    def list_audit_log(self, org_id: str, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/organizations/{org_id}/audit-log",
            headers=headers, params=params,
        )

    # =======================================================================
    # Test-driving / event-ingestion endpoints (PRD §3.8)
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def emit_event(self, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request("POST", "/_events/emit", payload, headers)


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
