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
    # Clients (PRD §3.1)
    # =======================================================================
    def create_client(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/customs/clients", payload, headers)

    def get_client(self, client_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/customs/clients/{client_id}",
                             headers=headers)

    def list_clients(self, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/customs/clients",
                             headers=headers, params=params)

    def update_client(self, client_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("PATCH", f"/customs/clients/{client_id}",
                             payload, headers)

    # =======================================================================
    # Agreements (PRD §3.1, §3.2)
    # =======================================================================
    def create_agreement(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", "/customs/agreements", payload, headers)

    def get_agreement(self, agreement_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/customs/agreements/{agreement_id}",
                             headers=headers)

    def request_signature(self, agreement_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/customs/agreements/{agreement_id}/request-signature",
            payload, headers,
        )

    def sign_agreement(self, agreement_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/customs/agreements/{agreement_id}/sign",
            payload, headers,
        )

    def terminate_agreement(self, agreement_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/customs/agreements/{agreement_id}/terminate",
            payload, headers,
        )

    # =======================================================================
    # Declarations (PRD §3.3 — §3.6, §3.11)
    # =======================================================================
    def create_declaration(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", "/customs/declarations", payload, headers)

    def get_declaration(self, declaration_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/customs/declarations/{declaration_id}",
                             headers=headers)

    def list_declarations(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/customs/declarations",
                             headers=headers, params=params)

    def update_declaration(self, declaration_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/customs/declarations/{declaration_id}",
            payload, headers,
        )

    def request_documents(self, declaration_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/customs/declarations/{declaration_id}/request-documents",
            payload, headers,
        )

    def attach_document(self, declaration_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/customs/declarations/{declaration_id}/documents",
            payload, headers,
        )

    def screen_document(self, document_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/customs/documents/{document_id}/screen",
            payload, headers,
        )

    def pre_validate_declaration(self, declaration_id: str,
                                 payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/customs/declarations/{declaration_id}/pre-validate",
            payload, headers,
        )

    def file_declaration(self, declaration_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/customs/declarations/{declaration_id}/file",
            payload, headers,
        )

    def respond_query(self, declaration_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/customs/declarations/{declaration_id}/respond-query",
            payload, headers,
        )

    def amend_declaration(self, declaration_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/customs/declarations/{declaration_id}/amend",
            payload, headers,
        )

    def withdraw_declaration(self, declaration_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/customs/declarations/{declaration_id}/withdraw",
            payload, headers,
        )

    # =======================================================================
    # Inspection (PRD §3.7)
    # =======================================================================
    def create_inspection_case(self, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", "/customs/inspection-cases", payload, headers,
        )

    def provide_sample(self, case_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/customs/inspection-cases/{case_id}/provide-sample",
            payload, headers,
        )

    def record_inspection_outcome(self, case_id: str,
                                  payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", f"/customs/inspection-cases/{case_id}/record-outcome",
            payload, headers,
        )

    def get_inspection_case(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/customs/inspection-cases/{case_id}", headers=headers,
        )

    # =======================================================================
    # Settlements (PRD §3.8 — §3.10)
    # =======================================================================
    def get_settlement(self, settlement_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/customs/settlements/{settlement_id}", headers=headers,
        )

    def list_settlements(self, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/customs/settlements", headers=headers, params=params,
        )

    def advance_settlement(self, settlement_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/customs/settlements/{settlement_id}/advance",
            payload, headers,
        )

    # =======================================================================
    # Audit & rejection records (PRD §2.8, §3.11)
    # =======================================================================
    def list_audit_log(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/customs/audit-log", headers=headers, params=params,
        )

    def list_rejection_records(self, headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/customs/rejection-records",
            headers=headers, params=params,
        )

    # =======================================================================
    # Test-driver endpoints (PRD §2.12)
    # =======================================================================
    def emit_event(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", "/customs/_events/emit", payload, headers,
        )

    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/customs/_clock/advance", payload, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
