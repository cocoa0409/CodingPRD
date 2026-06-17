"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Employee ----
    def create_employee(self, payload, headers):
        return self._request("POST", "/employees", payload, headers)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/employees/{employee_id}", headers=headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/employees", headers=headers, params=params)

    # ---- Grade ----
    def create_grade(self, payload, headers):
        return self._request("POST", "/grades", payload, headers)

    def get_grade(self, grade_id, headers):
        return self._request("GET", f"/grades/{grade_id}", headers=headers)

    def list_grades(self, headers, params=None):
        return self._request("GET", "/grades", headers=headers, params=params)

    # ---- CostCenter ----
    def create_cost_center(self, payload, headers):
        return self._request("POST", "/cost-centers", payload, headers)

    def get_cost_center(self, cost_center_id, headers):
        return self._request("GET", f"/cost-centers/{cost_center_id}", headers=headers)

    def list_cost_centers(self, headers, params=None):
        return self._request("GET", "/cost-centers", headers=headers, params=params)

    def list_cost_center_positions(self, cost_center_id, headers, params=None):
        return self._request("GET", f"/cost-centers/{cost_center_id}/positions", headers=headers, params=params)

    # ---- Position ----
    def create_position(self, payload, headers):
        return self._request("POST", "/positions", payload, headers)

    def get_position(self, position_id, headers):
        return self._request("GET", f"/positions/{position_id}", headers=headers)

    def list_positions(self, headers, params=None):
        return self._request("GET", "/positions", headers=headers, params=params)

    def update_position(self, position_id, payload, headers):
        return self._request("PATCH", f"/positions/{position_id}", payload, headers)

    def position_lifecycle(self, position_id, payload, headers):
        return self._request("POST", f"/positions/{position_id}/lifecycle", payload, headers)

    def list_position_reports(self, position_id, headers, params=None):
        return self._request("GET", f"/positions/{position_id}/reports", headers=headers, params=params)

    # ---- Incumbent ----
    def create_incumbent(self, position_id, payload, headers):
        return self._request("POST", f"/positions/{position_id}/incumbents", payload, headers)

    def list_position_incumbents(self, position_id, headers, params=None):
        return self._request("GET", f"/positions/{position_id}/incumbents", headers=headers, params=params)

    def get_incumbent(self, incumbent_id, headers):
        return self._request("GET", f"/incumbents/{incumbent_id}", headers=headers)

    def list_incumbents(self, headers, params=None):
        return self._request("GET", "/incumbents", headers=headers, params=params)

    def vacate_incumbent(self, incumbent_id, payload, headers):
        return self._request("POST", f"/incumbents/{incumbent_id}/vacate", payload, headers)

    # ---- FreezeOrder ----
    def create_freeze_order(self, cost_center_id, payload, headers):
        return self._request("POST", f"/cost-centers/{cost_center_id}/freeze-orders", payload, headers)

    def list_cost_center_freeze_orders(self, cost_center_id, headers, params=None):
        return self._request("GET", f"/cost-centers/{cost_center_id}/freeze-orders", headers=headers, params=params)

    def get_freeze_order(self, freeze_order_id, headers):
        return self._request("GET", f"/freeze-orders/{freeze_order_id}", headers=headers)

    def list_freeze_orders(self, headers, params=None):
        return self._request("GET", "/freeze-orders", headers=headers, params=params)

    def lift_freeze_order(self, freeze_order_id, headers):
        return self._request("POST", f"/freeze-orders/{freeze_order_id}/lift", headers=headers)

    # ---- Requisition ----
    def create_requisition(self, position_id, payload, headers):
        return self._request("POST", f"/positions/{position_id}/requisitions", payload, headers)

    def list_position_requisitions(self, position_id, headers, params=None):
        return self._request("GET", f"/positions/{position_id}/requisitions", headers=headers, params=params)

    def get_requisition(self, requisition_id, headers):
        return self._request("GET", f"/requisitions/{requisition_id}", headers=headers)

    def list_requisitions(self, headers, params=None):
        return self._request("GET", "/requisitions", headers=headers, params=params)

    def approve_requisition(self, requisition_id, headers):
        return self._request("POST", f"/requisitions/{requisition_id}/approve", headers=headers)

    def close_requisition(self, requisition_id, headers):
        return self._request("POST", f"/requisitions/{requisition_id}/close", headers=headers)

    def cancel_requisition(self, requisition_id, headers):
        return self._request("POST", f"/requisitions/{requisition_id}/cancel", headers=headers)

    # ---- ReclassRequest ----
    def create_reclass_request(self, position_id, payload, headers):
        return self._request("POST", f"/positions/{position_id}/reclass-requests", payload, headers)

    def list_position_reclass_requests(self, position_id, headers, params=None):
        return self._request("GET", f"/positions/{position_id}/reclass-requests", headers=headers, params=params)

    def get_reclass_request(self, reclass_id, headers):
        return self._request("GET", f"/reclass-requests/{reclass_id}", headers=headers)

    def list_reclass_requests(self, headers, params=None):
        return self._request("GET", "/reclass-requests", headers=headers, params=params)

    def review_reclass_request(self, reclass_id, headers):
        return self._request("POST", f"/reclass-requests/{reclass_id}/review", headers=headers)

    def return_reclass_request(self, reclass_id, headers):
        return self._request("POST", f"/reclass-requests/{reclass_id}/return", headers=headers)

    def approve_reclass_request(self, reclass_id, payload, headers):
        return self._request("POST", f"/reclass-requests/{reclass_id}/approve", payload, headers)

    def reject_reclass_request(self, reclass_id, headers):
        return self._request("POST", f"/reclass-requests/{reclass_id}/reject", headers=headers)

    # ---- ForecastPeriod ----
    def create_forecast_period(self, cost_center_id, payload, headers):
        return self._request("POST", f"/cost-centers/{cost_center_id}/forecast-periods", payload, headers)

    def list_cost_center_forecast_periods(self, cost_center_id, headers, params=None):
        return self._request("GET", f"/cost-centers/{cost_center_id}/forecast-periods", headers=headers, params=params)

    def get_forecast_period(self, forecast_period_id, headers):
        return self._request("GET", f"/forecast-periods/{forecast_period_id}", headers=headers)

    def list_forecast_periods(self, headers, params=None):
        return self._request("GET", "/forecast-periods", headers=headers, params=params)

    def snapshot_forecast_period(self, forecast_period_id, payload, headers):
        return self._request("POST", f"/forecast-periods/{forecast_period_id}/snapshot", payload, headers)

    # ---- BudgetAdjustment ----
    def create_budget_adjustment(self, cost_center_id, payload, headers):
        return self._request("POST", f"/cost-centers/{cost_center_id}/budget-adjustments", payload, headers)

    def list_cost_center_budget_adjustments(self, cost_center_id, headers, params=None):
        return self._request("GET", f"/cost-centers/{cost_center_id}/budget-adjustments", headers=headers, params=params)

    def get_budget_adjustment(self, budget_adjustment_id, headers):
        return self._request("GET", f"/budget-adjustments/{budget_adjustment_id}", headers=headers)

    def list_budget_adjustments(self, headers, params=None):
        return self._request("GET", "/budget-adjustments", headers=headers, params=params)

    # ---- Test-driving clock ----
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
