"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Clock ─────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def get_clock(self, headers):
        return self._request("GET", "/_clock/current_utc", headers=headers)

    # ─── Bank ──────────────────────────────────────────
    def create_bank(self, payload, headers):
        return self._request("POST", "/banks", payload, headers)

    def get_bank(self, bank_id, headers):
        return self._request("GET", f"/banks/{bank_id}", headers=headers)

    def list_banks(self, headers, params=None):
        return self._request("GET", "/banks", headers=headers, params=params)

    # ─── ReportingPeriod ───────────────────────────────
    def create_reporting_period(self, bank_id, payload, headers):
        return self._request("POST", f"/banks/{bank_id}/reporting-periods", payload, headers)

    def get_reporting_period(self, bank_id, period_id, headers):
        return self._request("GET", f"/banks/{bank_id}/reporting-periods/{period_id}", headers=headers)

    def list_reporting_periods(self, bank_id, headers, params=None):
        return self._request("GET", f"/banks/{bank_id}/reporting-periods", headers=headers, params=params)

    def close_reporting_period(self, bank_id, period_id, headers):
        return self._request("POST", f"/banks/{bank_id}/reporting-periods/{period_id}/close", headers=headers)

    # ─── CapitalInstrument ─────────────────────────────
    def create_capital_instrument(self, bank_id, payload, headers):
        return self._request("POST", f"/banks/{bank_id}/capital-instruments", payload, headers)

    def get_capital_instrument(self, bank_id, instrument_id, headers):
        return self._request("GET", f"/banks/{bank_id}/capital-instruments/{instrument_id}", headers=headers)

    def list_capital_instruments(self, bank_id, headers, params=None):
        return self._request("GET", f"/banks/{bank_id}/capital-instruments", headers=headers, params=params)

    def call_capital_instrument(self, bank_id, instrument_id, headers):
        return self._request("POST", f"/banks/{bank_id}/capital-instruments/{instrument_id}/call", headers=headers)

    def redeem_capital_instrument(self, bank_id, instrument_id, headers):
        return self._request("POST", f"/banks/{bank_id}/capital-instruments/{instrument_id}/redeem", headers=headers)

    # ─── RiskExposure ──────────────────────────────────
    def create_risk_exposure(self, bank_id, period_id, payload, headers):
        return self._request(
            "POST", f"/banks/{bank_id}/reporting-periods/{period_id}/risk-exposures", payload, headers
        )

    def get_risk_exposure(self, bank_id, period_id, exposure_id, headers):
        return self._request(
            "GET", f"/banks/{bank_id}/reporting-periods/{period_id}/risk-exposures/{exposure_id}", headers=headers
        )

    def list_risk_exposures(self, bank_id, period_id, headers, params=None):
        return self._request(
            "GET", f"/banks/{bank_id}/reporting-periods/{period_id}/risk-exposures", headers=headers, params=params
        )

    def list_bank_risk_exposures(self, bank_id, headers, params=None):
        return self._request("GET", f"/banks/{bank_id}/risk-exposures", headers=headers, params=params)

    # ─── CallReport ────────────────────────────────────
    def create_call_report(self, bank_id, period_id, payload, headers):
        return self._request(
            "POST", f"/banks/{bank_id}/reporting-periods/{period_id}/call-reports", payload, headers
        )

    def get_call_report(self, bank_id, period_id, report_id, headers):
        return self._request(
            "GET", f"/banks/{bank_id}/reporting-periods/{period_id}/call-reports/{report_id}", headers=headers
        )

    def list_call_reports(self, bank_id, period_id, headers, params=None):
        return self._request(
            "GET", f"/banks/{bank_id}/reporting-periods/{period_id}/call-reports", headers=headers, params=params
        )

    def list_bank_call_reports(self, bank_id, headers, params=None):
        return self._request("GET", f"/banks/{bank_id}/call-reports", headers=headers, params=params)

    def prepare_call_report(self, bank_id, period_id, report_id, headers):
        return self._request(
            "POST", f"/banks/{bank_id}/reporting-periods/{period_id}/call-reports/{report_id}/prepare", headers=headers
        )

    def submit_call_report(self, bank_id, period_id, report_id, headers):
        return self._request(
            "POST", f"/banks/{bank_id}/reporting-periods/{period_id}/call-reports/{report_id}/submit", headers=headers
        )

    def accept_call_report(self, bank_id, period_id, report_id, headers):
        return self._request(
            "POST", f"/banks/{bank_id}/reporting-periods/{period_id}/call-reports/{report_id}/accept", headers=headers
        )

    def open_amendment(self, bank_id, period_id, report_id, headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/reporting-periods/{period_id}/call-reports/{report_id}/open_amendment",
            headers=headers,
        )

    # ─── EditException ─────────────────────────────────
    def list_edit_exceptions(self, bank_id, period_id, report_id, headers, params=None):
        return self._request(
            "GET",
            f"/banks/{bank_id}/reporting-periods/{period_id}/call-reports/{report_id}/edit-exceptions",
            headers=headers,
            params=params,
        )

    def get_edit_exception(self, bank_id, period_id, report_id, edit_id, headers):
        return self._request(
            "GET",
            f"/banks/{bank_id}/reporting-periods/{period_id}/call-reports/{report_id}/edit-exceptions/{edit_id}",
            headers=headers,
        )

    def resolve_edit_exception(self, bank_id, period_id, report_id, edit_id, payload, headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/reporting-periods/{period_id}/call-reports/{report_id}/edit-exceptions/{edit_id}/resolve",
            payload,
            headers,
        )

    def explain_edit_exception(self, bank_id, period_id, report_id, edit_id, payload, headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/reporting-periods/{period_id}/call-reports/{report_id}/edit-exceptions/{edit_id}/explain",
            payload,
            headers,
        )

    # ─── StressScenario ────────────────────────────────
    def create_stress_scenario(self, bank_id, payload, headers):
        return self._request("POST", f"/banks/{bank_id}/stress-scenarios", payload, headers)

    def get_stress_scenario(self, bank_id, scenario_id, headers):
        return self._request("GET", f"/banks/{bank_id}/stress-scenarios/{scenario_id}", headers=headers)

    def list_stress_scenarios(self, bank_id, headers, params=None):
        return self._request("GET", f"/banks/{bank_id}/stress-scenarios", headers=headers, params=params)

    def activate_stress_scenario(self, bank_id, scenario_id, headers):
        return self._request("POST", f"/banks/{bank_id}/stress-scenarios/{scenario_id}/activate", headers=headers)

    def retire_stress_scenario(self, bank_id, scenario_id, headers):
        return self._request("POST", f"/banks/{bank_id}/stress-scenarios/{scenario_id}/retire", headers=headers)

    # ─── CapitalPlan ───────────────────────────────────
    def create_capital_plan(self, bank_id, payload, headers):
        return self._request("POST", f"/banks/{bank_id}/capital-plans", payload, headers)

    def get_capital_plan(self, bank_id, plan_id, headers):
        return self._request("GET", f"/banks/{bank_id}/capital-plans/{plan_id}", headers=headers)

    def list_capital_plans(self, bank_id, headers, params=None):
        return self._request("GET", f"/banks/{bank_id}/capital-plans", headers=headers, params=params)

    def submit_plan_board(self, bank_id, plan_id, headers):
        return self._request("POST", f"/banks/{bank_id}/capital-plans/{plan_id}/submit_board", headers=headers)

    def board_approve_plan(self, bank_id, plan_id, headers):
        return self._request("POST", f"/banks/{bank_id}/capital-plans/{plan_id}/board_approve", headers=headers)

    def submit_plan_regulator(self, bank_id, plan_id, payload, headers):
        return self._request("POST", f"/banks/{bank_id}/capital-plans/{plan_id}/submit_regulator", payload, headers)

    def regulator_approve_plan(self, bank_id, plan_id, headers):
        return self._request("POST", f"/banks/{bank_id}/capital-plans/{plan_id}/regulator_approve", headers=headers)

    def regulator_object_plan(self, bank_id, plan_id, headers):
        return self._request("POST", f"/banks/{bank_id}/capital-plans/{plan_id}/regulator_object", headers=headers)

    def amend_plan(self, bank_id, plan_id, headers):
        return self._request("POST", f"/banks/{bank_id}/capital-plans/{plan_id}/amend", headers=headers)

    # ─── CapitalDistributionRequest ────────────────────
    def create_distribution_request(self, bank_id, payload, headers):
        return self._request("POST", f"/banks/{bank_id}/distribution-requests", payload, headers)

    def get_distribution_request(self, bank_id, request_id, headers):
        return self._request("GET", f"/banks/{bank_id}/distribution-requests/{request_id}", headers=headers)

    def list_distribution_requests(self, bank_id, headers, params=None):
        return self._request("GET", f"/banks/{bank_id}/distribution-requests", headers=headers, params=params)

    def approve_distribution(self, bank_id, request_id, payload, headers):
        return self._request(
            "POST", f"/banks/{bank_id}/distribution-requests/{request_id}/approve", payload, headers
        )

    def execute_distribution(self, bank_id, request_id, headers):
        return self._request("POST", f"/banks/{bank_id}/distribution-requests/{request_id}/execute", headers=headers)

    def reject_distribution(self, bank_id, request_id, headers):
        return self._request("POST", f"/banks/{bank_id}/distribution-requests/{request_id}/reject", headers=headers)

    def withdraw_distribution(self, bank_id, request_id, headers):
        return self._request("POST", f"/banks/{bank_id}/distribution-requests/{request_id}/withdraw", headers=headers)

    # ─── SubordinatedDebtIssuance ──────────────────────
    def create_sub_debt_issuance(self, bank_id, payload, headers):
        return self._request("POST", f"/banks/{bank_id}/sub-debt-issuances", payload, headers)

    def get_sub_debt_issuance(self, bank_id, issuance_id, headers):
        return self._request("GET", f"/banks/{bank_id}/sub-debt-issuances/{issuance_id}", headers=headers)

    def list_sub_debt_issuances(self, bank_id, headers, params=None):
        return self._request("GET", f"/banks/{bank_id}/sub-debt-issuances", headers=headers, params=params)

    def approve_sub_debt(self, bank_id, issuance_id, payload, headers):
        return self._request("POST", f"/banks/{bank_id}/sub-debt-issuances/{issuance_id}/approve", payload, headers)

    def price_sub_debt(self, bank_id, issuance_id, headers):
        return self._request("POST", f"/banks/{bank_id}/sub-debt-issuances/{issuance_id}/price", headers=headers)

    def settle_sub_debt(self, bank_id, issuance_id, headers):
        return self._request("POST", f"/banks/{bank_id}/sub-debt-issuances/{issuance_id}/settle", headers=headers)

    def withdraw_sub_debt(self, bank_id, issuance_id, headers):
        return self._request("POST", f"/banks/{bank_id}/sub-debt-issuances/{issuance_id}/withdraw", headers=headers)

    # ─── PCAThresholdEvent ─────────────────────────────
    def list_pca_threshold_events(self, bank_id, headers, params=None):
        return self._request("GET", f"/banks/{bank_id}/pca-threshold-events", headers=headers, params=params)

    def get_pca_threshold_event(self, bank_id, event_id, headers):
        return self._request("GET", f"/banks/{bank_id}/pca-threshold-events/{event_id}", headers=headers)

    # ─── ICAAPDocument ─────────────────────────────────
    def create_icaap_document(self, bank_id, payload, headers):
        return self._request("POST", f"/banks/{bank_id}/icaap-documents", payload, headers)

    def get_icaap_document(self, bank_id, doc_id, headers):
        return self._request("GET", f"/banks/{bank_id}/icaap-documents/{doc_id}", headers=headers)

    def list_icaap_documents(self, bank_id, headers, params=None):
        return self._request("GET", f"/banks/{bank_id}/icaap-documents", headers=headers, params=params)

    def submit_icaap_review(self, bank_id, doc_id, headers):
        return self._request("POST", f"/banks/{bank_id}/icaap-documents/{doc_id}/submit_review", headers=headers)

    def attest_icaap(self, bank_id, doc_id, headers):
        return self._request("POST", f"/banks/{bank_id}/icaap-documents/{doc_id}/attest", headers=headers)

    def file_icaap(self, bank_id, doc_id, payload, headers):
        return self._request("POST", f"/banks/{bank_id}/icaap-documents/{doc_id}/file", payload, headers)

    # ─── Flat top-level reads ──────────────────────────
    def get_reporting_period_flat(self, period_id, headers):
        return self._request("GET", f"/reporting-periods/{period_id}", headers=headers)

    def list_reporting_periods_flat(self, headers, params=None):
        return self._request("GET", "/reporting-periods", headers=headers, params=params)

    def get_capital_instrument_flat(self, instrument_id, headers):
        return self._request("GET", f"/capital-instruments/{instrument_id}", headers=headers)

    def list_capital_instruments_flat(self, headers, params=None):
        return self._request("GET", "/capital-instruments", headers=headers, params=params)

    def get_risk_exposure_flat(self, exposure_id, headers):
        return self._request("GET", f"/risk-exposures/{exposure_id}", headers=headers)

    def list_risk_exposures_flat(self, headers, params=None):
        return self._request("GET", "/risk-exposures", headers=headers, params=params)

    def get_capital_plan_flat(self, plan_id, headers):
        return self._request("GET", f"/capital-plans/{plan_id}", headers=headers)

    def list_capital_plans_flat(self, headers, params=None):
        return self._request("GET", "/capital-plans", headers=headers, params=params)

    def get_stress_scenario_flat(self, scenario_id, headers):
        return self._request("GET", f"/stress-scenarios/{scenario_id}", headers=headers)

    def list_stress_scenarios_flat(self, headers, params=None):
        return self._request("GET", "/stress-scenarios", headers=headers, params=params)

    def get_call_report_flat(self, report_id, headers):
        return self._request("GET", f"/call-reports/{report_id}", headers=headers)

    def list_call_reports_flat(self, headers, params=None):
        return self._request("GET", "/call-reports", headers=headers, params=params)

    def get_edit_exception_flat(self, edit_id, headers):
        return self._request("GET", f"/edit-exceptions/{edit_id}", headers=headers)

    def list_edit_exceptions_flat(self, headers, params=None):
        return self._request("GET", "/edit-exceptions", headers=headers, params=params)

    def get_distribution_request_flat(self, request_id, headers):
        return self._request("GET", f"/distribution-requests/{request_id}", headers=headers)

    def list_distribution_requests_flat(self, headers, params=None):
        return self._request("GET", "/distribution-requests", headers=headers, params=params)

    def get_sub_debt_issuance_flat(self, issuance_id, headers):
        return self._request("GET", f"/sub-debt-issuances/{issuance_id}", headers=headers)

    def list_sub_debt_issuances_flat(self, headers, params=None):
        return self._request("GET", "/sub-debt-issuances", headers=headers, params=params)

    def get_pca_threshold_event_flat(self, event_id, headers):
        return self._request("GET", f"/pca-threshold-events/{event_id}", headers=headers)

    def list_pca_threshold_events_flat(self, headers, params=None):
        return self._request("GET", "/pca-threshold-events", headers=headers, params=params)

    def get_icaap_document_flat(self, doc_id, headers):
        return self._request("GET", f"/icaap-documents/{doc_id}", headers=headers)

    def list_icaap_documents_flat(self, headers, params=None):
        return self._request("GET", "/icaap-documents", headers=headers, params=params)


api_client = ApiClient()
