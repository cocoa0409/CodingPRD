"""
One method per declared endpoint of §4.

Every method returns the raw `requests.Response` so that tests can assert on the
status code as well as the envelope. Listing methods take an explicit `params`
dict so that the pagination and filter contract of §2.3 can be exercised.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class RefrigerantComplianceApiClient(GenericApiClient):
    """HTTP surface of the Supermarket Refrigerant Leak Compliance API."""

    # ─── Logical clock (§2.4) ─────────────────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        """The one endpoint exempt from the authentication headers of §2.1."""
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Stores (§3.1) ────────────────────────────────────────────────

    def create_store(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/stores", payload, headers)

    def list_stores(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/stores", params, headers)

    def get_store(self, store_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/stores/{store_id}", None, headers)

    # ─── Refrigerant types (§3.1) ─────────────────────────────────────

    def create_refrigerant_type(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/refrigerant-types", payload, headers)

    def list_refrigerant_types(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/refrigerant-types", params, headers)

    def get_refrigerant_type(self, refrigerant_type_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/refrigerant-types/{refrigerant_type_id}", None, headers
        )

    # ─── Systems (§3.1, §3.4, §3.7) ───────────────────────────────────

    def create_system(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/systems", payload, headers)

    def list_systems(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/systems", params, headers)

    def get_system(self, system_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/systems/{system_id}", None, headers)

    def get_leak_rate_projection(
        self, system_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        """The read-only projection of §3.4; it persists nothing."""
        return self._request(
            "GET", f"/systems/{system_id}/leak-rate-projection", params, headers
        )

    def retire_system(
        self, system_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/systems/{system_id}/retirement", payload, headers)

    # ─── Technicians (§3.2) ───────────────────────────────────────────

    def create_technician(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/technicians", payload, headers)

    def list_technicians(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/technicians", params, headers)

    def get_technician(self, technician_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/technicians/{technician_id}", None, headers)

    def change_technician_status(
        self, technician_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/technicians/{technician_id}/status-change", payload, headers
        )

    # ─── Recovery equipment (§3.2) ────────────────────────────────────

    def create_recovery_equipment(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/recovery-equipment", payload, headers)

    def list_recovery_equipment(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/recovery-equipment", params, headers)

    def get_recovery_equipment(self, equipment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/recovery-equipment/{equipment_id}", None, headers)

    def verify_recovery_equipment(
        self, equipment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/recovery-equipment/{equipment_id}/verification", payload, headers
        )

    # ─── Cylinders (§3.2) ─────────────────────────────────────────────

    def create_cylinder(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/cylinders", payload, headers)

    def list_cylinders(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/cylinders", params, headers)

    def get_cylinder(self, cylinder_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cylinders/{cylinder_id}", None, headers)

    def ship_for_reclaim(
        self, cylinder_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/cylinders/{cylinder_id}/reclaim-shipment", payload, headers
        )

    def certify_reclaim(
        self, cylinder_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/cylinders/{cylinder_id}/reclaim-certification", payload, headers
        )

    # ─── Service records (§3.3, §3.8) ─────────────────────────────────

    def create_service_record(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/service-records", payload, headers)

    def list_service_records(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/service-records", params, headers)

    def get_service_record(self, service_record_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/service-records/{service_record_id}", None, headers)

    def void_service_record(
        self, service_record_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/service-records/{service_record_id}/void", payload, headers
        )

    # ─── Leak events (§3.5) ───────────────────────────────────────────

    def create_leak_event(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/leak-events", payload, headers)

    def list_leak_events(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/leak-events", params, headers)

    def get_leak_event(self, leak_event_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/leak-events/{leak_event_id}", None, headers)

    # ─── Repair attempts and verification tests (§3.5) ────────────────

    def create_repair_attempt(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/repair-attempts", payload, headers)

    def list_repair_attempts(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/repair-attempts", params, headers)

    def get_repair_attempt(self, repair_attempt_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/repair-attempts/{repair_attempt_id}", None, headers)

    def create_verification_test(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/verification-tests", payload, headers)

    def list_verification_tests(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/verification-tests", params, headers)

    def get_verification_test(self, verification_test_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/verification-tests/{verification_test_id}", None, headers
        )

    # ─── Extension requests (§3.6) ────────────────────────────────────

    def create_extension_request(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/extension-requests", payload, headers)

    def list_extension_requests(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/extension-requests", params, headers)

    def get_extension_request(self, extension_request_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/extension-requests/{extension_request_id}", None, headers
        )

    def decide_extension_request(
        self, extension_request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/extension-requests/{extension_request_id}/decision", payload, headers
        )

    def revoke_extension_request(
        self, extension_request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/extension-requests/{extension_request_id}/revocation",
            payload,
            headers,
        )

    # ─── Retrofit plans (§3.7) ────────────────────────────────────────

    def create_retrofit_plan(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/retrofit-plans", payload, headers)

    def list_retrofit_plans(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/retrofit-plans", params, headers)

    def get_retrofit_plan(self, retrofit_plan_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/retrofit-plans/{retrofit_plan_id}", None, headers)

    def submit_retrofit_plan(
        self, retrofit_plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/retrofit-plans/{retrofit_plan_id}/submission", payload, headers
        )

    def decide_retrofit_plan(
        self, retrofit_plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/retrofit-plans/{retrofit_plan_id}/decision", payload, headers
        )

    def complete_retrofit_plan(
        self, retrofit_plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/retrofit-plans/{retrofit_plan_id}/completion", payload, headers
        )

    # ─── Regulatory reports (§3.9) ────────────────────────────────────

    def create_regulatory_report(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/regulatory-reports", payload, headers)

    def list_regulatory_reports(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/regulatory-reports", params, headers)

    def get_regulatory_report(self, regulatory_report_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/regulatory-reports/{regulatory_report_id}", None, headers
        )

    def submit_regulatory_report(
        self, regulatory_report_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/regulatory-reports/{regulatory_report_id}/submission", payload, headers
        )

    def decide_regulatory_report(
        self, regulatory_report_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/regulatory-reports/{regulatory_report_id}/decision", payload, headers
        )

    # ─── Inspections (§3.9) ───────────────────────────────────────────

    def create_inspection(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/inspections", payload, headers)

    def list_inspections(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/inspections", params, headers)

    def get_inspection(self, inspection_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/inspections/{inspection_id}", None, headers)

    def respond_to_inspection(
        self, inspection_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/inspections/{inspection_id}/response", payload, headers
        )

    def close_inspection(
        self, inspection_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/inspections/{inspection_id}/closure", payload, headers
        )

    # ─── Compliance sweep (§3.6) ──────────────────────────────────────

    def run_compliance_sweep(
        self, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ):
        return self._request("POST", "/compliance-runs", payload or {}, headers)

    # ─── Generic escape hatches ───────────────────────────────────────

    def get_path(
        self, path: str, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        """Read an arbitrary path, for the path-resolution checks of §2.10."""
        return self._request("GET", path, params, headers)

    def post_path(
        self, path: str, payload: Optional[Dict] = None, headers: Optional[Dict] = None
    ):
        """Write to an arbitrary path, for the path-resolution checks of §2.10."""
        return self._request("POST", path, payload, headers)
