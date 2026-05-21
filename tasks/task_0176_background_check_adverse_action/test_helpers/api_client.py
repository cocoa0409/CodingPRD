"""API client — one method per endpoint defined in PRD §4.

Subclasses GenericApiClient; the base `_request()` handles HTTP plumbing.
All endpoints are mounted under `/fcra` per PRD §1.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ======================================================================
    # Candidates — PRD §3.1
    # ======================================================================
    def create_candidate(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", "/fcra/candidates", payload, headers)

    def get_candidate(self, candidate_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/fcra/candidates/{candidate_id}", headers=headers,
        )

    def update_candidate(self, candidate_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/fcra/candidates/{candidate_id}", payload, headers,
        )

    def list_candidates(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/fcra/candidates", headers=headers, params=params,
        )

    # ======================================================================
    # Consent — PRD §3.2
    # ======================================================================
    def record_consent(self, candidate_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/fcra/candidates/{candidate_id}/consent",
            payload, headers,
        )

    def revoke_consent(self, candidate_id: str,
                       headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/fcra/candidates/{candidate_id}/consent/revoke",
            payload, headers,
        )

    # ======================================================================
    # Jurisdiction policies — PRD §3.1
    # ======================================================================
    def list_jurisdiction_policies(self, headers: Dict[str, str],
                                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/fcra/jurisdiction-policies",
            headers=headers, params=params,
        )

    def upsert_jurisdiction_policy(self, code: str,
                                   payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "PUT", f"/fcra/jurisdiction-policies/{code}", payload, headers,
        )

    # ======================================================================
    # Background-check orders — PRD §3.3 ff
    # ======================================================================
    def create_order(self, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", "/fcra/orders", payload, headers)

    def get_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/fcra/orders/{order_id}", headers=headers,
        )

    def list_orders(self, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/fcra/orders", headers=headers, params=params,
        )

    def start_verification(self, order_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/fcra/orders/{order_id}/start-verification",
            payload, headers,
        )

    def cancel_order(self, order_id: str,
                     headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/fcra/orders/{order_id}/cancel", payload, headers,
        )

    def issue_pre_adverse(self, order_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/fcra/orders/{order_id}/pre-adverse",
            payload, headers,
        )

    def issue_final_adverse(self, order_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/fcra/orders/{order_id}/final-adverse",
            payload, headers,
        )

    def request_rework(self, order_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/fcra/orders/{order_id}/request-rework",
            payload, headers,
        )

    def resume_verification(self, order_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/fcra/orders/{order_id}/resume-verification",
            payload, headers,
        )

    def get_audit_trail(self, order_id: str, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/fcra/orders/{order_id}/audit-trail",
            headers=headers, params=params,
        )

    # ======================================================================
    # Verification items — PRD §3.4
    # ======================================================================
    def get_verification_item(self, item_id: str,
                              headers: Dict[str, str]):
        return self._request(
            "GET", f"/fcra/verification-items/{item_id}",
            headers=headers,
        )

    def return_verification_item(self, item_id: str,
                                 payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/fcra/verification-items/{item_id}/return",
            payload, headers,
        )

    # ======================================================================
    # Disputes — PRD §3.7
    # ======================================================================
    def create_dispute(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/fcra/disputes", payload, headers)

    def get_dispute(self, dispute_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/fcra/disputes/{dispute_id}", headers=headers,
        )

    def resolve_dispute(self, dispute_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/fcra/disputes/{dispute_id}/resolve",
            payload, headers,
        )

    # ======================================================================
    # Test-driving — PRD §3.10
    # ======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/fcra/_clock/advance", payload, headers,
        )

    def run_sweep(self, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/fcra/_sweep/run", payload, headers,
        )


# Module-level singleton used by tests + fixtures.
api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
