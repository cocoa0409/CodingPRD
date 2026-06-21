"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- PoolPolicy ----
    def create_pool_policy(self, payload, headers):
        return self._request("POST", "/pool-policies", payload, headers)

    def get_pool_policy(self, policy_id, headers):
        return self._request("GET", f"/pool-policies/{policy_id}", headers=headers)

    # ---- AssetType ----
    def create_asset_type(self, payload, headers):
        return self._request("POST", "/asset-types", payload, headers)

    def get_asset_type(self, asset_type_id, headers):
        return self._request("GET", f"/asset-types/{asset_type_id}", headers=headers)

    def discontinue_asset_type(self, asset_type_id, headers):
        return self._request(
            "POST", f"/asset-types/{asset_type_id}/discontinue", headers=headers
        )

    # ---- Account ----
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def suspend_account(self, account_id, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/suspend", headers=headers
        )

    def reactivate_account(self, account_id, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/reactivate", headers=headers
        )

    def close_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/close", headers=headers)

    # ---- Location ----
    def create_location(self, payload, headers):
        return self._request("POST", "/locations", payload, headers)

    def get_location(self, location_id, headers):
        return self._request("GET", f"/locations/{location_id}", headers=headers)

    def list_locations(self, headers, params=None):
        return self._request("GET", "/locations", headers=headers, params=params)

    def close_location(self, location_id, headers):
        return self._request(
            "POST", f"/locations/{location_id}/close", headers=headers
        )

    # ---- Asset ----
    def create_asset(self, payload, headers):
        return self._request("POST", "/assets", payload, headers)

    def get_asset(self, asset_id, headers):
        return self._request("GET", f"/assets/{asset_id}", headers=headers)

    def list_assets(self, headers, params=None):
        return self._request("GET", "/assets", headers=headers, params=params)

    def report_damage(self, asset_id, headers):
        return self._request(
            "POST", f"/assets/{asset_id}/report-damage", headers=headers
        )

    # ---- TransferOrder ----
    def create_transfer_order(self, payload, headers):
        return self._request("POST", "/transfer-orders", payload, headers)

    def get_transfer_order(self, transfer_order_id, headers):
        return self._request(
            "GET", f"/transfer-orders/{transfer_order_id}", headers=headers
        )

    def list_transfer_orders(self, headers, params=None):
        return self._request(
            "GET", "/transfer-orders", headers=headers, params=params
        )

    def dispatch_transfer_order(self, transfer_order_id, headers):
        return self._request(
            "POST", f"/transfer-orders/{transfer_order_id}/dispatch", headers=headers
        )

    def receive_transfer_order(self, transfer_order_id, headers):
        return self._request(
            "POST", f"/transfer-orders/{transfer_order_id}/receive", headers=headers
        )

    def cancel_transfer_order(self, transfer_order_id, headers):
        return self._request(
            "POST", f"/transfer-orders/{transfer_order_id}/cancel", headers=headers
        )

    # ---- Hire ----
    def create_hire(self, payload, headers):
        return self._request("POST", "/hires", payload, headers)

    def get_hire(self, hire_id, headers):
        return self._request("GET", f"/hires/{hire_id}", headers=headers)

    def list_hires(self, headers, params=None):
        return self._request("GET", "/hires", headers=headers, params=params)

    def close_hire(self, hire_id, headers):
        return self._request("POST", f"/hires/{hire_id}/close", headers=headers)

    def void_hire(self, hire_id, headers):
        return self._request("POST", f"/hires/{hire_id}/void", headers=headers)

    # ---- AuditReconciliation ----
    def create_audit(self, payload, headers):
        return self._request("POST", "/audit-reconciliations", payload, headers)

    def get_audit(self, audit_id, headers):
        return self._request(
            "GET", f"/audit-reconciliations/{audit_id}", headers=headers
        )

    def list_audits(self, headers, params=None):
        return self._request(
            "GET", "/audit-reconciliations", headers=headers, params=params
        )

    def finalize_audit(self, audit_id, headers):
        return self._request(
            "POST", f"/audit-reconciliations/{audit_id}/finalize", headers=headers
        )

    def void_audit(self, audit_id, headers):
        return self._request(
            "POST", f"/audit-reconciliations/{audit_id}/void", headers=headers
        )

    # ---- Voucher ----
    def create_voucher(self, payload, headers):
        return self._request("POST", "/vouchers", payload, headers)

    def get_voucher(self, voucher_id, headers):
        return self._request("GET", f"/vouchers/{voucher_id}", headers=headers)

    def list_vouchers(self, headers, params=None):
        return self._request("GET", "/vouchers", headers=headers, params=params)

    def redeem_voucher(self, voucher_id, payload, headers):
        return self._request(
            "POST", f"/vouchers/{voucher_id}/redeem", payload, headers
        )

    def cancel_voucher(self, voucher_id, headers):
        return self._request(
            "POST", f"/vouchers/{voucher_id}/cancel", headers=headers
        )

    # ---- CollectionRequest ----
    def create_collection_request(self, payload, headers):
        return self._request("POST", "/collection-requests", payload, headers)

    def get_collection_request(self, collection_request_id, headers):
        return self._request(
            "GET", f"/collection-requests/{collection_request_id}", headers=headers
        )

    def list_collection_requests(self, headers, params=None):
        return self._request(
            "GET", "/collection-requests", headers=headers, params=params
        )

    def collect_collection_request(self, collection_request_id, headers):
        return self._request(
            "POST",
            f"/collection-requests/{collection_request_id}/collect",
            headers=headers,
        )

    def close_collection_request(self, collection_request_id, headers):
        return self._request(
            "POST",
            f"/collection-requests/{collection_request_id}/close",
            headers=headers,
        )

    def cancel_collection_request(self, collection_request_id, headers):
        return self._request(
            "POST",
            f"/collection-requests/{collection_request_id}/cancel",
            headers=headers,
        )

    # ---- RepairJob ----
    def create_repair_job(self, payload, headers):
        return self._request("POST", "/repair-jobs", payload, headers)

    def get_repair_job(self, repair_job_id, headers):
        return self._request("GET", f"/repair-jobs/{repair_job_id}", headers=headers)

    def list_repair_jobs(self, headers, params=None):
        return self._request("GET", "/repair-jobs", headers=headers, params=params)

    def complete_repair_job(self, repair_job_id, headers):
        return self._request(
            "POST", f"/repair-jobs/{repair_job_id}/complete", headers=headers
        )

    def scrap_repair_job(self, repair_job_id, headers):
        return self._request(
            "POST", f"/repair-jobs/{repair_job_id}/scrap", headers=headers
        )

    # ---- Invoice ----
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def add_invoice_line(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/invoices/{invoice_id}/lines", payload, headers
        )

    def list_invoice_lines(self, invoice_id, headers, params=None):
        return self._request(
            "GET", f"/invoices/{invoice_id}/lines", headers=headers, params=params
        )

    def get_invoice_line(self, invoice_line_id, headers):
        return self._request(
            "GET", f"/invoice-lines/{invoice_line_id}", headers=headers
        )

    def list_all_invoice_lines(self, headers, params=None):
        return self._request("GET", "/invoice-lines", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers):
        return self._request(
            "POST", f"/invoices/{invoice_id}/issue", headers=headers
        )

    def record_payment(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/invoices/{invoice_id}/record-payment", payload, headers
        )

    def void_invoice(self, invoice_id, headers):
        return self._request(
            "POST", f"/invoices/{invoice_id}/void", headers=headers
        )

    # ---- DemandForecast ----
    def create_demand_forecast(self, payload, headers):
        return self._request("POST", "/demand-forecasts", payload, headers)

    def get_demand_forecast(self, demand_forecast_id, headers):
        return self._request(
            "GET", f"/demand-forecasts/{demand_forecast_id}", headers=headers
        )

    def list_demand_forecasts(self, headers, params=None):
        return self._request(
            "GET", "/demand-forecasts", headers=headers, params=params
        )


api_client = ApiClient()
