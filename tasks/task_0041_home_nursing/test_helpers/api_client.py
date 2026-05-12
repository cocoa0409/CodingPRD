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
    # Nurses & Certification (PRD §3.1, §4)
    # =====================================================================
    def create_nurse(self, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", "/nurses", payload, headers)

    def list_nurses(self, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/nurses", headers=headers, params=params
        )

    def get_nurse(self, nurse_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/nurses/{nurse_id}", headers=headers
        )

    def create_certification_record(
        self, nurse_id: str,
        payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/nurses/{nurse_id}/certification-records",
            payload, headers,
        )

    def list_certification_records(
        self, nurse_id: str, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/nurses/{nurse_id}/certification-records",
            headers=headers, params=params,
        )

    # =====================================================================
    # ServiceItem (PRD §3.2, §4)
    # =====================================================================
    def create_service_item(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", "/service-items", payload, headers)

    def list_service_items(self, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/service-items", headers=headers, params=params
        )

    def get_service_item(self, code: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/service-items/{code}", headers=headers
        )

    # =====================================================================
    # Orders (PRD §3.2 - §3.5, §4)
    # =====================================================================
    def create_order(self, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", "/orders", payload, headers)

    def list_orders(self, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/orders", headers=headers, params=params
        )

    def get_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/orders/{order_id}", headers=headers
        )

    def review_order(self, order_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/orders/{order_id}/eligibility-review",
            payload, headers,
        )

    def cancel_order(self, order_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/orders/{order_id}/cancel",
            payload or {}, headers,
        )

    def confirm_completion(self, order_id: str, headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/orders/{order_id}/confirm-completion",
            payload or {}, headers,
        )

    def refund_order(self, order_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/orders/{order_id}/refund",
            payload or {}, headers,
        )

    # =====================================================================
    # Dispatches (PRD §3.3, §4)
    # =====================================================================
    def list_dispatches(self, order_id: str, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/orders/{order_id}/dispatches",
            headers=headers, params=params,
        )

    def get_dispatch(self, dispatch_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/dispatches/{dispatch_id}", headers=headers
        )

    def accept_dispatch(self, dispatch_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/dispatches/{dispatch_id}/accept",
            payload or {}, headers,
        )

    def reject_dispatch(self, dispatch_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/dispatches/{dispatch_id}/reject",
            payload or {}, headers,
        )

    # =====================================================================
    # ServiceRecord (PRD §3.4, §4)
    # =====================================================================
    def create_service_record(self, order_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/orders/{order_id}/service-record",
            payload, headers,
        )

    def patch_service_record(self, order_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/orders/{order_id}/service-record",
            payload, headers,
        )

    def finish_service_record(self, order_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/orders/{order_id}/service-record/finish",
            payload or {}, headers,
        )

    # =====================================================================
    # Waste entries (PRD §3.4, §4)
    # =====================================================================
    def create_waste_entry(self, order_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/orders/{order_id}/waste-entries",
            payload, headers,
        )

    def patch_waste_entry(self, order_id: str, waste_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/orders/{order_id}/waste-entries/{waste_id}",
            payload, headers,
        )

    def list_waste_entries(self, order_id: str, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/orders/{order_id}/waste-entries",
            headers=headers, params=params,
        )

    # =====================================================================
    # Packages (PRD §3.2, §4)
    # =====================================================================
    def create_package(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/packages", payload, headers)

    def list_packages(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/packages", headers=headers, params=params
        )

    # =====================================================================
    # Settlements & Payouts (PRD §3.5, §4)
    # =====================================================================
    def get_settlement(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/orders/{order_id}/settlement", headers=headers
        )

    def create_payout_batch(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", "/payout-batches", payload, headers
        )

    def list_payout_batches(self, headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/payout-batches", headers=headers, params=params
        )

    # =====================================================================
    # Complaints (PRD §3.5, §4)
    # =====================================================================
    def create_complaint(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", "/complaints", payload, headers)

    def list_complaints(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/complaints", headers=headers, params=params
        )

    def triage_complaint(self, complaint_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/complaints/{complaint_id}/triage",
            payload or {}, headers,
        )

    def escalate_complaint(self, complaint_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/complaints/{complaint_id}/escalate-mediation",
            payload or {}, headers,
        )

    def resolve_complaint(self, complaint_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/complaints/{complaint_id}/resolve",
            payload, headers,
        )

    # =====================================================================
    # Audit & Test Hooks (PRD §3.6, §3.7, §4)
    # =====================================================================
    def list_audit_logs(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/audit-logs", headers=headers, params=params
        )

    def advance_clock(self, to_iso: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", {"to": to_iso}, headers
        )

    def emit_event(self, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "POST", "/_events/emit", payload, headers
        )

    def reset_state(self, headers: Dict[str, str]):
        """Test-only hook to reset all in-memory state.

        Not part of the PRD; used by the test_helpers autouse fixture so
        each test starts with a clean db.
        """
        return self._request("POST", "/_test/reset", {}, headers)


api_client = ApiClient()


__all__ = ["ApiClient", "api_client", "PREFIX"]
