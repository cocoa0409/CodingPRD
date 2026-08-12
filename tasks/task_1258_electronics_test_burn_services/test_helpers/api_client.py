"""API client: one method per endpoint declared in PRD §4."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Electronics Test & Burn-In Services API.

    All endpoints are mounted under the /api prefix (PRD §2).
    """

    # --- Logical clock (PRD §2.5) ---
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- Customers ---
    def create_customer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/customers", payload, headers)

    def get_customer(self, customer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/customers/{customer_id}", headers=headers)

    def patch_customer(self, customer_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/api/customers/{customer_id}", payload, headers)

    # --- Test programs ---
    def create_test_program(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/test-programs", payload, headers)

    def get_test_program(self, program_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/test-programs/{program_id}", headers=headers)

    def list_test_programs(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/test-programs", headers=headers, params=params)

    def validate_program(self, program_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/test-programs/{program_id}/validate", {}, headers)

    def release_program(self, program_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/test-programs/{program_id}/release", {}, headers)

    def create_program_revision(self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/test-programs/{program_id}/revisions", payload, headers)

    # --- Fixtures ---
    def create_fixture(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/fixtures", payload, headers)

    def get_fixture(self, fixture_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/fixtures/{fixture_id}", headers=headers)

    def list_fixtures(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/fixtures", headers=headers, params=params)

    def commission_fixture(self, fixture_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/fixtures/{fixture_id}/commission", {}, headers)

    def fixture_maintenance(self, fixture_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/fixtures/{fixture_id}/maintenance", {}, headers)

    def fixture_return_from_maintenance(self, fixture_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/fixtures/{fixture_id}/return-from-maintenance", {}, headers)

    # --- Chambers ---
    def create_chamber(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/chambers", payload, headers)

    def get_chamber(self, chamber_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/chambers/{chamber_id}", headers=headers)

    def patch_chamber(self, chamber_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/api/chambers/{chamber_id}", payload, headers)

    def get_chamber_utilization(self, chamber_id: str, params: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "GET", f"/api/chambers/{chamber_id}/utilization", headers=headers, params=params
        )

    # --- Chamber reservations ---
    def create_chamber_reservation(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/chamber-reservations", payload, headers)

    def get_chamber_reservation(self, reservation_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/chamber-reservations/{reservation_id}", headers=headers)

    def list_chamber_reservations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/chamber-reservations", headers=headers, params=params)

    def reschedule_reservation(self, reservation_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/api/chamber-reservations/{reservation_id}", payload, headers)

    def start_reservation(self, reservation_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/chamber-reservations/{reservation_id}/start", {}, headers)

    def complete_reservation(self, reservation_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/chamber-reservations/{reservation_id}/complete", {}, headers)

    def cancel_reservation(self, reservation_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/chamber-reservations/{reservation_id}/cancel", {}, headers)

    # --- Lots ---
    def create_lot(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/lots", payload, headers)

    def get_lot(self, lot_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/lots/{lot_id}", headers=headers)

    def list_lots(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/lots", headers=headers, params=params)

    def enqueue_lot(self, lot_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/lots/{lot_id}/enqueue", {}, headers)

    def start_test_lot(self, lot_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/lots/{lot_id}/start-test", {}, headers)

    def complete_test_lot(self, lot_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/lots/{lot_id}/complete-test", {}, headers)

    def ship_lot(self, lot_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/lots/{lot_id}/ship", {}, headers)

    def get_yield_report(self, lot_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/lots/{lot_id}/yield-report", headers=headers)

    # --- Units ---
    def create_unit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/units", payload, headers)

    def get_unit(self, unit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/units/{unit_id}", headers=headers)

    def list_units(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/units", headers=headers, params=params)

    # --- Test results ---
    def create_test_result(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/test-results", payload, headers)

    def get_test_result(self, result_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/test-results/{result_id}", headers=headers)

    def list_test_results(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/test-results", headers=headers, params=params)

    def void_test_result(self, result_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/test-results/{result_id}/void", payload, headers)

    # --- Retest authorizations ---
    def create_retest_authorization(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/retest-authorizations", payload, headers)

    def get_retest_authorization(self, authorization_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/retest-authorizations/{authorization_id}", headers=headers)

    def list_retest_authorizations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/retest-authorizations", headers=headers, params=params)

    def revoke_retest_authorization(self, authorization_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/api/retest-authorizations/{authorization_id}/revoke", {}, headers
        )

    # --- Customer equipment ---
    def create_customer_equipment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/customer-equipment", payload, headers)

    def get_customer_equipment(self, equipment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/customer-equipment/{equipment_id}", headers=headers)

    def list_customer_equipment(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/customer-equipment", headers=headers, params=params)

    def return_customer_equipment(self, equipment_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/customer-equipment/{equipment_id}/return", {}, headers)

    # --- Maintenance orders ---
    def create_maintenance_order(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/maintenance-orders", payload, headers)

    def get_maintenance_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/maintenance-orders/{order_id}", headers=headers)

    def list_maintenance_orders(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/maintenance-orders", headers=headers, params=params)

    def start_maintenance_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/maintenance-orders/{order_id}/start", {}, headers)

    def complete_maintenance_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/maintenance-orders/{order_id}/complete", {}, headers)

    def cancel_maintenance_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/maintenance-orders/{order_id}/cancel", {}, headers)

    # --- ESD audits ---
    def create_esd_audit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/esd-audits", payload, headers)

    def get_esd_audit(self, audit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/esd-audits/{audit_id}", headers=headers)

    def list_esd_audits(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/esd-audits", headers=headers, params=params)

    def close_esd_audit(self, audit_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/esd-audits/{audit_id}/close", payload, headers)

    # --- RMA cases ---
    def create_rma_case(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/rma-cases", payload, headers)

    def get_rma_case(self, rma_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/rma-cases/{rma_id}", headers=headers)

    def list_rma_cases(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/rma-cases", headers=headers, params=params)

    def start_rma_fa(self, rma_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/rma-cases/{rma_id}/start-fa", {}, headers)

    def complete_rma_fa(self, rma_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/rma-cases/{rma_id}/complete-fa", payload, headers)

    def close_rma_case(self, rma_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/rma-cases/{rma_id}/close", {}, headers)

    # --- Lot disposition reviews ---
    def create_lot_disposition_review(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/lot-disposition-reviews", payload, headers)

    def get_lot_disposition_review(self, review_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/lot-disposition-reviews/{review_id}", headers=headers)

    def list_lot_disposition_reviews(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/lot-disposition-reviews", headers=headers, params=params)

    def decide_lot_disposition_review(self, review_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/api/lot-disposition-reviews/{review_id}/decide", payload, headers
        )


api_client = ApiClient()
