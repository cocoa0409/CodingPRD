"""API client for the IP Management API.

One method per endpoint defined in PRD §4. Inherits the generic `_request` from
the framework's `GenericApiClient`. Methods only thread inputs; they do not
mutate state or interpret responses.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Concrete client; every method returns the raw requests.Response."""

    # ────────────── Business Units (PRD §3.1, §3.7) ──────────────
    def create_business_unit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/business-units", payload, headers)

    def list_business_units(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/business-units", headers=headers, params=params)

    def get_business_unit(self, bu_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/business-units/{bu_id}", headers=headers)

    def archive_business_unit(
        self,
        bu_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", f"/business-units/{bu_id}/archive", payload or {}, headers
        )

    # ────────────── Agents (PRD §3.1) ────────────────────────────
    def create_agent(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/agents", payload, headers)

    def verify_agent(
        self,
        agent_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", f"/agents/{agent_id}/verify", payload or {}, headers
        )

    def list_agents(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/agents", headers=headers, params=params)

    def get_agent(self, agent_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/agents/{agent_id}", headers=headers)

    # ────────────── IP Rights (PRD §3.2) ──────────────────────────
    def create_ip_right(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/ip-rights", payload, headers)

    def list_ip_rights(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/ip-rights", headers=headers, params=params)

    def get_ip_right(self, ip_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/ip-rights/{ip_id}", headers=headers)

    def mark_materials_ready(
        self,
        ip_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", f"/ip-rights/{ip_id}/materials-ready", payload or {}, headers
        )

    def create_jurisdiction_filing(
        self, ip_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/ip-rights/{ip_id}/jurisdiction-filings", payload, headers
        )

    def register_filing(
        self, filing_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/jurisdiction-filings/{filing_id}/register", payload, headers
        )

    def create_office_action(
        self, ip_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/ip-rights/{ip_id}/office-actions", payload, headers
        )

    def respond_office_action(
        self,
        action_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", f"/office-actions/{action_id}/respond", payload or {}, headers
        )

    def abandon_office_action(
        self,
        action_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", f"/office-actions/{action_id}/abandon", payload or {}, headers
        )

    # ────────────── Annual Fees (PRD §3.3) ────────────────────────
    def create_annual_fee(
        self, ip_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/ip-rights/{ip_id}/annual-fees", payload, headers
        )

    def list_annual_fees(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/annual-fees", headers=headers, params=params)

    def pay_annual_fee(
        self,
        fee_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", f"/annual-fees/{fee_id}/pay", payload or {}, headers
        )

    # ────────────── Contract Templates (PRD §3.1) ─────────────────
    def create_contract_template(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/contract-templates", payload, headers)

    def list_contract_templates(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/contract-templates", headers=headers, params=params
        )

    # ────────────── Contracts (PRD §3.4) ──────────────────────────
    def create_contract(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/contracts", payload, headers)

    def start_signing(
        self,
        contract_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", f"/contracts/{contract_id}/start-signing", payload or {}, headers
        )

    def sign_contract(
        self, contract_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/contracts/{contract_id}/sign", payload, headers
        )

    def file_contract_with_authority(
        self,
        contract_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST",
            f"/contracts/{contract_id}/file-with-authority",
            payload or {},
            headers,
        )

    def amend_contract(
        self,
        contract_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", f"/contracts/{contract_id}/amend", payload or {}, headers
        )

    def terminate_contract(
        self,
        contract_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", f"/contracts/{contract_id}/terminate", payload or {}, headers
        )

    # ────────────── Royalty Schedules (PRD §3.5) ──────────────────
    def create_royalty_schedule(
        self, contract_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/contracts/{contract_id}/royalty-schedules", payload, headers
        )

    def settle_royalty_schedule(
        self, schedule_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/royalty-schedules/{schedule_id}/settle", payload, headers
        )

    def get_royalty_schedule(self, schedule_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/royalty-schedules/{schedule_id}", headers=headers
        )

    # ────────────── Protection Cases (PRD §3.6) ───────────────────
    def create_protection_case(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/protection-cases", payload, headers)

    def get_protection_case(self, case_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/protection-cases/{case_id}", headers=headers)

    def add_evidence(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/protection-cases/{case_id}/evidence", payload, headers
        )

    def route_protection_case(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/protection-cases/{case_id}/route", payload, headers
        )

    def resolve_protection_case(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/protection-cases/{case_id}/resolve", payload, headers
        )

    def close_protection_case(
        self,
        case_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", f"/protection-cases/{case_id}/close", payload or {}, headers
        )

    # ────────────── Costs (PRD §3.7) ──────────────────────────────
    def create_cost(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/costs", payload, headers)

    def reallocate_cost(
        self, cost_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"/costs/{cost_id}/allocation", payload, headers
        )

    def list_costs(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/costs", headers=headers, params=params)

    def get_cost_summary(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/reports/cost-summary", headers=headers, params=params
        )

    # ────────────── Audit (PRD §2.9) ──────────────────────────────
    def list_audit_entries(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/audit-entries", headers=headers, params=params)

    # ────────────── Test-driving / system endpoints (PRD §3.8) ────
    def advance_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def sweep_annual_fees(
        self,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request("POST", "/_sweep/annual-fees", payload or {}, headers)

    def event_payment_settled(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/_events/payment-settled", payload, headers)

    def event_esign_completed(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/_events/esign-completed", payload, headers)


api_client = ApiClient()
