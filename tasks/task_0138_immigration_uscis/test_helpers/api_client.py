"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles HTTP
plumbing. Tests pass headers explicitly because PRD §2.1 requires
X-User-Role and X-User-ID on every request.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Petitioners — PRD §4
    # =======================================================================
    def create_petitioner(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/petitioners", payload, headers)

    def get_petitioner(self, petitioner_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "GET", f"/petitioners/{petitioner_id}", headers=headers,
        )

    # =======================================================================
    # Beneficiaries — PRD §4
    # =======================================================================
    def create_beneficiary(self, petitioner_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/petitioners/{petitioner_id}/beneficiaries",
            payload, headers,
        )

    def get_beneficiary(self, beneficiary_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET", f"/beneficiaries/{beneficiary_id}", headers=headers,
        )

    # =======================================================================
    # Case-Type Configuration — PRD §4
    # =======================================================================
    def upsert_case_type_config(self, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", "/admin/case-type-config", payload, headers,
        )

    def get_case_type_config(self, case_type: str,
                             headers: Dict[str, str]):
        return self._request(
            "GET", f"/admin/case-type-config/{case_type}",
            headers=headers,
        )

    # =======================================================================
    # Cases — PRD §4
    # =======================================================================
    def create_case(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/cases", payload, headers)

    def get_case(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/cases/{case_id}", headers=headers,
        )

    def list_cases(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/cases", headers=headers, params=params,
        )

    def file_case(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cases/{case_id}/file", {}, headers,
        )

    def schedule_biometrics(self, case_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/cases/{case_id}/biometrics", payload, headers,
        )

    def issue_rfe(self, case_id: str, payload: Dict[str, Any],
                  headers: Dict[str, str]):
        return self._request(
            "POST", f"/cases/{case_id}/rfe", payload, headers,
        )

    def schedule_interview(self, case_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/cases/{case_id}/interview", payload, headers,
        )

    def ready_for_decision(self, case_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/cases/{case_id}/ready-for-decision",
            {}, headers,
        )

    def decide_case(self, case_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/cases/{case_id}/decide", payload, headers,
        )

    def withdraw_case(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cases/{case_id}/withdraw", {}, headers,
        )

    def refresh_priority_date(self, case_id: str,
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/cases/{case_id}/refresh-priority-date",
            {}, headers,
        )

    def get_case_summary(self, case_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "GET", f"/cases/{case_id}/summary", headers=headers,
        )

    def list_case_events(self, case_id: str,
                         headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/cases/{case_id}/events",
            headers=headers, params=params,
        )

    # =======================================================================
    # Biometrics — PRD §4
    # =======================================================================
    def get_biometrics(self, biometrics_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "GET", f"/biometrics/{biometrics_id}", headers=headers,
        )

    def complete_biometrics(self, biometrics_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/biometrics/{biometrics_id}/complete",
            {}, headers,
        )

    def no_show_biometrics(self, biometrics_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/biometrics/{biometrics_id}/no-show",
            {}, headers,
        )

    def reschedule_biometrics(self, biometrics_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/biometrics/{biometrics_id}/reschedule",
            payload, headers,
        )

    # =======================================================================
    # RFE — PRD §4
    # =======================================================================
    def get_rfe(self, rfe_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/rfes/{rfe_id}", headers=headers,
        )

    def respond_rfe(self, rfe_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/rfes/{rfe_id}/respond", {}, headers,
        )

    # =======================================================================
    # Interview — PRD §4
    # =======================================================================
    def get_interview(self, interview_id: str,
                      headers: Dict[str, str]):
        return self._request(
            "GET", f"/interviews/{interview_id}", headers=headers,
        )

    def complete_interview(self, interview_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/interviews/{interview_id}/complete",
            payload, headers,
        )

    def no_show_interview(self, interview_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/interviews/{interview_id}/no-show",
            {}, headers,
        )

    # =======================================================================
    # Visa Bulletin — PRD §4
    # =======================================================================
    def publish_visa_bulletin(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", "/admin/visa-bulletin", payload, headers,
        )

    def list_visa_bulletin(self, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/admin/visa-bulletin",
            headers=headers, params=params,
        )

    def set_chart_in_effect(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", "/admin/visa-bulletin/chart-in-effect",
            payload, headers,
        )

    # =======================================================================
    # Clock — PRD §4
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )

    def get_clock(self, headers: Dict[str, str]):
        return self._request("GET", "/_clock", headers=headers)


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
