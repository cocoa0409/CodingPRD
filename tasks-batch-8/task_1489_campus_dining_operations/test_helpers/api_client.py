"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Dining halls
    # ------------------------------------------------------------------
    def create_dining_hall(self, payload, headers):
        return self._request("POST", "/dining-halls", payload, headers)

    def list_dining_halls(self, headers, params=None):
        return self._request("GET", "/dining-halls", headers=headers, params=params)

    def get_dining_hall(self, hall_id, headers):
        return self._request("GET", f"/dining-halls/{hall_id}", headers=headers)

    def suspend_dining_hall(self, hall_id, headers):
        return self._request("POST", f"/dining-halls/{hall_id}/suspend", {}, headers)

    def reactivate_dining_hall(self, hall_id, headers):
        return self._request("POST", f"/dining-halls/{hall_id}/reactivate", {}, headers)

    # ------------------------------------------------------------------
    # Vendor contracts
    # ------------------------------------------------------------------
    def create_vendor_contract(self, payload, headers):
        return self._request("POST", "/vendor-contracts", payload, headers)

    def list_vendor_contracts(self, headers, params=None):
        return self._request("GET", "/vendor-contracts", headers=headers, params=params)

    def get_vendor_contract(self, contract_id, headers):
        return self._request("GET", f"/vendor-contracts/{contract_id}", headers=headers)

    def activate_vendor_contract(self, contract_id, headers):
        return self._request("POST", f"/vendor-contracts/{contract_id}/activate", {}, headers)

    def terminate_vendor_contract(self, contract_id, headers):
        return self._request("POST", f"/vendor-contracts/{contract_id}/terminate", {}, headers)

    # ------------------------------------------------------------------
    # Menu cycles
    # ------------------------------------------------------------------
    def create_menu_cycle(self, payload, headers):
        return self._request("POST", "/menu-cycles", payload, headers)

    def list_menu_cycles(self, headers, params=None):
        return self._request("GET", "/menu-cycles", headers=headers, params=params)

    def get_menu_cycle(self, cycle_id, headers):
        return self._request("GET", f"/menu-cycles/{cycle_id}", headers=headers)

    def publish_menu_cycle(self, cycle_id, headers):
        return self._request("POST", f"/menu-cycles/{cycle_id}/publish", {}, headers)

    def archive_menu_cycle(self, cycle_id, headers):
        return self._request("POST", f"/menu-cycles/{cycle_id}/archive", {}, headers)

    # ------------------------------------------------------------------
    # Recipes
    # ------------------------------------------------------------------
    def create_recipe(self, payload, headers):
        return self._request("POST", "/recipes", payload, headers)

    def list_recipes(self, headers, params=None):
        return self._request("GET", "/recipes", headers=headers, params=params)

    def get_recipe(self, recipe_id, headers):
        return self._request("GET", f"/recipes/{recipe_id}", headers=headers)

    def patch_recipe(self, recipe_id, payload, headers):
        return self._request("PATCH", f"/recipes/{recipe_id}", payload, headers)

    def suspend_recipe(self, recipe_id, headers):
        return self._request("POST", f"/recipes/{recipe_id}/suspend", {}, headers)

    def reinstate_recipe(self, recipe_id, headers):
        return self._request("POST", f"/recipes/{recipe_id}/reinstate", {}, headers)

    # ------------------------------------------------------------------
    # Meal periods
    # ------------------------------------------------------------------
    def create_meal_period(self, payload, headers):
        return self._request("POST", "/meal-periods", payload, headers)

    def list_meal_periods(self, headers, params=None):
        return self._request("GET", "/meal-periods", headers=headers, params=params)

    def get_meal_period(self, period_id, headers):
        return self._request("GET", f"/meal-periods/{period_id}", headers=headers)

    def lock_meal_period_forecast(self, period_id, headers):
        return self._request("POST", f"/meal-periods/{period_id}/lock-forecast", {}, headers)

    def open_meal_period_service(self, period_id, headers):
        return self._request("POST", f"/meal-periods/{period_id}/open-service", {}, headers)

    def reconcile_meal_period(self, period_id, headers):
        return self._request("POST", f"/meal-periods/{period_id}/reconcile", {}, headers)

    def close_meal_period(self, period_id, headers):
        return self._request("POST", f"/meal-periods/{period_id}/close", {}, headers)

    # ------------------------------------------------------------------
    # Swipe events
    # ------------------------------------------------------------------
    def ingest_swipes(self, period_id, payload, headers):
        return self._request("POST", f"/meal-periods/{period_id}/swipes", payload, headers)

    def list_swipe_events(self, headers, params=None):
        return self._request("GET", "/swipe-events", headers=headers, params=params)

    def get_swipe_event(self, event_id, headers):
        return self._request("GET", f"/swipe-events/{event_id}", headers=headers)

    # ------------------------------------------------------------------
    # Production forecasts
    # ------------------------------------------------------------------
    def create_production_forecast(self, period_id, payload, headers):
        return self._request("POST", f"/meal-periods/{period_id}/forecasts", payload, headers)

    def list_production_forecasts(self, headers, params=None):
        return self._request("GET", "/production-forecasts", headers=headers, params=params)

    def get_production_forecast(self, forecast_id, headers):
        return self._request("GET", f"/production-forecasts/{forecast_id}", headers=headers)

    def lock_production_forecast(self, forecast_id, headers):
        return self._request("POST", f"/production-forecasts/{forecast_id}/lock", {}, headers)

    # ------------------------------------------------------------------
    # Accommodation requests
    # ------------------------------------------------------------------
    def create_accommodation_request(self, payload, headers):
        return self._request("POST", "/accommodation-requests", payload, headers)

    def list_accommodation_requests(self, headers, params=None):
        return self._request("GET", "/accommodation-requests", headers=headers, params=params)

    def get_accommodation_request(self, request_id, headers):
        return self._request("GET", f"/accommodation-requests/{request_id}", headers=headers)

    def start_accommodation_review(self, request_id, headers):
        return self._request("POST", f"/accommodation-requests/{request_id}/start-review", {}, headers)

    def request_accommodation_info(self, request_id, payload, headers):
        return self._request("POST", f"/accommodation-requests/{request_id}/request-info", payload, headers)

    def approve_accommodation_request(self, request_id, headers):
        return self._request("POST", f"/accommodation-requests/{request_id}/approve", {}, headers)

    def activate_accommodation_request(self, request_id, headers):
        return self._request("POST", f"/accommodation-requests/{request_id}/activate", {}, headers)

    def cancel_accommodation_request(self, request_id, headers):
        return self._request("POST", f"/accommodation-requests/{request_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Labor shifts
    # ------------------------------------------------------------------
    def create_labor_shift(self, payload, headers):
        return self._request("POST", "/labor-shifts", payload, headers)

    def list_labor_shifts(self, headers, params=None):
        return self._request("GET", "/labor-shifts", headers=headers, params=params)

    def get_labor_shift(self, shift_id, headers):
        return self._request("GET", f"/labor-shifts/{shift_id}", headers=headers)

    def assign_labor_shift(self, shift_id, payload, headers):
        return self._request("POST", f"/labor-shifts/{shift_id}/assign", payload, headers)

    def confirm_labor_shift(self, shift_id, headers):
        return self._request("POST", f"/labor-shifts/{shift_id}/confirm", {}, headers)

    def complete_labor_shift(self, shift_id, payload, headers):
        return self._request("POST", f"/labor-shifts/{shift_id}/complete", payload, headers)

    def mark_labor_shift_no_show(self, shift_id, headers):
        return self._request("POST", f"/labor-shifts/{shift_id}/mark-no-show", {}, headers)

    # ------------------------------------------------------------------
    # Waste logs
    # ------------------------------------------------------------------
    def create_waste_log(self, period_id, payload, headers):
        return self._request("POST", f"/meal-periods/{period_id}/waste-logs", payload, headers)

    def list_waste_logs(self, headers, params=None):
        return self._request("GET", "/waste-logs", headers=headers, params=params)

    def get_waste_log(self, log_id, headers):
        return self._request("GET", f"/waste-logs/{log_id}", headers=headers)

    def verify_waste_log(self, log_id, headers):
        return self._request("POST", f"/waste-logs/{log_id}/verify", {}, headers)

    def post_waste_log(self, log_id, headers):
        return self._request("POST", f"/waste-logs/{log_id}/post", {}, headers)

    def reject_waste_log(self, log_id, headers, payload=None):
        return self._request("POST", f"/waste-logs/{log_id}/reject", payload or {}, headers)

    # ------------------------------------------------------------------
    # Inspection reports and corrective actions
    # ------------------------------------------------------------------
    def create_inspection_report(self, payload, headers):
        return self._request("POST", "/inspection-reports", payload, headers)

    def list_inspection_reports(self, headers, params=None):
        return self._request("GET", "/inspection-reports", headers=headers, params=params)

    def get_inspection_report(self, report_id, headers):
        return self._request("GET", f"/inspection-reports/{report_id}", headers=headers)

    def submit_inspection_report(self, report_id, headers):
        return self._request("POST", f"/inspection-reports/{report_id}/submit", {}, headers)

    def acknowledge_inspection_report(self, report_id, headers):
        return self._request("POST", f"/inspection-reports/{report_id}/acknowledge", {}, headers)

    def close_inspection_report(self, report_id, headers):
        return self._request("POST", f"/inspection-reports/{report_id}/close", {}, headers)

    def add_corrective_action(self, report_id, payload, headers):
        return self._request("POST", f"/inspection-reports/{report_id}/corrective-actions",
                             payload, headers)

    def list_corrective_actions(self, headers, params=None):
        return self._request("GET", "/corrective-actions", headers=headers, params=params)

    def get_corrective_action(self, action_id, headers):
        return self._request("GET", f"/corrective-actions/{action_id}", headers=headers)

    def resolve_corrective_action(self, action_id, headers):
        return self._request("POST", f"/corrective-actions/{action_id}/resolve", {}, headers)

    def verify_corrective_action(self, action_id, headers):
        return self._request("POST", f"/corrective-actions/{action_id}/verify", {}, headers)

    def reopen_corrective_action(self, action_id, headers):
        return self._request("POST", f"/corrective-actions/{action_id}/reopen", {}, headers)

    # ------------------------------------------------------------------
    # Departments and catering orders
    # ------------------------------------------------------------------
    def create_department(self, payload, headers):
        return self._request("POST", "/departments", payload, headers)

    def get_department(self, department_id, headers):
        return self._request("GET", f"/departments/{department_id}", headers=headers)

    def create_catering_order(self, payload, headers):
        return self._request("POST", "/catering-orders", payload, headers)

    def list_catering_orders(self, headers, params=None):
        return self._request("GET", "/catering-orders", headers=headers, params=params)

    def get_catering_order(self, order_id, headers):
        return self._request("GET", f"/catering-orders/{order_id}", headers=headers)

    def submit_catering_order(self, order_id, headers):
        return self._request("POST", f"/catering-orders/{order_id}/submit", {}, headers)

    def approve_catering_order(self, order_id, payload, headers):
        return self._request("POST", f"/catering-orders/{order_id}/approve", payload, headers)

    def reject_catering_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/catering-orders/{order_id}/reject", payload or {}, headers)

    def schedule_catering_order(self, order_id, headers):
        return self._request("POST", f"/catering-orders/{order_id}/schedule", {}, headers)

    def fulfill_catering_order(self, order_id, headers):
        return self._request("POST", f"/catering-orders/{order_id}/fulfill", {}, headers)

    def invoice_catering_order(self, order_id, payload, headers):
        return self._request("POST", f"/catering-orders/{order_id}/invoice", payload, headers)

    def pay_catering_order(self, order_id, headers):
        return self._request("POST", f"/catering-orders/{order_id}/pay", {}, headers)

    def cancel_catering_order(self, order_id, headers):
        return self._request("POST", f"/catering-orders/{order_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Commission statements
    # ------------------------------------------------------------------
    def create_commission_statement(self, contract_id, payload, headers):
        return self._request("POST", f"/vendor-contracts/{contract_id}/commission-statements",
                             payload, headers)

    def list_commission_statements(self, headers, params=None):
        return self._request("GET", "/commission-statements", headers=headers, params=params)

    def get_commission_statement(self, statement_id, headers):
        return self._request("GET", f"/commission-statements/{statement_id}", headers=headers)

    def finalize_commission_statement(self, statement_id, headers):
        return self._request("POST", f"/commission-statements/{statement_id}/finalize", {}, headers)

    def dispute_commission_statement(self, statement_id, headers, payload=None):
        return self._request("POST", f"/commission-statements/{statement_id}/dispute",
                             payload or {}, headers)

    def recompute_commission_statement(self, statement_id, headers):
        return self._request("POST", f"/commission-statements/{statement_id}/recompute", {}, headers)


api_client = ApiClient()
