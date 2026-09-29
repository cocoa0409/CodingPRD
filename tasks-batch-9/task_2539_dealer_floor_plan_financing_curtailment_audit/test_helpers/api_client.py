"""API client: one method per endpoint the PRD declares."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/floorplan"


class ApiClient(GenericApiClient):
    """Endpoint methods for the Dealer Floorplan Curtailment Audit API."""

    # -- logical clock ----------------------------------------------------
    def set_current_utc(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # -- dealers ----------------------------------------------------------
    def create_dealer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/dealers", payload, headers)

    def get_dealer(self, dealer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/dealers/{dealer_id}", headers=headers)

    def list_dealers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/dealers", headers=headers, params=params)

    # -- covenant tests ---------------------------------------------------
    def file_covenant_test(
        self, dealer_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/dealers/{dealer_id}/covenant-tests", payload, headers
        )

    def list_covenant_tests(
        self, dealer_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/dealers/{dealer_id}/covenant-tests",
            headers=headers,
            params=params,
        )

    # -- remedy actions ---------------------------------------------------
    def issue_remedy_action(
        self, dealer_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/dealers/{dealer_id}/remedy-actions", payload, headers
        )

    def list_remedy_actions(
        self, dealer_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/dealers/{dealer_id}/remedy-actions",
            headers=headers,
            params=params,
        )

    def execute_remedy_action(
        self, remedy_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/remedy-actions/{remedy_id}/execute", payload or {}, headers
        )

    # -- credit lines -----------------------------------------------------
    def create_credit_line(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/credit-lines", payload, headers)

    def get_credit_line(self, credit_line_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/credit-lines/{credit_line_id}", headers=headers
        )

    def list_credit_lines(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/credit-lines", headers=headers, params=params
        )

    def activate_credit_line(
        self, credit_line_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{PREFIX}/credit-lines/{credit_line_id}/activate",
            payload or {},
            headers,
        )

    def reinstate_credit_line(
        self, credit_line_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{PREFIX}/credit-lines/{credit_line_id}/reinstate",
            payload or {},
            headers,
        )

    # -- curtailment tiers ------------------------------------------------
    def create_curtailment_tier(
        self, credit_line_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/credit-lines/{credit_line_id}/curtailment-tiers",
            payload,
            headers,
        )

    def list_curtailment_tiers(
        self, credit_line_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/credit-lines/{credit_line_id}/curtailment-tiers",
            headers=headers,
            params=params,
        )

    # -- inventory units --------------------------------------------------
    def create_unit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/units", payload, headers)

    def get_unit(self, unit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/units/{unit_id}", headers=headers)

    def list_units(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/units", headers=headers, params=params)

    def change_title_custody(
        self, unit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/units/{unit_id}/title-custody", payload, headers
        )

    def classify_ineligibility(
        self, unit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/units/{unit_id}/ineligibility", payload, headers
        )

    def get_curtailment_schedule(self, unit_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/units/{unit_id}/curtailment-schedule", headers=headers
        )

    def list_unit_audit_observations(
        self, unit_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/units/{unit_id}/audit-observations",
            headers=headers,
            params=params,
        )

    # -- funding advances -------------------------------------------------
    def request_funding_advance(
        self, unit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/units/{unit_id}/funding-advances", payload, headers
        )

    def fund_advance(
        self, advance_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/funding-advances/{advance_id}/fund", payload, headers
        )

    def reject_advance(
        self, advance_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/funding-advances/{advance_id}/reject", payload, headers
        )

    def reverse_advance(
        self, advance_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/funding-advances/{advance_id}/reverse", payload, headers
        )

    def get_funding_advance(self, advance_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/funding-advances/{advance_id}", headers=headers
        )

    def list_funding_advances(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/funding-advances", headers=headers, params=params
        )

    # -- curtailment obligations and runs ---------------------------------
    def get_curtailment_obligation(self, obligation_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/curtailment-obligations/{obligation_id}", headers=headers
        )

    def list_curtailment_obligations(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/curtailment-obligations", headers=headers, params=params
        )

    def run_curtailment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/curtailment-runs", payload, headers)

    # -- aging exceptions -------------------------------------------------
    def file_aging_exception(
        self, obligation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/curtailment-obligations/{obligation_id}/aging-exceptions",
            payload,
            headers,
        )

    def list_aging_exceptions(
        self, obligation_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/curtailment-obligations/{obligation_id}/aging-exceptions",
            headers=headers,
            params=params,
        )

    def decide_aging_exception(
        self, exception_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/aging-exceptions/{exception_id}/decision", payload, headers
        )

    # -- audits -----------------------------------------------------------
    def schedule_audit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/audits", payload, headers)

    def start_audit(
        self, audit_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/audits/{audit_id}/start", payload or {}, headers
        )

    def record_observation(
        self, audit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/audits/{audit_id}/observations", payload, headers
        )

    def list_audit_observations(
        self, audit_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/audits/{audit_id}/observations",
            headers=headers,
            params=params,
        )

    def reconcile_audit(
        self, audit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/audits/{audit_id}/reconcile", payload, headers
        )

    def abort_audit(
        self, audit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/audits/{audit_id}/abort", payload, headers
        )

    def get_audit(self, audit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/audits/{audit_id}", headers=headers)

    def list_audits(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/audits", headers=headers, params=params)

    # -- out-of-trust incidents -------------------------------------------
    def get_out_of_trust_incident(self, incident_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/out-of-trust-incidents/{incident_id}", headers=headers
        )

    def list_out_of_trust_incidents(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/out-of-trust-incidents", headers=headers, params=params
        )

    # -- remittances ------------------------------------------------------
    def create_remittance(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/remittances", payload, headers)

    def get_remittance(self, remittance_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/remittances/{remittance_id}", headers=headers
        )

    def list_remittances(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/remittances", headers=headers, params=params
        )

    # -- raw helpers for header-level probes ------------------------------
    def raw_get(self, path: str, headers: Optional[Dict[str, str]] = None):
        """GET an absolute API path with caller-supplied (possibly incomplete) headers."""
        return self._request("GET", path, headers=headers)

    def raw_post(
        self,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        """POST an absolute API path with caller-supplied (possibly incomplete) headers."""
        return self._request("POST", path, payload or {}, headers)


api_client = ApiClient()
