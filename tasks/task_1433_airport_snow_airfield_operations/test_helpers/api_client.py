"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- SnowEvent ---
    def create_snow_event(self, payload, headers):
        return self._request("POST", "/snow-events", payload, headers)

    def list_snow_events(self, headers, params=None):
        return self._request("GET", "/snow-events", headers=headers, params=params)

    def get_snow_event(self, event_id, headers):
        return self._request("GET", f"/snow-events/{event_id}", headers=headers)

    def event_action(self, event_id, payload, headers):
        return self._request("POST", f"/snow-events/{event_id}/event-actions",
                             payload, headers)

    def closure_action(self, event_id, payload, headers):
        return self._request("POST", f"/snow-events/{event_id}/closure-actions",
                             payload, headers)

    def get_dispatch_order(self, event_id, headers):
        return self._request("GET", f"/snow-events/{event_id}/dispatch-order",
                             headers=headers)

    def get_cost_summary(self, event_id, headers):
        return self._request("GET", f"/snow-events/{event_id}/cost-summary",
                             headers=headers)

    # --- AirfieldSurface ---
    def create_surface(self, payload, headers):
        return self._request("POST", "/airfield-surfaces", payload, headers)

    def list_surfaces(self, headers, params=None):
        return self._request("GET", "/airfield-surfaces", headers=headers,
                             params=params)

    def get_surface(self, surface_id, headers):
        return self._request("GET", f"/airfield-surfaces/{surface_id}",
                             headers=headers)

    def surface_action(self, surface_id, payload, headers):
        return self._request("POST",
                             f"/airfield-surfaces/{surface_id}/surface-actions",
                             payload, headers)

    # --- ConditionReport ---
    def create_condition_report(self, payload, headers):
        return self._request("POST", "/condition-reports", payload, headers)

    def list_condition_reports(self, headers, params=None):
        return self._request("GET", "/condition-reports", headers=headers,
                             params=params)

    def get_condition_report(self, report_id, headers):
        return self._request("GET", f"/condition-reports/{report_id}",
                             headers=headers)

    # --- FrictionAssessment ---
    def create_friction_assessment(self, payload, headers):
        return self._request("POST", "/friction-assessments", payload, headers)

    def list_friction_assessments(self, headers, params=None):
        return self._request("GET", "/friction-assessments", headers=headers,
                             params=params)

    def get_friction_assessment(self, assessment_id, headers):
        return self._request("GET", f"/friction-assessments/{assessment_id}",
                             headers=headers)

    # --- Notam ---
    def create_notam(self, payload, headers):
        return self._request("POST", "/notams", payload, headers)

    def notam_action(self, notam_id, payload, headers):
        return self._request("POST", f"/notams/{notam_id}/notam-actions",
                             payload, headers)

    def list_notams(self, headers, params=None):
        return self._request("GET", "/notams", headers=headers, params=params)

    def get_notam(self, notam_id, headers):
        return self._request("GET", f"/notams/{notam_id}", headers=headers)

    # --- ChemicalProduct ---
    def create_chemical_product(self, payload, headers):
        return self._request("POST", "/chemical-products", payload, headers)

    def list_chemical_products(self, headers, params=None):
        return self._request("GET", "/chemical-products", headers=headers,
                             params=params)

    def get_chemical_product(self, product_id, headers):
        return self._request("GET", f"/chemical-products/{product_id}",
                             headers=headers)

    # --- ChemicalApplication ---
    def create_chemical_application(self, payload, headers):
        return self._request("POST", "/chemical-applications", payload, headers)

    def application_action(self, application_id, payload, headers):
        return self._request(
            "POST", f"/chemical-applications/{application_id}/application-actions",
            payload, headers)

    def list_chemical_applications(self, headers, params=None):
        return self._request("GET", "/chemical-applications", headers=headers,
                             params=params)

    def get_chemical_application(self, application_id, headers):
        return self._request("GET", f"/chemical-applications/{application_id}",
                             headers=headers)

    # --- EquipmentUnit ---
    def create_equipment_unit(self, payload, headers):
        return self._request("POST", "/equipment-units", payload, headers)

    def equipment_readiness_action(self, unit_id, payload, headers):
        return self._request("POST",
                             f"/equipment-units/{unit_id}/readiness-actions",
                             payload, headers)

    # --- OperatorShift ---
    def create_operator_shift(self, payload, headers):
        return self._request("POST", "/operator-shifts", payload, headers)

    def shift_action(self, shift_id, payload, headers):
        return self._request("POST", f"/operator-shifts/{shift_id}/shift-actions",
                             payload, headers)

    def list_operator_shifts(self, headers, params=None):
        return self._request("GET", "/operator-shifts", headers=headers,
                             params=params)

    def get_operator_shift(self, shift_id, headers):
        return self._request("GET", f"/operator-shifts/{shift_id}",
                             headers=headers)

    # --- Logical clock (test-driving endpoint) ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
