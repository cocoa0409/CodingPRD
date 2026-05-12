"""API client: one method per endpoint defined in PRD §4.

Every method delegates to GenericApiClient._request and returns the raw
Response object. Tests pass headers explicitly because PRD §2.1 makes
X-User-ID / X-User-Role mandatory for every call (with the narrow
exceptions noted in PRD §2.3 and §3.8).
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


PREFIX = ""  # PRD §4 endpoints use bare paths (no API prefix)


class ApiClient(GenericApiClient):
    # =====================================================================
    # Templates (PRD §3.1, §4)
    # =====================================================================
    def create_template(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/templates", payload, headers)

    def list_templates(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/templates", headers=headers, params=params
        )

    def get_template(self, template_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/templates/{template_id}", headers=headers
        )

    def patch_template(self, template_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/templates/{template_id}", payload, headers
        )

    # ----- TemplateVersion (nested under Template) -----------------------
    def create_template_version(self, template_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/templates/{template_id}/versions", payload, headers
        )

    def list_template_versions(self, template_id: str,
                               headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/templates/{template_id}/versions",
            headers=headers, params=params,
        )

    def get_template_version(self, template_id: str, version_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/templates/{template_id}/versions/{version_id}",
            headers=headers,
        )

    def patch_template_version(self, template_id: str, version_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "PATCH",
            f"/templates/{template_id}/versions/{version_id}",
            payload, headers,
        )

    def publish_template_version(self, template_id: str, version_id: str,
                                 headers: Dict[str, str],
                                 payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/templates/{template_id}/versions/{version_id}/publish",
            payload or {}, headers,
        )

    def deprecate_template_version(self, template_id: str, version_id: str,
                                   headers: Dict[str, str],
                                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/templates/{template_id}/versions/{version_id}/deprecate",
            payload or {}, headers,
        )

    # =====================================================================
    # Contracts (PRD §3.2-§3.7, §4)
    # =====================================================================
    def create_contract(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/contracts", payload, headers)

    def list_contracts(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/contracts", headers=headers, params=params
        )

    def get_contract(self, contract_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/contracts/{contract_id}", headers=headers
        )

    def patch_contract(self, contract_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/contracts/{contract_id}", payload, headers
        )

    def create_signing_step(self, contract_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/contracts/{contract_id}/signing-steps",
            payload, headers,
        )

    def create_signing_party(self, contract_id: str, signing_step_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/contracts/{contract_id}/signing-steps/"
            f"{signing_step_id}/parties",
            payload, headers,
        )

    def activate_contract(self, contract_id: str, headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/contracts/{contract_id}/activate",
            payload or {}, headers,
        )

    def void_contract(self, contract_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/contracts/{contract_id}/void",
            payload or {}, headers,
        )

    def get_contract_progress(self, contract_id: str,
                              headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/contracts/{contract_id}/progress",
            headers=headers, params=params,
        )

    def list_contract_audit_logs(self, contract_id: str,
                                 headers: Dict[str, str],
                                 params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/contracts/{contract_id}/audit-logs",
            headers=headers, params=params,
        )

    # =====================================================================
    # Signing parties (PRD §3.5, §3.6)
    # =====================================================================
    def sign_party(self, party_id: str, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/signing-parties/{party_id}/sign", payload, headers
        )

    def decline_party(self, party_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/signing-parties/{party_id}/decline",
            payload or {}, headers,
        )

    # =====================================================================
    # Identity verifications (PRD §3.5)
    # =====================================================================
    def create_identity_verification(self, payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request(
            "POST", "/identity-verifications", payload, headers
        )

    def get_identity_verification(self, verification_id: str,
                                  headers: Dict[str, str]):
        return self._request(
            "GET", f"/identity-verifications/{verification_id}",
            headers=headers,
        )

    # =====================================================================
    # Reminder rules and events (PRD §3.8)
    # =====================================================================
    def create_reminder_rule(self, contract_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/contracts/{contract_id}/reminder-rules",
            payload, headers,
        )

    def patch_reminder_rule(self, rule_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/reminder-rules/{rule_id}", payload, headers
        )

    def fire_reminder(self, rule_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/reminder-rules/{rule_id}/fire", payload, headers
        )

    def list_reminder_events(self, contract_id: str,
                             headers: Dict[str, str],
                             params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/contracts/{contract_id}/reminder-events",
            headers=headers, params=params,
        )

    # =====================================================================
    # Evidence (PRD §3.10, §3.11)
    # =====================================================================
    def get_evidence_package(self, contract_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "GET", f"/contracts/{contract_id}/evidence", headers=headers
        )

    def get_evidence_preview(self, contract_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "GET", f"/contracts/{contract_id}/evidence/preview",
            headers=headers,
        )

    def seal_evidence(self, contract_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/contracts/{contract_id}/evidence/seal",
            payload, headers,
        )

    def export_evidence(self, contract_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/contracts/{contract_id}/evidence/export",
            payload or {}, headers,
        )

    # =====================================================================
    # Test-driving endpoints (PRD §3.8, §4)
    # =====================================================================
    def advance_clock(self, to_iso: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", {"to": to_iso}, headers
        )

    def run_sweep(self, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/_sweep/run", payload or {}, headers
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client", "PREFIX"]
