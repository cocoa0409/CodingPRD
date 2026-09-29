"""Typed API client: one method per endpoint of the load planning API.

Every method returns the raw ``requests.Response`` so tests can assert on the
status code as well as on the decoded envelope.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Thin, explicit wrapper around every documented endpoint."""

    # -----------------------------------------------------------------
    # Aircraft
    # -----------------------------------------------------------------
    def create_aircraft(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/aircraft", payload, headers)

    def get_aircraft(self, aircraft_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/aircraft/{aircraft_id}", None, headers)

    def list_aircraft(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/aircraft", params, headers)

    def ground_aircraft(self, aircraft_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/aircraft/{aircraft_id}/ground", None, headers)

    # -----------------------------------------------------------------
    # Compartments
    # -----------------------------------------------------------------
    def create_compartment(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/compartments", payload, headers)

    def get_compartment(self, compartment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/compartments/{compartment_id}", None, headers)

    def list_aircraft_compartments(
        self, aircraft_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"/aircraft/{aircraft_id}/compartments", params, headers)

    # -----------------------------------------------------------------
    # Runways
    # -----------------------------------------------------------------
    def create_runway(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/runways", payload, headers)

    def get_runway(self, runway_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/runways/{runway_id}", None, headers)

    def close_runway(self, runway_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/runways/{runway_id}/close", None, headers)

    # -----------------------------------------------------------------
    # Performance bands
    # -----------------------------------------------------------------
    def create_performance_band(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/performance-bands", payload, headers)

    def get_performance_band(self, band_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/performance-bands/{band_id}", None, headers)

    def list_runway_performance_bands(
        self, runway_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"/runways/{runway_id}/performance-bands", params, headers)

    # -----------------------------------------------------------------
    # Weight programs
    # -----------------------------------------------------------------
    def create_weight_program(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/weight-programs", payload, headers)

    def get_weight_program(self, program_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/weight-programs/{program_id}", None, headers)

    def withdraw_weight_program(self, program_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/weight-programs/{program_id}/withdraw", None, headers)

    # -----------------------------------------------------------------
    # Flights
    # -----------------------------------------------------------------
    def create_flight(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/flights", payload, headers)

    def get_flight(self, flight_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/flights/{flight_id}", None, headers)

    def list_flights(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/flights", params, headers)

    def patch_flight_conditions(
        self, flight_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"/flights/{flight_id}/conditions", payload, headers)

    def depart_flight(self, flight_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/flights/{flight_id}/depart", None, headers)

    def close_flight(self, flight_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/flights/{flight_id}/close", None, headers)

    def cancel_flight(self, flight_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/flights/{flight_id}/cancel", None, headers)

    # -----------------------------------------------------------------
    # Load plans
    # -----------------------------------------------------------------
    def create_load_plan(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/load-plans", payload, headers)

    def get_load_plan(self, load_plan_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/load-plans/{load_plan_id}", None, headers)

    def list_flight_load_plans(
        self, flight_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"/flights/{flight_id}/load-plans", params, headers)

    def compute_load_plan(self, load_plan_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/load-plans/{load_plan_id}/compute", None, headers)

    def apply_offload(self, load_plan_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/load-plans/{load_plan_id}/apply-offload", None, headers)

    def get_offload_preview(self, load_plan_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/load-plans/{load_plan_id}/offload-preview", None, headers)

    def add_gate_bag(
        self, load_plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/load-plans/{load_plan_id}/gate-bags", payload, headers)

    # -----------------------------------------------------------------
    # Passenger distribution lines
    # -----------------------------------------------------------------
    def create_pax_line(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/pax-lines", payload, headers)

    def get_pax_line(self, pax_line_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/pax-lines/{pax_line_id}", None, headers)

    def list_pax_lines(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/pax-lines", params, headers)

    def delete_pax_line(self, pax_line_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("DELETE", f"/pax-lines/{pax_line_id}", None, headers)

    # -----------------------------------------------------------------
    # Bag allocations
    # -----------------------------------------------------------------
    def create_bag_allocation(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/bag-allocations", payload, headers)

    def get_bag_allocation(self, allocation_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/bag-allocations/{allocation_id}", None, headers)

    def list_bag_allocations(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/bag-allocations", params, headers)

    # -----------------------------------------------------------------
    # Cargo items
    # -----------------------------------------------------------------
    def create_cargo_item(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/cargo-items", payload, headers)

    def get_cargo_item(self, cargo_item_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/cargo-items/{cargo_item_id}", None, headers)

    def list_cargo_items(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/cargo-items", params, headers)

    def assign_cargo_item(
        self, cargo_item_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/cargo-items/{cargo_item_id}/assign", payload, headers)

    def accept_cargo_item(self, cargo_item_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/cargo-items/{cargo_item_id}/accept", None, headers)

    def reject_cargo_item(self, cargo_item_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/cargo-items/{cargo_item_id}/reject", None, headers)

    # -----------------------------------------------------------------
    # Hazmat declarations
    # -----------------------------------------------------------------
    def create_hazmat_declaration(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/hazmat-declarations", payload, headers)

    def get_hazmat_declaration(self, declaration_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/hazmat-declarations/{declaration_id}", None, headers)

    def list_cargo_hazmat_declarations(
        self, cargo_item_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"/cargo-items/{cargo_item_id}/hazmat-declarations", params, headers)

    def accept_hazmat_declaration(
        self, declaration_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/hazmat-declarations/{declaration_id}/accept", None, headers)

    def reject_hazmat_declaration(
        self, declaration_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/hazmat-declarations/{declaration_id}/reject", None, headers)

    # -----------------------------------------------------------------
    # Load sheets
    # -----------------------------------------------------------------
    def create_load_sheet(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/load-sheets", payload, headers)

    def get_load_sheet(self, load_sheet_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/load-sheets/{load_sheet_id}", None, headers)

    def list_load_plan_load_sheets(
        self, load_plan_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"/load-plans/{load_plan_id}/load-sheets", params, headers)

    def accept_load_sheet(self, load_sheet_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/load-sheets/{load_sheet_id}/accept", None, headers)

    def reject_load_sheet(self, load_sheet_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/load-sheets/{load_sheet_id}/reject", None, headers)

    def amend_load_sheet(self, load_sheet_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/load-sheets/{load_sheet_id}/amend", None, headers)

    # -----------------------------------------------------------------
    # Last-minute changes
    # -----------------------------------------------------------------
    def create_last_minute_change(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/last-minute-changes", payload, headers)

    def get_last_minute_change(self, change_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/last-minute-changes/{change_id}", None, headers)

    def list_last_minute_changes(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/last-minute-changes", params, headers)

    def reverse_last_minute_change(self, change_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/last-minute-changes/{change_id}/reverse", None, headers)

    # -----------------------------------------------------------------
    # Load audits
    # -----------------------------------------------------------------
    def create_load_audit(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/load-audits", payload, headers)

    def get_load_audit(self, audit_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/load-audits/{audit_id}", None, headers)

    def list_flight_load_audits(
        self, flight_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"/flights/{flight_id}/load-audits", params, headers)

    def investigate_load_audit(self, audit_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/load-audits/{audit_id}/investigate", None, headers)

    def close_load_audit(
        self, audit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/load-audits/{audit_id}/close", payload, headers)

    # -----------------------------------------------------------------
    # Logical clock
    # -----------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def set_clock_raw(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


# Module-level shared instance used by fixtures and tests.
api_client = ApiClient()
