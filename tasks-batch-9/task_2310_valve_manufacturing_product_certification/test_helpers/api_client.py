"""
HTTP client for the Valve Manufacturing & Product Certification API.

One method per endpoint declared in the PRD endpoint table (§4). Everything is
mounted beneath the ``/valve-mfg`` prefix. Methods return the raw
``requests.Response`` so tests can assert HTTP status codes themselves.
"""

from typing import Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX
from .types import Headers, Payload


class ApiClient(GenericApiClient):
    """Thin endpoint façade over the generic request machinery."""

    # ─── Product-line designs (valve models) ──────────

    def create_valve_model(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/valve-models", payload, headers)

    def list_valve_models(
        self, headers: Headers, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/valve-models", headers=headers, params=params)

    def get_valve_model(self, model_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/valve-models/{model_id}", headers=headers)

    def valve_model_action(
        self, model_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/valve-models/{model_id}/actions", payload, headers
        )

    # ─── Foundries ────────────────────────────────────

    def create_foundry(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/foundries", payload, headers)

    def list_foundries(
        self, headers: Headers, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/foundries", headers=headers, params=params)

    def get_foundry(self, foundry_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/foundries/{foundry_id}", headers=headers)

    # ─── Foundry qualifications ───────────────────────

    def create_foundry_qualification(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/foundry-qualifications", payload, headers)

    def list_foundry_qualifications(
        self, headers: Headers, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/foundry-qualifications", headers=headers, params=params
        )

    def get_foundry_qualification(
        self, qualification_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/foundry-qualifications/{qualification_id}", headers=headers
        )

    def foundry_qualification_action(
        self, qualification_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/foundry-qualifications/{qualification_id}/actions",
            payload,
            headers,
        )

    # ─── Heat lots ────────────────────────────────────

    def create_heat_lot(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/heat-lots", payload, headers)

    def list_heat_lots(
        self, headers: Headers, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/heat-lots", headers=headers, params=params)

    def get_heat_lot(self, heat_lot_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/heat-lots/{heat_lot_id}", headers=headers)

    def heat_lot_disposition(
        self, heat_lot_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/heat-lots/{heat_lot_id}/dispositions", payload, headers
        )

    # ─── Components ───────────────────────────────────

    def create_component(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/components", payload, headers)

    def list_components(
        self, headers: Headers, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/components", headers=headers, params=params)

    def get_component(self, component_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/components/{component_id}", headers=headers)

    def component_disposition(
        self, component_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/components/{component_id}/dispositions", payload, headers
        )

    # ─── Valve units ──────────────────────────────────

    def create_valve_unit(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/valve-units", payload, headers)

    def list_valve_units(
        self, headers: Headers, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/valve-units", headers=headers, params=params)

    def get_valve_unit(self, unit_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/valve-units/{unit_id}", headers=headers)

    def valve_unit_build_action(
        self, unit_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/valve-units/{unit_id}/build-actions", payload, headers
        )

    def create_test_record(
        self, unit_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/valve-units/{unit_id}/test-records", payload, headers
        )

    def list_test_records(
        self, unit_id: str, headers: Headers, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/valve-units/{unit_id}/test-records", headers=headers, params=params
        )

    def valve_unit_cert_action(
        self, unit_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/valve-units/{unit_id}/cert-actions", payload, headers
        )

    def valve_unit_service_action(
        self, unit_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/valve-units/{unit_id}/service-actions", payload, headers
        )

    # ─── Actuator packages ────────────────────────────

    def create_actuator_package(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/actuator-packages", payload, headers)

    def list_actuator_packages(
        self, headers: Headers, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/actuator-packages", headers=headers, params=params
        )

    def get_actuator_package(self, package_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/actuator-packages/{package_id}", headers=headers
        )

    def actuator_package_decision(
        self, package_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/actuator-packages/{package_id}/decision", payload, headers
        )

    # ─── Monogram licenses ────────────────────────────

    def create_monogram_license(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/monogram-licenses", payload, headers)

    def list_monogram_licenses(
        self, headers: Headers, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/monogram-licenses", headers=headers, params=params
        )

    def get_monogram_license(self, license_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/monogram-licenses/{license_id}", headers=headers
        )

    def monogram_license_action(
        self, license_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/monogram-licenses/{license_id}/actions", payload, headers
        )

    def create_finding_entry(
        self, license_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/monogram-licenses/{license_id}/finding-entries", payload, headers
        )

    # ─── Engineered orders ────────────────────────────

    def create_engineered_order(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/engineered-orders", payload, headers)

    def list_engineered_orders(
        self, headers: Headers, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/engineered-orders", headers=headers, params=params
        )

    def get_engineered_order(self, order_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/engineered-orders/{order_id}", headers=headers
        )

    def create_datasheet_revision(
        self, order_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/engineered-orders/{order_id}/datasheet-revisions", payload, headers
        )

    def engineered_order_review_action(
        self, order_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/engineered-orders/{order_id}/review-actions", payload, headers
        )

    def engineered_order_lifecycle_action(
        self, order_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/engineered-orders/{order_id}/lifecycle-actions", payload, headers
        )

    def append_order_document(
        self, order_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/engineered-orders/{order_id}/documents", payload, headers
        )

    # ─── The logical works clock ──────────────────────

    def set_clock(self, to_iso8601: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


# Module-level client shared by every test in the suite.
api_client = ApiClient()
