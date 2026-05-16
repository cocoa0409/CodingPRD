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
    # Patient — PRD §4
    # =======================================================================
    def create_patient(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/patients/{patient_id}", headers=headers,
        )

    # =======================================================================
    # Provider — PRD §4
    # =======================================================================
    def create_provider(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/providers", payload, headers)

    def get_provider(self, provider_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/providers/{provider_id}", headers=headers,
        )

    # =======================================================================
    # ServiceCatalogItem — PRD §4
    # =======================================================================
    def create_service_catalog_item(self, payload: Dict[str, Any],
                                    headers: Dict[str, str]):
        return self._request(
            "POST", "/service-catalog-items", payload, headers,
        )

    def get_service_catalog_item(self, item_id: str,
                                 headers: Dict[str, str]):
        return self._request(
            "GET", f"/service-catalog-items/{item_id}", headers=headers,
        )

    def patch_service_catalog_item(self, item_id: str,
                                   payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/service-catalog-items/{item_id}", payload, headers,
        )

    # =======================================================================
    # AuthorizationRequest — PRD §4
    # =======================================================================
    def create_authorization_request(self, payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request(
            "POST", "/authorization-requests", payload, headers,
        )

    def get_authorization_request(self, auth_id: str,
                                  headers: Dict[str, str]):
        return self._request(
            "GET", f"/authorization-requests/{auth_id}", headers=headers,
        )

    def list_authorization_requests(self, headers: Dict[str, str],
                                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/authorization-requests",
            headers=headers, params=params,
        )

    def patch_authorization_request(self, auth_id: str,
                                    payload: Dict[str, Any],
                                    headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/authorization-requests/{auth_id}",
            payload, headers,
        )

    def submit_authorization_request(self, auth_id: str,
                                     payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/authorization-requests/{auth_id}/submit",
            payload, headers,
        )

    def start_review(self, auth_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/authorization-requests/{auth_id}/start-review",
            payload, headers,
        )

    def request_info(self, auth_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/authorization-requests/{auth_id}/request-info",
            payload, headers,
        )

    def resume_review(self, auth_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/authorization-requests/{auth_id}/resume-review",
            payload, headers,
        )

    def schedule_peer_to_peer(self, auth_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/authorization-requests/{auth_id}/peer-to-peer",
            payload, headers,
        )

    def decide_authorization_request(self, auth_id: str,
                                     payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/authorization-requests/{auth_id}/decide",
            payload, headers,
        )

    def withdraw_authorization_request(self, auth_id: str,
                                       payload: Dict[str, Any],
                                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/authorization-requests/{auth_id}/withdraw",
            payload, headers,
        )

    # =======================================================================
    # ClinicalEvidence — PRD §4
    # =======================================================================
    def attach_clinical_evidence(self, auth_id: str,
                                 payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/authorization-requests/{auth_id}/clinical-evidence",
            payload, headers,
        )

    def list_clinical_evidence(self, auth_id: str,
                               headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/authorization-requests/{auth_id}/clinical-evidence",
            headers=headers, params=params,
        )

    def withdraw_clinical_evidence(self, auth_id: str, evidence_id: str,
                                   headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/authorization-requests/{auth_id}/clinical-evidence/"
            f"{evidence_id}/withdraw",
            {}, headers,
        )

    # =======================================================================
    # PeerToPeerReview — PRD §4
    # =======================================================================
    def get_peer_to_peer_review(self, p2p_id: str,
                                headers: Dict[str, str]):
        return self._request(
            "GET", f"/peer-to-peer-reviews/{p2p_id}", headers=headers,
        )

    def complete_peer_to_peer_review(self, p2p_id: str,
                                     payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/peer-to-peer-reviews/{p2p_id}/complete",
            payload, headers,
        )

    def cancel_peer_to_peer_review(self, p2p_id: str,
                                   payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/peer-to-peer-reviews/{p2p_id}/cancel",
            payload, headers,
        )

    # =======================================================================
    # Appeal — PRD §4
    # =======================================================================
    def file_appeal(self, auth_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/authorization-requests/{auth_id}/appeals",
            payload, headers,
        )

    def get_appeal(self, appeal_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/appeals/{appeal_id}", headers=headers,
        )

    def decide_appeal(self, appeal_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/appeals/{appeal_id}/decide", payload, headers,
        )

    def withdraw_appeal(self, appeal_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/appeals/{appeal_id}/withdraw", payload, headers,
        )

    # =======================================================================
    # Clock / Sweep — PRD §3.10 / §4
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )

    def sweep_run(self, headers: Dict[str, str]):
        return self._request(
            "POST", "/_sweep/run", {}, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
