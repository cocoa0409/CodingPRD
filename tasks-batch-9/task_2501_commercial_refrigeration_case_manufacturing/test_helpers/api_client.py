"""API client: one method per endpoint defined in PRD §4."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Commercial Refrigeration Case Manufacturing API."""

    # ─── Reference data seeding (PRD §3.1) ──────────────────────────────

    def create_refrigerant(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/refrigerants", payload, headers)

    def create_energy_standard(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/energy-standards", payload, headers)

    def create_test_chamber(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/test-chambers", payload, headers)

    def create_install_crew(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/install-crews", payload, headers)

    def create_part_inventory(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/part-inventories", payload, headers)

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Case design (PRD §3.2, §3.5) ───────────────────────────────────

    def create_case_model(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/case-models", payload, headers)

    def run_airflow_model(self, case_model_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/case-models/{case_model_id}/airflow-model", {}, headers
        )

    def submit_case_model_for_test(self, case_model_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/case-models/{case_model_id}/submit-for-test", {}, headers
        )

    def open_engineering_change(
        self, case_model_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/case-models/{case_model_id}/engineering-change", payload, headers
        )

    def get_case_model(self, case_model_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/case-models/{case_model_id}", headers=headers)

    def list_case_models(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/case-models", headers=headers, params=params)

    # ─── Chamber scheduling and energy testing (PRD §3.3) ───────────────

    def create_energy_test(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/energy-tests", payload, headers)

    def start_energy_test(self, energy_test_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/energy-tests/{energy_test_id}/start", {}, headers
        )

    def complete_energy_test(
        self, energy_test_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/energy-tests/{energy_test_id}/complete", payload, headers
        )

    def get_energy_test(self, energy_test_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/energy-tests/{energy_test_id}", headers=headers)

    def list_energy_tests(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/energy-tests", headers=headers, params=params)

    # ─── Certification and labelling (PRD §3.4) ─────────────────────────

    def create_compliance_label(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/compliance-labels", payload, headers)

    def revoke_compliance_label(
        self, label_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/compliance-labels/{label_id}/revoke", payload, headers
        )

    def get_compliance_label(self, label_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/compliance-labels/{label_id}", headers=headers)

    def list_compliance_labels(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/compliance-labels", headers=headers, params=params)

    # ─── Store plans (PRD §3.6) ─────────────────────────────────────────

    def create_store_plan(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/store-plans", payload, headers)

    def add_store_plan_line(
        self, store_plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/store-plans/{store_plan_id}/lines", payload, headers
        )

    def price_store_plan(self, store_plan_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/store-plans/{store_plan_id}/price", {}, headers)

    def approve_store_plan(self, store_plan_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/store-plans/{store_plan_id}/approve", {}, headers
        )

    def release_store_plan(self, store_plan_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/store-plans/{store_plan_id}/release", {}, headers
        )

    def get_store_plan(self, store_plan_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/store-plans/{store_plan_id}", headers=headers)

    def get_store_plan_line(self, line_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/store-plan-lines/{line_id}", headers=headers)

    def list_store_plan_lines(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/store-plan-lines", headers=headers, params=params)

    # ─── Plant release and fabrication (PRD §3.7) ───────────────────────

    def advance_work_order(self, work_order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/advance", {}, headers
        )

    def record_qa_result(
        self, work_order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/qa-result", payload, headers
        )

    def get_work_order(self, work_order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def list_work_orders(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    # ─── Shipments and installation (PRD §3.8) ──────────────────────────

    def create_shipment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/shipments", payload, headers)

    def advance_shipment(self, shipment_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/shipments/{shipment_id}/advance", {}, headers)

    def cancel_shipment(
        self, shipment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/shipments/{shipment_id}/cancel", payload, headers
        )

    def handoff_shipment(
        self, shipment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/shipments/{shipment_id}/handoff", payload, headers
        )

    def get_shipment(self, shipment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/shipments/{shipment_id}", headers=headers)

    def list_shipments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/shipments", headers=headers, params=params)

    def create_install_booking(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/install-bookings", payload, headers)

    def release_install_booking(
        self, booking_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/install-bookings/{booking_id}/release", payload, headers
        )

    def get_install_booking(self, booking_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/install-bookings/{booking_id}", headers=headers)

    def list_install_bookings(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/install-bookings", headers=headers, params=params)

    def get_install_crew(self, crew_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/install-crews/{crew_id}", headers=headers)

    # ─── Warranty and field service (PRD §3.9) ──────────────────────────

    def create_warranty_claim(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/warranty-claims", payload, headers)

    def reserve_claim_parts(self, claim_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/warranty-claims/{claim_id}/reserve-parts", {}, headers
        )

    def resolve_warranty_claim(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/warranty-claims/{claim_id}/resolve", payload, headers
        )

    def deny_warranty_claim(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/warranty-claims/{claim_id}/deny", payload, headers
        )

    def get_warranty_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/warranty-claims/{claim_id}", headers=headers)

    def list_warranty_claims(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/warranty-claims", headers=headers, params=params)

    def get_part_inventory(self, part_inventory_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/part-inventories/{part_inventory_id}", headers=headers
        )

    def list_part_inventories(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/part-inventories", headers=headers, params=params)


api_client = ApiClient()
