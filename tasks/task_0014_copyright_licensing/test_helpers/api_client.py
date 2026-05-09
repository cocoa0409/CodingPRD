"""API client: one method per endpoint defined in the PRD."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- RightsHolders ---
    def create_rights_holder(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/rights-holders", payload, headers)

    def get_rights_holder(self, holder_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/rights-holders/{holder_id}", headers=headers)

    # --- Works ---
    def create_work(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/works", payload, headers)

    def get_work(self, work_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/works/{work_id}", headers=headers)

    def patch_work(self, work_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/works/{work_id}", payload, headers)

    def submit_work(self, work_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/works/{work_id}/submit", payload or {}, headers)

    def get_rights_chain(self, work_id: str, headers: Optional[Dict[str, str]] = None,
                         params: Optional[Dict[str, Any]] = None):
        # PRD §2.1: rights-chain history is the public exception to auth.
        return self._request("GET", f"/works/{work_id}/rights-chain",
                             headers=headers, params=params)

    # --- Licenses ---
    def create_license(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/licenses", payload, headers)

    def get_license(self, license_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/licenses/{license_id}", headers=headers)

    def list_rounds(self, license_id: str, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/licenses/{license_id}/rounds",
                             headers=headers, params=params)

    def submit_round(self, license_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/licenses/{license_id}/rounds", payload, headers)

    def terminate_license(self, license_id: str, headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/licenses/{license_id}/terminate",
                             payload or {}, headers)

    # --- Contracts ---
    def create_contract(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/contracts", payload, headers)

    def get_contract(self, contract_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def submit_signature(self, contract_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/contracts/{contract_id}/signatures", payload, headers)

    # --- RoyaltyStatements ---
    def create_royalty_statement(self, license_id: str, payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request("POST", f"/licenses/{license_id}/royalty-statements",
                             payload, headers)

    def get_royalty_statement(self, license_id: str, statement_id: str,
                              headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/licenses/{license_id}/royalty-statements/{statement_id}",
            headers=headers,
        )

    def list_royalty_statements(self, license_id: str, headers: Dict[str, str],
                                 params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/licenses/{license_id}/royalty-statements",
                             headers=headers, params=params)

    # --- InfringementCases ---
    def create_infringement_case(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/infringement-cases", payload, headers)

    def get_infringement_case(self, case_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/infringement-cases/{case_id}", headers=headers)

    def verify_ownership(self, case_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/infringement-cases/{case_id}/verify-ownership",
                             payload or {}, headers)

    def respond_infringement(self, case_id: str, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request("POST", f"/infringement-cases/{case_id}/respond",
                             payload, headers)

    def escalate_infringement(self, case_id: str, headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/infringement-cases/{case_id}/escalate",
                             payload or {}, headers)

    def resolve_infringement(self, case_id: str, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request("POST", f"/infringement-cases/{case_id}/resolve",
                             payload, headers)

    def dismiss_infringement(self, case_id: str, headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/infringement-cases/{case_id}/dismiss",
                             payload or {}, headers)

    # --- Audit logs ---
    def list_audit_logs(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/audit-logs", headers=headers, params=params)

    # --- External events ---
    def emit_event(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_events/emit", payload, headers)

    # --- Test-driving clock control ---
    def advance_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance",
                             {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
