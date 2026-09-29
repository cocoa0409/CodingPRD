"""Typed HTTP client: one method per declared endpoint of the cooperative purchasing API."""

from prd_bench_local_runner.testing import GenericApiClient

CLOCK_PATH = "/_clock/set_current_utc"
PREFIX = "/coop"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", CLOCK_PATH, payload, headers)

    # ------------------------------------------------------------------
    # State law configuration
    # ------------------------------------------------------------------
    def create_state_law_rule(self, payload, headers):
        return self._request("POST", f"{PREFIX}/state-law-rules", payload, headers)

    def list_state_law_rules(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/state-law-rules", headers=headers, params=params)

    def get_state_law_rule(self, rule_id, headers):
        return self._request("GET", f"{PREFIX}/state-law-rules/{rule_id}", headers=headers)

    # ------------------------------------------------------------------
    # Solicitations
    # ------------------------------------------------------------------
    def create_solicitation(self, payload, headers):
        return self._request("POST", f"{PREFIX}/solicitations", payload, headers)

    def list_solicitations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/solicitations", headers=headers, params=params)

    def get_solicitation(self, solicitation_id, headers):
        return self._request("GET", f"{PREFIX}/solicitations/{solicitation_id}", headers=headers)

    def solicitation_lifecycle(self, solicitation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/solicitations/{solicitation_id}/lifecycle", payload, headers
        )

    def solicitation_audit_package(self, solicitation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/solicitations/{solicitation_id}/audit-package", payload, headers
        )

    def list_responses_of_solicitation(self, solicitation_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/solicitations/{solicitation_id}/responses",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Suppliers
    # ------------------------------------------------------------------
    def create_supplier(self, payload, headers):
        return self._request("POST", f"{PREFIX}/suppliers", payload, headers)

    def list_suppliers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/suppliers", headers=headers, params=params)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"{PREFIX}/suppliers/{supplier_id}", headers=headers)

    def supplier_qualification(self, supplier_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/suppliers/{supplier_id}/qualification", payload, headers
        )

    # ------------------------------------------------------------------
    # Solicitation responses
    # ------------------------------------------------------------------
    def create_solicitation_response(self, payload, headers):
        return self._request("POST", f"{PREFIX}/solicitation-responses", payload, headers)

    def list_solicitation_responses(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/solicitation-responses", headers=headers, params=params
        )

    def get_solicitation_response(self, response_id, headers):
        return self._request(
            "GET", f"{PREFIX}/solicitation-responses/{response_id}", headers=headers
        )

    def response_review(self, response_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/solicitation-responses/{response_id}/review", payload, headers
        )

    def response_submission(self, response_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/solicitation-responses/{response_id}/submission", payload, headers
        )

    # ------------------------------------------------------------------
    # Master contracts and price-sheet lines
    # ------------------------------------------------------------------
    def create_master_contract(self, payload, headers):
        return self._request("POST", f"{PREFIX}/master-contracts", payload, headers)

    def list_master_contracts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/master-contracts", headers=headers, params=params)

    def get_master_contract(self, contract_id, headers):
        return self._request("GET", f"{PREFIX}/master-contracts/{contract_id}", headers=headers)

    def contract_award_status(self, contract_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/master-contracts/{contract_id}/award-status", payload, headers
        )

    def contract_compliance_sweep(self, contract_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/master-contracts/{contract_id}/compliance-sweep", payload, headers
        )

    def create_line_item(self, contract_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/master-contracts/{contract_id}/line-items", payload, headers
        )

    def list_line_items_of_contract(self, contract_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/master-contracts/{contract_id}/line-items",
            headers=headers,
            params=params,
        )

    def list_usage_reports_of_contract(self, contract_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/master-contracts/{contract_id}/usage-reports",
            headers=headers,
            params=params,
        )

    def get_price_quote(self, contract_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/master-contracts/{contract_id}/price-quote",
            headers=headers,
            params=params,
        )

    def list_contract_line_items(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/contract-line-items", headers=headers, params=params
        )

    def get_contract_line_item(self, line_item_id, headers):
        return self._request(
            "GET", f"{PREFIX}/contract-line-items/{line_item_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Member agencies
    # ------------------------------------------------------------------
    def create_member_agency(self, payload, headers):
        return self._request("POST", f"{PREFIX}/member-agencies", payload, headers)

    def list_member_agencies(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/member-agencies", headers=headers, params=params)

    def get_member_agency(self, member_id, headers):
        return self._request("GET", f"{PREFIX}/member-agencies/{member_id}", headers=headers)

    def member_registration(self, member_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/member-agencies/{member_id}/registration", payload, headers
        )

    def list_analyses_of_member(self, member_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/member-agencies/{member_id}/piggyback-analyses",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Piggyback authority analyses
    # ------------------------------------------------------------------
    def create_piggyback_analysis(self, payload, headers):
        return self._request("POST", f"{PREFIX}/piggyback-analyses", payload, headers)

    def list_piggyback_analyses(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/piggyback-analyses", headers=headers, params=params)

    def get_piggyback_analysis(self, analysis_id, headers):
        return self._request("GET", f"{PREFIX}/piggyback-analyses/{analysis_id}", headers=headers)

    def analysis_determination(self, analysis_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/piggyback-analyses/{analysis_id}/determination", payload, headers
        )

    # ------------------------------------------------------------------
    # Contract usage
    # ------------------------------------------------------------------
    def create_contract_usage(self, payload, headers):
        return self._request("POST", f"{PREFIX}/contract-usages", payload, headers)

    def list_contract_usages(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/contract-usages", headers=headers, params=params)

    def get_contract_usage(self, usage_id, headers):
        return self._request("GET", f"{PREFIX}/contract-usages/{usage_id}", headers=headers)

    def usage_disposition(self, usage_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/contract-usages/{usage_id}/disposition", payload, headers
        )

    # ------------------------------------------------------------------
    # Usage reports and fee remittance
    # ------------------------------------------------------------------
    def create_usage_report(self, payload, headers):
        return self._request("POST", f"{PREFIX}/usage-reports", payload, headers)

    def list_usage_reports(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/usage-reports", headers=headers, params=params)

    def get_usage_report(self, report_id, headers):
        return self._request("GET", f"{PREFIX}/usage-reports/{report_id}", headers=headers)

    def report_submission(self, report_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/usage-reports/{report_id}/submission", payload, headers
        )

    def report_review(self, report_id, payload, headers):
        return self._request("POST", f"{PREFIX}/usage-reports/{report_id}/review", payload, headers)

    def report_fee_remittance(self, report_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/usage-reports/{report_id}/fee-remittance", payload, headers
        )

    # ------------------------------------------------------------------
    # Contract amendments
    # ------------------------------------------------------------------
    def create_contract_amendment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/contract-amendments", payload, headers)

    def list_contract_amendments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/contract-amendments", headers=headers, params=params
        )

    def get_contract_amendment(self, amendment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/contract-amendments/{amendment_id}", headers=headers
        )

    def amendment_decision(self, amendment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/contract-amendments/{amendment_id}/decision", payload, headers
        )

    def amendment_withdrawal(self, amendment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/contract-amendments/{amendment_id}/withdrawal", payload, headers
        )

    # ------------------------------------------------------------------
    # Member complaints
    # ------------------------------------------------------------------
    def create_complaint(self, payload, headers):
        return self._request("POST", f"{PREFIX}/complaints", payload, headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/complaints", headers=headers, params=params)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"{PREFIX}/complaints/{complaint_id}", headers=headers)

    def complaint_investigation(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/complaints/{complaint_id}/investigation", payload, headers
        )

    def complaint_decision(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/complaints/{complaint_id}/decision", payload, headers
        )

    def complaint_appeal(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/complaints/{complaint_id}/appeal", payload, headers
        )

    def complaint_appeal_decision(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/complaints/{complaint_id}/appeal-decision", payload, headers
        )


api_client = ApiClient()
