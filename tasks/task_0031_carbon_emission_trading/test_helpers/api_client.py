"""API client: one method per endpoint defined in PRD §4.

Every method delegates to GenericApiClient._request and returns the raw
Response. Tests pass headers explicitly because PRD §2.1 makes
X-User-ID / X-User-Role mandatory for every call.

PRD §4: 'All endpoints are mounted under the /enterprises-anchored API
surface (with several non-enterprise-prefixed paths for cycle, allocation,
trading, and administrative operations as listed below).' The endpoint
table uses absolute paths verbatim — there is no implicit prefix.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # =====================================================================
    # Enterprise
    # =====================================================================
    def create_enterprise(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/enterprises", payload, headers)

    def get_enterprise(self, enterprise_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "GET", f"/enterprises/{enterprise_id}", headers=headers
        )

    def list_enterprises(self, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/enterprises", headers=headers, params=params
        )

    # =====================================================================
    # Allocation cycle
    # =====================================================================
    def create_allocation_cycle(self, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request("POST", "/allocation-cycles", payload, headers)

    def create_allocation(self, cycle_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/allocation-cycles/{cycle_id}/allocations",
            payload,
            headers,
        )

    def publish_allocation_cycle(self, cycle_id: str,
                                 headers: Dict[str, str],
                                 payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/allocation-cycles/{cycle_id}/publish",
            payload or {},
            headers,
        )

    def finalize_allocation_cycle(self, cycle_id: str,
                                  headers: Dict[str, str],
                                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/allocation-cycles/{cycle_id}/finalize",
            payload or {},
            headers,
        )

    def settle_allocation_cycle(self, cycle_id: str,
                                headers: Dict[str, str],
                                payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/allocation-cycles/{cycle_id}/settle",
            payload or {},
            headers,
        )

    def close_allocation_cycle(self, cycle_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/allocation-cycles/{cycle_id}/close",
            payload or {},
            headers,
        )

    def get_allocation_cycle(self, cycle_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "GET", f"/allocation-cycles/{cycle_id}", headers=headers
        )

    # =====================================================================
    # Objection
    # =====================================================================
    def file_objection(self, allocation_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/allocations/{allocation_id}/objections",
            payload,
            headers,
        )

    def uphold_objection(self, objection_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/objections/{objection_id}/uphold",
            payload,
            headers,
        )

    def reject_objection(self, objection_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/objections/{objection_id}/reject",
            payload or {},
            headers,
        )

    # =====================================================================
    # Emission report
    # =====================================================================
    def create_emission_report(self, enterprise_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/enterprises/{enterprise_id}/emission-reports",
            payload,
            headers,
        )

    def add_emission_line(self, report_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/emission-reports/{report_id}/lines",
            payload,
            headers,
        )

    def upload_supporting_document(self, report_id: str,
                                   payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/emission-reports/{report_id}/documents",
            payload,
            headers,
        )

    def submit_emission_report(self, report_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/emission-reports/{report_id}/submit",
            payload or {},
            headers,
        )

    def assign_verifier(self, report_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/emission-reports/{report_id}/assign-verifier",
            payload,
            headers,
        )

    def complete_onsite(self, assignment_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/verification-assignments/{assignment_id}/complete-onsite",
            payload,
            headers,
        )

    def issue_verification_report(self, assignment_id: str,
                                  headers: Dict[str, str],
                                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/verification-assignments/{assignment_id}/issue-report",
            payload or {},
            headers,
        )

    def dispute_emission_report(self, report_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/emission-reports/{report_id}/dispute",
            payload,
            headers,
        )

    def resolve_dispute(self, assignment_id: str,
                        headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/verification-assignments/{assignment_id}/resolve-dispute",
            payload or {},
            headers,
        )

    def finalize_emission_report(self, report_id: str,
                                 headers: Dict[str, str],
                                 payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/emission-reports/{report_id}/finalize",
            payload or {},
            headers,
        )

    def reject_emission_report(self, report_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/emission-reports/{report_id}/reject",
            payload,
            headers,
        )

    def get_emission_report(self, report_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "GET", f"/emission-reports/{report_id}", headers=headers
        )

    # =====================================================================
    # Trading
    # =====================================================================
    def create_trading_order(self, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request("POST", "/trading-orders", payload, headers)

    def cancel_trading_order(self, order_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/trading-orders/{order_id}/cancel",
            payload or {},
            headers,
        )

    def get_trading_order(self, order_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "GET", f"/trading-orders/{order_id}", headers=headers
        )

    def list_trades(self, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/trades", headers=headers, params=params
        )

    # =====================================================================
    # Compliance & penalty
    # =====================================================================
    def create_compliance_declaration(self, enterprise_id: str,
                                      payload: Dict[str, Any],
                                      headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/enterprises/{enterprise_id}/compliance-declarations",
            payload,
            headers,
        )

    def submit_compliance_declaration(self, declaration_id: str,
                                      payload: Dict[str, Any],
                                      headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/compliance-declarations/{declaration_id}/submit",
            payload,
            headers,
        )

    def pay_penalty_order(self, penalty_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/penalty-orders/{penalty_id}/pay",
            payload or {},
            headers,
        )

    def get_penalty_order(self, penalty_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "GET", f"/penalty-orders/{penalty_id}", headers=headers
        )

    # =====================================================================
    # Settlement & audit
    # =====================================================================
    def list_annual_settlements(self, headers: Dict[str, str],
                                params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/annual-settlements", headers=headers, params=params
        )

    def list_audit_logs(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/audit-logs", headers=headers, params=params
        )

    # =====================================================================
    # Test-driver capabilities (PRD §2.10)
    # =====================================================================
    def advance_clock(self, target_timestamp: str,
                      headers: Dict[str, str]):
        return self._request(
            "POST",
            "/_clock/advance",
            {"target_timestamp": target_timestamp},
            headers,
        )

    def run_sweep(self, headers: Dict[str, str]):
        return self._request("POST", "/_sweep/run", {}, headers)

    def emit_event(self, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request("POST", "/_events/emit", payload, headers)


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
