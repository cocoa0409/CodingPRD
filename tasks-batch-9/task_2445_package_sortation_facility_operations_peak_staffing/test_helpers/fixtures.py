"""Composite setup helpers and pytest fixtures.

The harness restarts the API server before every individual test, so each test
begins against an empty database. Everything a test needs must therefore be
built from scratch through the documented endpoints, and that is what this
module does.

`SortationWorld` groups the builders by how deep they reach:

* clock control and single-row creation (`create_center`, `create_chute`, ...);
* the facility surface as a unit (`setup_facility`), which is what almost every
  test starts from;
* lifecycle shortcuts that drive an entity to a named state (`unloading_
  appointment`, `create_approved_plan`, `create_certified_worker`,
  `create_sealed_load`);
* threshold helpers that put a counter exactly on a boundary (`freeze_center`,
  `ensure_wip`, `complete_assignment_with_hours`);
* read-back and ledger helpers (`center`, `center_version`, `assert_ledgers`).

Every builder raises immediately when a setup call fails, so a broken fixture
surfaces as a setup error rather than as a confusing assertion later.
"""

from datetime import datetime, timedelta, timezone

import pytest

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import api_errors  # noqa: F401  (registers the error/HTTP status map)
from .api_client import SortationApiClient
from .assertions import assert_flex_pool_conservation, assert_package_conservation
from .constants import CLOCK_STARTUP_UTC
from . import factories as f
from .test_users import (
    FACILITY_ADMIN_HEADERS,
    INBOUND_COORDINATOR_HEADERS,
    LABOR_PLANNER_HEADERS,
    OPS_MANAGER_HEADERS,
    SORT_SUPERVISOR_HEADERS,
    make_labor_planner_headers,
    make_ops_manager_headers,
    make_worker_headers,
)

_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def parse_instant(text: str) -> datetime:
    """Parse an RFC 3339 UTC instant, tolerating fractional seconds."""
    cleaned = text.replace("Z", "+00:00")
    return datetime.fromisoformat(cleaned).astimezone(timezone.utc)


def format_instant(moment: datetime) -> str:
    """Render a UTC instant the way this API's windows are written."""
    return moment.astimezone(timezone.utc).strftime(_TS_FORMAT)


def shift_instant(text: str, **delta) -> str:
    """`text` moved by a `timedelta` keyword, e.g. `shift_instant(x, minutes=15)`."""
    return format_instant(parse_instant(text) + timedelta(**delta))


class SortationWorld:
    """Setup helpers bound to one API client."""

    def __init__(self, api: SortationApiClient):
        self.api = api
        self._door_slot = {}

    # ─────────────────────────────────────────────────
    # Logical clock
    # ─────────────────────────────────────────────────

    def set_clock(self, instant: str, headers: dict = None) -> dict:
        """Move the logical clock, which mutates no entity."""
        response = self.api.set_clock(instant, headers or FACILITY_ADMIN_HEADERS)
        return get_success_data(response)

    def reset_clock(self) -> dict:
        return self.set_clock(CLOCK_STARTUP_UTC)

    # ─────────────────────────────────────────────────
    # Facility surface
    # ─────────────────────────────────────────────────

    def create_center(self, headers: dict = None, **overrides) -> dict:
        response = self.api.create_sort_center(
            f.sort_center_payload(**overrides), headers or FACILITY_ADMIN_HEADERS
        )
        return get_success_data(response, 201)

    def create_door(self, center_id: str, headers: dict = None, **overrides) -> dict:
        response = self.api.create_dock_door(
            center_id, f.dock_door_payload(**overrides), headers or FACILITY_ADMIN_HEADERS
        )
        return get_success_data(response, 201)

    def create_chute(self, center_id: str, headers: dict = None, **overrides) -> dict:
        response = self.api.create_sort_chute(
            center_id, f.sort_chute_payload(**overrides), headers or FACILITY_ADMIN_HEADERS
        )
        return get_success_data(response, 201)

    def create_lane(self, center_id: str, headers: dict = None, **overrides) -> dict:
        response = self.api.create_destination_lane(
            center_id,
            f.destination_lane_payload(**overrides),
            headers or FACILITY_ADMIN_HEADERS,
        )
        return get_success_data(response, 201)

    def take_door_out_of_service(self, door_id: str) -> dict:
        response = self.api.patch_dock_door(
            door_id, {"status": "OUT_OF_SERVICE"}, FACILITY_ADMIN_HEADERS
        )
        return get_success_data(response)

    def return_door_to_service(self, door_id: str) -> dict:
        response = self.api.patch_dock_door(
            door_id, {"status": "ACTIVE"}, FACILITY_ADMIN_HEADERS
        )
        return get_success_data(response)

    def close_lane(self, lane_id: str) -> dict:
        response = self.api.patch_destination_lane(
            lane_id, {"status": "CLOSED"}, FACILITY_ADMIN_HEADERS
        )
        return get_success_data(response)

    def map_lane_to_chute(
        self,
        chute_id: str,
        lane_id: str,
        headers: dict = None,
        expected_chute_version: int = None,
        **overrides,
    ) -> dict:
        """Create a chute assignment, pinning the chute's current `version` unless
        the caller supplies a value of its own."""
        version = (
            expected_chute_version
            if expected_chute_version is not None
            else self.chute_version(chute_id)
        )
        response = self.api.create_chute_assignment(
            f.chute_assignment_payload(chute_id, lane_id, version, **overrides),
            headers or SORT_SUPERVISOR_HEADERS,
        )
        return get_success_data(response, 201)

    def setup_facility(
        self,
        automation_utilization_pct: float = 70.00,
        flex_pool_total: int = 10,
        throughput_pph: int = 1200,
        forecast_hourly_volume: int = 100,
        map_assignment: bool = True,
        center_overrides: dict = None,
    ) -> dict:
        """A commissioned building: one center, an inbound and an outbound door,
        one chute, one lane, and by default a chute assignment whose window
        covers the clock's startup instant.

        Returns a dict keyed `center`, `inbound_door`, `outbound_door`, `chute`,
        `lane` and `assignment`.
        """
        center = self.create_center(
            automation_utilization_pct=automation_utilization_pct,
            flex_pool_total=flex_pool_total,
            **(center_overrides or {}),
        )
        inbound_door = self.create_door(center["id"], door_number=1, kind="INBOUND")
        outbound_door = self.create_door(center["id"], door_number=2, kind="OUTBOUND")
        chute = self.create_chute(
            center["id"], chute_number=1, throughput_pph=throughput_pph
        )
        lane = self.create_lane(
            center["id"], forecast_hourly_volume=forecast_hourly_volume
        )
        assignment = None
        if map_assignment:
            assignment = self.map_lane_to_chute(chute["id"], lane["id"])
        return {
            "center": self.center(center["id"]),
            "inbound_door": inbound_door,
            "outbound_door": outbound_door,
            "chute": chute,
            "lane": lane,
            "assignment": assignment,
        }

    # ─────────────────────────────────────────────────
    # Inbound trailers
    # ─────────────────────────────────────────────────

    def _next_door_window(self, door_id: str) -> dict:
        """A window on `door_id` that clears the door's turnaround buffer.

        Successive bookings on one door are spaced two hours apart, which is far
        wider than any buffer these tests configure.
        """
        slot = self._door_slot.get(door_id, 0)
        self._door_slot[door_id] = slot + 1
        start = parse_instant("2026-08-01T06:00:00Z") + timedelta(hours=2 * slot)
        return {
            "window_start": format_instant(start),
            "window_end": format_instant(start + timedelta(hours=1)),
        }

    def schedule_appointment(
        self, center_id: str, door_id: str, headers: dict = None, **overrides
    ) -> dict:
        payload_overrides = dict(self._next_door_window(door_id))
        payload_overrides.update(overrides)
        response = self.api.create_trailer_appointment(
            f.trailer_appointment_payload(center_id, door_id, **payload_overrides),
            headers or INBOUND_COORDINATOR_HEADERS,
        )
        return get_success_data(response, 201)

    def arrived_appointment(self, center_id: str, door_id: str, **overrides) -> dict:
        appointment = self.schedule_appointment(center_id, door_id, **overrides)
        response = self.api.arrive_trailer_appointment(
            appointment["id"], INBOUND_COORDINATOR_HEADERS
        )
        return get_success_data(response)

    def unloading_appointment(self, center_id: str, door_id: str, **overrides) -> dict:
        appointment = self.arrived_appointment(center_id, door_id, **overrides)
        response = self.api.start_unload(appointment["id"], INBOUND_COORDINATOR_HEADERS)
        return get_success_data(response)

    def jam_held_appointment(
        self, center_id: str, door_id: str, chute_id: str, **overrides
    ) -> dict:
        appointment = self.unloading_appointment(center_id, door_id, **overrides)
        response = self.api.jam_hold(
            appointment["id"], f.jam_hold_payload(chute_id), INBOUND_COORDINATOR_HEADERS
        )
        return get_success_data(response)

    def jam_hold(self, appointment_id: str, chute_id: str, **overrides) -> dict:
        response = self.api.jam_hold(
            appointment_id,
            f.jam_hold_payload(chute_id, **overrides),
            INBOUND_COORDINATOR_HEADERS,
        )
        return get_success_data(response)

    def resume_unload(self, appointment_id: str, chute_id: str) -> dict:
        response = self.api.resume_unload(
            appointment_id, f.resume_unload_payload(chute_id), INBOUND_COORDINATOR_HEADERS
        )
        return get_success_data(response)

    def induct_packages(
        self, center_id: str, door_id: str, manifest_package_count: int, **overrides
    ) -> dict:
        """Run one trailer all the way to `UNLOADED`, inducting its manifest into
        work-in-process. Returns the terminal appointment."""
        appointment = self.unloading_appointment(
            center_id,
            door_id,
            manifest_package_count=manifest_package_count,
            **overrides,
        )
        response = self.api.complete_unload(
            appointment["id"], INBOUND_COORDINATOR_HEADERS
        )
        return get_success_data(response)

    def ensure_wip(self, center_id: str, door_id: str, wanted: int) -> dict:
        """Induct enough packages that the center's `wip_package_count` reaches
        at least `wanted`."""
        current = self.center(center_id)["wip_package_count"]
        if current < wanted:
            self.induct_packages(center_id, door_id, wanted - current)
        return self.center(center_id)

    # ─────────────────────────────────────────────────
    # Shift plans
    # ─────────────────────────────────────────────────

    def create_draft_plan(
        self, center_id: str, headers: dict = None, **overrides
    ) -> dict:
        response = self.api.create_shift_plan(
            center_id, f.shift_plan_payload(**overrides), headers or LABOR_PLANNER_HEADERS
        )
        return get_success_data(response, 201)

    def create_submitted_plan(
        self, center_id: str, submitter_id: str = None, **overrides
    ) -> dict:
        plan = self.create_draft_plan(center_id, **overrides)
        headers = (
            make_labor_planner_headers(submitter_id)
            if submitter_id
            else LABOR_PLANNER_HEADERS
        )
        response = self.api.submit_shift_plan(plan["id"], headers)
        return get_success_data(response)

    def approve_plan(
        self, plan_id: str, center_id: str, approver_id: str = None, **overrides
    ) -> dict:
        headers = (
            make_ops_manager_headers(approver_id) if approver_id else OPS_MANAGER_HEADERS
        )
        response = self.api.approve_shift_plan(
            plan_id,
            f.approve_payload(self.center_version(center_id), **overrides),
            headers,
        )
        return get_success_data(response)

    def create_approved_plan(
        self,
        center_id: str,
        submitter_id: str = None,
        approver_id: str = None,
        **overrides,
    ) -> dict:
        plan = self.create_submitted_plan(center_id, submitter_id=submitter_id, **overrides)
        return self.approve_plan(plan["id"], center_id, approver_id=approver_id)

    def reject_plan(self, plan_id: str, rejector_id: str = None, **overrides) -> dict:
        headers = (
            make_ops_manager_headers(rejector_id) if rejector_id else OPS_MANAGER_HEADERS
        )
        response = self.api.reject_shift_plan(plan_id, f.reject_payload(**overrides), headers)
        return get_success_data(response)

    def create_rejected_plan(self, center_id: str, **overrides) -> dict:
        plan = self.create_submitted_plan(center_id, **overrides)
        return self.reject_plan(plan["id"])

    def revise_plan(self, plan_id: str, **overrides) -> dict:
        response = self.api.revise_shift_plan(
            plan_id, f.revise_payload(**overrides), LABOR_PLANNER_HEADERS
        )
        return get_success_data(response)

    def close_plan(self, plan_id: str, center_id: str, **overrides) -> dict:
        response = self.api.close_shift_plan(
            plan_id,
            f.close_plan_payload(self.center_version(center_id), **overrides),
            OPS_MANAGER_HEADERS,
        )
        return get_success_data(response)

    # ─────────────────────────────────────────────────
    # Workers and attendance
    # ─────────────────────────────────────────────────

    def create_worker(self, center_id: str, headers: dict = None, **overrides) -> dict:
        response = self.api.create_worker(
            center_id, f.worker_payload(**overrides), headers or LABOR_PLANNER_HEADERS
        )
        return get_success_data(response, 201)

    def record_event(self, worker_id: str, event_type: str) -> dict:
        response = self.api.create_onboarding_event(
            worker_id, f.onboarding_event_payload(event_type), LABOR_PLANNER_HEADERS
        )
        return get_success_data(response)

    def create_cleared_worker(self, center_id: str, **overrides) -> dict:
        """A worker driven to `CLEARED`: enough to be scheduled, not enough to
        clock in."""
        worker = self.create_worker(center_id, **overrides)
        self.record_event(worker["id"], "ONBOARDING_STARTED")
        return self.record_event(worker["id"], "BACKGROUND_CLEARED")

    def create_certified_worker(
        self, center_id: str, training_sessions: int = 2, **overrides
    ) -> dict:
        """A worker driven to `CERTIFIED` through the two training sessions that
        certification demands."""
        worker = self.create_cleared_worker(center_id, **overrides)
        for _ in range(training_sessions):
            self.record_event(worker["id"], "TRAINING_SESSION_COMPLETED")
        return self.record_event(worker["id"], "CERTIFIED")

    def separate_worker(self, worker_id: str) -> dict:
        return self.record_event(worker_id, "SEPARATED")

    def create_assignment(
        self,
        plan_id: str,
        worker_id: str,
        line_chute_id: str,
        headers: dict = None,
        **overrides,
    ) -> dict:
        response = self.api.create_staff_assignment(
            f.staff_assignment_payload(plan_id, worker_id, line_chute_id, **overrides),
            headers or LABOR_PLANNER_HEADERS,
        )
        return get_success_data(response, 201)

    def check_in(self, assignment_id: str, worker_id: str) -> dict:
        response = self.api.check_in(assignment_id, make_worker_headers(worker_id))
        return get_success_data(response)

    def check_out(self, assignment_id: str, worker_id: str) -> dict:
        response = self.api.check_out(assignment_id, make_worker_headers(worker_id))
        return get_success_data(response)

    def no_show(self, assignment_id: str) -> dict:
        response = self.api.no_show(assignment_id, LABOR_PLANNER_HEADERS)
        return get_success_data(response)

    def complete_assignment_with_hours(
        self,
        plan_id: str,
        worker_id: str,
        line_chute_id: str,
        check_in_at: str,
        check_out_at: str,
        **overrides,
    ) -> dict:
        """Drive one assignment to `COMPLETED` with `worked_hours` equal to the
        span between the two supplied clock positions."""
        assignment = self.create_assignment(
            plan_id, worker_id, line_chute_id, **overrides
        )
        self.set_clock(check_in_at)
        self.check_in(assignment["id"], worker_id)
        self.set_clock(check_out_at)
        return self.check_out(assignment["id"], worker_id)

    # ─────────────────────────────────────────────────
    # Outbound loading
    # ─────────────────────────────────────────────────

    def stage_load(
        self,
        center_id: str,
        door_id: str,
        lane_id: str,
        headers: dict = None,
        **overrides,
    ) -> dict:
        response = self.api.create_outbound_load(
            f.outbound_load_payload(center_id, door_id, lane_id, **overrides),
            headers or SORT_SUPERVISOR_HEADERS,
        )
        return get_success_data(response, 201)

    def scan(self, load_id: str, **counts) -> dict:
        response = self.api.scan_packages(
            load_id, f.scan_packages_payload(**counts), SORT_SUPERVISOR_HEADERS
        )
        return get_success_data(response)

    def close_load(self, load_id: str) -> dict:
        response = self.api.close_load(load_id, SORT_SUPERVISOR_HEADERS)
        return get_success_data(response)

    def seal(self, load_id: str, **overrides) -> dict:
        response = self.api.seal_load(
            load_id, f.seal_payload(**overrides), SORT_SUPERVISOR_HEADERS
        )
        return get_success_data(response)

    def dispatch(self, load_id: str) -> dict:
        response = self.api.dispatch_load(load_id, OPS_MANAGER_HEADERS)
        return get_success_data(response)

    def create_loading_load(
        self,
        center_id: str,
        inbound_door_id: str,
        outbound_door_id: str,
        lane_id: str,
        small_count: int = 10,
        **overrides,
    ) -> dict:
        """A staged load advanced to `LOADING` by one scan, with the scanned
        packages inducted first so the conservation ledger stays balanced."""
        self.ensure_wip(center_id, inbound_door_id, small_count)
        load = self.stage_load(center_id, outbound_door_id, lane_id, **overrides)
        return self.scan(load["id"], small_count=small_count)

    def create_loaded_load(self, center_id, inbound_door_id, outbound_door_id, lane_id, **kwargs) -> dict:
        load = self.create_loading_load(
            center_id, inbound_door_id, outbound_door_id, lane_id, **kwargs
        )
        return self.close_load(load["id"])

    def create_sealed_load(self, center_id, inbound_door_id, outbound_door_id, lane_id, **kwargs) -> dict:
        """A load that is `LOADED` and `SEALED`, i.e. everything dispatch needs
        except a clock still before the cut time."""
        load = self.create_loaded_load(
            center_id, inbound_door_id, outbound_door_id, lane_id, **kwargs
        )
        return self.seal(load["id"])

    # ─────────────────────────────────────────────────
    # Exceptions and injuries
    # ─────────────────────────────────────────────────

    def create_exception(self, center_id: str, headers: dict = None, **overrides) -> dict:
        response = self.api.create_package_exception(
            f.package_exception_payload(center_id, **overrides),
            headers or SORT_SUPERVISOR_HEADERS,
        )
        return get_success_data(response, 201)

    def resolve_exception(self, exception_id: str, resolution: str, **overrides) -> dict:
        response = self.api.resolve_package_exception(
            exception_id,
            f.resolve_exception_payload(resolution, **overrides),
            SORT_SUPERVISOR_HEADERS,
        )
        return get_success_data(response)

    def file_injury(
        self, center_id: str, worker_id: str, headers: dict = None, **overrides
    ) -> dict:
        response = self.api.create_injury_report(
            f.injury_report_payload(center_id, worker_id, **overrides),
            headers or SORT_SUPERVISOR_HEADERS,
        )
        return get_success_data(response, 201)

    def close_injury(self, report_id: str, lost_time_days: int = 0) -> dict:
        response = self.api.close_injury_report(
            report_id, f.close_injury_payload(lost_time_days), OPS_MANAGER_HEADERS
        )
        return get_success_data(response)

    def freeze_center(self, center_id: str, worker_id: str = None) -> dict:
        """Freeze a center the fastest way the PRD allows: one open `SERIOUS`
        injury. Returns the report, which is how the caller thaws it again."""
        if worker_id is None:
            worker_id = self.create_worker(center_id)["id"]
        return self.file_injury(center_id, worker_id, severity="SERIOUS")

    # ─────────────────────────────────────────────────
    # Read-back
    # ─────────────────────────────────────────────────

    def center(self, center_id: str) -> dict:
        return get_success_data(self.api.get_sort_center(center_id, FACILITY_ADMIN_HEADERS))

    def center_version(self, center_id: str) -> int:
        return self.center(center_id)["version"]

    def door(self, door_id: str) -> dict:
        return get_success_data(self.api.get_dock_door(door_id, FACILITY_ADMIN_HEADERS))

    def chute(self, chute_id: str) -> dict:
        return get_success_data(self.api.get_sort_chute(chute_id, FACILITY_ADMIN_HEADERS))

    def chute_version(self, chute_id: str) -> int:
        return self.chute(chute_id)["version"]

    def lane(self, lane_id: str) -> dict:
        return get_success_data(
            self.api.get_destination_lane(lane_id, FACILITY_ADMIN_HEADERS)
        )

    def assignment(self, assignment_id: str) -> dict:
        return get_success_data(
            self.api.get_chute_assignment(assignment_id, SORT_SUPERVISOR_HEADERS)
        )

    def appointment(self, appointment_id: str) -> dict:
        return get_success_data(
            self.api.get_trailer_appointment(appointment_id, INBOUND_COORDINATOR_HEADERS)
        )

    def plan(self, plan_id: str) -> dict:
        return get_success_data(self.api.get_shift_plan(plan_id, LABOR_PLANNER_HEADERS))

    def worker(self, worker_id: str) -> dict:
        return get_success_data(self.api.get_worker(worker_id, LABOR_PLANNER_HEADERS))

    def staff_assignment(self, assignment_id: str) -> dict:
        return get_success_data(
            self.api.get_staff_assignment(assignment_id, LABOR_PLANNER_HEADERS)
        )

    def load(self, load_id: str) -> dict:
        return get_success_data(
            self.api.get_outbound_load(load_id, SORT_SUPERVISOR_HEADERS)
        )

    def exception(self, exception_id: str) -> dict:
        return get_success_data(
            self.api.get_package_exception(exception_id, SORT_SUPERVISOR_HEADERS)
        )

    def injury(self, report_id: str) -> dict:
        return get_success_data(
            self.api.get_injury_report(report_id, SORT_SUPERVISOR_HEADERS)
        )

    def all_lanes(self, center_id: str) -> list:
        data, _ = validate_paginated(
            self.api.list_destination_lanes(center_id, FACILITY_ADMIN_HEADERS, limit=100)
        )
        return data

    def all_plans(self, center_id: str) -> list:
        data, _ = validate_paginated(
            self.api.list_shift_plans(center_id, LABOR_PLANNER_HEADERS, limit=100)
        )
        return data

    def all_chutes(self, center_id: str) -> list:
        data, _ = validate_paginated(
            self.api.list_sort_chutes(center_id, FACILITY_ADMIN_HEADERS, limit=100)
        )
        return data

    # ─────────────────────────────────────────────────
    # Ledgers
    # ─────────────────────────────────────────────────

    def assert_ledgers(self, center_id: str):
        """Assert both conservation identities of PRD §2.8 on a live center."""
        center = self.center(center_id)
        assert_package_conservation(center, self.all_lanes(center_id))
        assert_flex_pool_conservation(center, self.all_plans(center_id))
        return center


# ─── pytest fixtures ──────────────────────────────────

@pytest.fixture
def api() -> SortationApiClient:
    """A client pointed at the freshly restarted server for this test."""
    return SortationApiClient()


@pytest.fixture
def world(api) -> SortationWorld:
    """Composite setup helpers bound to the `api` client."""
    return SortationWorld(api)


@pytest.fixture
def facility(world) -> dict:
    """A commissioned building on the mid throughput tier: center at automation
    70 with a ten-body flex bench, an inbound door, an outbound door, one chute
    rated 1,200 packages per hour, one lane, and a mapping between them.
    """
    return world.setup_facility()
