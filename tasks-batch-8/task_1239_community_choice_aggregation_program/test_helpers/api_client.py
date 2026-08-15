"""API client: one method per endpoint defined in the PRD (§4 Endpoint Definitions)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- bootstrap & clock ---
    def create_authority(self, payload, headers):
        return self._request("POST", "/cca/authority", payload, headers)

    def get_authority(self, headers):
        return self._request("GET", "/cca/authority", headers=headers)

    def patch_authority(self, payload, headers):
        return self._request("PATCH", "/cca/authority", payload, headers)

    def activate_authority(self, payload, headers):
        return self._request("POST", "/cca/authority/activate", payload, headers)

    def suspend_authority(self, payload, headers):
        return self._request("POST", "/cca/authority/suspend", payload, headers)

    def reinstate_authority(self, payload, headers):
        return self._request("POST", "/cca/authority/reinstate", payload, headers)

    def dissolve_authority(self, payload, headers):
        return self._request("POST", "/cca/authority/dissolve", payload, headers)

    def set_current_utc(self, payload, headers):
        return self._request("POST", "/cca/_clock/set_current_utc", payload, headers)

    def advance_epoch(self, payload, headers):
        return self._request("POST", "/cca/_clock/advance_epoch", payload, headers)

    # --- service accounts ---
    def ingest_service_accounts(self, payload, headers):
        return self._request("POST", "/cca/service-accounts/ingest", payload, headers)

    def list_service_accounts(self, headers, params=None):
        return self._request("GET", "/cca/service-accounts", headers=headers, params=params)

    def get_service_account(self, account_id, headers):
        return self._request("GET", f"/cca/service-accounts/{account_id}", headers=headers)

    def change_product_election(self, account_id, payload, headers):
        return self._request(
            "POST", f"/cca/service-accounts/{account_id}/product-election", payload, headers
        )

    def close_service_account(self, account_id, payload, headers):
        return self._request(
            "POST", f"/cca/service-accounts/{account_id}/close", payload, headers
        )

    def write_off_service_account(self, account_id, payload, headers):
        return self._request(
            "POST", f"/cca/service-accounts/{account_id}/write-off", payload, headers
        )

    # --- enrollment notices & opt-outs ---
    def create_enrollment_notice(self, payload, headers):
        return self._request("POST", "/cca/enrollment-notices", payload, headers)

    def list_enrollment_notices(self, headers, params=None):
        return self._request("GET", "/cca/enrollment-notices", headers=headers, params=params)

    def get_enrollment_notice(self, notice_id, headers):
        return self._request("GET", f"/cca/enrollment-notices/{notice_id}", headers=headers)

    def issue_enrollment_notice(self, notice_id, payload, headers):
        return self._request(
            "POST", f"/cca/enrollment-notices/{notice_id}/issue", payload, headers
        )

    def close_enrollment_notice(self, notice_id, payload, headers):
        return self._request(
            "POST", f"/cca/enrollment-notices/{notice_id}/close", payload, headers
        )

    def cancel_enrollment_notice(self, notice_id, payload, headers):
        return self._request(
            "POST", f"/cca/enrollment-notices/{notice_id}/cancel", payload, headers
        )

    def list_notice_opt_out_requests(self, notice_id, headers):
        return self._request(
            "GET", f"/cca/enrollment-notices/{notice_id}/opt-out-requests", headers=headers
        )

    def create_opt_out_request(self, payload, headers):
        return self._request("POST", "/cca/opt-out-requests", payload, headers)

    def list_opt_out_requests(self, headers, params=None):
        return self._request("GET", "/cca/opt-out-requests", headers=headers, params=params)

    def get_opt_out_request(self, request_id, headers):
        return self._request("GET", f"/cca/opt-out-requests/{request_id}", headers=headers)

    # --- products & rates ---
    def create_product(self, payload, headers):
        return self._request("POST", "/cca/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/cca/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/cca/products/{product_id}", headers=headers)

    def adopt_product(self, product_id, payload, headers):
        return self._request("POST", f"/cca/products/{product_id}/adopt", payload, headers)

    def retire_product(self, product_id, payload, headers):
        return self._request("POST", f"/cca/products/{product_id}/retire", payload, headers)

    def list_product_rate_schedules(self, product_id, headers):
        return self._request(
            "GET", f"/cca/products/{product_id}/rate-schedules", headers=headers
        )

    def create_rate_schedule(self, payload, headers):
        return self._request("POST", "/cca/rate-schedules", payload, headers)

    def list_rate_schedules(self, headers, params=None):
        return self._request("GET", "/cca/rate-schedules", headers=headers, params=params)

    def get_rate_schedule(self, schedule_id, headers):
        return self._request("GET", f"/cca/rate-schedules/{schedule_id}", headers=headers)

    def update_rate_schedule(self, schedule_id, payload, headers):
        return self._request("PUT", f"/cca/rate-schedules/{schedule_id}", payload, headers)

    def propose_rate_schedule(self, schedule_id, payload, headers):
        return self._request(
            "POST", f"/cca/rate-schedules/{schedule_id}/propose", payload, headers
        )

    def adopt_rate_schedule(self, schedule_id, payload, headers):
        return self._request(
            "POST", f"/cca/rate-schedules/{schedule_id}/adopt", payload, headers
        )

    def reject_rate_schedule(self, schedule_id, payload, headers):
        return self._request(
            "POST", f"/cca/rate-schedules/{schedule_id}/reject", payload, headers
        )

    # --- supply portfolio ---
    def create_supply_contract(self, payload, headers):
        return self._request("POST", "/cca/supply-contracts", payload, headers)

    def list_supply_contracts(self, headers, params=None):
        return self._request("GET", "/cca/supply-contracts", headers=headers, params=params)

    def get_supply_contract(self, contract_id, headers):
        return self._request("GET", f"/cca/supply-contracts/{contract_id}", headers=headers)

    def execute_supply_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/cca/supply-contracts/{contract_id}/execute", payload, headers
        )

    def terminate_supply_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/cca/supply-contracts/{contract_id}/terminate", payload, headers
        )

    def list_contract_rec_retirements(self, contract_id, headers):
        return self._request(
            "GET", f"/cca/supply-contracts/{contract_id}/rec-retirements", headers=headers
        )

    # --- load forecast ---
    def create_load_forecast(self, payload, headers):
        return self._request("POST", "/cca/load-forecasts", payload, headers)

    def list_load_forecasts(self, headers, params=None):
        return self._request("GET", "/cca/load-forecasts", headers=headers, params=params)

    def get_load_forecast(self, forecast_id, headers):
        return self._request("GET", f"/cca/load-forecasts/{forecast_id}", headers=headers)

    # --- billing ---
    def create_billing_extract(self, payload, headers):
        return self._request("POST", "/cca/billing-extracts", payload, headers)

    def list_billing_extracts(self, headers, params=None):
        return self._request("GET", "/cca/billing-extracts", headers=headers, params=params)

    def get_billing_extract(self, extract_id, headers):
        return self._request("GET", f"/cca/billing-extracts/{extract_id}", headers=headers)

    def post_billing_line(self, extract_id, payload, headers):
        return self._request(
            "POST", f"/cca/billing-extracts/{extract_id}/lines", payload, headers
        )

    def list_extract_lines(self, extract_id, headers):
        return self._request(
            "GET", f"/cca/billing-extracts/{extract_id}/lines", headers=headers
        )

    def list_billing_lines(self, headers, params=None):
        return self._request("GET", "/cca/billing-lines", headers=headers, params=params)

    def get_billing_line(self, line_id, headers):
        return self._request("GET", f"/cca/billing-lines/{line_id}", headers=headers)

    def submit_billing_extract(self, extract_id, payload, headers):
        return self._request(
            "POST", f"/cca/billing-extracts/{extract_id}/submit", payload, headers
        )

    def utility_accept_extract(self, extract_id, payload, headers):
        return self._request(
            "POST", f"/cca/billing-extracts/{extract_id}/utility-accept", payload, headers
        )

    def utility_reject_extract(self, extract_id, payload, headers):
        return self._request(
            "POST", f"/cca/billing-extracts/{extract_id}/utility-reject", payload, headers
        )

    def reopen_billing_extract(self, extract_id, payload, headers):
        return self._request(
            "POST", f"/cca/billing-extracts/{extract_id}/reopen", payload, headers
        )

    # --- remittance ---
    def create_remittance_file(self, payload, headers):
        return self._request("POST", "/cca/remittance-files", payload, headers)

    def list_remittance_files(self, headers, params=None):
        return self._request("GET", "/cca/remittance-files", headers=headers, params=params)

    def get_remittance_file(self, remittance_id, headers):
        return self._request("GET", f"/cca/remittance-files/{remittance_id}", headers=headers)

    def reconcile_remittance_file(self, remittance_id, payload, headers):
        return self._request(
            "POST", f"/cca/remittance-files/{remittance_id}/reconcile", payload, headers
        )

    def dispute_remittance_file(self, remittance_id, payload, headers):
        return self._request(
            "POST", f"/cca/remittance-files/{remittance_id}/dispute", payload, headers
        )

    def reopen_remittance_file(self, remittance_id, payload, headers):
        return self._request(
            "POST", f"/cca/remittance-files/{remittance_id}/reopen", payload, headers
        )

    def settle_remittance_file(self, remittance_id, payload, headers):
        return self._request(
            "POST", f"/cca/remittance-files/{remittance_id}/settle", payload, headers
        )

    # --- bad debt ---
    def create_bad_debt_pool(self, payload, headers):
        return self._request("POST", "/cca/bad-debt-pools", payload, headers)

    def list_bad_debt_pools(self, headers, params=None):
        return self._request("GET", "/cca/bad-debt-pools", headers=headers, params=params)

    def get_bad_debt_pool(self, pool_id, headers):
        return self._request("GET", f"/cca/bad-debt-pools/{pool_id}", headers=headers)

    def close_bad_debt_pool(self, pool_id, payload, headers):
        return self._request("POST", f"/cca/bad-debt-pools/{pool_id}/close", payload, headers)

    def true_up_bad_debt_pool(self, pool_id, payload, headers):
        return self._request(
            "POST", f"/cca/bad-debt-pools/{pool_id}/true-up", payload, headers
        )

    # --- compliance ---
    def create_compliance_filing(self, payload, headers):
        return self._request("POST", "/cca/compliance-filings", payload, headers)

    def list_compliance_filings(self, headers, params=None):
        return self._request("GET", "/cca/compliance-filings", headers=headers, params=params)

    def get_compliance_filing(self, filing_id, headers):
        return self._request("GET", f"/cca/compliance-filings/{filing_id}", headers=headers)

    def list_filing_rec_retirements(self, filing_id, headers):
        return self._request(
            "GET", f"/cca/compliance-filings/{filing_id}/rec-retirements", headers=headers
        )

    def prepare_compliance_filing(self, filing_id, payload, headers):
        return self._request(
            "POST", f"/cca/compliance-filings/{filing_id}/prepare", payload, headers
        )

    def review_compliance_filing(self, filing_id, payload, headers):
        return self._request(
            "POST", f"/cca/compliance-filings/{filing_id}/review", payload, headers
        )

    def file_compliance_filing(self, filing_id, payload, headers):
        return self._request(
            "POST", f"/cca/compliance-filings/{filing_id}/file", payload, headers
        )

    def cpuc_accept_filing(self, filing_id, payload, headers):
        return self._request(
            "POST", f"/cca/compliance-filings/{filing_id}/cpuc-accept", payload, headers
        )

    def cpuc_reject_filing(self, filing_id, payload, headers):
        return self._request(
            "POST", f"/cca/compliance-filings/{filing_id}/cpuc-reject", payload, headers
        )

    def revise_compliance_filing(self, filing_id, payload, headers):
        return self._request(
            "POST", f"/cca/compliance-filings/{filing_id}/revise", payload, headers
        )

    def withdraw_compliance_filing(self, filing_id, payload, headers):
        return self._request(
            "POST", f"/cca/compliance-filings/{filing_id}/withdraw", payload, headers
        )

    # --- REC retirements ---
    def create_rec_retirement(self, payload, headers):
        return self._request("POST", "/cca/rec-retirements", payload, headers)

    def list_rec_retirements(self, headers, params=None):
        return self._request("GET", "/cca/rec-retirements", headers=headers, params=params)


api_client = ApiClient()
