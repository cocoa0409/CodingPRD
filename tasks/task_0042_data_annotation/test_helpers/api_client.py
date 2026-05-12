"""API client: one method per endpoint defined in PRD §4.

Every method delegates to GenericApiClient._request and returns the raw
Response object. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID / X-User-Role on every call.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


PREFIX = ""  # PRD §4 endpoints use bare paths.


class ApiClient(GenericApiClient):
    # =====================================================================
    # AnnotationProject (PRD §3.1, §4)
    # =====================================================================
    def create_project(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/annotation-projects", payload, headers)

    def list_projects(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/annotation-projects", headers=headers, params=params
        )

    def get_project(self, project_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/annotation-projects/{project_id}", headers=headers
        )

    def patch_project(self, project_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/annotation-projects/{project_id}", payload, headers
        )

    def add_golden_sample(self, project_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/annotation-projects/{project_id}/golden-samples",
            payload, headers,
        )

    def list_golden_samples(self, project_id: str,
                            headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/annotation-projects/{project_id}/golden-samples",
            headers=headers, params=params,
        )

    def split_packages(self, project_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/annotation-projects/{project_id}/task-packages/split",
            payload, headers,
        )

    def open_project(self, project_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/annotation-projects/{project_id}/open",
            payload or {}, headers,
        )

    def close_project(self, project_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/annotation-projects/{project_id}/close",
            payload or {}, headers,
        )

    def archive_project(self, project_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/annotation-projects/{project_id}/archive",
            payload or {}, headers,
        )

    # =====================================================================
    # TaskPackage (PRD §3.3, §3.4, §4)
    # =====================================================================
    def list_packages(self, project_id: str, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/annotation-projects/{project_id}/task-packages",
            headers=headers, params=params,
        )

    def get_package(self, package_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/task-packages/{package_id}", headers=headers
        )

    def claim_package(self, package_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/task-packages/{package_id}/claim",
            payload or {}, headers,
        )

    def dispatch_package(self, package_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/task-packages/{package_id}/dispatch",
            payload, headers,
        )

    def submit_package(self, package_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/task-packages/{package_id}/submit",
            payload, headers,
        )

    def start_inspection(self, package_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/task-packages/{package_id}/start-inspection",
            payload or {}, headers,
        )

    def finalize_inspection(self, package_id: str, inspection_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/task-packages/{package_id}/inspections/"
            f"{inspection_id}/finalize",
            payload, headers,
        )

    def rework_claim(self, package_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/task-packages/{package_id}/rework-claim",
            payload or {}, headers,
        )

    def rework_dispatch(self, package_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/task-packages/{package_id}/rework-dispatch",
            payload or {}, headers,
        )

    def arbitrate_package(self, package_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/task-packages/{package_id}/arbitrate",
            payload, headers,
        )

    # =====================================================================
    # Appeal (PRD §3.8, §4)
    # =====================================================================
    def create_appeal(self, package_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/task-packages/{package_id}/appeals",
            payload, headers,
        )

    def get_appeal(self, appeal_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/appeals/{appeal_id}", headers=headers
        )

    def assign_arbiter(self, appeal_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/appeals/{appeal_id}/assign-arbiter",
            payload or {}, headers,
        )

    def decide_appeal(self, appeal_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/appeals/{appeal_id}/decide",
            payload, headers,
        )

    # =====================================================================
    # AnnotatorProfile (PRD §3.2, §4)
    # =====================================================================
    def create_annotator(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", "/annotators", payload, headers)

    def list_annotators(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/annotators", headers=headers, params=params
        )

    def get_annotator(self, annotator_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/annotators/{annotator_id}", headers=headers
        )

    def re_evaluate_annotator(self, annotator_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/annotators/{annotator_id}/re-evaluate",
            payload or {}, headers,
        )

    def reinstate_annotator(self, annotator_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/annotators/{annotator_id}/reinstate",
            payload or {}, headers,
        )

    def get_projected_pass_rate(self, annotator_id: str,
                                headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/annotators/{annotator_id}/projected-pass-rate",
            headers=headers,
        )

    # =====================================================================
    # PayrollPeriod (PRD §3.10, §4)
    # =====================================================================
    def create_payroll_period(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", "/payroll-periods", payload, headers)

    def list_payroll_periods(self, headers: Dict[str, str],
                             params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/payroll-periods", headers=headers, params=params
        )

    def lock_payroll_period(self, period_id: str, headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/payroll-periods/{period_id}/lock",
            payload or {}, headers,
        )

    def settle_payroll_period(self, period_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/payroll-periods/{period_id}/settle",
            payload or {}, headers,
        )

    def list_ledger_entries(self, period_id: str,
                            headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/payroll-periods/{period_id}/ledger-entries",
            headers=headers, params=params,
        )

    # =====================================================================
    # AuditLog and ExternalEvent (PRD §3.11, §4)
    # =====================================================================
    def list_audit_logs(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/audit-logs", headers=headers, params=params
        )

    def list_external_events(self, headers: Dict[str, str],
                             params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/external-events", headers=headers, params=params
        )

    # =====================================================================
    # Test-driving endpoints (PRD §3.5, §4)
    # =====================================================================
    def advance_clock(self, to_iso: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", {"to": to_iso}, headers
        )

    def dispatch_pending_events(self, headers: Dict[str, str],
                                payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/_events/dispatch-pending",
            payload or {}, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client", "PREFIX"]
