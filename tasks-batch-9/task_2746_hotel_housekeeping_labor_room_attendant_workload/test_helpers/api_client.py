"""Domain API client: one method per endpoint of PRD 4.

Every method returns the raw `requests.Response` so tests can assert on status
codes as well as bodies.  Payload construction is left to `factories.py`.
"""

from __future__ import annotations

from typing import Any, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

from .constants import (
    PATH_ATTENDANTS,
    PATH_CLOCK_SET,
    PATH_FORECAST_DAYS,
    PATH_INSPECTIONS,
    PATH_LAUNDRY_CYCLES,
    PATH_LINEN_ITEMS,
    PATH_LOST_FOUND_ITEMS,
    PATH_PROPERTIES,
    PATH_ROOM_ASSIGNMENTS,
    PATH_ROOM_TYPES,
    PATH_ROOMS,
    PATH_SERVICE_ENROLLMENTS,
    PATH_SHIFT_ROSTERS,
)

Headers = Optional[dict[str, str]]
Payload = Optional[dict[str, Any]]


class ApiClient(GenericApiClient):
    """Thin, explicit wrapper over the housekeeping endpoint surface."""

    # ------------------------------------------------------------------
    # Logical clock (PRD 2.4)
    # ------------------------------------------------------------------

    def set_clock(self, to_iso8601: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "POST", PATH_CLOCK_SET, {"to_iso8601": to_iso8601}, headers
        )

    def set_clock_raw(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", PATH_CLOCK_SET, payload, headers)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    def create_property(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", PATH_PROPERTIES, payload, headers)

    def get_property(self, property_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{PATH_PROPERTIES}/{property_id}", None, headers)

    # ------------------------------------------------------------------
    # Room types
    # ------------------------------------------------------------------

    def create_room_type(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", PATH_ROOM_TYPES, payload, headers)

    def get_room_type(self, room_type_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{PATH_ROOM_TYPES}/{room_type_id}", None, headers)

    def list_room_types(self, params: Payload = None, headers: Headers = None) -> requests.Response:
        return self._request("GET", PATH_ROOM_TYPES, params, headers)

    # ------------------------------------------------------------------
    # Rooms
    # ------------------------------------------------------------------

    def create_room(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", PATH_ROOMS, payload, headers)

    def get_room(self, room_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{PATH_ROOMS}/{room_id}", None, headers)

    def list_rooms(self, params: Payload = None, headers: Headers = None) -> requests.Response:
        return self._request("GET", PATH_ROOMS, params, headers)

    def patch_room(
        self, room_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("PATCH", f"{PATH_ROOMS}/{room_id}", payload, headers)

    # ------------------------------------------------------------------
    # Attendants
    # ------------------------------------------------------------------

    def create_attendant(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", PATH_ATTENDANTS, payload, headers)

    def get_attendant(self, attendant_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{PATH_ATTENDANTS}/{attendant_id}", None, headers)

    def list_attendants(self, params: Payload = None, headers: Headers = None) -> requests.Response:
        return self._request("GET", PATH_ATTENDANTS, params, headers)

    def patch_attendant(
        self, attendant_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "PATCH", f"{PATH_ATTENDANTS}/{attendant_id}", payload, headers
        )

    # ------------------------------------------------------------------
    # Forecast days
    # ------------------------------------------------------------------

    def create_forecast_day(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", PATH_FORECAST_DAYS, payload, headers)

    def get_forecast_day(self, day_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{PATH_FORECAST_DAYS}/{day_id}", None, headers)

    def list_forecast_days(self, params: Payload = None, headers: Headers = None) -> requests.Response:
        return self._request("GET", PATH_FORECAST_DAYS, params, headers)

    def publish_forecast_day(
        self, day_id: str, headers: Headers = None, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PATH_FORECAST_DAYS}/{day_id}/publish", payload, headers
        )

    def close_forecast_day(
        self, day_id: str, headers: Headers = None, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PATH_FORECAST_DAYS}/{day_id}/close", payload, headers
        )

    # ------------------------------------------------------------------
    # Shift rosters
    # ------------------------------------------------------------------

    def create_shift_roster(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", PATH_SHIFT_ROSTERS, payload, headers)

    def get_shift_roster(self, roster_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{PATH_SHIFT_ROSTERS}/{roster_id}", None, headers)

    def list_shift_rosters(self, params: Payload = None, headers: Headers = None) -> requests.Response:
        return self._request("GET", PATH_SHIFT_ROSTERS, params, headers)

    def clock_in(
        self, roster_id: str, headers: Headers = None, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PATH_SHIFT_ROSTERS}/{roster_id}/clock-in", payload, headers
        )

    def close_roster(
        self, roster_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PATH_SHIFT_ROSTERS}/{roster_id}/close", payload, headers
        )

    def request_waiver(
        self, roster_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PATH_SHIFT_ROSTERS}/{roster_id}/waiver-request", payload, headers
        )

    def decide_waiver(
        self, roster_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PATH_SHIFT_ROSTERS}/{roster_id}/waiver-decision", payload, headers
        )

    def get_sample_plan(self, roster_id: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "GET", f"{PATH_SHIFT_ROSTERS}/{roster_id}/inspection-sample-plan", None, headers
        )

    # ------------------------------------------------------------------
    # Room assignments
    # ------------------------------------------------------------------

    def create_room_assignment(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", PATH_ROOM_ASSIGNMENTS, payload, headers)

    def get_room_assignment(self, assignment_id: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "GET", f"{PATH_ROOM_ASSIGNMENTS}/{assignment_id}", None, headers
        )

    def list_room_assignments(self, params: Payload = None, headers: Headers = None) -> requests.Response:
        return self._request("GET", PATH_ROOM_ASSIGNMENTS, params, headers)

    def start_assignment(
        self, assignment_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PATH_ROOM_ASSIGNMENTS}/{assignment_id}/start", payload, headers
        )

    def complete_assignment(
        self, assignment_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PATH_ROOM_ASSIGNMENTS}/{assignment_id}/complete", payload, headers
        )

    def cancel_assignment(
        self, assignment_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PATH_ROOM_ASSIGNMENTS}/{assignment_id}/cancel", payload, headers
        )

    # ------------------------------------------------------------------
    # Inspections
    # ------------------------------------------------------------------

    def create_inspection(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", PATH_INSPECTIONS, payload, headers)

    def get_inspection(self, inspection_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{PATH_INSPECTIONS}/{inspection_id}", None, headers)

    def list_inspections(self, params: Payload = None, headers: Headers = None) -> requests.Response:
        return self._request("GET", PATH_INSPECTIONS, params, headers)

    # ------------------------------------------------------------------
    # Linen items
    # ------------------------------------------------------------------

    def create_linen_item(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", PATH_LINEN_ITEMS, payload, headers)

    def get_linen_item(self, linen_item_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{PATH_LINEN_ITEMS}/{linen_item_id}", None, headers)

    def list_linen_items(self, params: Payload = None, headers: Headers = None) -> requests.Response:
        return self._request("GET", PATH_LINEN_ITEMS, params, headers)

    def soil_linen(
        self, linen_item_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PATH_LINEN_ITEMS}/{linen_item_id}/soil", payload, headers
        )

    # ------------------------------------------------------------------
    # Laundry cycles
    # ------------------------------------------------------------------

    def create_laundry_cycle(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", PATH_LAUNDRY_CYCLES, payload, headers)

    def get_laundry_cycle(self, cycle_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{PATH_LAUNDRY_CYCLES}/{cycle_id}", None, headers)

    def list_laundry_cycles(self, params: Payload = None, headers: Headers = None) -> requests.Response:
        return self._request("GET", PATH_LAUNDRY_CYCLES, params, headers)

    def return_laundry_cycle(
        self, cycle_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PATH_LAUNDRY_CYCLES}/{cycle_id}/return", payload, headers
        )

    def void_laundry_cycle(
        self, cycle_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PATH_LAUNDRY_CYCLES}/{cycle_id}/void", payload, headers
        )

    # ------------------------------------------------------------------
    # Lost and found
    # ------------------------------------------------------------------

    def create_lost_found_item(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", PATH_LOST_FOUND_ITEMS, payload, headers)

    def get_lost_found_item(self, item_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{PATH_LOST_FOUND_ITEMS}/{item_id}", None, headers)

    def list_lost_found_items(self, params: Payload = None, headers: Headers = None) -> requests.Response:
        return self._request("GET", PATH_LOST_FOUND_ITEMS, params, headers)

    def store_item(
        self, item_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PATH_LOST_FOUND_ITEMS}/{item_id}/store", payload, headers
        )

    def claim_item(
        self, item_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PATH_LOST_FOUND_ITEMS}/{item_id}/claim", payload, headers
        )

    def decide_claim(
        self, item_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PATH_LOST_FOUND_ITEMS}/{item_id}/claim-decision", payload, headers
        )

    def dispose_item(
        self, item_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PATH_LOST_FOUND_ITEMS}/{item_id}/dispose", payload, headers
        )

    # ------------------------------------------------------------------
    # Service enrollments
    # ------------------------------------------------------------------

    def create_service_enrollment(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", PATH_SERVICE_ENROLLMENTS, payload, headers)

    def get_service_enrollment(self, enrollment_id: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "GET", f"{PATH_SERVICE_ENROLLMENTS}/{enrollment_id}", None, headers
        )

    def list_service_enrollments(self, params: Payload = None, headers: Headers = None) -> requests.Response:
        return self._request("GET", PATH_SERVICE_ENROLLMENTS, params, headers)

    def accrue_enrollment(
        self, enrollment_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PATH_SERVICE_ENROLLMENTS}/{enrollment_id}/accrue", payload, headers
        )

    def void_enrollment(
        self, enrollment_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PATH_SERVICE_ENROLLMENTS}/{enrollment_id}/void", payload, headers
        )


# Shared session-wide instance used by conftest's `api` fixture.
api_client = ApiClient()
