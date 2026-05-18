"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles HTTP
plumbing. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every call (except GET /_clock per PRD
validation table priority 1, where headers are still required by the
broader rule that every request must carry them — see PRD §2.1).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Applicants (PRD §4)
    # =======================================================================
    def create_applicant(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/applicants", payload, headers)

    def get_applicant(self, applicant_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/applicants/{applicant_id}", headers=headers)

    def patch_applicant(
        self, applicant_id: str, payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request(
            "PATCH", f"/applicants/{applicant_id}", payload, headers,
        )

    def list_applicants(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", "/applicants", headers=headers, params=params,
        )

    # =======================================================================
    # Applications (PRD §4)
    # =======================================================================
    def create_application(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/applications/{application_id}", headers=headers,
        )

    def patch_application(
        self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request(
            "PATCH", f"/applications/{application_id}", payload, headers,
        )

    def list_applications(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", "/applications", headers=headers, params=params,
        )

    def create_fee_transaction(
        self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/applications/{application_id}/fees", payload, headers,
        )

    def list_fee_transactions(
        self, application_id: str, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/applications/{application_id}/fees",
            headers=headers, params=params,
        )

    def file_application(self, application_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/applications/{application_id}/file", {}, headers,
        )

    def begin_examination(self, application_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/applications/{application_id}/begin-examination", {}, headers,
        )

    def issue_office_action(
        self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/applications/{application_id}/office-actions",
            payload, headers,
        )

    def list_office_actions(
        self, application_id: str, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/applications/{application_id}/office-actions",
            headers=headers, params=params,
        )

    def allow_application(self, application_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/applications/{application_id}/allow", {}, headers,
        )

    def grant_application(self, application_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/applications/{application_id}/grant", {}, headers,
        )

    def abandon_application(self, application_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/applications/{application_id}/abandon", {}, headers,
        )

    def initiate_pct_phase(self, application_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/applications/{application_id}/pct-phases", {}, headers,
        )

    def list_maintenance_fees(
        self, application_id: str, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/applications/{application_id}/maintenance-fees",
            headers=headers, params=params,
        )

    def list_audit_events(
        self, application_id: str, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/applications/{application_id}/audit-events",
            headers=headers, params=params,
        )

    # =======================================================================
    # Office Actions (PRD §4)
    # =======================================================================
    def get_office_action(self, office_action_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/office-actions/{office_action_id}", headers=headers,
        )

    def file_response(self, office_action_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/office-actions/{office_action_id}/responses", {}, headers,
        )

    # =======================================================================
    # Maintenance Fees (PRD §4)
    # =======================================================================
    def get_maintenance_fee(
        self, maintenance_fee_id: str, headers: Dict[str, str],
    ):
        return self._request(
            "GET", f"/maintenance-fees/{maintenance_fee_id}", headers=headers,
        )

    def pay_maintenance_fee(
        self, maintenance_fee_id: str, headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/maintenance-fees/{maintenance_fee_id}/pay", {}, headers,
        )

    # =======================================================================
    # PCT phases (PRD §4)
    # =======================================================================
    def get_pct_phase(self, pct_phase_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/pct-phases/{pct_phase_id}", headers=headers,
        )

    def enter_national_phase(
        self, pct_phase_id: str, headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/pct-phases/{pct_phase_id}/enter-national", {}, headers,
        )

    # =======================================================================
    # Clock (PRD §2.8 / §4)
    # =======================================================================
    def get_clock(self, headers: Dict[str, str]):
        return self._request("GET", "/_clock", headers=headers)

    def advance_clock(self, to_iso: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", {"to": to_iso}, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
