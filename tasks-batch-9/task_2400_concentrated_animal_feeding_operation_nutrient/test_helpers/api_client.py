"""API client: one method per endpoint defined in the PRD.

Every method returns the raw ``requests.Response`` so tests can assert status
codes. All paths are mounted under ``/cafo``.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/cafo"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------
    def create_operation(self, payload, headers):
        return self._request("POST", f"{PREFIX}/operations", payload, headers)

    def update_operation(self, operation_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/operations/{operation_id}", payload, headers
        )

    def get_operation(self, operation_id, headers):
        return self._request(
            "GET", f"{PREFIX}/operations/{operation_id}", headers=headers
        )

    def list_operations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/operations", headers=headers, params=params
        )

    def get_operation_nutrient_summary(self, operation_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/operations/{operation_id}/nutrient-summary",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Haulers
    # ------------------------------------------------------------------
    def create_hauler(self, payload, headers):
        return self._request("POST", f"{PREFIX}/haulers", payload, headers)

    def get_hauler(self, hauler_id, headers):
        return self._request("GET", f"{PREFIX}/haulers/{hauler_id}", headers=headers)

    def list_haulers(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/haulers", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Permits
    # ------------------------------------------------------------------
    def create_permit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/permits", payload, headers)

    def submit_permit(self, permit_id, headers):
        return self._request(
            "POST", f"{PREFIX}/permits/{permit_id}/submit", headers=headers
        )

    def issue_permit_coverage(self, permit_id, headers):
        return self._request(
            "POST", f"{PREFIX}/permits/{permit_id}/issue-coverage", headers=headers
        )

    def initiate_permit_renewal(self, permit_id, headers):
        return self._request(
            "POST", f"{PREFIX}/permits/{permit_id}/initiate-renewal", headers=headers
        )

    def complete_permit_renewal(self, permit_id, headers):
        return self._request(
            "POST", f"{PREFIX}/permits/{permit_id}/complete-renewal", headers=headers
        )

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"{PREFIX}/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/permits", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Nutrient management plans
    # ------------------------------------------------------------------
    def create_nutrient_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/nutrient-plans", payload, headers)

    def update_nutrient_plan(self, plan_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/nutrient-plans/{plan_id}", payload, headers
        )

    def certify_nutrient_plan(self, plan_id, headers):
        return self._request(
            "POST", f"{PREFIX}/nutrient-plans/{plan_id}/certify", headers=headers
        )

    def submit_nutrient_plan(self, plan_id, headers):
        return self._request(
            "POST", f"{PREFIX}/nutrient-plans/{plan_id}/submit", headers=headers
        )

    def approve_nutrient_plan(self, plan_id, headers):
        return self._request(
            "POST", f"{PREFIX}/nutrient-plans/{plan_id}/approve", headers=headers
        )

    def require_plan_revision(self, plan_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/nutrient-plans/{plan_id}/require-revision",
            headers=headers,
        )

    def get_nutrient_plan(self, plan_id, headers):
        return self._request(
            "GET", f"{PREFIX}/nutrient-plans/{plan_id}", headers=headers
        )

    def list_nutrient_plans(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/nutrient-plans", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Fields
    # ------------------------------------------------------------------
    def create_field(self, payload, headers):
        return self._request("POST", f"{PREFIX}/fields", payload, headers)

    def get_field(self, field_id, headers):
        return self._request("GET", f"{PREFIX}/fields/{field_id}", headers=headers)

    def list_fields(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/fields", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Soil tests
    # ------------------------------------------------------------------
    def create_soil_test(self, payload, headers):
        return self._request("POST", f"{PREFIX}/soil-tests", payload, headers)

    def get_soil_test(self, soil_test_id, headers):
        return self._request(
            "GET", f"{PREFIX}/soil-tests/{soil_test_id}", headers=headers
        )

    def list_soil_tests(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/soil-tests", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Field nutrient budgets
    # ------------------------------------------------------------------
    def create_field_budget(self, payload, headers):
        return self._request("POST", f"{PREFIX}/field-budgets", payload, headers)

    def get_field_budget(self, budget_id, headers):
        return self._request(
            "GET", f"{PREFIX}/field-budgets/{budget_id}", headers=headers
        )

    def list_field_budgets(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/field-budgets", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Manure storage structures
    # ------------------------------------------------------------------
    def create_manure_storage(self, payload, headers):
        return self._request("POST", f"{PREFIX}/manure-storages", payload, headers)

    def record_storage_intake(self, storage_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/manure-storages/{storage_id}/intake", payload, headers
        )

    def return_storage_to_service(self, storage_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/manure-storages/{storage_id}/return-to-service",
            headers=headers,
        )

    def get_manure_storage(self, storage_id, headers):
        return self._request(
            "GET", f"{PREFIX}/manure-storages/{storage_id}", headers=headers
        )

    def list_manure_storages(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/manure-storages", headers=headers, params=params
        )

    def get_storage_capacity_projection(self, storage_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/manure-storages/{storage_id}/capacity-projection",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Storage inspections
    # ------------------------------------------------------------------
    def create_storage_inspection(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/storage-inspections", payload, headers
        )

    def get_storage_inspection(self, storage_inspection_id, headers):
        return self._request(
            "GET",
            f"{PREFIX}/storage-inspections/{storage_inspection_id}",
            headers=headers,
        )

    def list_storage_inspections(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/storage-inspections", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Land application records
    # ------------------------------------------------------------------
    def create_application_event(self, payload, headers):
        return self._request("POST", f"{PREFIX}/application-events", payload, headers)

    def verify_application_event(self, event_id, headers):
        return self._request(
            "POST", f"{PREFIX}/application-events/{event_id}/verify", headers=headers
        )

    def void_application_event(self, event_id, headers):
        return self._request(
            "POST", f"{PREFIX}/application-events/{event_id}/void", headers=headers
        )

    def get_application_event(self, event_id, headers):
        return self._request(
            "GET", f"{PREFIX}/application-events/{event_id}", headers=headers
        )

    def list_application_events(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/application-events", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Manure transfers
    # ------------------------------------------------------------------
    def create_manure_transfer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/manure-transfers", payload, headers)

    def acknowledge_manure_transfer(self, transfer_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/manure-transfers/{transfer_id}/acknowledge",
            headers=headers,
        )

    def complete_manure_transfer(self, transfer_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/manure-transfers/{transfer_id}/complete",
            headers=headers,
        )

    def cancel_manure_transfer(self, transfer_id, headers):
        return self._request(
            "POST", f"{PREFIX}/manure-transfers/{transfer_id}/cancel", headers=headers
        )

    def resume_manure_transfer(self, transfer_id, headers):
        return self._request(
            "POST", f"{PREFIX}/manure-transfers/{transfer_id}/resume", headers=headers
        )

    def get_manure_transfer(self, transfer_id, headers):
        return self._request(
            "GET", f"{PREFIX}/manure-transfers/{transfer_id}", headers=headers
        )

    def list_manure_transfers(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/manure-transfers", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Incident reports
    # ------------------------------------------------------------------
    def create_incident_report(self, payload, headers):
        return self._request("POST", f"{PREFIX}/incident-reports", payload, headers)

    def record_oral_notification(self, incident_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/incident-reports/{incident_id}/record-oral-notification",
            headers=headers,
        )

    def submit_written_report(self, incident_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/incident-reports/{incident_id}/submit-written-report",
            headers=headers,
        )

    def close_incident_report(self, incident_id, headers):
        return self._request(
            "POST", f"{PREFIX}/incident-reports/{incident_id}/close", headers=headers
        )

    def get_incident_report(self, incident_id, headers):
        return self._request(
            "GET", f"{PREFIX}/incident-reports/{incident_id}", headers=headers
        )

    def list_incident_reports(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/incident-reports", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Agency inspections
    # ------------------------------------------------------------------
    def create_inspection(self, payload, headers):
        return self._request("POST", f"{PREFIX}/inspections", payload, headers)

    def conduct_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/inspections/{inspection_id}/conduct", payload, headers
        )

    def issue_nov(self, inspection_id, headers):
        return self._request(
            "POST", f"{PREFIX}/inspections/{inspection_id}/issue-nov", headers=headers
        )

    def submit_inspection_response(self, inspection_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/inspections/{inspection_id}/submit-response",
            payload,
            headers,
        )

    def close_inspection(self, inspection_id, headers):
        return self._request(
            "POST", f"{PREFIX}/inspections/{inspection_id}/close", headers=headers
        )

    def get_inspection(self, inspection_id, headers):
        return self._request(
            "GET", f"{PREFIX}/inspections/{inspection_id}", headers=headers
        )

    def list_inspections(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/inspections", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Annual reports
    # ------------------------------------------------------------------
    def create_annual_report(self, payload, headers):
        return self._request("POST", f"{PREFIX}/annual-reports", payload, headers)

    def submit_annual_report(self, report_id, headers):
        return self._request(
            "POST", f"{PREFIX}/annual-reports/{report_id}/submit", headers=headers
        )

    def accept_annual_report(self, report_id, headers):
        return self._request(
            "POST", f"{PREFIX}/annual-reports/{report_id}/accept", headers=headers
        )

    def return_annual_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/annual-reports/{report_id}/return", payload, headers
        )

    def get_annual_report(self, report_id, headers):
        return self._request(
            "GET", f"{PREFIX}/annual-reports/{report_id}", headers=headers
        )

    def list_annual_reports(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/annual-reports", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST",
            f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )


api_client = ApiClient()
