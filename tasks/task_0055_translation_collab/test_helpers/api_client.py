"""API client: one method per endpoint defined in PRD §4.

Each method delegates to GenericApiClient._request and returns the raw
Response object. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every call.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Clients (PRD §3.1, §4)
    # =======================================================================
    def create_client(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/clients/{client_id}", headers=headers,
        )

    def list_clients(self, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/clients", headers=headers, params=params,
        )

    # =======================================================================
    # Translators (PRD §3.1, §4)
    # =======================================================================
    def create_translator(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/translators", payload, headers)

    def pass_test_translator(self, translator_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/translators/{translator_id}/pass-test",
            payload or {}, headers,
        )

    def get_translator(self, translator_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/translators/{translator_id}", headers=headers,
        )

    def list_translators(self, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/translators", headers=headers, params=params,
        )

    # =======================================================================
    # Projects (PRD §3.2, §4)
    # =======================================================================
    def create_project(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/projects", payload, headers)

    def get_project(self, project_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/projects/{project_id}", headers=headers,
        )

    def update_project(self, project_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "PUT", f"/projects/{project_id}", payload, headers,
        )

    def quote_project(self, project_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/projects/{project_id}/quote",
            payload or {}, headers,
        )

    def activate_project(self, project_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/projects/{project_id}/activate",
            payload or {}, headers,
        )

    def publish_project(self, project_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/projects/{project_id}/publish",
            payload or {}, headers,
        )

    def cancel_project(self, project_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/projects/{project_id}/cancel",
            payload or {}, headers,
        )

    def list_projects(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/projects", headers=headers, params=params,
        )

    # =======================================================================
    # Project Templates (PRD §3.2, §4)
    # =======================================================================
    def create_project_template(self, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request("POST", "/project-templates", payload, headers)

    def get_project_template(self, template_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "GET", f"/project-templates/{template_id}", headers=headers,
        )

    # =======================================================================
    # Documents (PRD §3.2, §4)
    # =======================================================================
    def upload_document(self, project_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/projects/{project_id}/documents", payload, headers,
        )

    def split_document(self, document_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/documents/{document_id}/split",
            payload or {}, headers,
        )

    def archive_document(self, document_id: str, headers: Dict[str, str]):
        return self._request(
            "DELETE", f"/documents/{document_id}", headers=headers,
        )

    # =======================================================================
    # Segments (PRD §3.4, §4)
    # =======================================================================
    def get_segment(self, segment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/segments/{segment_id}", headers=headers,
        )

    def submit_translation(self, segment_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/segments/{segment_id}/submit-translation",
            payload, headers,
        )

    def submit_review(self, segment_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/segments/{segment_id}/submit-review",
            payload, headers,
        )

    def final_approve_segment(self, segment_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/segments/{segment_id}/final-approve",
            payload or {}, headers,
        )

    def reject_segment(self, segment_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/segments/{segment_id}/reject", payload, headers,
        )

    # =======================================================================
    # Assignments (PRD §3.3, §4)
    # =======================================================================
    def dispatch_assignment(self, project_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/projects/{project_id}/assignments",
            payload, headers,
        )

    def get_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/assignments/{assignment_id}", headers=headers,
        )

    def accept_assignment(self, assignment_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/assignments/{assignment_id}/accept",
            payload or {}, headers,
        )

    def reject_assignment(self, assignment_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/assignments/{assignment_id}/reject",
            payload, headers,
        )

    def reassign_assignment(self, assignment_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/assignments/{assignment_id}/reassign",
            payload, headers,
        )

    # =======================================================================
    # Terminology (PRD §3.5, §4)
    # =======================================================================
    def create_terminology(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", "/terminology", payload, headers)

    def approve_terminology(self, term_id: str, headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/terminology/{term_id}/approve",
            payload or {}, headers,
        )

    def resolve_terminology(self, term_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/terminology/{term_id}/resolve", payload, headers,
        )

    def delete_terminology(self, term_id: str, headers: Dict[str, str]):
        return self._request(
            "DELETE", f"/terminology/{term_id}", headers=headers,
        )

    def list_terminology(self, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/terminology", headers=headers, params=params,
        )

    # =======================================================================
    # Quality Scores (PRD §3.6, §4)
    # =======================================================================
    def create_quality_score(self, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request("POST", "/quality-scores", payload, headers)

    def finalize_quality_score(self, score_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/quality-scores/{score_id}/finalize",
            payload or {}, headers,
        )

    def void_quality_score(self, score_id: str, headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/quality-scores/{score_id}/void",
            payload or {}, headers,
        )

    # =======================================================================
    # Audit & Sync (PRD §3.9, §4)
    # =======================================================================
    def list_audit_entries(self, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/audit-entries", headers=headers, params=params,
        )

    def list_external_sync_records(self, headers: Dict[str, str],
                                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/external-sync-records", headers=headers, params=params,
        )

    # =======================================================================
    # Test-driving (PRD §2.10, §4)
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )

    def run_sweep(self, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/_sweep/run", payload or {}, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
