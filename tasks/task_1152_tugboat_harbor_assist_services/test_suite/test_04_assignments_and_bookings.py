"""Tug assignments and pilot bookings: window conflicts, buffers, licenses, OCC."""
import pytest

from test_helpers import (
    TEST_USERS,
    confirm_job_order,
    create_job_order,
    create_pilot,
    create_tariff_rate,
    create_tug,
    create_vessel,
    get_job,
    propose_assignment,
    propose_pilot_booking,
    record_passed_inspection,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import make_tug_captain_headers


class TestTugWindowHalfOpenAdjacency:
    """Resource Tug with strict half-open interval semantics."""

    def _setup_three_jobs(self):
        tug = create_tug(name="Tug Atlas", bollard_pull_tons=60.0)
        vessel = create_vessel(name="MV Aurora", imo_number="IMO9074729")
        tariff = create_tariff_rate(tariff_code="TAR-DOCK-01")
        set_clock("2026-06-01T00:00:00Z")
        job1 = create_job_order(
            vessel["id"],
            tariff["id"],
            scheduled_start="2026-06-01T08:00:00Z",
            scheduled_end="2026-06-01T10:00:00Z",
        )
        propose_assignment(
            job1["id"],
            tug["id"],
            job1["version"],
            window_start="2026-06-01T08:00:00Z",
            window_end="2026-06-01T10:00:00Z",
        )
        job2 = create_job_order(
            vessel["id"],
            tariff["id"],
            scheduled_start="2026-06-01T10:00:00Z",
            scheduled_end="2026-06-01T12:00:00Z",
        )
        job3 = create_job_order(
            vessel["id"],
            tariff["id"],
            scheduled_start="2026-06-01T09:30:00Z",
            scheduled_end="2026-06-01T11:00:00Z",
        )
        return tug, vessel, tariff, job1, job2, job3

    def test_adjacent_assignment_accepted(self, api):
        """PRD §3.3: "strict adjacency, where the new window starts exactly when an
        existing one ends, is allowed."

        Design: Difficulty/resource_temporal_overlap/tug_window_half_open_adjacency
        """
        tug, vessel, tariff, job1, job2, job3 = self._setup_three_jobs()
        res = api.create_tug_assignment(
            {
                "job_order_id": job2["id"],
                "tug_id": tug["id"],
                "window_start": "2026-06-01T10:00:00Z",
                "window_end": "2026-06-01T12:00:00Z",
                "expected_job_order_version": job2["version"],
            },
            TEST_USERS["port_dispatcher_headers"],
        )
        asg2 = validate_success(res, 201)
        assert asg2["status"] == "PROPOSED"

    def test_overlapping_assignment_rejected(self, api):
        """PRD §3.3: "the proposed window must not overlap — under the half-open
        convention of §2.4 — any existing assignment of the same tug in `PROPOSED`,
        `CONFIRMED`, or `ACTIVE` status ... A clash is rejected with
        `ERR_TUG_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/tug_window_half_open_adjacency
        """
        tug, vessel, tariff, job1, job2, job3 = self._setup_three_jobs()
        res = api.create_tug_assignment(
            {
                "job_order_id": job3["id"],
                "tug_id": tug["id"],
                "window_start": "2026-06-01T09:30:00Z",
                "window_end": "2026-06-01T11:00:00Z",
                "expected_job_order_version": job3["version"],
            },
            TEST_USERS["port_dispatcher_headers"],
        )
        validate_error(res, "ERR_TUG_WINDOW_CONFLICT")


class TestPilotTurnaroundBuffer:
    """Resource Pilot with a 60-minute buffered interval."""

    def _setup_booked_pilot(self):
        vessel = create_vessel(name="MV Aurora", imo_number="IMO9074729")
        pilot = create_pilot(name="Pilot Reyes", license_class="CLASS_I")
        tariff = create_tariff_rate(tariff_code="TAR-DOCK-01")
        set_clock("2026-06-01T00:00:00Z")
        job1 = create_job_order(
            vessel["id"],
            tariff["id"],
            scheduled_start="2026-06-01T08:00:00Z",
            scheduled_end="2026-06-01T10:00:00Z",
        )
        booking1 = propose_pilot_booking(
            job1["id"],
            pilot["id"],
            window_start="2026-06-01T08:00:00Z",
            window_end="2026-06-01T10:00:00Z",
        )
        job2 = create_job_order(
            vessel["id"],
            tariff["id"],
            scheduled_start="2026-06-01T11:00:00Z",
            scheduled_end="2026-06-01T12:00:00Z",
        )
        job3 = create_job_order(
            vessel["id"],
            tariff["id"],
            scheduled_start="2026-06-01T10:30:00Z",
            scheduled_end="2026-06-01T11:30:00Z",
        )
        return pilot, booking1, job2, job3

    def test_sixty_minute_gap_accepted(self, api):
        """PRD §3.4: "the new window must start at least sixty minutes after the
        existing window ends, or end at least sixty minutes before the existing
        window starts."

        Design: Difficulty/resource_temporal_overlap/pilot_turnaround_buffer_gap_semantics
        """
        pilot, booking1, job2, job3 = self._setup_booked_pilot()
        res = api.create_pilot_booking(
            {
                "job_order_id": job2["id"],
                "pilot_id": pilot["id"],
                "window_start": "2026-06-01T11:00:00Z",
                "window_end": "2026-06-01T12:00:00Z",
            },
            TEST_USERS["port_dispatcher_headers"],
        )
        booking2 = validate_success(res, 201)
        assert booking2["status"] == "REQUESTED"

    def test_thirty_minute_gap_rejected(self, api):
        """PRD §3.4: "A booking that crowds that buffer is rejected with
        `ERR_PILOT_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/pilot_turnaround_buffer_gap_semantics
        """
        pilot, booking1, job2, job3 = self._setup_booked_pilot()
        res = api.create_pilot_booking(
            {
                "job_order_id": job3["id"],
                "pilot_id": pilot["id"],
                "window_start": "2026-06-01T10:30:00Z",
                "window_end": "2026-06-01T11:30:00Z",
            },
            TEST_USERS["port_dispatcher_headers"],
        )
        validate_error(res, "ERR_PILOT_WINDOW_CONFLICT")


class TestDuplicateTugAssignment:
    def test_duplicate_tug_assignment_returns_duplicate_error(self, api):
        """PRD §3.3: "the job must not already hold a `PROPOSED`, `CONFIRMED`, or
        `ACTIVE` assignment for the same tug; the duplicate is rejected with
        `ERR_DUPLICATE_TUG_ASSIGNMENT`."

        Design: Corner/validations/duplicate_tug_assignment_returns_duplicate_error
        """
        tug = create_tug(name="Tug Atlas", bollard_pull_tons=60.0)
        vessel = create_vessel(name="MV Aurora", imo_number="IMO9074729")
        tariff = create_tariff_rate(tariff_code="TAR-DOCK-01")
        job = create_job_order(
            vessel["id"],
            tariff["id"],
            scheduled_start="2026-06-01T08:00:00Z",
            scheduled_end="2026-06-01T10:00:00Z",
        )
        job = confirm_job_order(job["id"])
        propose_assignment(
            job["id"],
            tug["id"],
            job["version"],
            window_start="2026-06-01T08:00:00Z",
            window_end="2026-06-01T10:00:00Z",
        )
        job = get_job(job["id"])
        res = api.create_tug_assignment(
            {
                "job_order_id": job["id"],
                "tug_id": tug["id"],
                "window_start": "2026-06-01T12:00:00Z",
                "window_end": "2026-06-01T14:00:00Z",
                "expected_job_order_version": job["version"],
            },
            TEST_USERS["port_dispatcher_headers"],
        )
        validate_error(res, "ERR_DUPLICATE_TUG_ASSIGNMENT")


class TestAssignmentConfirmGearGate:
    def test_confirm_with_expired_inspection_returns_gear_overdue(self, api):
        """PRD §3.3: "the tug's most recent gear inspection — the latest by
        `inspected_at`, ties broken by later `created_at` — must show `outcome`
        `PASSED`, and its `next_due_at` must lie strictly after the current
        logical-clock reading. A tug whose latest inspection failed, or whose
        inspection has lapsed past its due instant, cannot be confirmed; the
        rejection is `ERR_GEAR_INSPECTION_OVERDUE`."

        Design: Corner/validations/confirm_with_expired_inspection_returns_gear_overdue
        """
        tug = create_tug(name="Tug Atlas", bollard_pull_tons=60.0)
        vessel = create_vessel(name="MV Aurora", imo_number="IMO9074729")
        tariff = create_tariff_rate(tariff_code="TAR-DOCK-01")
        set_clock("2026-06-01T00:00:00Z")
        record_passed_inspection(
            tug["id"],
            inspected_at="2026-04-01T00:00:00Z",
            next_due_at="2026-05-20T00:00:00Z",
        )
        job = create_job_order(
            vessel["id"],
            tariff["id"],
            scheduled_start="2026-06-01T08:00:00Z",
            scheduled_end="2026-06-01T10:00:00Z",
        )
        job = confirm_job_order(job["id"])
        asg = propose_assignment(
            job["id"],
            tug["id"],
            job["version"],
            window_start="2026-06-01T08:00:00Z",
            window_end="2026-06-01T10:00:00Z",
        )
        res = api.confirm_tug_assignment(asg["id"], make_tug_captain_headers(tug["id"]))
        validate_error(res, "ERR_GEAR_INSPECTION_OVERDUE")


class TestPilotLicenseGate:
    def test_class_three_pilot_on_towage_returns_license_insufficient(self, api):
        """PRD §3.4: "`TOWAGE` and `ESCORT` demand `CLASS_I`; `DOCKING` and
        `UNDOCKING` accept `CLASS_I` or `CLASS_II`; `SHIFTING` is open to any class.
        An under-licensed booking is rejected with `ERR_PILOT_LICENSE_INSUFFICIENT`."

        Design: Corner/validations/class_three_pilot_on_towage_returns_license_insufficient
        """
        vessel = create_vessel(name="MV Aurora", imo_number="IMO9074729")
        pilot3 = create_pilot(name="Pilot Quinn", license_class="CLASS_III")
        tariff = create_tariff_rate(
            tariff_code="TAR-TOW-01",
            maneuver_type="TOWAGE",
            base_fee_cents=900000,
            standby_block_rate_cents=40000,
        )
        job = create_job_order(
            vessel["id"],
            tariff["id"],
            maneuver_type="TOWAGE",
            scheduled_start="2026-06-01T08:00:00Z",
            scheduled_end="2026-06-01T14:00:00Z",
        )
        res = api.create_pilot_booking(
            {
                "job_order_id": job["id"],
                "pilot_id": pilot3["id"],
                "window_start": "2026-06-01T08:00:00Z",
                "window_end": "2026-06-01T14:00:00Z",
            },
            TEST_USERS["port_dispatcher_headers"],
        )
        validate_error(res, "ERR_PILOT_LICENSE_INSUFFICIENT")


class TestPilotBoardGate:
    def test_board_before_dispatch_returns_invalid_state(self, api):
        """PRD §3.4: "boarding while the job is in any other state is refused with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/board_before_dispatch_returns_invalid_state
        """
        from test_helpers import (
            confirm_booking,
            confirm_job_order,
            create_job_order,
            create_pilot,
            create_tariff_rate,
            create_vessel,
            propose_pilot_booking,
        )
        from test_helpers.test_users import make_pilot_headers

        vessel = create_vessel(name="MV Aurora", imo_number="IMO9074729")
        pilot = create_pilot(name="Pilot Reyes", license_class="CLASS_I")
        tariff = create_tariff_rate(tariff_code="TAR-DOCK-01")
        job = create_job_order(
            vessel["id"],
            tariff["id"],
            scheduled_start="2026-06-01T08:00:00Z",
            scheduled_end="2026-06-01T10:00:00Z",
        )
        confirm_job_order(job["id"])
        booking = propose_pilot_booking(
            job["id"],
            pilot["id"],
            window_start="2026-06-01T08:00:00Z",
            window_end="2026-06-01T10:00:00Z",
        )
        confirm_booking(booking["id"], pilot["id"])
        res = api.board_pilot_booking(
            booking["id"], make_pilot_headers(pilot["id"])
        )
        validate_error(res, "ERR_INVALID_STATE")
        after = validate_success(
            api.get_pilot_booking(
                booking["id"], TEST_USERS["port_dispatcher_headers"]
            ),
            200,
        )
        assert after["status"] == "CONFIRMED"


class TestAssignmentCreateOcc:
    def test_assignment_create_with_stale_job_version_returns_412(self, api):
        """PRD §2.6: "creating a tug assignment likewise requires
        `expected_job_order_version` equal to the current `version` of the job it
        attaches to ... the write is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/endpoints/assignment_create_with_stale_job_version_returns_412
        """
        tug = create_tug(name="Tug Atlas", bollard_pull_tons=60.0)
        vessel = create_vessel(name="MV Aurora", imo_number="IMO9074729")
        tariff = create_tariff_rate(tariff_code="TAR-DOCK-01")
        job = create_job_order(
            vessel["id"],
            tariff["id"],
            scheduled_start="2026-06-01T08:00:00Z",
            scheduled_end="2026-06-01T10:00:00Z",
        )
        assert job["version"] == 1
        confirm_job_order(job["id"])  # bumps version to 2
        res = api.create_tug_assignment(
            {
                "job_order_id": job["id"],
                "tug_id": tug["id"],
                "window_start": "2026-06-01T08:00:00Z",
                "window_end": "2026-06-01T10:00:00Z",
                "expected_job_order_version": 1,
            },
            TEST_USERS["port_dispatcher_headers"],
        )
        validate_error(res, "ERR_STALE_VERSION")


class TestAssignmentFiltering:
    def test_filtered_list_finds_assignments_by_tug(self, api, port_dispatcher_headers):
        """PRD §3.3: "Assignments can be listed filtered by `job_order_id`,
        `tug_id`, or `status`."

        Design: Corner/endpoints/filtered_list_finds_assignments_by_tug
        """
        tug = create_tug(name="Tug Atlas", bollard_pull_tons=60.0)
        vessel = create_vessel(name="MV Aurora", imo_number="IMO9074729")
        tariff = create_tariff_rate(tariff_code="TAR-DOCK-01")
        job = create_job_order(
            vessel["id"],
            tariff["id"],
            scheduled_start="2026-06-01T08:00:00Z",
            scheduled_end="2026-06-01T10:00:00Z",
        )
        propose_assignment(
            job["id"],
            tug["id"],
            job["version"],
            window_start="2026-06-01T08:00:00Z",
            window_end="2026-06-01T10:00:00Z",
        )
        res = api.list_tug_assignments(
            port_dispatcher_headers, params={"tug_id": tug["id"]}
        )
        data = validate_success(res, 200)
        assert isinstance(data, list) and len(data) == 1
        assert data[0]["tug_id"] == tug["id"]
        assert data[0]["job_order_id"] == job["id"]
