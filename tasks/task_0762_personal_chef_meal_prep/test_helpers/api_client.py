"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Client ----
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def cancel_client(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/cancel", {}, headers)

    # ---- Chef ----
    def create_chef(self, payload, headers):
        return self._request("POST", "/chefs", payload, headers)

    # ---- DietaryPlan ----
    def create_dietary_plan(self, payload, headers):
        return self._request("POST", "/dietary-plans", payload, headers)

    def get_dietary_plan(self, plan_id, headers):
        return self._request("GET", f"/dietary-plans/{plan_id}", headers=headers)

    def list_dietary_plans(self, headers, params=None):
        return self._request("GET", "/dietary-plans", headers=headers, params=params)

    # ---- WeeklyMenu ----
    def create_weekly_menu(self, payload, headers):
        return self._request("POST", "/weekly-menus", payload, headers)

    def get_weekly_menu(self, menu_id, headers):
        return self._request("GET", f"/weekly-menus/{menu_id}", headers=headers)

    def list_weekly_menus(self, headers, params=None):
        return self._request("GET", "/weekly-menus", headers=headers, params=params)

    def propose_menu(self, menu_id, headers):
        return self._request("POST", f"/weekly-menus/{menu_id}/propose", {}, headers)

    def reject_menu(self, menu_id, headers):
        return self._request("POST", f"/weekly-menus/{menu_id}/reject", {}, headers)

    def approve_menu(self, menu_id, headers):
        return self._request("POST", f"/weekly-menus/{menu_id}/approve", {}, headers)

    def skip_menu(self, menu_id, headers):
        return self._request("POST", f"/weekly-menus/{menu_id}/skip", {}, headers)

    def resume_menu(self, menu_id, headers):
        return self._request("POST", f"/weekly-menus/{menu_id}/resume", {}, headers)

    # ---- MenuMeal ----
    def create_menu_meal(self, payload, headers):
        return self._request("POST", "/menu-meals", payload, headers)

    def get_menu_meal(self, meal_id, headers):
        return self._request("GET", f"/menu-meals/{meal_id}", headers=headers)

    def list_menu_meals(self, headers, params=None):
        return self._request("GET", "/menu-meals", headers=headers, params=params)

    def substitute_ingredient(self, meal_id, payload, headers):
        return self._request("POST", f"/menu-meals/{meal_id}/substitute", payload, headers)

    def feedback_meal(self, meal_id, payload, headers):
        return self._request("POST", f"/menu-meals/{meal_id}/feedback", payload, headers)

    # ---- CookSession ----
    def create_cook_session(self, payload, headers):
        return self._request("POST", "/cook-sessions", payload, headers)

    def get_cook_session(self, session_id, headers):
        return self._request("GET", f"/cook-sessions/{session_id}", headers=headers)

    def list_cook_sessions(self, headers, params=None):
        return self._request("GET", "/cook-sessions", headers=headers, params=params)

    def start_session(self, session_id, headers):
        return self._request("POST", f"/cook-sessions/{session_id}/start", {}, headers)

    def complete_session(self, session_id, headers):
        return self._request("POST", f"/cook-sessions/{session_id}/complete", {}, headers)

    def no_show_session(self, session_id, headers):
        return self._request("POST", f"/cook-sessions/{session_id}/no-show", {}, headers)

    # ---- Container ----
    def get_container(self, container_id, headers):
        return self._request("GET", f"/containers/{container_id}", headers=headers)

    def list_containers(self, headers, params=None):
        return self._request("GET", "/containers", headers=headers, params=params)

    # ---- BillingInvoice ----
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/billing-invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/billing-invoices", headers=headers, params=params)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/billing-invoices/{invoice_id}/pay", {}, headers)

    # ---- Clock (test-driving) ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
