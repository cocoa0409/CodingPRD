"""API client: one method per endpoint defined in the PRD (§4 routing table).

All paths live under the /ucp prefix. Methods return raw requests.Response
objects; tests assert via validate_success / validate_error / validate_paginated.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint, PRD §2.6)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/ucp/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Capital programs (PRD §3.1)
    # ------------------------------------------------------------------
    def create_capital_program(self, payload, headers):
        return self._request("POST", "/ucp/capital-programs", payload, headers)

    def get_capital_program(self, program_id, headers):
        return self._request("GET", f"/ucp/capital-programs/{program_id}",
                             headers=headers)

    def list_capital_programs(self, headers, params=None):
        return self._request("GET", "/ucp/capital-programs", headers=headers,
                             params=params)

    def close_capital_program(self, program_id, headers):
        return self._request("POST", f"/ucp/capital-programs/{program_id}/close",
                             {}, headers)

    # ------------------------------------------------------------------
    # Unit catalog (PRD §3.1)
    # ------------------------------------------------------------------
    def create_unit_catalog_entry(self, payload, headers):
        return self._request("POST", "/ucp/unit-catalog", payload, headers)

    def get_unit_catalog_entry(self, catalog_id, headers):
        return self._request("GET", f"/ucp/unit-catalog/{catalog_id}",
                             headers=headers)

    def list_unit_catalog(self, headers, params=None):
        return self._request("GET", "/ucp/unit-catalog", headers=headers,
                             params=params)

    # ------------------------------------------------------------------
    # Overhead schedules (PRD §3.1)
    # ------------------------------------------------------------------
    def create_overhead_schedule(self, payload, headers):
        return self._request("POST", "/ucp/overhead-schedules", payload, headers)

    def get_overhead_schedule(self, schedule_id, headers):
        return self._request("GET", f"/ucp/overhead-schedules/{schedule_id}",
                             headers=headers)

    def list_overhead_schedules(self, headers, params=None):
        return self._request("GET", "/ucp/overhead-schedules", headers=headers,
                             params=params)

    # ------------------------------------------------------------------
    # Accounting periods (PRD §3.2, §3.9)
    # ------------------------------------------------------------------
    def create_accounting_period(self, payload, headers):
        return self._request("POST", "/ucp/accounting-periods", payload, headers)

    def get_accounting_period(self, period_id, headers):
        return self._request("GET", f"/ucp/accounting-periods/{period_id}",
                             headers=headers)

    def list_accounting_periods(self, headers, params=None):
        return self._request("GET", "/ucp/accounting-periods", headers=headers,
                             params=params)

    def close_accounting_period(self, period_id, headers):
        return self._request("POST", f"/ucp/accounting-periods/{period_id}/close",
                             {}, headers)

    def reopen_accounting_period(self, period_id, headers):
        return self._request("POST",
                             f"/ucp/accounting-periods/{period_id}/reopen",
                             {}, headers)

    # ------------------------------------------------------------------
    # Work orders (PRD §3.3, §3.7, §3.8)
    # ------------------------------------------------------------------
    def create_work_order(self, payload, headers):
        return self._request("POST", "/ucp/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/ucp/work-orders/{work_order_id}",
                             headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/ucp/work-orders", headers=headers,
                             params=params)

    def submit_work_order(self, work_order_id, headers):
        return self._request("POST", f"/ucp/work-orders/{work_order_id}/submit",
                             {}, headers)

    def return_work_order(self, work_order_id, reason, headers):
        return self._request("POST", f"/ucp/work-orders/{work_order_id}/return",
                             {"reason": reason}, headers)

    def authorize_work_order(self, work_order_id, headers):
        return self._request("POST",
                             f"/ucp/work-orders/{work_order_id}/authorize",
                             {}, headers)

    def start_work_order(self, work_order_id, headers):
        return self._request("POST", f"/ucp/work-orders/{work_order_id}/start",
                             {}, headers)

    def suspend_work_order(self, work_order_id, headers):
        return self._request("POST", f"/ucp/work-orders/{work_order_id}/suspend",
                             {}, headers)

    def resume_work_order(self, work_order_id, headers):
        return self._request("POST", f"/ucp/work-orders/{work_order_id}/resume",
                             {}, headers)

    def cancel_work_order(self, work_order_id, headers, payload=None):
        return self._request("POST", f"/ucp/work-orders/{work_order_id}/cancel",
                             payload or {}, headers)

    def complete_work_order(self, work_order_id, in_service_date, headers):
        return self._request("POST", f"/ucp/work-orders/{work_order_id}/complete",
                             {"in_service_date": in_service_date}, headers)

    def closeout_work_order(self, work_order_id, unitization_lines, headers):
        return self._request("POST", f"/ucp/work-orders/{work_order_id}/closeout",
                             {"unitization_lines": unitization_lines}, headers)

    # ------------------------------------------------------------------
    # Estimates (PRD §3.4)
    # ------------------------------------------------------------------
    def create_estimate(self, payload, headers):
        return self._request("POST", "/ucp/estimates", payload, headers)

    def get_estimate(self, estimate_id, headers):
        return self._request("GET", f"/ucp/estimates/{estimate_id}",
                             headers=headers)

    def list_estimates(self, headers, params=None):
        return self._request("GET", "/ucp/estimates", headers=headers,
                             params=params)

    def approve_estimate(self, estimate_id, expected_work_order_version, headers):
        return self._request("POST", f"/ucp/estimates/{estimate_id}/approve",
                             {"expected_work_order_version":
                              expected_work_order_version}, headers)

    def reject_estimate(self, estimate_id, headers):
        return self._request("POST", f"/ucp/estimates/{estimate_id}/reject",
                             {}, headers)

    # ------------------------------------------------------------------
    # Cost charges (PRD §3.5)
    # ------------------------------------------------------------------
    def create_cost_charge(self, payload, headers):
        return self._request("POST", "/ucp/cost-charges", payload, headers)

    def get_cost_charge(self, charge_id, headers):
        return self._request("GET", f"/ucp/cost-charges/{charge_id}",
                             headers=headers)

    def list_cost_charges(self, headers, params=None):
        return self._request("GET", "/ucp/cost-charges", headers=headers,
                             params=params)

    def reverse_cost_charge(self, charge_id, headers):
        return self._request("POST", f"/ucp/cost-charges/{charge_id}/reverse",
                             {}, headers)

    # ------------------------------------------------------------------
    # CIAC agreements (PRD §3.6)
    # ------------------------------------------------------------------
    def create_ciac_agreement(self, payload, headers):
        return self._request("POST", "/ucp/ciac-agreements", payload, headers)

    def get_ciac_agreement(self, ciac_id, headers):
        return self._request("GET", f"/ucp/ciac-agreements/{ciac_id}",
                             headers=headers)

    def list_ciac_agreements(self, headers, params=None):
        return self._request("GET", "/ucp/ciac-agreements", headers=headers,
                             params=params)

    def receive_ciac_agreement(self, ciac_id, headers):
        return self._request("POST", f"/ucp/ciac-agreements/{ciac_id}/receive",
                             {}, headers)

    # ------------------------------------------------------------------
    # Fixed asset units (PRD §3.8)
    # ------------------------------------------------------------------
    def get_fixed_asset_unit(self, unit_id, headers):
        return self._request("GET", f"/ucp/fixed-asset-units/{unit_id}",
                             headers=headers)

    def list_fixed_asset_units(self, headers, params=None):
        return self._request("GET", "/ucp/fixed-asset-units", headers=headers,
                             params=params)

    def retire_fixed_asset_unit(self, unit_id, retirement_date, headers):
        return self._request("POST",
                             f"/ucp/fixed-asset-units/{unit_id}/retire",
                             {"retirement_date": retirement_date}, headers)

    # ------------------------------------------------------------------
    # Regulatory assets (PRD §3.7)
    # ------------------------------------------------------------------
    def create_regulatory_asset(self, payload, headers):
        return self._request("POST", "/ucp/regulatory-assets", payload, headers)

    def get_regulatory_asset(self, reg_asset_id, headers):
        return self._request("GET", f"/ucp/regulatory-assets/{reg_asset_id}",
                             headers=headers)

    def list_regulatory_assets(self, headers, params=None):
        return self._request("GET", "/ucp/regulatory-assets", headers=headers,
                             params=params)

    def approve_regulatory_asset(self, reg_asset_id, headers):
        return self._request("POST",
                             f"/ucp/regulatory-assets/{reg_asset_id}/approve",
                             {}, headers)

    def reject_regulatory_asset(self, reg_asset_id, headers):
        return self._request("POST",
                             f"/ucp/regulatory-assets/{reg_asset_id}/reject",
                             {}, headers)

    # ------------------------------------------------------------------
    # Ledger entry logs (read-only, PRD §3.9)
    # ------------------------------------------------------------------
    def get_afudc_entry(self, entry_id, headers):
        return self._request("GET", f"/ucp/afudc-entries/{entry_id}",
                             headers=headers)

    def list_afudc_entries(self, headers, params=None):
        return self._request("GET", "/ucp/afudc-entries", headers=headers,
                             params=params)

    def get_depreciation_entry(self, entry_id, headers):
        return self._request("GET", f"/ucp/depreciation-entries/{entry_id}",
                             headers=headers)

    def list_depreciation_entries(self, headers, params=None):
        return self._request("GET", "/ucp/depreciation-entries", headers=headers,
                             params=params)

    def get_amortization_entry(self, entry_id, headers):
        return self._request("GET", f"/ucp/amortization-entries/{entry_id}",
                             headers=headers)

    def list_amortization_entries(self, headers, params=None):
        return self._request("GET", "/ucp/amortization-entries", headers=headers,
                             params=params)


api_client = ApiClient()
