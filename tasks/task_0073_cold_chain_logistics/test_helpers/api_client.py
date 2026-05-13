"""API client: one method per endpoint defined in the PRD §4.

Inherits the generic _request() / build-URL machinery from
GenericApiClient. Tests should call api_client.<method>(...).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock test-fixture ----
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )

    def clock_get(self, headers: Dict[str, str]):
        return self._request("GET", "/_clock", headers=headers)

    # ---- Vehicle ----
    def create_vehicle(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/vehicles/{vehicle_id}", headers=headers,
        )

    def list_vehicles(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/vehicles", headers=headers, params=params,
        )

    # ---- Driver ----
    def create_driver(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/drivers", payload, headers)

    def get_driver(self, driver_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/drivers/{driver_id}", headers=headers,
        )

    # ---- TransportTask ----
    def create_transport_task(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", "/transport-tasks", payload, headers,
        )

    def get_transport_task(self, task_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/transport-tasks/{task_id}", headers=headers,
        )

    def patch_transport_task(self, task_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/transport-tasks/{task_id}", payload, headers,
        )

    def list_transport_tasks(self, headers: Dict[str, str],
                             params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/transport-tasks", headers=headers, params=params,
        )

    def dispatch_task(self, task_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/transport-tasks/{task_id}/dispatch",
            headers=headers,
        )

    def depart_task(self, task_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/transport-tasks/{task_id}/depart",
            headers=headers,
        )

    def arrive_stop(self, task_id: str, stop_id: str,
                    headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/transport-tasks/{task_id}/stops/{stop_id}/arrive",
            headers=headers,
        )

    def depart_stop(self, task_id: str, stop_id: str,
                    headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/transport-tasks/{task_id}/stops/{stop_id}/depart",
            headers=headers,
        )

    def create_handover(self, task_id: str, stop_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/transport-tasks/{task_id}/stops/{stop_id}/handovers",
            payload, headers,
        )

    def skip_stop(self, task_id: str, stop_id: str,
                  headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/transport-tasks/{task_id}/stops/{stop_id}/skip",
            headers=headers,
        )

    def close_task(self, task_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/transport-tasks/{task_id}/close",
            headers=headers,
        )

    def abort_task(self, task_id: str, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/transport-tasks/{task_id}/abort", payload, headers,
        )

    # ---- Temperature readings ----
    def ingest_reading(self, task_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/transport-tasks/{task_id}/temperature-readings",
            payload, headers, params=params,
        )

    def list_readings(self, task_id: str, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/transport-tasks/{task_id}/temperature-readings",
            headers=headers, params=params,
        )

    def archive_readings(self, task_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/transport-tasks/{task_id}/temperature-readings/archive",
            headers=headers,
        )

    # ---- Alerts ----
    def get_alert(self, alert_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/alerts/{alert_id}", headers=headers,
        )

    def list_alerts(self, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/alerts", headers=headers, params=params,
        )

    def acknowledge_alert(self, alert_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/alerts/{alert_id}/acknowledge",
            headers=headers,
        )

    def respond_alert(self, alert_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/alerts/{alert_id}/responses", payload, headers,
        )

    def escalate_alert(self, alert_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/alerts/{alert_id}/escalate", headers=headers,
        )

    def resolve_alert(self, alert_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/alerts/{alert_id}/resolve", headers=headers,
        )

    # ---- DamageAssessment ----
    def create_damage_assessment(self, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", "/damage-assessments", payload, headers,
        )

    def patch_damage_assessment(self, assessment_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/damage-assessments/{assessment_id}",
            payload, headers,
        )

    def finalize_damage_assessment(self, assessment_id: str,
                                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/damage-assessments/{assessment_id}/finalize",
            headers=headers,
        )

    def get_damage_assessment(self, assessment_id: str,
                              headers: Dict[str, str]):
        return self._request(
            "GET", f"/damage-assessments/{assessment_id}",
            headers=headers,
        )

    # ---- ResponsibilityDecision ----
    def create_responsibility_decision(self, payload: Dict[str, Any],
                                       headers: Dict[str, str]):
        return self._request(
            "POST", "/responsibility-decisions", payload, headers,
        )

    def patch_responsibility_decision(self, decision_id: str,
                                      payload: Dict[str, Any],
                                      headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/responsibility-decisions/{decision_id}",
            payload, headers,
        )

    def submit_decision(self, decision_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/responsibility-decisions/{decision_id}/submit",
            headers=headers,
        )

    def accept_decision(self, decision_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/responsibility-decisions/{decision_id}/accept",
            headers=headers,
        )

    def dispute_decision(self, decision_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/responsibility-decisions/{decision_id}/dispute",
            payload, headers,
        )

    def mediate_decision(self, decision_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/responsibility-decisions/{decision_id}/mediate",
            headers=headers,
        )

    def finalize_decision(self, decision_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/responsibility-decisions/{decision_id}/finalize",
            headers=headers,
        )

    def get_responsibility_decision(self, decision_id: str,
                                    headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/responsibility-decisions/{decision_id}",
            headers=headers,
        )

    # ---- InsuranceClaim ----
    def create_insurance_claim(self, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", "/insurance-claims", payload, headers,
        )

    def prepare_evidence(self, claim_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/insurance-claims/{claim_id}/prepare-evidence",
            headers=headers,
        )

    def assess_claim(self, claim_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/insurance-claims/{claim_id}/assess",
            payload, headers,
        )

    def negotiate_claim(self, claim_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/insurance-claims/{claim_id}/negotiate",
            headers=headers,
        )

    def pay_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/insurance-claims/{claim_id}/pay",
            headers=headers,
        )

    def reject_claim(self, claim_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/insurance-claims/{claim_id}/reject",
            payload, headers,
        )

    def subrogate_claim(self, claim_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/insurance-claims/{claim_id}/subrogate",
            payload, headers,
        )

    def close_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/insurance-claims/{claim_id}/close",
            headers=headers,
        )

    def get_insurance_claim(self, claim_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "GET", f"/insurance-claims/{claim_id}", headers=headers,
        )

    # ---- ComplianceReport ----
    def create_compliance_report(self, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", "/compliance-reports", payload, headers,
        )

    def generate_compliance_report(self, report_id: str,
                                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/compliance-reports/{report_id}/generate",
            headers=headers,
        )

    def submit_compliance_report(self, report_id: str,
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/compliance-reports/{report_id}/submit",
            headers=headers,
        )

    def acknowledge_compliance_report(self, report_id: str,
                                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/compliance-reports/{report_id}/acknowledge",
            headers=headers,
        )

    def get_compliance_report(self, report_id: str,
                              headers: Dict[str, str]):
        return self._request(
            "GET", f"/compliance-reports/{report_id}",
            headers=headers,
        )

    # ---- AuditLog ----
    def list_audit_log(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/audit-log", headers=headers, params=params,
        )


api_client = ApiClient()

__all__ = ["ApiClient", "api_client"]
