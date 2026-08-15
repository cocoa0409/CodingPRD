"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- ServiceLine ---
    def create_service_line(self, payload, headers):
        return self._request("POST", "/cost-accounting/service-lines", payload, headers)

    def list_service_lines(self, headers, params=None):
        return self._request("GET", "/cost-accounting/service-lines", headers=headers, params=params)

    def get_service_line(self, service_line_id, headers):
        return self._request("GET", f"/cost-accounting/service-lines/{service_line_id}", headers=headers)

    def archive_service_line(self, service_line_id, headers):
        return self._request("POST", f"/cost-accounting/service-lines/{service_line_id}/archive", headers=headers)

    # --- CostCenter ---
    def create_cost_center(self, payload, headers):
        return self._request("POST", "/cost-accounting/cost-centers", payload, headers)

    def list_cost_centers(self, headers, params=None):
        return self._request("GET", "/cost-accounting/cost-centers", headers=headers, params=params)

    def get_cost_center(self, cost_center_id, headers):
        return self._request("GET", f"/cost-accounting/cost-centers/{cost_center_id}", headers=headers)

    def archive_cost_center(self, cost_center_id, headers):
        return self._request("POST", f"/cost-accounting/cost-centers/{cost_center_id}/archive", headers=headers)

    def list_cost_center_activity_lines(self, cost_center_id, headers, params=None):
        return self._request("GET", f"/cost-accounting/cost-centers/{cost_center_id}/activity-lines", headers=headers, params=params)

    # --- Physician ---
    def create_physician(self, payload, headers):
        return self._request("POST", "/cost-accounting/physicians", payload, headers)

    def list_physicians(self, headers, params=None):
        return self._request("GET", "/cost-accounting/physicians", headers=headers, params=params)

    def get_physician(self, physician_id, headers):
        return self._request("GET", f"/cost-accounting/physicians/{physician_id}", headers=headers)

    def deactivate_physician(self, physician_id, headers):
        return self._request("POST", f"/cost-accounting/physicians/{physician_id}/deactivate", headers=headers)

    def reactivate_physician(self, physician_id, headers):
        return self._request("POST", f"/cost-accounting/physicians/{physician_id}/reactivate", headers=headers)

    # --- Drg ---
    def create_drg(self, payload, headers):
        return self._request("POST", "/cost-accounting/drgs", payload, headers)

    def list_drgs(self, headers, params=None):
        return self._request("GET", "/cost-accounting/drgs", headers=headers, params=params)

    def get_drg(self, drg_id, headers):
        return self._request("GET", f"/cost-accounting/drgs/{drg_id}", headers=headers)

    # --- CostModel ---
    def create_cost_model(self, payload, headers):
        return self._request("POST", "/cost-accounting/cost-models", payload, headers)

    def list_cost_models(self, headers, params=None):
        return self._request("GET", "/cost-accounting/cost-models", headers=headers, params=params)

    def get_cost_model(self, model_id, headers):
        return self._request("GET", f"/cost-accounting/cost-models/{model_id}", headers=headers)

    def approve_cost_model(self, model_id, headers):
        return self._request("POST", f"/cost-accounting/cost-models/{model_id}/approve", headers=headers)

    def archive_cost_model(self, model_id, headers):
        return self._request("POST", f"/cost-accounting/cost-models/{model_id}/archive", headers=headers)

    # --- CostModelRefresh ---
    def create_cost_model_refresh(self, payload, headers):
        return self._request("POST", "/cost-accounting/cost-model-refreshes", payload, headers)

    def list_cost_model_refreshes(self, headers, params=None):
        return self._request("GET", "/cost-accounting/cost-model-refreshes", headers=headers, params=params)

    def get_cost_model_refresh(self, refresh_id, headers):
        return self._request("GET", f"/cost-accounting/cost-model-refreshes/{refresh_id}", headers=headers)

    def approve_cost_model_refresh(self, refresh_id, payload, headers):
        return self._request("POST", f"/cost-accounting/cost-model-refreshes/{refresh_id}/approve", payload, headers)

    def reject_cost_model_refresh(self, refresh_id, headers):
        return self._request("POST", f"/cost-accounting/cost-model-refreshes/{refresh_id}/reject", headers=headers)

    def apply_cost_model_refresh(self, refresh_id, headers):
        return self._request("POST", f"/cost-accounting/cost-model-refreshes/{refresh_id}/apply", headers=headers)

    # --- Case ---
    def create_case(self, payload, headers):
        return self._request("POST", "/cost-accounting/cases", payload, headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/cost-accounting/cases", headers=headers, params=params)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/cost-accounting/cases/{case_id}", headers=headers)

    def add_activity_line(self, case_id, payload, headers):
        return self._request("POST", f"/cost-accounting/cases/{case_id}/activity-lines", payload, headers)

    def list_activity_lines(self, case_id, headers, params=None):
        return self._request("GET", f"/cost-accounting/cases/{case_id}/activity-lines", headers=headers, params=params)

    def add_implant(self, case_id, payload, headers):
        return self._request("POST", f"/cost-accounting/cases/{case_id}/implants", payload, headers)

    def list_implants(self, case_id, headers, params=None):
        return self._request("GET", f"/cost-accounting/cases/{case_id}/implants", headers=headers, params=params)

    def add_supply_line(self, case_id, payload, headers):
        return self._request("POST", f"/cost-accounting/cases/{case_id}/supply-lines", payload, headers)

    def list_supply_lines(self, case_id, headers, params=None):
        return self._request("GET", f"/cost-accounting/cases/{case_id}/supply-lines", headers=headers, params=params)

    def post_case(self, case_id, payload, headers):
        return self._request("POST", f"/cost-accounting/cases/{case_id}/post", payload, headers)

    def void_case(self, case_id, headers):
        return self._request("POST", f"/cost-accounting/cases/{case_id}/void", headers=headers)

    def lock_case(self, case_id, headers):
        return self._request("POST", f"/cost-accounting/cases/{case_id}/lock", headers=headers)

    # --- PayerContract ---
    def create_payer_contract(self, payload, headers):
        return self._request("POST", "/cost-accounting/payer-contracts", payload, headers)

    def list_payer_contracts(self, headers, params=None):
        return self._request("GET", "/cost-accounting/payer-contracts", headers=headers, params=params)

    def get_payer_contract(self, contract_id, headers):
        return self._request("GET", f"/cost-accounting/payer-contracts/{contract_id}", headers=headers)

    # --- BudgetPeriod ---
    def create_budget_period(self, payload, headers):
        return self._request("POST", "/cost-accounting/budget-periods", payload, headers)

    def list_budget_periods(self, headers, params=None):
        return self._request("GET", "/cost-accounting/budget-periods", headers=headers, params=params)

    def get_budget_period(self, budget_period_id, headers):
        return self._request("GET", f"/cost-accounting/budget-periods/{budget_period_id}", headers=headers)

    def lock_budget_period(self, budget_period_id, headers):
        return self._request("POST", f"/cost-accounting/budget-periods/{budget_period_id}/lock", headers=headers)

    # --- Reports ---
    def get_physician_margin_report(self, headers, params=None):
        return self._request("GET", "/cost-accounting/reports/physician-margin", headers=headers, params=params)

    def get_drg_margin_report(self, headers, params=None):
        return self._request("GET", "/cost-accounting/reports/drg-margin", headers=headers, params=params)

    def get_payer_mix_report(self, headers, params=None):
        return self._request("GET", "/cost-accounting/reports/payer-mix", headers=headers, params=params)

    def get_implant_variation_report(self, headers, params=None):
        return self._request("GET", "/cost-accounting/reports/implant-variation", headers=headers, params=params)

    def get_service_line_profitability_report(self, headers, params=None):
        return self._request("GET", "/cost-accounting/reports/service-line-profitability", headers=headers, params=params)


api_client = ApiClient()
