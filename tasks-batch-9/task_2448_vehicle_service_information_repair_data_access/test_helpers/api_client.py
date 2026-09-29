"""One method per endpoint of the Vehicle Service Information Access API."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed wrapper over the API surface described in the PRD."""

    # ------------------------------------------------------------------
    # System areas
    # ------------------------------------------------------------------
    def create_system_area(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/system-areas", payload, headers)

    # ------------------------------------------------------------------
    # Manufacturers and the catalogue axes
    # ------------------------------------------------------------------
    def create_manufacturer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/manufacturers", payload, headers)

    def get_manufacturer(self, manufacturer_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/manufacturers/{manufacturer_id}", headers=headers
        )

    def restate_manufacturer_pricing(
        self, manufacturer_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"/manufacturers/{manufacturer_id}/pricing", payload, headers
        )

    def get_parity_report(
        self,
        manufacturer_id: str,
        headers: Dict[str, str],
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"/manufacturers/{manufacturer_id}/parity-report",
            headers=headers,
            params=params,
        )

    def list_manufacturer_licenses(
        self,
        manufacturer_id: str,
        headers: Dict[str, str],
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"/manufacturers/{manufacturer_id}/licenses",
            headers=headers,
            params=params,
        )

    def create_vehicle_model(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/vehicle-models", payload, headers)

    def list_manufacturer_vehicle_models(
        self,
        manufacturer_id: str,
        headers: Dict[str, str],
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"/manufacturers/{manufacturer_id}/vehicle-models",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Licenses
    # ------------------------------------------------------------------
    def create_license(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/licenses", payload, headers)

    def activate_license(self, license_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/licenses/{license_id}/activate", {}, headers)

    def suspend_license(
        self, license_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/licenses/{license_id}/suspend", payload, headers
        )

    def terminate_license(
        self, license_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/licenses/{license_id}/terminate", payload, headers
        )

    # ------------------------------------------------------------------
    # Shops, data credit and coverage
    # ------------------------------------------------------------------
    def create_shop(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/shops", payload, headers)

    def get_shop(self, shop_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/shops/{shop_id}", headers=headers)

    def fund_shop_credit(
        self, shop_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/shops/{shop_id}/credit-funding", payload, headers
        )

    def get_coverage_map(
        self, shop_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/shops/{shop_id}/coverage-map", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Technicians
    # ------------------------------------------------------------------
    def create_technician(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/technicians", payload, headers)

    def list_shop_technicians(
        self, shop_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/shops/{shop_id}/technicians", headers=headers, params=params
        )

    def verify_technician(
        self, technician_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/technicians/{technician_id}/verify", payload, headers
        )

    def suspend_technician(
        self, technician_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/technicians/{technician_id}/suspend", payload, headers
        )

    def revoke_technician(
        self, technician_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/technicians/{technician_id}/revoke", payload, headers
        )

    # ------------------------------------------------------------------
    # Entitlements
    # ------------------------------------------------------------------
    def create_entitlement(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/entitlements", payload, headers)

    def get_entitlement(self, entitlement_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/entitlements/{entitlement_id}", headers=headers)

    def list_entitlements(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/entitlements", headers=headers, params=params)

    def activate_entitlement(self, entitlement_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/entitlements/{entitlement_id}/activate", {}, headers
        )

    def cancel_entitlement(
        self, entitlement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/entitlements/{entitlement_id}/cancel", payload, headers
        )

    # ------------------------------------------------------------------
    # Seat assignments
    # ------------------------------------------------------------------
    def create_seat_assignment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/seat-assignments", payload, headers)

    def get_seat_assignment(self, seat_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/seat-assignments/{seat_id}", headers=headers)

    def list_seat_assignments(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/seat-assignments", headers=headers, params=params)

    def revoke_seat_assignment(
        self, seat_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/seat-assignments/{seat_id}/revoke", payload, headers
        )

    # ------------------------------------------------------------------
    # Diagnostic tools
    # ------------------------------------------------------------------
    def create_diagnostic_tool(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/diagnostic-tools", payload, headers)

    def list_shop_diagnostic_tools(
        self, shop_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/shops/{shop_id}/diagnostic-tools", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Publications and versions
    # ------------------------------------------------------------------
    def create_publication(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/publications", payload, headers)

    def get_publication(self, publication_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/publications/{publication_id}", headers=headers)

    def list_publications(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/publications", headers=headers, params=params)

    def create_publication_version(
        self, publication_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/publications/{publication_id}/versions", payload, headers
        )

    def list_publication_versions(
        self,
        publication_id: str,
        headers: Dict[str, str],
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"/publications/{publication_id}/versions",
            headers=headers,
            params=params,
        )

    def validate_publication_version(
        self, version_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/publication-versions/{version_id}/validate", payload, headers
        )

    def publish_publication_version(self, version_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/publication-versions/{version_id}/publish", {}, headers
        )

    def recall_publication_version(
        self, version_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/publication-versions/{version_id}/recall", payload, headers
        )

    # ------------------------------------------------------------------
    # Gateway sessions
    # ------------------------------------------------------------------
    def create_gateway_session(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/gateway-sessions", payload, headers)

    def get_gateway_session(self, session_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/gateway-sessions/{session_id}", headers=headers
        )

    def list_gateway_sessions(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/gateway-sessions", headers=headers, params=params
        )

    def activate_gateway_session(self, session_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/gateway-sessions/{session_id}/activate", {}, headers
        )

    def complete_gateway_session(self, session_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/gateway-sessions/{session_id}/complete", {}, headers
        )

    # ------------------------------------------------------------------
    # Module programming jobs
    # ------------------------------------------------------------------
    def create_programming_job(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/programming-jobs", payload, headers)

    def get_programming_job(self, job_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/programming-jobs/{job_id}", headers=headers)

    def list_programming_jobs(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/programming-jobs", headers=headers, params=params
        )

    def start_programming_job(self, job_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/programming-jobs/{job_id}/start", {}, headers
        )

    def complete_programming_job(self, job_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/programming-jobs/{job_id}/complete", {}, headers
        )

    def repin_programming_job(
        self, job_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/programming-jobs/{job_id}/repin", payload, headers
        )

    # ------------------------------------------------------------------
    # Audit trail and the logical clock
    # ------------------------------------------------------------------
    def list_audit_events(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/audit-events", headers=headers, params=params)

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
