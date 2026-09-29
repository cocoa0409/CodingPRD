"""Typed client with one method per endpoint of the offsite modular API.

Every resource is mounted flat under the ``/modular`` namespace, one collection
segment per entity type and one item segment beneath it, so each method below
maps to exactly one row of the endpoint table.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


class ModularApiClient(GenericApiClient):
    """One method per declared endpoint; every method returns the raw response."""

    # ─── Factories ────────────────────────────────────────────────────────────
    def create_factory(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/factories", payload, headers)

    def get_factory(self, factory_id: str, headers=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/factories/{factory_id}", None, headers
        )

    def list_factories(
        self, params: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/factories", params, headers)

    def update_factory_line_state(
        self, factory_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "PATCH", f"{API_PREFIX}/factories/{factory_id}/line-state", payload, headers
        )

    # ─── Inspection agencies ──────────────────────────────────────────────────
    def create_agency(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/agencies", payload, headers)

    def get_agency(self, agency_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/agencies/{agency_id}", None, headers)

    def list_agencies(
        self, params: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/agencies", params, headers)

    def update_agency_accreditation(
        self, agency_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "PATCH",
            f"{API_PREFIX}/agencies/{agency_id}/accreditation",
            payload,
            headers,
        )

    # ─── Projects ─────────────────────────────────────────────────────────────
    def create_project(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/projects", payload, headers)

    def get_project(self, project_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/projects/{project_id}", None, headers)

    def list_projects(
        self, params: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/projects", params, headers)

    def get_set_readiness(self, project_id: str, headers=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/projects/{project_id}/set-readiness", None, headers
        )

    def record_weather_observation(
        self, project_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/projects/{project_id}/weather-observations",
            payload,
            headers,
        )

    # ─── Design packages ──────────────────────────────────────────────────────
    def create_design_package(
        self, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/design-packages", payload, headers)

    def get_design_package(self, package_id: str, headers=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/design-packages/{package_id}", None, headers
        )

    def list_design_packages(
        self, params: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/design-packages", params, headers)

    def submit_design_package(
        self, package_id: str, payload: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/design-packages/{package_id}/submit",
            payload or {},
            headers,
        )

    def decide_design_review(
        self, package_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/design-packages/{package_id}/review-decision",
            payload,
            headers,
        )

    # ─── Modules ──────────────────────────────────────────────────────────────
    def create_module(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/modules", payload, headers)

    def get_module(self, module_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/modules/{module_id}", None, headers)

    def list_modules(
        self, params: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/modules", params, headers)

    def schedule_line_slot(
        self, module_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/modules/{module_id}/schedule-line-slot",
            payload,
            headers,
        )

    def release_line_slot(
        self, module_id: str, payload: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/modules/{module_id}/release-line-slot",
            payload or {},
            headers,
        )

    def advance_station(
        self, module_id: str, payload: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/modules/{module_id}/advance-station",
            payload or {},
            headers,
        )

    def schedule_pick(
        self, module_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/modules/{module_id}/schedule-pick", payload, headers
        )

    def execute_set(
        self, module_id: str, payload: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/modules/{module_id}/execute-set",
            payload or {},
            headers,
        )

    def close_connections(
        self, module_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/modules/{module_id}/close-connections",
            payload,
            headers,
        )

    # ─── Permit records ───────────────────────────────────────────────────────
    def create_permit(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/permits", payload, headers)

    def get_permit(self, permit_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/permits/{permit_id}", None, headers)

    def list_permits(
        self, params: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/permits", params, headers)

    def decide_permit(
        self, permit_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/permits/{permit_id}/decide", payload, headers
        )

    # ─── Inspection records ───────────────────────────────────────────────────
    def create_inspection(
        self, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/inspections", payload, headers)

    def get_inspection(self, inspection_id: str, headers=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/inspections/{inspection_id}", None, headers
        )

    def list_inspections(
        self, params: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/inspections", params, headers)

    def record_inspection_result(
        self, inspection_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/inspections/{inspection_id}/record-result",
            payload,
            headers,
        )

    def clear_hold(
        self, inspection_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/inspections/{inspection_id}/clear-hold",
            payload,
            headers,
        )

    # ─── Shipments ────────────────────────────────────────────────────────────
    def create_shipment(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/shipments", payload, headers)

    def get_shipment(self, shipment_id: str, headers=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/shipments/{shipment_id}", None, headers
        )

    def list_shipments(
        self, params: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/shipments", params, headers)

    def load_module(
        self, shipment_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/shipments/{shipment_id}/load-module",
            payload,
            headers,
        )

    def record_route_survey(
        self, shipment_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/shipments/{shipment_id}/route-survey",
            payload,
            headers,
        )

    def dispatch_shipment(
        self, shipment_id: str, payload: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/shipments/{shipment_id}/dispatch",
            payload or {},
            headers,
        )

    def deliver_shipment(
        self, shipment_id: str, payload: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/shipments/{shipment_id}/deliver",
            payload or {},
            headers,
        )

    def cancel_shipment(
        self, shipment_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/shipments/{shipment_id}/cancel", payload, headers
        )

    # ─── Defect claims ────────────────────────────────────────────────────────
    def create_defect_claim(
        self, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/defect-claims", payload, headers)

    def get_defect_claim(self, claim_id: str, headers=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/defect-claims/{claim_id}", None, headers
        )

    def list_defect_claims(
        self, params: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/defect-claims", params, headers)

    def adjudicate_defect_claim(
        self, claim_id: str, payload: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/defect-claims/{claim_id}/adjudicate",
            payload or {},
            headers,
        )

    def dispute_defect_claim(
        self, claim_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/defect-claims/{claim_id}/dispute", payload, headers
        )

    # ─── Draw requests ────────────────────────────────────────────────────────
    def create_draw_request(
        self, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/draw-requests", payload, headers)

    def get_draw_request(self, draw_id: str, headers=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/draw-requests/{draw_id}", None, headers
        )

    def list_draw_requests(
        self, params: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/draw-requests", params, headers)

    def certify_draw(
        self, draw_id: str, payload: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/draw-requests/{draw_id}/certify",
            payload or {},
            headers,
        )

    def fund_draw(
        self, draw_id: str, payload: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/draw-requests/{draw_id}/fund", payload or {}, headers
        )

    def reject_draw(
        self, draw_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/draw-requests/{draw_id}/reject", payload, headers
        )

    # ─── Logical clock ────────────────────────────────────────────────────────
    def set_clock(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/_clock/set_current_utc", payload, headers
        )
