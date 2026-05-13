"""API client: one method per endpoint defined in PRD §4.

Each method delegates to GenericApiClient._request and returns the raw
Response object. Tests pass headers explicitly because PRD §2.1 requires
X-User-Role and X-User-ID on every call.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Departments (PRD §3.1, §4)
    # =======================================================================
    def create_department(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/departments", payload, headers)

    def list_departments(self, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/departments", headers=headers, params=params,
        )

    def get_department(self, department_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/departments/{department_id}", headers=headers,
        )

    def update_department(self, department_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/departments/{department_id}", payload, headers,
        )

    # =======================================================================
    # Handlers (PRD §3.1, §4)
    # =======================================================================
    def create_handler(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/handlers", payload, headers)

    def get_handler(self, handler_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/handlers/{handler_id}", headers=headers,
        )

    def update_handler(self, handler_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/handlers/{handler_id}", payload, headers,
        )

    # =======================================================================
    # Category rules (PRD §3.1, §4)
    # =======================================================================
    def create_category_rule(self, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request("POST", "/category-rules", payload, headers)

    def list_category_rules(self, headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/category-rules", headers=headers, params=params,
        )

    # =======================================================================
    # Work orders (PRD §3.2 – §3.10, §4)
    # =======================================================================
    def create_work_order(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/work-orders", payload, headers)

    def list_work_orders(self, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/work-orders", headers=headers, params=params,
        )

    def get_work_order(self, work_order_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/work-orders/{work_order_id}", headers=headers,
        )

    def update_work_order(self, work_order_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/work-orders/{work_order_id}", payload, headers,
        )

    def classify_work_order(self, work_order_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/classify",
            payload, headers,
        )

    def dispatch_work_order(self, work_order_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/dispatch",
            payload or {}, headers,
        )

    def reject_work_order(self, work_order_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/reject",
            payload, headers,
        )

    def pause_work_order(self, work_order_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/pause",
            payload, headers,
        )

    def resume_work_order(self, work_order_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/resume",
            payload or {}, headers,
        )

    def resolve_work_order(self, work_order_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/resolve",
            payload, headers,
        )

    def reopen_work_order(self, work_order_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/reopen",
            payload or {}, headers,
        )

    def close_work_order(self, work_order_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/close",
            payload or {}, headers,
        )

    # =======================================================================
    # Department assignments (PRD §3.4 – §3.7, §4)
    # =======================================================================
    def list_assignments(self, work_order_id: str,
                         headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/work-orders/{work_order_id}/assignments",
            headers=headers, params=params,
        )

    def accept_assignment(self, work_order_id: str, assignment_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/work-orders/{work_order_id}/assignments/"
            f"{assignment_id}/accept",
            payload or {}, headers,
        )

    def reject_assignment(self, work_order_id: str, assignment_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/work-orders/{work_order_id}/assignments/"
            f"{assignment_id}/reject",
            payload, headers,
        )

    def reassign_assignment(self, work_order_id: str, assignment_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/work-orders/{work_order_id}/assignments/"
            f"{assignment_id}/reassign",
            payload, headers,
        )

    def submit_opinion(self, work_order_id: str, assignment_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/work-orders/{work_order_id}/assignments/"
            f"{assignment_id}/opinion",
            payload, headers,
        )

    def escalate_assignment(self, work_order_id: str, assignment_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/work-orders/{work_order_id}/assignments/"
            f"{assignment_id}/escalate",
            payload or {}, headers,
        )

    # =======================================================================
    # Surveys (PRD §3.9, §4)
    # =======================================================================
    def list_surveys(self, work_order_id: str,
                     headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/work-orders/{work_order_id}/surveys",
            headers=headers, params=params,
        )

    def create_survey(self, work_order_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/surveys",
            payload, headers,
        )

    def respond_survey(self, survey_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/surveys/{survey_id}/respond", payload, headers,
        )

    # =======================================================================
    # Supervision (PRD §3.11, §4)
    # =======================================================================
    def list_supervision(self, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/supervision", headers=headers, params=params,
        )

    def ack_supervision(self, supervision_id: str,
                        headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/supervision/{supervision_id}/ack",
            payload or {}, headers,
        )

    def close_supervision(self, supervision_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/supervision/{supervision_id}/close",
            payload or {}, headers,
        )

    # =======================================================================
    # Statistics (PRD §3.14, §4)
    # =======================================================================
    def stats_satisfaction(self, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/stats/satisfaction",
            headers=headers, params=params,
        )

    def stats_breach_rate(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/stats/breach-rate",
            headers=headers, params=params,
        )

    def stats_trend(self, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/stats/trend",
            headers=headers, params=params,
        )

    # =======================================================================
    # Audit & sync (PRD §2.9, §4)
    # =======================================================================
    def list_audit_logs(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/audit-logs", headers=headers, params=params,
        )

    def list_sync_events(self, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/sync-events", headers=headers, params=params,
        )

    # =======================================================================
    # Test-harness drivers (PRD §2.10, §4)
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def sweep_run(self, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/_sweep/run", payload or {}, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
