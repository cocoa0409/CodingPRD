"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Customer accounts ---
    def create_customer_account(self, payload, headers):
        return self._request("POST", "/customer-accounts", payload, headers)

    def get_customer_account(self, customer_id, headers):
        return self._request("GET", f"/customer-accounts/{customer_id}", headers=headers)

    # --- Furnace recipes ---
    def create_furnace_recipe(self, payload, headers):
        return self._request("POST", "/furnace-recipes", payload, headers)

    def get_furnace_recipe(self, recipe_id, headers):
        return self._request("GET", f"/furnace-recipes/{recipe_id}", headers=headers)

    def approve_furnace_recipe(self, recipe_id, headers):
        return self._request("POST", f"/furnace-recipes/{recipe_id}/approve", {}, headers)

    # --- Furnaces ---
    def create_furnace(self, payload, headers):
        return self._request("POST", "/furnaces", payload, headers)

    def get_furnace(self, furnace_id, headers):
        return self._request("GET", f"/furnaces/{furnace_id}", headers=headers)

    # --- Pyrometry records ---
    def create_pyrometry_record(self, payload, headers):
        return self._request("POST", "/pyrometry-records", payload, headers)

    def list_pyrometry_records(self, headers, params=None):
        return self._request("GET", "/pyrometry-records", headers=headers, params=params)

    def get_pyrometry_record(self, record_id, headers):
        return self._request("GET", f"/pyrometry-records/{record_id}", headers=headers)

    # --- Work orders ---
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def ship_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/ship", {}, headers)

    def cancel_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/cancel", {}, headers)

    # --- Inspection tests ---
    def create_inspection_test(self, payload, headers):
        return self._request("POST", "/inspection-tests", payload, headers)

    def list_inspection_tests(self, headers, params=None):
        return self._request("GET", "/inspection-tests", headers=headers, params=params)

    def get_inspection_test(self, test_id, headers):
        return self._request("GET", f"/inspection-tests/{test_id}", headers=headers)

    # --- Disposition cases ---
    def list_disposition_cases(self, headers, params=None):
        return self._request("GET", "/disposition-cases", headers=headers, params=params)

    def get_disposition_case(self, case_id, headers):
        return self._request("GET", f"/disposition-cases/{case_id}", headers=headers)

    def decide_disposition_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/disposition-cases/{case_id}/decide", payload, headers
        )

    # --- Liability claims ---
    def list_liability_claims(self, headers, params=None):
        return self._request("GET", "/liability-claims", headers=headers, params=params)

    def get_liability_claim(self, claim_id, headers):
        return self._request("GET", f"/liability-claims/{claim_id}", headers=headers)

    def accept_liability_claim(self, claim_id, headers):
        return self._request("POST", f"/liability-claims/{claim_id}/accept", {}, headers)

    def reject_liability_claim(self, claim_id, headers):
        return self._request("POST", f"/liability-claims/{claim_id}/reject", {}, headers)

    def pay_liability_claim(self, claim_id, headers):
        return self._request("POST", f"/liability-claims/{claim_id}/pay", {}, headers)

    # --- Load batches and assignments ---
    def create_load_batch(self, payload, headers):
        return self._request("POST", "/load-batches", payload, headers)

    def list_load_batches(self, headers, params=None):
        return self._request("GET", "/load-batches", headers=headers, params=params)

    def get_load_batch(self, load_batch_id, headers):
        return self._request("GET", f"/load-batches/{load_batch_id}", headers=headers)

    def create_load_assignment(self, load_batch_id, payload, headers):
        return self._request(
            "POST", f"/load-batches/{load_batch_id}/assignments", payload, headers
        )

    def unassign_load_assignment(self, load_batch_id, assignment_id, payload, headers):
        return self._request(
            "POST",
            f"/load-batches/{load_batch_id}/assignments/{assignment_id}/unassign",
            payload,
            headers,
        )

    def list_load_assignments(self, headers, params=None):
        return self._request("GET", "/load-assignments", headers=headers, params=params)

    def get_load_assignment(self, assignment_id, headers):
        return self._request("GET", f"/load-assignments/{assignment_id}", headers=headers)

    def release_load_batch(self, load_batch_id, headers):
        return self._request("POST", f"/load-batches/{load_batch_id}/release", {}, headers)

    def start_run_load_batch(self, load_batch_id, headers):
        return self._request(
            "POST", f"/load-batches/{load_batch_id}/start-run", {}, headers
        )

    def complete_run_load_batch(self, load_batch_id, headers):
        return self._request(
            "POST", f"/load-batches/{load_batch_id}/complete-run", {}, headers
        )

    def abort_load_batch(self, load_batch_id, headers):
        return self._request("POST", f"/load-batches/{load_batch_id}/abort", {}, headers)

    # --- Thermocouple readings ---
    def create_thermocouple_reading(self, payload, headers):
        return self._request("POST", "/thermocouple-readings", payload, headers)

    def list_thermocouple_readings(self, headers, params=None):
        return self._request(
            "GET", "/thermocouple-readings", headers=headers, params=params
        )

    def get_thermocouple_reading(self, reading_id, headers):
        return self._request(
            "GET", f"/thermocouple-readings/{reading_id}", headers=headers
        )

    # --- Audit packages ---
    def create_audit_package(self, payload, headers):
        return self._request("POST", "/audit-packages", payload, headers)

    def list_audit_packages(self, headers, params=None):
        return self._request("GET", "/audit-packages", headers=headers, params=params)

    def get_audit_package(self, package_id, headers):
        return self._request("GET", f"/audit-packages/{package_id}", headers=headers)

    def issue_audit_package(self, package_id, headers):
        return self._request("POST", f"/audit-packages/{package_id}/issue", {}, headers)

    # --- Logical clock test-driving ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
