"""HTTP client with one method per endpoint the PRD declares.

Every path is served under the API root, so the paths below are complete as
written. Creation endpoints answer HTTP 201; every other successful call answers
HTTP 200, with the single exception of statement reissue, which creates a
successor statement and therefore answers HTTP 201.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

Headers = Optional[Dict[str, str]]
Payload = Optional[Dict[str, Any]]


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock — the one endpoint exempt from the header requirement
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers or {}
        )

    def set_clock_raw(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers or {})

    # ------------------------------------------------------------------
    # Employer
    # ------------------------------------------------------------------
    def create_employer(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/employers", payload, headers)

    def get_employer(self, employer_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/employers/{employer_id}", None, headers)

    def list_employers(self, params: Payload = None, headers: Headers = None) -> requests.Response:
        return self._request("GET", "/employers", params, headers)

    def patch_employer(
        self, employer_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("PATCH", f"/employers/{employer_id}", payload, headers)

    # ------------------------------------------------------------------
    # TaxAgency
    # ------------------------------------------------------------------
    def create_tax_agency(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/tax-agencies", payload, headers)

    def get_tax_agency(self, tax_agency_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/tax-agencies/{tax_agency_id}", None, headers)

    def list_tax_agencies(
        self, params: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", "/tax-agencies", params, headers)

    # ------------------------------------------------------------------
    # AgencyAccount
    # ------------------------------------------------------------------
    def create_agency_account(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/agency-accounts", payload, headers)

    def get_agency_account(
        self, agency_account_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/agency-accounts/{agency_account_id}", None, headers)

    def list_agency_accounts(
        self, params: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", "/agency-accounts", params, headers)

    def activate_agency_account(
        self, agency_account_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/agency-accounts/{agency_account_id}/activate", payload or {}, headers
        )

    def close_agency_account(
        self, agency_account_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/agency-accounts/{agency_account_id}/close", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Employee
    # ------------------------------------------------------------------
    def create_employee(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/employees", payload, headers)

    def get_employee(self, employee_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/employees/{employee_id}", None, headers)

    def list_employees(self, params: Payload = None, headers: Headers = None) -> requests.Response:
        return self._request("GET", "/employees", params, headers)

    # ------------------------------------------------------------------
    # PayrollRegisterLine
    # ------------------------------------------------------------------
    def create_register_line(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/payroll-register-lines", payload, headers)

    def get_register_line(
        self, register_line_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/payroll-register-lines/{register_line_id}", None, headers
        )

    def list_register_lines(
        self, params: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", "/payroll-register-lines", params, headers)

    # ------------------------------------------------------------------
    # DepositRecord
    # ------------------------------------------------------------------
    def create_deposit_record(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/deposit-records", payload, headers)

    def get_deposit_record(
        self, deposit_record_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/deposit-records/{deposit_record_id}", None, headers)

    def list_deposit_records(
        self, params: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", "/deposit-records", params, headers)

    # ------------------------------------------------------------------
    # FiledReturn
    # ------------------------------------------------------------------
    def create_filed_return(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/filed-returns", payload, headers)

    def get_filed_return(self, filed_return_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/filed-returns/{filed_return_id}", None, headers)

    def list_filed_returns(
        self, params: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", "/filed-returns", params, headers)

    # ------------------------------------------------------------------
    # CorrectionCase
    # ------------------------------------------------------------------
    def create_correction_case(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/correction-cases", payload, headers)

    def get_correction_case(
        self, correction_case_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/correction-cases/{correction_case_id}", None, headers)

    def list_correction_cases(
        self, params: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", "/correction-cases", params, headers)

    def reconcile_case(
        self, correction_case_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/correction-cases/{correction_case_id}/reconcile", payload or {}, headers
        )

    def close_case(
        self, correction_case_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/correction-cases/{correction_case_id}/close", payload or {}, headers
        )

    def get_exposure_summary(
        self, correction_case_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/correction-cases/{correction_case_id}/exposure-summary", None, headers
        )

    # ------------------------------------------------------------------
    # Discrepancy
    # ------------------------------------------------------------------
    def get_discrepancy(self, discrepancy_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/discrepancies/{discrepancy_id}", None, headers)

    def list_discrepancies(
        self, params: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", "/discrepancies", params, headers)

    def categorize_discrepancy(
        self, discrepancy_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/discrepancies/{discrepancy_id}/categorize", payload, headers
        )

    def dismiss_discrepancy(
        self, discrepancy_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"/discrepancies/{discrepancy_id}/dismiss", payload, headers)

    # ------------------------------------------------------------------
    # AmendedReturn
    # ------------------------------------------------------------------
    def create_amended_return(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/amended-returns", payload, headers)

    def get_amended_return(
        self, amended_return_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/amended-returns/{amended_return_id}", None, headers)

    def list_amended_returns(
        self, params: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", "/amended-returns", params, headers)

    def prepare_amended_return(
        self, amended_return_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/amended-returns/{amended_return_id}/prepare", payload or {}, headers
        )

    def sign_amended_return(
        self, amended_return_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/amended-returns/{amended_return_id}/sign", payload or {}, headers
        )

    def submit_amended_return(
        self, amended_return_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/amended-returns/{amended_return_id}/submit", payload or {}, headers
        )

    def record_agency_outcome(
        self, amended_return_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/amended-returns/{amended_return_id}/agency-outcome", payload, headers
        )

    def void_amended_return(
        self, amended_return_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/amended-returns/{amended_return_id}/void", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # CorrectedWageStatement
    # ------------------------------------------------------------------
    def create_statement(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/corrected-wage-statements", payload, headers)

    def get_statement(self, statement_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/corrected-wage-statements/{statement_id}", None, headers)

    def list_statements(self, params: Payload = None, headers: Headers = None) -> requests.Response:
        return self._request("GET", "/corrected-wage-statements", params, headers)

    def issue_statement(
        self, statement_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/corrected-wage-statements/{statement_id}/issue", payload or {}, headers
        )

    def acknowledge_statement(
        self, statement_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/corrected-wage-statements/{statement_id}/acknowledge", payload or {}, headers
        )

    def report_statement_undeliverable(
        self, statement_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/corrected-wage-statements/{statement_id}/report-undeliverable",
            payload,
            headers,
        )

    def reissue_statement(
        self, statement_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/corrected-wage-statements/{statement_id}/reissue", payload, headers
        )

    # ------------------------------------------------------------------
    # WageRepayment
    # ------------------------------------------------------------------
    def create_wage_repayment(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/wage-repayments", payload, headers)

    def get_wage_repayment(
        self, wage_repayment_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/wage-repayments/{wage_repayment_id}", None, headers)

    def list_wage_repayments(
        self, params: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", "/wage-repayments", params, headers)

    def agree_wage_repayment(
        self, wage_repayment_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/wage-repayments/{wage_repayment_id}/agree", payload or {}, headers
        )

    def renegotiate_wage_repayment(
        self, wage_repayment_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/wage-repayments/{wage_repayment_id}/renegotiate", payload, headers
        )

    def collect_wage_repayment(
        self, wage_repayment_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/wage-repayments/{wage_repayment_id}/collect", payload, headers
        )

    def write_off_wage_repayment(
        self, wage_repayment_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/wage-repayments/{wage_repayment_id}/write-off", payload, headers
        )

    # ------------------------------------------------------------------
    # AgencyNotice
    # ------------------------------------------------------------------
    def create_agency_notice(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/agency-notices", payload, headers)

    def get_agency_notice(
        self, agency_notice_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/agency-notices/{agency_notice_id}", None, headers)

    def list_agency_notices(
        self, params: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", "/agency-notices", params, headers)

    def draft_notice_response(
        self, agency_notice_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/agency-notices/{agency_notice_id}/draft-response", payload, headers
        )

    def respond_to_notice(
        self, agency_notice_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/agency-notices/{agency_notice_id}/respond", payload or {}, headers
        )

    def request_notice_info(
        self, agency_notice_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/agency-notices/{agency_notice_id}/request-info", payload or {}, headers
        )

    def record_notice_outcome(
        self, agency_notice_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/agency-notices/{agency_notice_id}/record-outcome", payload, headers
        )

    # ------------------------------------------------------------------
    # ControlRemediation
    # ------------------------------------------------------------------
    def create_control_remediation(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/control-remediations", payload, headers)

    def get_control_remediation(
        self, control_remediation_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/control-remediations/{control_remediation_id}", None, headers
        )

    def list_control_remediations(
        self, params: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", "/control-remediations", params, headers)

    def assign_control_remediation(
        self, control_remediation_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/control-remediations/{control_remediation_id}/assign", payload, headers
        )

    def submit_remediation_verification(
        self, control_remediation_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/control-remediations/{control_remediation_id}/submit-verification",
            payload,
            headers,
        )

    def verify_control_remediation(
        self, control_remediation_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/control-remediations/{control_remediation_id}/verify", payload, headers
        )

    # ------------------------------------------------------------------
    # Generic path read, used by the per-entity not-found sweep
    # ------------------------------------------------------------------
    def get_by_collection(
        self, collection: str, resource_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/{collection}/{resource_id}", None, headers)
