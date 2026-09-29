"""Typed client for the Package Sortation Peak Staffing API (PRD §4).

One method per routing-table row. Every method takes the caller's headers
explicitly because authorization and identity are part of what the tests
exercise; nothing is defaulted to a privileged role.

List methods accept `**filters` which are sent as query parameters, so
pagination (`limit`, `offset`) and the endpoint-specific filters named in §3 go
through the same channel.
"""

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

API_PREFIX = "/sortation"


class SortationApiClient:
    """Thin, explicit wrapper over the shared HTTP client."""

    def __init__(self, base_url: Optional[str] = None):
        self._client = GenericApiClient(base_url)

    # ─── Raw escape hatch ─────────────────────────────
    def request(self, method: str, path: str, payload=None, headers=None, params=None):
        return self._client._request(method, path, payload=payload, headers=headers, params=params)

    # ─── Logical clock (PRD §2.4) ─────────────────────
    def set_clock(self, current_utc: str, headers: dict):
        """POST /_clock/set_current_utc"""
        return self._client.post(
            "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload: dict, headers: dict):
        """POST /_clock/set_current_utc with a caller-supplied body."""
        return self._client.post("/_clock/set_current_utc", payload, headers)

    # ─── SortCenter (PRD §3.1) ────────────────────────
    def create_sort_center(self, payload: dict, headers: dict):
        """POST /sortation/sort-centers"""
        return self._client.post(f"{API_PREFIX}/sort-centers", payload, headers)

    def list_sort_centers(self, headers: dict, **filters):
        """GET /sortation/sort-centers"""
        return self._client.get(
            f"{API_PREFIX}/sort-centers",
            headers=headers,
            params=filters or None,
        )

    def get_sort_center(self, center_id: str, headers: dict):
        """GET /sortation/sort-centers/{id}"""
        return self._client.get(f"{API_PREFIX}/sort-centers/{center_id}", headers=headers)

    def patch_sort_center(self, center_id: str, payload: dict, headers: dict):
        """PATCH /sortation/sort-centers/{id}"""
        return self._client._request(
            "PATCH", f"{API_PREFIX}/sort-centers/{center_id}", payload, headers
        )

    # ─── DockDoor (PRD §3.1) ──────────────────────────
    def create_dock_door(self, center_id: str, payload: dict, headers: dict):
        """POST /sortation/sort-centers/{id}/dock-doors"""
        return self._client.post(
            f"{API_PREFIX}/sort-centers/{center_id}/dock-doors", payload, headers
        )

    def list_dock_doors(self, center_id: str, headers: dict, **filters):
        """GET /sortation/sort-centers/{id}/dock-doors"""
        return self._client.get(
            f"{API_PREFIX}/sort-centers/{center_id}/dock-doors",
            headers=headers,
            params=filters or None,
        )

    def get_dock_door(self, door_id: str, headers: dict):
        """GET /sortation/dock-doors/{id}"""
        return self._client.get(f"{API_PREFIX}/dock-doors/{door_id}", headers=headers)

    def patch_dock_door(self, door_id: str, payload: dict, headers: dict):
        """PATCH /sortation/dock-doors/{id}"""
        return self._client._request(
            "PATCH", f"{API_PREFIX}/dock-doors/{door_id}", payload, headers
        )

    # ─── SortChute (PRD §3.1) ─────────────────────────
    def create_sort_chute(self, center_id: str, payload: dict, headers: dict):
        """POST /sortation/sort-centers/{id}/sort-chutes"""
        return self._client.post(
            f"{API_PREFIX}/sort-centers/{center_id}/sort-chutes", payload, headers
        )

    def list_sort_chutes(self, center_id: str, headers: dict, **filters):
        """GET /sortation/sort-centers/{id}/sort-chutes"""
        return self._client.get(
            f"{API_PREFIX}/sort-centers/{center_id}/sort-chutes",
            headers=headers,
            params=filters or None,
        )

    def get_sort_chute(self, chute_id: str, headers: dict):
        """GET /sortation/sort-chutes/{id}"""
        return self._client.get(f"{API_PREFIX}/sort-chutes/{chute_id}", headers=headers)

    # ─── DestinationLane (PRD §3.1) ───────────────────
    def create_destination_lane(self, center_id: str, payload: dict, headers: dict):
        """POST /sortation/sort-centers/{id}/destination-lanes"""
        return self._client.post(
            f"{API_PREFIX}/sort-centers/{center_id}/destination-lanes", payload, headers
        )

    def list_destination_lanes(self, center_id: str, headers: dict, **filters):
        """GET /sortation/sort-centers/{id}/destination-lanes"""
        return self._client.get(
            f"{API_PREFIX}/sort-centers/{center_id}/destination-lanes",
            headers=headers,
            params=filters or None,
        )

    def get_destination_lane(self, lane_id: str, headers: dict):
        """GET /sortation/destination-lanes/{id}"""
        return self._client.get(f"{API_PREFIX}/destination-lanes/{lane_id}", headers=headers)

    def patch_destination_lane(self, lane_id: str, payload: dict, headers: dict):
        """PATCH /sortation/destination-lanes/{id}"""
        return self._client._request(
            "PATCH", f"{API_PREFIX}/destination-lanes/{lane_id}", payload, headers
        )

    # ─── ChuteAssignment (PRD §3.2) ───────────────────
    def create_chute_assignment(self, payload: dict, headers: dict):
        """POST /sortation/chute-assignments"""
        return self._client.post(f"{API_PREFIX}/chute-assignments", payload, headers)

    def list_chute_assignments(self, headers: dict, **filters):
        """GET /sortation/chute-assignments"""
        return self._client.get(
            f"{API_PREFIX}/chute-assignments",
            headers=headers,
            params=filters or None,
        )

    def get_chute_assignment(self, assignment_id: str, headers: dict):
        """GET /sortation/chute-assignments/{id}"""
        return self._client.get(f"{API_PREFIX}/chute-assignments/{assignment_id}", headers=headers)

    # ─── TrailerAppointment (PRD §3.3) ────────────────
    def create_trailer_appointment(self, payload: dict, headers: dict):
        """POST /sortation/trailer-appointments"""
        return self._client.post(f"{API_PREFIX}/trailer-appointments", payload, headers)

    def list_trailer_appointments(self, headers: dict, **filters):
        """GET /sortation/trailer-appointments"""
        return self._client.get(
            f"{API_PREFIX}/trailer-appointments",
            headers=headers,
            params=filters or None,
        )

    def get_trailer_appointment(self, appointment_id: str, headers: dict):
        """GET /sortation/trailer-appointments/{id}"""
        return self._client.get(f"{API_PREFIX}/trailer-appointments/{appointment_id}", headers=headers)

    def arrive_trailer_appointment(self, appointment_id: str, headers: dict, payload=None):
        """POST /sortation/trailer-appointments/{id}/arrive"""
        return self._client.post(
            f"{API_PREFIX}/trailer-appointments/{appointment_id}/arrive",
            payload if payload is not None else {},
            headers,
        )

    def start_unload(self, appointment_id: str, headers: dict, payload=None):
        """POST /sortation/trailer-appointments/{id}/start-unload"""
        return self._client.post(
            f"{API_PREFIX}/trailer-appointments/{appointment_id}/start-unload",
            payload if payload is not None else {},
            headers,
        )

    def jam_hold(self, appointment_id: str, payload: dict, headers: dict):
        """POST /sortation/trailer-appointments/{id}/jam-hold"""
        return self._client.post(
            f"{API_PREFIX}/trailer-appointments/{appointment_id}/jam-hold",
            payload,
            headers,
        )

    def resume_unload(self, appointment_id: str, payload: dict, headers: dict):
        """POST /sortation/trailer-appointments/{id}/resume-unload"""
        return self._client.post(
            f"{API_PREFIX}/trailer-appointments/{appointment_id}/resume-unload",
            payload,
            headers,
        )

    def complete_unload(self, appointment_id: str, headers: dict, payload=None):
        """POST /sortation/trailer-appointments/{id}/complete-unload"""
        return self._client.post(
            f"{API_PREFIX}/trailer-appointments/{appointment_id}/complete-unload",
            payload if payload is not None else {},
            headers,
        )

    # ─── ShiftPlan (PRD §3.4, §3.5, §3.9) ─────────────
    def create_shift_plan(self, center_id: str, payload: dict, headers: dict):
        """POST /sortation/sort-centers/{id}/shift-plans"""
        return self._client.post(
            f"{API_PREFIX}/sort-centers/{center_id}/shift-plans", payload, headers
        )

    def list_shift_plans(self, center_id: str, headers: dict, **filters):
        """GET /sortation/sort-centers/{id}/shift-plans"""
        return self._client.get(
            f"{API_PREFIX}/sort-centers/{center_id}/shift-plans",
            headers=headers,
            params=filters or None,
        )

    def get_shift_plan(self, plan_id: str, headers: dict):
        """GET /sortation/shift-plans/{id}"""
        return self._client.get(f"{API_PREFIX}/shift-plans/{plan_id}", headers=headers)

    def submit_shift_plan(self, plan_id: str, headers: dict, payload=None):
        """POST /sortation/shift-plans/{id}/submit"""
        return self._client.post(
            f"{API_PREFIX}/shift-plans/{plan_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def approve_shift_plan(self, plan_id: str, payload: dict, headers: dict):
        """POST /sortation/shift-plans/{id}/approve"""
        return self._client.post(
            f"{API_PREFIX}/shift-plans/{plan_id}/approve", payload, headers
        )

    def reject_shift_plan(self, plan_id: str, payload: dict, headers: dict):
        """POST /sortation/shift-plans/{id}/reject"""
        return self._client.post(
            f"{API_PREFIX}/shift-plans/{plan_id}/reject", payload, headers
        )

    def revise_shift_plan(self, plan_id: str, payload: dict, headers: dict):
        """POST /sortation/shift-plans/{id}/revise"""
        return self._client.post(
            f"{API_PREFIX}/shift-plans/{plan_id}/revise", payload, headers
        )

    def close_shift_plan(self, plan_id: str, payload: dict, headers: dict):
        """POST /sortation/shift-plans/{id}/close"""
        return self._client.post(
            f"{API_PREFIX}/shift-plans/{plan_id}/close", payload, headers
        )

    # ─── Worker (PRD §3.6) ────────────────────────────
    def create_worker(self, center_id: str, payload: dict, headers: dict):
        """POST /sortation/sort-centers/{id}/workers"""
        return self._client.post(
            f"{API_PREFIX}/sort-centers/{center_id}/workers", payload, headers
        )

    def list_workers(self, center_id: str, headers: dict, **filters):
        """GET /sortation/sort-centers/{id}/workers"""
        return self._client.get(
            f"{API_PREFIX}/sort-centers/{center_id}/workers",
            headers=headers,
            params=filters or None,
        )

    def get_worker(self, worker_id: str, headers: dict):
        """GET /sortation/workers/{id}"""
        return self._client.get(f"{API_PREFIX}/workers/{worker_id}", headers=headers)

    def create_onboarding_event(self, worker_id: str, payload: dict, headers: dict):
        """POST /sortation/workers/{id}/onboarding-events"""
        return self._client.post(
            f"{API_PREFIX}/workers/{worker_id}/onboarding-events", payload, headers
        )

    # ─── StaffAssignment (PRD §3.7) ───────────────────
    def create_staff_assignment(self, payload: dict, headers: dict):
        """POST /sortation/staff-assignments"""
        return self._client.post(f"{API_PREFIX}/staff-assignments", payload, headers)

    def list_staff_assignments(self, headers: dict, **filters):
        """GET /sortation/staff-assignments"""
        return self._client.get(
            f"{API_PREFIX}/staff-assignments",
            headers=headers,
            params=filters or None,
        )

    def get_staff_assignment(self, assignment_id: str, headers: dict):
        """GET /sortation/staff-assignments/{id}"""
        return self._client.get(f"{API_PREFIX}/staff-assignments/{assignment_id}", headers=headers)

    def check_in(self, assignment_id: str, headers: dict, payload=None):
        """POST /sortation/staff-assignments/{id}/check-in"""
        return self._client.post(
            f"{API_PREFIX}/staff-assignments/{assignment_id}/check-in",
            payload if payload is not None else {},
            headers,
        )

    def check_out(self, assignment_id: str, headers: dict, payload=None):
        """POST /sortation/staff-assignments/{id}/check-out"""
        return self._client.post(
            f"{API_PREFIX}/staff-assignments/{assignment_id}/check-out",
            payload if payload is not None else {},
            headers,
        )

    def no_show(self, assignment_id: str, headers: dict, payload=None):
        """POST /sortation/staff-assignments/{id}/no-show"""
        return self._client.post(
            f"{API_PREFIX}/staff-assignments/{assignment_id}/no-show",
            payload if payload is not None else {},
            headers,
        )

    # ─── OutboundLoad (PRD §3.8) ──────────────────────
    def create_outbound_load(self, payload: dict, headers: dict):
        """POST /sortation/outbound-loads"""
        return self._client.post(f"{API_PREFIX}/outbound-loads", payload, headers)

    def list_outbound_loads(self, headers: dict, **filters):
        """GET /sortation/outbound-loads"""
        return self._client.get(
            f"{API_PREFIX}/outbound-loads",
            headers=headers,
            params=filters or None,
        )

    def get_outbound_load(self, load_id: str, headers: dict):
        """GET /sortation/outbound-loads/{id}"""
        return self._client.get(f"{API_PREFIX}/outbound-loads/{load_id}", headers=headers)

    def scan_packages(self, load_id: str, payload: dict, headers: dict):
        """POST /sortation/outbound-loads/{id}/scan-packages"""
        return self._client.post(
            f"{API_PREFIX}/outbound-loads/{load_id}/scan-packages", payload, headers
        )

    def close_load(self, load_id: str, headers: dict, payload=None):
        """POST /sortation/outbound-loads/{id}/close-load"""
        return self._client.post(
            f"{API_PREFIX}/outbound-loads/{load_id}/close-load",
            payload if payload is not None else {},
            headers,
        )

    def seal_load(self, load_id: str, payload: dict, headers: dict):
        """POST /sortation/outbound-loads/{id}/seal"""
        return self._client.post(
            f"{API_PREFIX}/outbound-loads/{load_id}/seal", payload, headers
        )

    def dispatch_load(self, load_id: str, headers: dict, payload=None):
        """POST /sortation/outbound-loads/{id}/dispatch"""
        return self._client.post(
            f"{API_PREFIX}/outbound-loads/{load_id}/dispatch",
            payload if payload is not None else {},
            headers,
        )

    # ─── PackageException (PRD §3.8) ──────────────────
    def create_package_exception(self, payload: dict, headers: dict):
        """POST /sortation/package-exceptions"""
        return self._client.post(f"{API_PREFIX}/package-exceptions", payload, headers)

    def list_package_exceptions(self, headers: dict, **filters):
        """GET /sortation/package-exceptions"""
        return self._client.get(
            f"{API_PREFIX}/package-exceptions",
            headers=headers,
            params=filters or None,
        )

    def get_package_exception(self, exception_id: str, headers: dict):
        """GET /sortation/package-exceptions/{id}"""
        return self._client.get(f"{API_PREFIX}/package-exceptions/{exception_id}", headers=headers)

    def resolve_package_exception(self, exception_id: str, payload: dict, headers: dict):
        """POST /sortation/package-exceptions/{id}/resolve"""
        return self._client.post(
            f"{API_PREFIX}/package-exceptions/{exception_id}/resolve", payload, headers
        )

    # ─── InjuryReport (PRD §3.9) ──────────────────────
    def create_injury_report(self, payload: dict, headers: dict):
        """POST /sortation/injury-reports"""
        return self._client.post(f"{API_PREFIX}/injury-reports", payload, headers)

    def list_injury_reports(self, headers: dict, **filters):
        """GET /sortation/injury-reports"""
        return self._client.get(
            f"{API_PREFIX}/injury-reports",
            headers=headers,
            params=filters or None,
        )

    def get_injury_report(self, report_id: str, headers: dict):
        """GET /sortation/injury-reports/{id}"""
        return self._client.get(f"{API_PREFIX}/injury-reports/{report_id}", headers=headers)

    def close_injury_report(self, report_id: str, payload: dict, headers: dict):
        """POST /sortation/injury-reports/{id}/close"""
        return self._client.post(
            f"{API_PREFIX}/injury-reports/{report_id}/close", payload, headers
        )
