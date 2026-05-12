"""API client: one method per endpoint defined in PRD §4.

Every method delegates to GenericApiClient._request and returns the raw
Response object. Tests pass headers explicitly because PRD §2.1 makes
X-User-ID / X-User-Role mandatory for every call.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


PREFIX = ""  # PRD §4 endpoints use bare paths (no API prefix)


class ApiClient(GenericApiClient):
    # =====================================================================
    # Initiators
    # =====================================================================
    def create_initiator(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", "/initiators", payload, headers)

    def verify_kyc(self, initiator_id: str, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/initiators/{initiator_id}/verify-kyc",
            payload,
            headers,
        )

    # =====================================================================
    # Backers
    # =====================================================================
    def create_backer(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/backers", payload, headers)

    # =====================================================================
    # Projects
    # =====================================================================
    def create_project(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/projects", payload, headers)

    def get_project(self, project_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/projects/{project_id}", headers=headers
        )

    def list_projects(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/projects", headers=headers, params=params
        )

    def patch_project(self, project_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/projects/{project_id}", payload, headers
        )

    def submit_project(self, project_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/projects/{project_id}/submit",
            payload or {}, headers,
        )

    def review_content(self, project_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/projects/{project_id}/review-content",
            payload, headers,
        )

    def review_legal(self, project_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/projects/{project_id}/review-legal",
            payload, headers,
        )

    def review_financial(self, project_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/projects/{project_id}/review-financial",
            payload, headers,
        )

    def cancel_project(self, project_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/projects/{project_id}/cancel",
            payload or {}, headers,
        )

    # =====================================================================
    # Rewards & add-on items (nested under project)
    # =====================================================================
    def create_reward(self, project_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/projects/{project_id}/rewards",
            payload, headers,
        )

    def list_rewards(self, project_id: str, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/projects/{project_id}/rewards",
            headers=headers, params=params,
        )

    def patch_reward(self, project_id: str, reward_id: str,
                     payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "PATCH",
            f"/projects/{project_id}/rewards/{reward_id}",
            payload, headers,
        )

    def create_add_on_item(self, project_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/projects/{project_id}/add-on-items",
            payload, headers,
        )

    def list_add_on_items(self, project_id: str, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/projects/{project_id}/add-on-items",
            headers=headers, params=params,
        )

    # =====================================================================
    # Orders
    # =====================================================================
    def create_order(self, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/orders/{order_id}", headers=headers
        )

    def patch_order(self, order_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/orders/{order_id}", payload, headers
        )

    def cancel_order(self, order_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/orders/{order_id}/cancel",
            payload or {}, headers,
        )

    # =====================================================================
    # Progress updates
    # =====================================================================
    def create_progress_update(self, project_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/projects/{project_id}/progress-updates",
            payload, headers,
        )

    def list_progress_updates(self, project_id: str,
                              headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/projects/{project_id}/progress-updates",
            headers=headers, params=params,
        )

    # =====================================================================
    # Refund requests
    # =====================================================================
    def create_refund_request(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", "/refund-requests", payload, headers)

    def get_refund_request(self, refund_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/refund-requests/{refund_id}", headers=headers
        )

    def approve_refund(self, refund_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/refund-requests/{refund_id}/approve",
            payload or {}, headers,
        )

    def reject_refund(self, refund_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/refund-requests/{refund_id}/reject",
            payload, headers,
        )

    def execute_refund(self, refund_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/refund-requests/{refund_id}/execute",
            payload or {}, headers,
        )

    # =====================================================================
    # Settlement batches
    # =====================================================================
    def create_settlement_batch(self, project_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/projects/{project_id}/settlement-batches",
            payload, headers,
        )

    def finalize_settlement_batch(self, project_id: str, batch_id: str,
                                  headers: Dict[str, str],
                                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/projects/{project_id}/settlement-batches/{batch_id}/finalize",
            payload or {}, headers,
        )

    def get_settlement_batch(self, project_id: str, batch_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/projects/{project_id}/settlement-batches/{batch_id}",
            headers=headers,
        )

    # =====================================================================
    # Audit & ledger
    # =====================================================================
    def list_audit_log(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/audit-log", headers=headers, params=params
        )

    def list_escrow_ledger(self, project_id: str, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/projects/{project_id}/escrow-ledger",
            headers=headers, params=params,
        )

    # =====================================================================
    # Test-driving endpoints (PRD §4)
    # =====================================================================
    def advance_clock(self, to_iso: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", {"to": to_iso}, headers
        )

    def emit_payment_event(self, order_id: str, result: str,
                           headers: Dict[str, str],
                           external_ref: Optional[str] = None):
        payload: Dict[str, Any] = {"order_id": order_id, "result": result}
        if external_ref is not None:
            payload["external_ref"] = external_ref
        return self._request("POST", "/_events/payment", payload, headers)

    def emit_banking_event(self, subject_type: str, subject_id: str,
                           result: str, headers: Dict[str, str],
                           external_ref: Optional[str] = None):
        payload: Dict[str, Any] = {
            "subject_type": subject_type,
            "subject_id": subject_id,
            "result": result,
        }
        if external_ref is not None:
            payload["external_ref"] = external_ref
        return self._request("POST", "/_events/banking", payload, headers)

    def emit_logistics_event(self, order_id: str,
                             lines: list,
                             headers: Dict[str, str]):
        payload: Dict[str, Any] = {"order_id": order_id, "lines": lines}
        return self._request("POST", "/_events/logistics", payload, headers)


api_client = ApiClient()


__all__ = ["ApiClient", "api_client", "PREFIX"]
