"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clients ----
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def update_client(self, client_id, payload, headers):
        return self._request("PATCH", f"/clients/{client_id}", payload, headers)

    def activate_client(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/activate", headers=headers)

    def discharge_client(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/discharge", headers=headers)

    def get_client_summary(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}/summary", headers=headers)

    # ---- Assessments ----
    def create_assessment(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/assessments", payload, headers)

    def list_client_assessments(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/assessments", headers=headers, params=params)

    def finalize_assessment(self, assessment_id, headers):
        return self._request("POST", f"/assessments/{assessment_id}/finalize", headers=headers)

    # ---- Meal Plans ----
    def create_meal_plan(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/meal-plans", payload, headers)

    def get_meal_plan(self, meal_plan_id, headers):
        return self._request("GET", f"/meal-plans/{meal_plan_id}", headers=headers)

    def list_meal_plans(self, headers, params=None):
        return self._request("GET", "/meal-plans", headers=headers, params=params)

    def cancel_meal_plan(self, meal_plan_id, headers):
        return self._request("POST", f"/meal-plans/{meal_plan_id}/cancel", headers=headers)

    # ---- Routes ----
    def create_route(self, payload, headers):
        return self._request("POST", "/routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/routes/{route_id}", headers=headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/routes", headers=headers, params=params)

    def assign_driver(self, route_id, payload, headers):
        return self._request("POST", f"/routes/{route_id}/assign-driver", payload, headers)

    def activate_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/activate", headers=headers)

    # ---- Volunteer Drivers ----
    def create_driver(self, payload, headers):
        return self._request("POST", "/drivers", payload, headers)

    def list_drivers(self, headers, params=None):
        return self._request("GET", "/drivers", headers=headers, params=params)

    def activate_driver(self, driver_id, headers):
        return self._request("POST", f"/drivers/{driver_id}/activate", headers=headers)

    # ---- Deliveries ----
    def create_delivery(self, payload, headers):
        return self._request("POST", "/deliveries", payload, headers)

    def get_delivery(self, delivery_id, headers):
        return self._request("GET", f"/deliveries/{delivery_id}", headers=headers)

    def list_deliveries(self, headers, params=None):
        return self._request("GET", "/deliveries", headers=headers, params=params)

    def complete_delivery(self, delivery_id, payload, headers):
        return self._request("POST", f"/deliveries/{delivery_id}/complete", payload, headers)

    def void_delivery(self, delivery_id, headers):
        return self._request("POST", f"/deliveries/{delivery_id}/void", headers=headers)

    # ---- Wellness Checks ----
    def get_wellness_check(self, wellness_check_id, headers):
        return self._request("GET", f"/wellness-checks/{wellness_check_id}", headers=headers)

    def list_wellness_checks(self, headers, params=None):
        return self._request("GET", "/wellness-checks", headers=headers, params=params)

    # ---- Welfare Alerts ----
    def get_welfare_alert(self, alert_id, headers):
        return self._request("GET", f"/welfare-alerts/{alert_id}", headers=headers)

    def list_welfare_alerts(self, headers, params=None):
        return self._request("GET", "/welfare-alerts", headers=headers, params=params)

    def acknowledge_alert(self, alert_id, headers):
        return self._request("POST", f"/welfare-alerts/{alert_id}/acknowledge", headers=headers)

    def escalate_alert(self, alert_id, headers):
        return self._request("POST", f"/welfare-alerts/{alert_id}/escalate", headers=headers)

    def resolve_alert(self, alert_id, headers):
        return self._request("POST", f"/welfare-alerts/{alert_id}/resolve", headers=headers)

    # ---- Contributions ----
    def create_contribution(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/contributions", payload, headers)

    def get_contribution(self, contribution_id, headers):
        return self._request("GET", f"/contributions/{contribution_id}", headers=headers)

    def list_contributions(self, headers, params=None):
        return self._request("GET", "/contributions", headers=headers, params=params)

    def void_contribution(self, contribution_id, headers):
        return self._request("POST", f"/contributions/{contribution_id}/void", headers=headers)

    # ---- Vacation Holds ----
    def create_vacation_hold(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/vacation-holds", payload, headers)

    def get_vacation_hold(self, hold_id, headers):
        return self._request("GET", f"/vacation-holds/{hold_id}", headers=headers)

    def list_vacation_holds(self, headers, params=None):
        return self._request("GET", "/vacation-holds", headers=headers, params=params)

    def end_vacation_hold(self, hold_id, headers):
        return self._request("POST", f"/vacation-holds/{hold_id}/end", headers=headers)


api_client = ApiClient()
