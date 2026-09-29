"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (PRD §2.5) ------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- meal programs -----------------------------------------------------
    def create_meal_program(self, payload, headers):
        return self._request("POST", "/meal-programs", payload, headers)

    def get_meal_program(self, program_id, headers):
        return self._request("GET", f"/meal-programs/{program_id}", headers=headers)

    def patch_meal_program(self, program_id, payload, headers):
        return self._request("PATCH", f"/meal-programs/{program_id}", payload, headers)

    def create_employee_group(self, program_id, payload, headers):
        return self._request(
            "POST", f"/meal-programs/{program_id}/employee-groups", payload, headers
        )

    def list_employee_groups(self, program_id, headers, params=None):
        return self._request(
            "GET",
            f"/meal-programs/{program_id}/employee-groups",
            headers=headers,
            params=params,
        )

    def create_delivery_location(self, program_id, payload, headers):
        return self._request(
            "POST", f"/meal-programs/{program_id}/delivery-locations", payload, headers
        )

    def list_delivery_locations(self, program_id, headers, params=None):
        return self._request(
            "GET",
            f"/meal-programs/{program_id}/delivery-locations",
            headers=headers,
            params=params,
        )

    def list_eligible_restaurants(self, program_id, headers, params=None):
        return self._request(
            "GET",
            f"/meal-programs/{program_id}/eligible-restaurants",
            headers=headers,
            params=params,
        )

    def get_forecast(self, program_id, headers, params=None):
        return self._request(
            "GET", f"/meal-programs/{program_id}/forecast", headers=headers, params=params
        )

    def create_expense_export(self, program_id, payload, headers):
        return self._request(
            "POST", f"/meal-programs/{program_id}/expense-exports", payload, headers
        )

    def list_expense_exports(self, program_id, headers, params=None):
        return self._request(
            "GET",
            f"/meal-programs/{program_id}/expense-exports",
            headers=headers,
            params=params,
        )

    def acknowledge_expense_export(self, export_id, headers):
        return self._request(
            "POST", f"/expense-exports/{export_id}/acknowledge", None, headers
        )

    # --- employee groups / budget rules ------------------------------------
    def get_employee_group(self, group_id, headers):
        return self._request("GET", f"/employee-groups/{group_id}", headers=headers)

    def create_budget_rule(self, group_id, payload, headers):
        return self._request(
            "POST", f"/employee-groups/{group_id}/budget-rules", payload, headers
        )

    def list_budget_rules(self, group_id, headers, params=None):
        return self._request(
            "GET",
            f"/employee-groups/{group_id}/budget-rules",
            headers=headers,
            params=params,
        )

    def activate_budget_rule(self, rule_id, payload, headers):
        return self._request(
            "POST", f"/budget-rules/{rule_id}/activate", payload, headers
        )

    # --- employees ---------------------------------------------------------
    def create_employee(self, payload, headers):
        return self._request("POST", "/employees", payload, headers)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/employees/{employee_id}", headers=headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/employees", headers=headers, params=params)

    def deactivate_employee(self, employee_id, headers):
        return self._request(
            "POST", f"/employees/{employee_id}/deactivate", None, headers
        )

    def list_imputed_income_records(self, employee_id, headers, params=None):
        return self._request(
            "GET",
            f"/employees/{employee_id}/imputed-income-records",
            headers=headers,
            params=params,
        )

    # --- restaurants -------------------------------------------------------
    def create_restaurant(self, payload, headers):
        return self._request("POST", "/restaurants", payload, headers)

    def get_restaurant(self, restaurant_id, headers):
        return self._request("GET", f"/restaurants/{restaurant_id}", headers=headers)

    def patch_restaurant(self, restaurant_id, payload, headers):
        return self._request("PATCH", f"/restaurants/{restaurant_id}", payload, headers)

    # --- benefit periods ---------------------------------------------------
    def create_benefit_period(self, payload, headers):
        return self._request("POST", "/benefit-periods", payload, headers)

    def get_benefit_period(self, period_id, headers):
        return self._request("GET", f"/benefit-periods/{period_id}", headers=headers)

    def list_benefit_periods(self, headers, params=None):
        return self._request("GET", "/benefit-periods", headers=headers, params=params)

    def close_benefit_period(self, period_id, payload, headers):
        return self._request(
            "POST", f"/benefit-periods/{period_id}/close", payload, headers
        )

    # --- orders ------------------------------------------------------------
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def place_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/place", payload, headers)

    def confirm_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/confirm", None, headers)

    def deliver_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/deliver", None, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", None, headers)

    def list_order_refund_entries(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/orders/{order_id}/refund-entries", headers=headers, params=params
        )

    # --- group orders ------------------------------------------------------
    def create_group_order(self, payload, headers):
        return self._request("POST", "/group-orders", payload, headers)

    def get_group_order(self, group_order_id, headers):
        return self._request("GET", f"/group-orders/{group_order_id}", headers=headers)

    def list_group_orders(self, headers, params=None):
        return self._request("GET", "/group-orders", headers=headers, params=params)

    def lock_group_order(self, group_order_id, headers):
        return self._request(
            "POST", f"/group-orders/{group_order_id}/lock", None, headers
        )

    def reopen_group_order(self, group_order_id, headers):
        return self._request(
            "POST", f"/group-orders/{group_order_id}/reopen", None, headers
        )

    def submit_group_order(self, group_order_id, headers):
        return self._request(
            "POST", f"/group-orders/{group_order_id}/submit", None, headers
        )

    def cancel_group_order(self, group_order_id, headers):
        return self._request(
            "POST", f"/group-orders/{group_order_id}/cancel", None, headers
        )

    # --- credit claims -----------------------------------------------------
    def create_credit_claim(self, payload, headers):
        return self._request("POST", "/credit-claims", payload, headers)

    def get_credit_claim(self, claim_id, headers):
        return self._request("GET", f"/credit-claims/{claim_id}", headers=headers)

    def list_credit_claims(self, headers, params=None):
        return self._request("GET", "/credit-claims", headers=headers, params=params)

    def resolve_credit_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/credit-claims/{claim_id}/resolve", payload, headers
        )

    def settle_credit_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/credit-claims/{claim_id}/settle", None, headers
        )

    def list_claim_refund_entries(self, claim_id, headers, params=None):
        return self._request(
            "GET",
            f"/credit-claims/{claim_id}/refund-entries",
            headers=headers,
            params=params,
        )


api_client = ApiClient()
