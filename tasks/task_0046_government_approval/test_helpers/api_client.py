"""API client: one method per endpoint defined in the PRD.

Every method delegates to GenericApiClient._request and returns the raw
Response object. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID / X-User-Role on every call.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # =====================================================================
    # Department (PRD §3.1, §4)
    # =====================================================================
    def create_department(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/departments", payload, headers)

    def list_departments(self, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/departments", headers=headers, params=params
        )

    # =====================================================================
    # Matter & MatterVersion (PRD §3.1, §4)
    # =====================================================================
    def create_matter(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/matters", payload, headers)

    def list_matters(self, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/matters", headers=headers, params=params
        )

    def get_matter(self, matter_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/matters/{matter_id}", headers=headers
        )

    def create_matter_version(self, matter_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/matters/{matter_id}/versions", payload, headers
        )

    def get_matter_version(self, matter_id: str, version_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/matters/{matter_id}/versions/{version_id}",
            headers=headers,
        )

    def publish_matter_version(self, matter_id: str, version_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/matters/{matter_id}/versions/{version_id}/publish",
            payload or {}, headers,
        )

    def retire_matter_version(self, matter_id: str, version_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/matters/{matter_id}/versions/{version_id}/retire",
            payload or {}, headers,
        )

    # =====================================================================
    # MaterialTemplate (PRD §3.3, §4)
    # =====================================================================
    def create_material_template(self, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", "/material-templates", payload, headers
        )

    def publish_material_template(self, template_id: str,
                                  headers: Dict[str, str],
                                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/material-templates/{template_id}/publish",
            payload or {}, headers,
        )

    def list_material_templates(self, headers: Dict[str, str],
                                params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/material-templates",
            headers=headers, params=params,
        )

    # =====================================================================
    # CertificateTemplate (PRD §3.3, §4)
    # =====================================================================
    def create_certificate_template(self, payload: Dict[str, Any],
                                    headers: Dict[str, str]):
        return self._request(
            "POST", "/certificate-templates", payload, headers
        )

    def publish_certificate_template(self, template_id: str,
                                     headers: Dict[str, str],
                                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/certificate-templates/{template_id}/publish",
            payload or {}, headers,
        )

    def list_certificate_templates(self, headers: Dict[str, str],
                                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/certificate-templates",
            headers=headers, params=params,
        )

    # =====================================================================
    # Application (PRD §3.4 -- §3.6, §3.12, §4)
    # =====================================================================
    def submit_application(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/applications/{application_id}", headers=headers
        )

    def get_application_sla(self, application_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "GET", f"/applications/{application_id}/sla", headers=headers
        )

    def withdraw_application(self, application_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/applications/{application_id}/withdraw",
            payload or {}, headers,
        )

    def escalate_application(self, application_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/applications/{application_id}/escalate",
            payload or {}, headers,
        )

    def resolve_escalation(self, application_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/applications/{application_id}/escalation-resolve",
            payload, headers,
        )

    def list_review_tasks(self, application_id: str,
                          headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/applications/{application_id}/review-tasks",
            headers=headers, params=params,
        )

    # =====================================================================
    # ReviewTask (PRD §3.6, §4)
    # =====================================================================
    def decide_review_task(self, review_task_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/review-tasks/{review_task_id}/decide",
            payload, headers,
        )

    # =====================================================================
    # CorrectionNotice (PRD §3.6, §4)
    # =====================================================================
    def issue_correction_notice(self, application_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/applications/{application_id}/correction-notices",
            payload, headers,
        )

    def list_correction_notices(self, application_id: str,
                                headers: Dict[str, str],
                                params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/applications/{application_id}/correction-notices",
            headers=headers, params=params,
        )

    def resubmit_correction(self, application_id: str,
                            correction_notice_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/applications/{application_id}/correction-notices/"
            f"{correction_notice_id}/resubmit",
            payload, headers,
        )

    # =====================================================================
    # Certificate (PRD §3.10, §4)
    # =====================================================================
    def get_application_certificate(self, application_id: str,
                                    headers: Dict[str, str]):
        return self._request(
            "GET", f"/applications/{application_id}/certificate",
            headers=headers,
        )

    def reissue_certificate(self, certificate_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/certificates/{certificate_id}/reissue",
            payload or {}, headers,
        )

    def revoke_certificate(self, certificate_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/certificates/{certificate_id}/revoke",
            payload or {}, headers,
        )

    def verify_certificate(self, verification_code: str,
                           headers: Dict[str, str]):
        return self._request(
            "GET", f"/certificates/verify/{verification_code}",
            headers=headers,
        )

    # =====================================================================
    # ExternalEvent ingress (PRD §2.12, §3.5, §4)
    # =====================================================================
    def emit_event(self, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "POST", "/_events/emit", payload, headers
        )

    # =====================================================================
    # Audit log (PRD §2.13, §3.13, §4)
    # =====================================================================
    def list_audit_logs(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/audit-logs", headers=headers, params=params
        )

    # =====================================================================
    # Test-driving endpoints (PRD §2.14, §4)
    # =====================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", payload, headers
        )

    def run_sweep(self, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/_sweep/run", payload or {}, headers
        )

    # =====================================================================
    # Performance reporting (PRD §3.13, §4)
    # =====================================================================
    def get_sla_performance(self, headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/reports/sla-performance",
            headers=headers, params=params,
        )


api_client = ApiClient()


__all__ = ["api_client", "ApiClient"]
