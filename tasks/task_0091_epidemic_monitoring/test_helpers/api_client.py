"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles the
HTTP plumbing. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every call.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Institutions (PRD §3.1)
    # =======================================================================
    def create_institution(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", "/epi/institutions", payload, headers)

    def get_institution(self, institution_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/epi/institutions/{institution_id}", headers=headers,
        )

    # =======================================================================
    # Regions (PRD §3.1, §3.6)
    # =======================================================================
    def create_region(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/epi/regions", payload, headers)

    def get_region(self, region_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/epi/regions/{region_id}", headers=headers,
        )

    def recompute_region_risk(self, region_id: str,
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/epi/regions/{region_id}/recompute-risk", {}, headers,
        )

    # =======================================================================
    # Persons (PRD §3.1, §3.8)
    # =======================================================================
    def create_person(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/epi/persons", payload, headers)

    def get_person(self, person_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/epi/persons/{person_id}", headers=headers,
        )

    def get_person_exposure_score(self, person_id: str,
                                   headers: Dict[str, str],
                                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/epi/persons/{person_id}/exposure-score",
            headers=headers, params=params,
        )

    def get_person_contact_graph(self, person_id: str,
                                  headers: Dict[str, str],
                                  params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/epi/persons/{person_id}/contact-graph",
            headers=headers, params=params,
        )

    # =======================================================================
    # Facilities (PRD §3.1)
    # =======================================================================
    def create_facility(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/epi/facilities", payload, headers)

    def get_facility(self, facility_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/epi/facilities/{facility_id}", headers=headers,
        )

    # =======================================================================
    # Cases (PRD §3.2, §3.10)
    # =======================================================================
    def create_case(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/epi/cases", payload, headers)

    def get_case(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/epi/cases/{case_id}", headers=headers,
        )

    def list_cases(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/epi/cases", headers=headers, params=params,
        )

    def recover_case(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/epi/cases/{case_id}/recover", {}, headers,
        )

    # =======================================================================
    # Contact events (PRD §3.3, §3.8)
    # =======================================================================
    def create_contact_event(self, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request("POST", "/epi/contact-events", payload, headers)

    # =======================================================================
    # Tracing tasks (PRD §3.3)
    # =======================================================================
    def create_tracing_task(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", "/epi/tracing-tasks", payload, headers)

    def get_tracing_task(self, task_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/epi/tracing-tasks/{task_id}", headers=headers,
        )

    def list_tracing_tasks(self, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/epi/tracing-tasks", headers=headers, params=params,
        )

    def accept_tracing_task(self, task_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/epi/tracing-tasks/{task_id}/accept", {}, headers,
        )

    def complete_tracing_task(self, task_id: str, headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/epi/tracing-tasks/{task_id}/complete",
            payload or {}, headers,
        )

    def reject_tracing_task(self, task_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/epi/tracing-tasks/{task_id}/reject", {}, headers,
        )

    def close_tracing_task(self, task_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/epi/tracing-tasks/{task_id}/close", {}, headers,
        )

    # =======================================================================
    # Isolations (PRD §3.4)
    # =======================================================================
    def create_isolation(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", "/epi/isolations", payload, headers)

    def get_isolation(self, isolation_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/epi/isolations/{isolation_id}", headers=headers,
        )

    def submit_daily_report(self, isolation_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/epi/isolations/{isolation_id}/daily-report",
            payload, headers,
        )

    def record_isolation_violation(self, isolation_id: str,
                                    payload: Dict[str, Any],
                                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/epi/isolations/{isolation_id}/violation",
            payload, headers,
        )

    def check_isolation_release(self, isolation_id: str,
                                 headers: Dict[str, str],
                                 payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/epi/isolations/{isolation_id}/check-release",
            payload or {}, headers,
        )

    # =======================================================================
    # Test orders (PRD §3.5)
    # =======================================================================
    def create_test_order(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/epi/test-orders", payload, headers)

    def collect_test_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/epi/test-orders/{order_id}/collect", {}, headers,
        )

    def result_test_order(self, order_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/epi/test-orders/{order_id}/result", payload, headers,
        )

    def flag_test_order_followup(self, order_id: str,
                                  headers: Dict[str, str]):
        return self._request(
            "POST", f"/epi/test-orders/{order_id}/flag-followup", {}, headers,
        )

    def close_test_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/epi/test-orders/{order_id}/close", {}, headers,
        )

    def get_test_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/epi/test-orders/{order_id}", headers=headers,
        )

    def list_test_orders(self, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/epi/test-orders", headers=headers, params=params,
        )

    # =======================================================================
    # Risk decisions (PRD §3.6)
    # =======================================================================
    def create_risk_decision(self, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", "/epi/risk-decisions", payload, headers,
        )

    def get_risk_decision(self, decision_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/epi/risk-decisions/{decision_id}", headers=headers,
        )

    def submit_risk_decision_review(self, decision_id: str,
                                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/epi/risk-decisions/{decision_id}/submit-review",
            {}, headers,
        )

    def approve_risk_decision(self, decision_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/epi/risk-decisions/{decision_id}/approve",
            payload, headers,
        )

    def reject_risk_decision(self, decision_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/epi/risk-decisions/{decision_id}/reject",
            payload, headers,
        )

    def publish_risk_decision(self, decision_id: str,
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/epi/risk-decisions/{decision_id}/publish",
            {}, headers,
        )

    # =======================================================================
    # Supply items & supply requests (PRD §3.7)
    # =======================================================================
    def create_supply_item(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", "/epi/supply-items", payload, headers)

    def get_supply_item(self, item_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/epi/supply-items/{item_id}", headers=headers,
        )

    def create_supply_request(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", "/epi/supply-requests", payload, headers,
        )

    def get_supply_request(self, request_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "GET", f"/epi/supply-requests/{request_id}", headers=headers,
        )

    def allocate_supply_request(self, request_id: str,
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/epi/supply-requests/{request_id}/allocate",
            {}, headers,
        )

    def allocate_supply_batch(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", "/epi/supply/allocate-batch", payload, headers,
        )

    def dispatch_supply_request(self, request_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/epi/supply-requests/{request_id}/dispatch",
            payload, headers,
        )

    def deliver_dispatch(self, dispatch_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/epi/dispatches/{dispatch_id}/deliver", {}, headers,
        )

    def consume_supply_request(self, request_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/epi/supply-requests/{request_id}/consume",
            payload, headers,
        )

    def cancel_supply_request(self, request_id: str,
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/epi/supply-requests/{request_id}/cancel",
            {}, headers,
        )

    # =======================================================================
    # Bulletins (PRD §3.9)
    # =======================================================================
    def create_bulletin(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/epi/bulletins", payload, headers)

    def get_bulletin(self, bulletin_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/epi/bulletins/{bulletin_id}", headers=headers,
        )

    def list_bulletins(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/epi/bulletins", headers=headers, params=params,
        )

    def publish_bulletin(self, bulletin_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/epi/bulletins/{bulletin_id}/publish", {}, headers,
        )

    def retract_bulletin(self, bulletin_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/epi/bulletins/{bulletin_id}/retract",
            payload or {}, headers,
        )

    def archive_bulletin(self, bulletin_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/epi/bulletins/{bulletin_id}/archive", {}, headers,
        )

    # =======================================================================
    # Audit logs (PRD §2.10)
    # =======================================================================
    def list_audit_logs(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/epi/audit-logs", headers=headers, params=params,
        )

    # =======================================================================
    # Test-driver endpoints (PRD §2.9)
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def sweep_run(self, headers: Dict[str, str]):
        return self._request("POST", "/_sweep/run", {}, headers)

    def events_emit(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/_events/emit", payload, headers)


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
