"""API client: one method per endpoint the PRD defines."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/nutrition"


class ApiClient(GenericApiClient):
    # --- Logical clock ------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Wards --------------------------------------------------------------
    def create_ward(self, payload, headers):
        return self._request("POST", f"{PREFIX}/wards", payload, headers)

    def list_wards(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/wards", headers=headers, params=params)

    def get_ward(self, ward_id, headers):
        return self._request("GET", f"{PREFIX}/wards/{ward_id}", headers=headers)

    def update_ward(self, ward_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/wards/{ward_id}", payload, headers)

    # --- Patients -----------------------------------------------------------
    def create_patient(self, payload, headers):
        return self._request("POST", f"{PREFIX}/patients", payload, headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/patients", headers=headers, params=params)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"{PREFIX}/patients/{patient_id}", headers=headers)

    def update_patient(self, patient_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/patients/{patient_id}", payload, headers)

    def discharge_patient(self, patient_id, headers):
        return self._request(
            "POST", f"{PREFIX}/patients/{patient_id}/discharge", {}, headers
        )

    # --- Therapeutic diet rules --------------------------------------------
    def create_diet_rule(self, payload, headers):
        return self._request("POST", f"{PREFIX}/diet-rules", payload, headers)

    def list_diet_rules(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/diet-rules", headers=headers, params=params)

    def get_diet_rule(self, rule_id, headers):
        return self._request("GET", f"{PREFIX}/diet-rules/{rule_id}", headers=headers)

    def update_diet_rule(self, rule_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/diet-rules/{rule_id}", payload, headers)

    # --- Diet orders --------------------------------------------------------
    def create_diet_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/diet-orders", payload, headers)

    def list_diet_orders(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/diet-orders", headers=headers, params=params
        )

    def get_diet_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/diet-orders/{order_id}", headers=headers)

    def submit_diet_order(self, order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/diet-orders/{order_id}/submit", {}, headers
        )

    def request_diet_order_revision(self, order_id, revision_note, headers):
        return self._request(
            "POST",
            f"{PREFIX}/diet-orders/{order_id}/request-revision",
            {"revision_note": revision_note},
            headers,
        )

    def cosign_diet_order(self, order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/diet-orders/{order_id}/cosign", {}, headers
        )

    def discontinue_diet_order(self, order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/diet-orders/{order_id}/discontinue", {}, headers
        )

    # --- Meal periods -------------------------------------------------------
    def create_meal_period(self, payload, headers):
        return self._request("POST", f"{PREFIX}/meal-periods", payload, headers)

    def list_meal_periods(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/meal-periods", headers=headers, params=params
        )

    def get_meal_period(self, period_id, headers):
        return self._request("GET", f"{PREFIX}/meal-periods/{period_id}", headers=headers)

    def lock_forecast(self, period_id, forecast_variant, headers):
        return self._request(
            "POST",
            f"{PREFIX}/meal-periods/{period_id}/lock-forecast",
            {"forecast_variant": forecast_variant},
            headers,
        )

    def open_service(self, period_id, headers):
        return self._request(
            "POST", f"{PREFIX}/meal-periods/{period_id}/open-service", {}, headers
        )

    def close_meal_period(self, period_id, headers):
        return self._request(
            "POST", f"{PREFIX}/meal-periods/{period_id}/close", {}, headers
        )

    # --- Menu items ---------------------------------------------------------
    def create_menu_item(self, payload, headers):
        return self._request("POST", f"{PREFIX}/menu-items", payload, headers)

    def list_menu_items(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/menu-items", headers=headers, params=params)

    def get_menu_item(self, item_id, headers):
        return self._request("GET", f"{PREFIX}/menu-items/{item_id}", headers=headers)

    def update_menu_item(self, item_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/menu-items/{item_id}", payload, headers)

    # --- Meal orders --------------------------------------------------------
    def create_meal_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/meal-orders", payload, headers)

    def list_meal_orders(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/meal-orders", headers=headers, params=params
        )

    def get_meal_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/meal-orders/{order_id}", headers=headers)

    def validate_meal_order(self, order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/meal-orders/{order_id}/validate", {}, headers
        )

    def start_production(self, order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/meal-orders/{order_id}/start-production", {}, headers
        )

    def plate_meal_order(self, order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/meal-orders/{order_id}/plate", {}, headers
        )

    def accuracy_check(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/meal-orders/{order_id}/accuracy-check", payload, headers
        )

    def temperature_check(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/meal-orders/{order_id}/temperature-check", payload, headers
        )

    def deliver_meal_order(self, order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/meal-orders/{order_id}/deliver", {}, headers
        )

    def cancel_meal_order(self, order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/meal-orders/{order_id}/cancel", {}, headers
        )

    # --- Meal order lines ---------------------------------------------------
    def list_meal_order_lines(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/meal-order-lines", headers=headers, params=params
        )

    def get_meal_order_line(self, line_id, headers):
        return self._request(
            "GET", f"{PREFIX}/meal-order-lines/{line_id}", headers=headers
        )

    def substitute_line(self, order_id, line_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/meal-orders/{order_id}/lines/{line_id}/substitute",
            payload,
            headers,
        )

    # --- Procedure holds ----------------------------------------------------
    def create_procedure_hold(self, payload, headers):
        return self._request("POST", f"{PREFIX}/procedure-holds", payload, headers)

    def list_procedure_holds(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/procedure-holds", headers=headers, params=params
        )

    def get_procedure_hold(self, hold_id, headers):
        return self._request(
            "GET", f"{PREFIX}/procedure-holds/{hold_id}", headers=headers
        )

    def activate_procedure_hold(self, hold_id, headers):
        return self._request(
            "POST", f"{PREFIX}/procedure-holds/{hold_id}/activate", {}, headers
        )

    def release_procedure_hold(self, hold_id, headers):
        return self._request(
            "POST", f"{PREFIX}/procedure-holds/{hold_id}/release", {}, headers
        )

    def cancel_procedure_hold(self, hold_id, headers):
        return self._request(
            "POST", f"{PREFIX}/procedure-holds/{hold_id}/cancel", {}, headers
        )

    # --- Nutrition consults -------------------------------------------------
    def create_consult(self, payload, headers):
        return self._request("POST", f"{PREFIX}/nutrition-consults", payload, headers)

    def list_consults(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/nutrition-consults", headers=headers, params=params
        )

    def get_consult(self, consult_id, headers):
        return self._request(
            "GET", f"{PREFIX}/nutrition-consults/{consult_id}", headers=headers
        )

    def assign_consult(self, consult_id, dietitian_user_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/nutrition-consults/{consult_id}/assign",
            {"dietitian_user_id": dietitian_user_id},
            headers,
        )

    def assess_consult(self, consult_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/nutrition-consults/{consult_id}/assess", payload, headers
        )

    def sign_consult(self, consult_id, headers):
        return self._request(
            "POST", f"{PREFIX}/nutrition-consults/{consult_id}/sign", {}, headers
        )

    def cancel_consult(self, consult_id, headers):
        return self._request(
            "POST", f"{PREFIX}/nutrition-consults/{consult_id}/cancel", {}, headers
        )

    # --- Supplement orders --------------------------------------------------
    def create_supplement_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/supplement-orders", payload, headers)

    def list_supplement_orders(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/supplement-orders", headers=headers, params=params
        )

    def get_supplement_order(self, order_id, headers):
        return self._request(
            "GET", f"{PREFIX}/supplement-orders/{order_id}", headers=headers
        )

    def activate_supplement_order(self, order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/supplement-orders/{order_id}/activate", {}, headers
        )

    def cancel_supplement_order(self, order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/supplement-orders/{order_id}/cancel", {}, headers
        )

    # --- Satisfaction surveys -----------------------------------------------
    def create_survey(self, payload, headers):
        return self._request("POST", f"{PREFIX}/satisfaction-surveys", payload, headers)

    def list_surveys(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/satisfaction-surveys", headers=headers, params=params
        )

    def get_survey(self, survey_id, headers):
        return self._request(
            "GET", f"{PREFIX}/satisfaction-surveys/{survey_id}", headers=headers
        )


api_client = ApiClient()
