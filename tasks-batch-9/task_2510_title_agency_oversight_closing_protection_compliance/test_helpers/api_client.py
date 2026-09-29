"""API client: one method per endpoint in the PRD's endpoint table (§4).

"All routes sit at the root of the API with no version or namespace prefix", so
`API_PREFIX` is the empty string.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

API_PREFIX = ""


class ApiClient(GenericApiClient):
    """Endpoint methods for the Title Agency Oversight API."""

    # ------------------------------------------------------------------
    # Logical clock (PRD §2.4)
    # ------------------------------------------------------------------

    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{API_PREFIX}/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers,
        )

    # ------------------------------------------------------------------
    # Agencies (PRD §3.1)
    # ------------------------------------------------------------------

    def create_agency(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/agencies", payload, headers)

    def get_agency(self, agency_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/agencies/{agency_id}", headers=headers
        )

    def list_agencies(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/agencies", headers=headers, params=params
        )

    def submit_financial_review(
        self, agency_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/agencies/{agency_id}/financial-review",
            payload,
            headers,
        )

    def decide_financial_review(
        self, agency_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/agencies/{agency_id}/financial-review-decision",
            payload,
            headers,
        )

    def decide_appointment(
        self, agency_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/agencies/{agency_id}/appointment-decision",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # State programs (PRD §3.2)
    # ------------------------------------------------------------------

    def create_state_program(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/state-programs", payload, headers)

    def get_state_program(self, state_program_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/state-programs/{state_program_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Agency appointments (PRD §3.2)
    # ------------------------------------------------------------------

    def create_appointment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/agency-appointments", payload, headers
        )

    def get_appointment(self, appointment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/agency-appointments/{appointment_id}", headers=headers
        )

    def list_appointments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/agency-appointments", headers=headers, params=params
        )

    def verify_license(
        self, appointment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/agency-appointments/{appointment_id}/license-verification",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Closing protection letters (PRD §3.3)
    # ------------------------------------------------------------------

    def request_letter(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/closing-protection-letters", payload, headers
        )

    def get_letter(self, cpl_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/closing-protection-letters/{cpl_id}", headers=headers
        )

    def list_letters(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET",
            f"{API_PREFIX}/closing-protection-letters",
            headers=headers,
            params=params,
        )

    def transition_letter(
        self, cpl_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/closing-protection-letters/{cpl_id}/state",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Policy files (PRD §3.4)
    # ------------------------------------------------------------------

    def create_policy_file(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/policy-files", payload, headers)

    def get_policy_file(self, policy_file_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/policy-files/{policy_file_id}", headers=headers
        )

    def list_policy_files(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/policy-files", headers=headers, params=params
        )

    def transition_issuance(
        self, policy_file_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/policy-files/{policy_file_id}/issuance-state",
            payload,
            headers,
        )

    def transition_transfer(
        self, policy_file_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/policy-files/{policy_file_id}/transfer-state",
            payload,
            headers,
        )

    def list_policy_remittance_lines(
        self,
        policy_file_id: str,
        headers: Dict[str, str],
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/policy-files/{policy_file_id}/remittance-lines",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Remittance statements and lines (PRD §3.5)
    # ------------------------------------------------------------------

    def create_statement(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/remittance-statements", payload, headers
        )

    def get_statement(self, statement_id: str, headers: Dict[str, str]):
        return self._request(
            "GET",
            f"{API_PREFIX}/remittance-statements/{statement_id}",
            headers=headers,
        )

    def list_statements(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET",
            f"{API_PREFIX}/remittance-statements",
            headers=headers,
            params=params,
        )

    def create_line(
        self, statement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/remittance-statements/{statement_id}/lines",
            payload,
            headers,
        )

    def list_lines(
        self, statement_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/remittance-statements/{statement_id}/lines",
            headers=headers,
            params=params,
        )

    def transition_statement(
        self, statement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/remittance-statements/{statement_id}/state",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Escrow accounts (PRD §3.6)
    # ------------------------------------------------------------------

    def create_escrow_account(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/escrow-accounts", payload, headers)

    def get_escrow_account(self, account_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/escrow-accounts/{account_id}", headers=headers
        )

    def list_escrow_accounts(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/escrow-accounts", headers=headers, params=params
        )

    def post_balance_snapshot(
        self, account_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/escrow-accounts/{account_id}/balance-snapshot",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Escrow audits and findings (PRD §3.6, §3.7)
    # ------------------------------------------------------------------

    def create_escrow_audit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/escrow-audits", payload, headers)

    def get_escrow_audit(self, audit_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/escrow-audits/{audit_id}", headers=headers
        )

    def list_escrow_audits(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/escrow-audits", headers=headers, params=params
        )

    def create_finding(
        self, audit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/escrow-audits/{audit_id}/findings",
            payload,
            headers,
        )

    def list_findings(
        self, audit_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/escrow-audits/{audit_id}/findings",
            headers=headers,
            params=params,
        )

    def transition_audit(
        self, audit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/escrow-audits/{audit_id}/state", payload, headers
        )

    def get_finding(self, finding_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/audit-findings/{finding_id}", headers=headers
        )

    def transition_finding(
        self, finding_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/audit-findings/{finding_id}/state", payload, headers
        )

    # ------------------------------------------------------------------
    # Agency claims (PRD §3.8)
    # ------------------------------------------------------------------

    def create_claim(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/agency-claims", payload, headers)

    def get_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/agency-claims/{claim_id}", headers=headers
        )

    def list_claims(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/agency-claims", headers=headers, params=params
        )

    def transition_claim(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/agency-claims/{claim_id}/state", payload, headers
        )


api_client = ApiClient()
