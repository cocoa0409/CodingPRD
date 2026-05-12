"""API client: one method per endpoint defined in PRD §4.

Subclasses GenericApiClient from the framework. Each method delegates to
_request and returns the raw Response object. Headers are passed explicitly
because PRD §2.1 requires X-User-ID and X-User-Role on every call.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """One method per PRD §4 endpoint."""

    # =======================================================================
    # Project
    # =======================================================================
    def create_project(
        self, payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request("POST", "/projects", payload, headers)

    def list_projects(
        self, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", "/projects", headers=headers, params=params,
        )

    def get_project(self, project_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/projects/{project_id}", headers=headers,
        )

    def archive_project(
        self, project_id: str, headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/projects/{project_id}/archive",
            payload or {}, headers,
        )

    # =======================================================================
    # Module
    # =======================================================================
    def create_module(
        self, project_id: str, payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/projects/{project_id}/modules", payload, headers,
        )

    def list_modules(
        self, project_id: str, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/projects/{project_id}/modules",
            headers=headers, params=params,
        )

    def get_module(
        self, project_id: str, module_id: str, headers: Dict[str, str],
    ):
        return self._request(
            "GET", f"/projects/{project_id}/modules/{module_id}",
            headers=headers,
        )

    def archive_module(
        self, project_id: str, module_id: str, headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/projects/{project_id}/modules/{module_id}/archive",
            payload or {}, headers,
        )

    # =======================================================================
    # TeamMember
    # =======================================================================
    def create_team_member(
        self, project_id: str, payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/projects/{project_id}/team-members",
            payload, headers,
        )

    def list_team_members(
        self, project_id: str, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/projects/{project_id}/team-members",
            headers=headers, params=params,
        )

    def get_team_member(
        self, project_id: str, team_member_id: str,
        headers: Dict[str, str],
    ):
        return self._request(
            "GET",
            f"/projects/{project_id}/team-members/{team_member_id}",
            headers=headers,
        )

    # =======================================================================
    # Defect
    # =======================================================================
    def create_defect(
        self, payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request("POST", "/defects", payload, headers)

    def list_defects(
        self, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", "/defects", headers=headers, params=params,
        )

    def get_defect(self, defect_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/defects/{defect_id}", headers=headers,
        )

    def assign_defect(
        self, defect_id: str, headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/defects/{defect_id}/assign",
            payload or {}, headers,
        )

    def reassign_defect(
        self, defect_id: str, payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/defects/{defect_id}/reassign", payload, headers,
        )

    def start_progress(
        self, defect_id: str, headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/defects/{defect_id}/start-progress",
            payload or {}, headers,
        )

    def submit_fix(
        self, defect_id: str, payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/defects/{defect_id}/submit-fix", payload, headers,
        )

    def verify_defect(
        self, defect_id: str, payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/defects/{defect_id}/verify", payload, headers,
        )

    def close_defect(
        self, defect_id: str, headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/defects/{defect_id}/close",
            payload or {}, headers,
        )

    def pause_sla(
        self, defect_id: str, payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/defects/{defect_id}/pause-sla", payload, headers,
        )

    def resume_sla(
        self, defect_id: str, headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/defects/{defect_id}/resume-sla",
            payload or {}, headers,
        )

    # =======================================================================
    # Attachments
    # =======================================================================
    def upload_attachment(
        self, defect_id: str, payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/defects/{defect_id}/attachments", payload, headers,
        )

    def list_attachments(
        self, defect_id: str, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/defects/{defect_id}/attachments",
            headers=headers, params=params,
        )

    # =======================================================================
    # DuplicateLink
    # =======================================================================
    def create_duplicate_link(
        self, payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request(
            "POST", "/duplicate-links", payload, headers,
        )

    def list_duplicate_links(
        self, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", "/duplicate-links",
            headers=headers, params=params,
        )

    # =======================================================================
    # SeverityOverride
    # =======================================================================
    def request_severity_override(
        self, defect_id: str, payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/defects/{defect_id}/severity-overrides",
            payload, headers,
        )

    def approve_severity_override(
        self, override_id: str, headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/severity-overrides/{override_id}/approve",
            payload or {}, headers,
        )

    def reject_severity_override(
        self, override_id: str, headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/severity-overrides/{override_id}/reject",
            payload or {}, headers,
        )

    def get_severity_override(
        self, override_id: str, headers: Dict[str, str],
    ):
        return self._request(
            "GET", f"/severity-overrides/{override_id}",
            headers=headers,
        )

    # =======================================================================
    # FixRecord / VerificationRecord
    # =======================================================================
    def list_fix_records(
        self, defect_id: str, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/defects/{defect_id}/fix-records",
            headers=headers, params=params,
        )

    def list_verification_records(
        self, defect_id: str, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/defects/{defect_id}/verification-records",
            headers=headers, params=params,
        )

    # =======================================================================
    # RegressionRun
    # =======================================================================
    def create_regression_run(
        self, defect_id: str, payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/defects/{defect_id}/regression-runs",
            payload, headers,
        )

    def start_regression_run(
        self, regression_run_id: str, headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/regression-runs/{regression_run_id}/start",
            payload or {}, headers,
        )

    def complete_regression_run(
        self, regression_run_id: str, payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/regression-runs/{regression_run_id}/complete",
            payload, headers,
        )

    def list_regression_runs(
        self, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", "/regression-runs",
            headers=headers, params=params,
        )

    def get_regression_run(
        self, regression_run_id: str, headers: Dict[str, str],
    ):
        return self._request(
            "GET", f"/regression-runs/{regression_run_id}",
            headers=headers,
        )

    # =======================================================================
    # Audit log
    # =======================================================================
    def list_audit_entries(
        self, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", "/audit-entries",
            headers=headers, params=params,
        )

    # =======================================================================
    # Statistics
    # =======================================================================
    def get_distribution(
        self, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", "/statistics/distribution",
            headers=headers, params=params,
        )

    def get_density(
        self, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", "/statistics/density",
            headers=headers, params=params,
        )

    def get_reopen_rate(
        self, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", "/statistics/reopen-rate",
            headers=headers, params=params,
        )

    def get_removal_rate(
        self, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", "/statistics/removal-rate",
            headers=headers, params=params,
        )

    def get_sla_performance(
        self, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", "/statistics/sla-performance",
            headers=headers, params=params,
        )

    # =======================================================================
    # Test-driving endpoints (clock / sweep / events)
    # =======================================================================
    def advance_clock(
        self, project_id: str, minutes: int, headers: Dict[str, str],
    ):
        return self._request(
            "POST", "/_clock/advance",
            {"project_id": project_id, "minutes": minutes}, headers,
        )

    def run_sla_escalation_sweep(
        self, project_id: str, headers: Dict[str, str],
    ):
        return self._request(
            "POST", "/_sweep/sla-escalation",
            {"project_id": project_id}, headers,
        )

    def emit_event(
        self, payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request(
            "POST", "/_events/emit", payload, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
