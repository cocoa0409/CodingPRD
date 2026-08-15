"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def get_clock(self, headers):
        return self._request("GET", "/_clock", headers=headers)

    # ------------------------------------------------------------------
    # Programs
    # ------------------------------------------------------------------
    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/programs", headers=headers, params=params)

    def suspend_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/suspend", {}, headers)

    def resume_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/resume", {}, headers)

    def close_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/close", {}, headers)

    def sweep_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/sweep", {}, headers)

    # ------------------------------------------------------------------
    # Tariff schedules
    # ------------------------------------------------------------------
    def create_tariff_schedule(self, payload, headers):
        return self._request("POST", "/tariff-schedules", payload, headers)

    def get_tariff_schedule(self, tariff_schedule_id, headers):
        return self._request("GET", f"/tariff-schedules/{tariff_schedule_id}",
                             headers=headers)

    def list_tariff_schedules(self, headers, params=None):
        return self._request("GET", "/tariff-schedules", headers=headers,
                             params=params)

    # ------------------------------------------------------------------
    # Feeders
    # ------------------------------------------------------------------
    def create_feeder(self, payload, headers):
        return self._request("POST", "/feeders", payload, headers)

    def get_feeder(self, feeder_id, headers):
        return self._request("GET", f"/feeders/{feeder_id}", headers=headers)

    def list_feeders(self, headers, params=None):
        return self._request("GET", "/feeders", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Service transformers
    # ------------------------------------------------------------------
    def create_service_transformer(self, payload, headers):
        return self._request("POST", "/service-transformers", payload, headers)

    def get_service_transformer(self, service_transformer_id, headers):
        return self._request("GET",
                             f"/service-transformers/{service_transformer_id}",
                             headers=headers)

    def list_service_transformers(self, headers, params=None):
        return self._request("GET", "/service-transformers", headers=headers,
                             params=params)

    # ------------------------------------------------------------------
    # Customers
    # ------------------------------------------------------------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Service accounts
    # ------------------------------------------------------------------
    def create_service_account(self, payload, headers):
        return self._request("POST", "/service-accounts", payload, headers)

    def get_service_account(self, service_account_id, headers):
        return self._request("GET", f"/service-accounts/{service_account_id}",
                             headers=headers)

    def list_service_accounts(self, headers, params=None):
        return self._request("GET", "/service-accounts", headers=headers,
                             params=params)

    def suspend_service_account(self, service_account_id, headers):
        return self._request("POST",
                             f"/service-accounts/{service_account_id}/suspend",
                             {}, headers)

    def reactivate_service_account(self, service_account_id, headers):
        return self._request("POST",
                             f"/service-accounts/{service_account_id}/reactivate",
                             {}, headers)

    def close_service_account(self, service_account_id, headers):
        return self._request("POST",
                             f"/service-accounts/{service_account_id}/close",
                             {}, headers)

    # ------------------------------------------------------------------
    # Applications
    # ------------------------------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}",
                             headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers,
                             params=params)

    def submit_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/submit",
                             {}, headers)

    def amend_application(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/amend",
                             payload, headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/withdraw",
                             {}, headers)

    def completeness_decision(self, application_id, payload, headers):
        return self._request("POST",
                             f"/applications/{application_id}/completeness-decision",
                             payload, headers)

    def grant_pto(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/grant-pto",
                             {}, headers)

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------
    def create_document(self, payload, headers):
        return self._request("POST", "/documents", payload, headers)

    def get_document(self, document_id, headers):
        return self._request("GET", f"/documents/{document_id}", headers=headers)

    def list_documents(self, headers, params=None):
        return self._request("GET", "/documents", headers=headers, params=params)

    def review_document(self, document_id, payload, headers):
        return self._request("POST", f"/documents/{document_id}/review",
                             payload, headers)

    # ------------------------------------------------------------------
    # Screening reports
    # ------------------------------------------------------------------
    def create_screening_report(self, payload, headers):
        return self._request("POST", "/screening-reports", payload, headers)

    def get_screening_report(self, screening_report_id, headers):
        return self._request("GET", f"/screening-reports/{screening_report_id}",
                             headers=headers)

    def list_screening_reports(self, headers, params=None):
        return self._request("GET", "/screening-reports", headers=headers,
                             params=params)

    # ------------------------------------------------------------------
    # Supplemental reviews
    # ------------------------------------------------------------------
    def create_supplemental_review(self, payload, headers):
        return self._request("POST", "/supplemental-reviews", payload, headers)

    def get_supplemental_review(self, supplemental_review_id, headers):
        return self._request("GET",
                             f"/supplemental-reviews/{supplemental_review_id}",
                             headers=headers)

    def list_supplemental_reviews(self, headers, params=None):
        return self._request("GET", "/supplemental-reviews", headers=headers,
                             params=params)

    def complete_supplemental_review(self, supplemental_review_id, payload,
                                     headers):
        return self._request(
            "POST",
            f"/supplemental-reviews/{supplemental_review_id}/complete",
            payload, headers)

    # ------------------------------------------------------------------
    # Cost estimates
    # ------------------------------------------------------------------
    def create_cost_estimate(self, payload, headers):
        return self._request("POST", "/cost-estimates", payload, headers)

    def get_cost_estimate(self, cost_estimate_id, headers):
        return self._request("GET", f"/cost-estimates/{cost_estimate_id}",
                             headers=headers)

    def list_cost_estimates(self, headers, params=None):
        return self._request("GET", "/cost-estimates", headers=headers,
                             params=params)

    def accept_cost_estimate(self, cost_estimate_id, headers):
        return self._request("POST", f"/cost-estimates/{cost_estimate_id}/accept",
                             {}, headers)

    def decline_cost_estimate(self, cost_estimate_id, headers):
        return self._request("POST",
                             f"/cost-estimates/{cost_estimate_id}/decline",
                             {}, headers)

    def mark_work_complete(self, cost_estimate_id, headers):
        return self._request(
            "POST", f"/cost-estimates/{cost_estimate_id}/mark-work-complete",
            {}, headers)

    # ------------------------------------------------------------------
    # Meter exchanges
    # ------------------------------------------------------------------
    def create_meter_exchange(self, payload, headers):
        return self._request("POST", "/meter-exchanges", payload, headers)

    def get_meter_exchange(self, meter_exchange_id, headers):
        return self._request("GET", f"/meter-exchanges/{meter_exchange_id}",
                             headers=headers)

    def list_meter_exchanges(self, headers, params=None):
        return self._request("GET", "/meter-exchanges", headers=headers,
                             params=params)

    def complete_meter_exchange(self, meter_exchange_id, installed_meter_serial,
                                headers):
        return self._request(
            "POST", f"/meter-exchanges/{meter_exchange_id}/complete",
            {"installed_meter_serial": installed_meter_serial}, headers)

    def fail_meter_exchange(self, meter_exchange_id, fail_reason, headers):
        return self._request("POST",
                             f"/meter-exchanges/{meter_exchange_id}/fail",
                             {"fail_reason": fail_reason}, headers)

    def reschedule_meter_exchange(self, meter_exchange_id, window_start,
                                  window_end, headers):
        return self._request(
            "POST", f"/meter-exchanges/{meter_exchange_id}/reschedule",
            {"window_start": window_start, "window_end": window_end}, headers)

    def cancel_meter_exchange(self, meter_exchange_id, headers):
        return self._request("POST",
                             f"/meter-exchanges/{meter_exchange_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Inspections
    # ------------------------------------------------------------------
    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}",
                             headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers,
                             params=params)

    def record_inspection_result(self, inspection_id, payload, headers):
        return self._request("POST",
                             f"/inspections/{inspection_id}/record-result",
                             payload, headers)

    def cancel_inspection(self, inspection_id, headers):
        return self._request("POST", f"/inspections/{inspection_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Meter readings
    # ------------------------------------------------------------------
    def create_meter_reading(self, payload, headers):
        return self._request("POST", "/meter-readings", payload, headers)

    def get_meter_reading(self, meter_reading_id, headers):
        return self._request("GET", f"/meter-readings/{meter_reading_id}",
                             headers=headers)

    def list_meter_readings(self, headers, params=None):
        return self._request("GET", "/meter-readings", headers=headers,
                             params=params)

    def void_meter_reading(self, meter_reading_id, reason, headers):
        return self._request("POST",
                             f"/meter-readings/{meter_reading_id}/void",
                             {"reason": reason}, headers)

    # ------------------------------------------------------------------
    # Credit ledger
    # ------------------------------------------------------------------
    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/ledger-entries", headers=headers,
                             params=params)

    def get_ledger_entry(self, ledger_entry_id, headers):
        return self._request("GET", f"/ledger-entries/{ledger_entry_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Annual reconciliations
    # ------------------------------------------------------------------
    def create_annual_reconciliation(self, payload, headers):
        return self._request("POST", "/annual-reconciliations", payload, headers)

    def get_annual_reconciliation(self, annual_reconciliation_id, headers):
        return self._request("GET",
                             f"/annual-reconciliations/{annual_reconciliation_id}",
                             headers=headers)

    def list_annual_reconciliations(self, headers, params=None):
        return self._request("GET", "/annual-reconciliations", headers=headers,
                             params=params)

    def finalize_annual_reconciliation(self, annual_reconciliation_id, headers):
        return self._request(
            "POST",
            f"/annual-reconciliations/{annual_reconciliation_id}/finalize",
            {}, headers)

    def void_annual_reconciliation(self, annual_reconciliation_id, headers):
        return self._request(
            "POST", f"/annual-reconciliations/{annual_reconciliation_id}/void",
            {}, headers)


api_client = ApiClient()
