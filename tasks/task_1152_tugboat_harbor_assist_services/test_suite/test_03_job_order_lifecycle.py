"""JobOrder lifecycle: initial state, invalid transitions, version increments, OCC."""
import pytest

from test_helpers import (
    TEST_USERS,
    create_job_order_payload,
    create_tariff_rate,
    create_vessel,
    create_job_order,
    get_job,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import make_vessel_agent_headers


class TestJobInitialState:
    def test_job_order_initial_state_requested(self, api):
        """PRD §3.2: "The new order enters life in `REQUESTED` status."

        Design: Corner/state_machines/job_order_initial_state_requested
        """
        vessel = create_vessel(name="MV Aurora", imo_number="IMO9074729")
        tariff = create_tariff_rate(tariff_code="TAR-DOCK-01")
        job = create_job_order(
            vessel["id"],
            tariff["id"],
            scheduled_start="2026-06-01T08:00:00Z",
            scheduled_end="2026-06-01T10:00:00Z",
        )
        assert job["status"] == "REQUESTED"


class TestInvalidStart:
    def test_start_from_requested_returns_invalid_state(self, api, port_dispatcher_headers):
        """PRD §3.8: "Starting a dispatched job is the dispatcher's signal that work
        has begun: the job moves `DISPATCHED` → `IN_PROGRESS`."
        PRD §2.8 stage 7: "the target's current state is a legitimate starting state
        for the attempted transition ... else `ERR_INVALID_STATE`."

        Design: Corner/state_machines/start_from_requested_returns_invalid_state
        """
        vessel = create_vessel(name="MV Aurora", imo_number="IMO9074729")
        tariff = create_tariff_rate(tariff_code="TAR-DOCK-01")
        job = create_job_order(
            vessel["id"],
            tariff["id"],
            scheduled_start="2026-06-01T08:00:00Z",
            scheduled_end="2026-06-01T10:00:00Z",
        )
        res = api.start_job_order(job["id"], port_dispatcher_headers)
        validate_error(res, "ERR_INVALID_STATE")
        after = get_job(job["id"])
        assert after["status"] == "REQUESTED"
        assert after.get("actual_start") is None


class TestJobVersionIncrements:
    def test_job_version_increments_on_each_mutation(self, api):
        """PRD §2.5: "an integer that increments by one on every mutation of the
        resource — including mutations delivered by a cascade originating on another
        resource."

        Design: Corner/endpoints/job_version_increments_on_each_mutation
        """
        vessel = create_vessel(name="MV Aurora", imo_number="IMO9074729")
        tariff = create_tariff_rate(tariff_code="TAR-DOCK-01")
        job = create_job_order(
            vessel["id"],
            tariff["id"],
            scheduled_start="2026-06-01T08:00:00Z",
            scheduled_end="2026-06-01T10:00:00Z",
        )
        assert job["version"] == 1
        job = validate_success(
            api.confirm_job_order(job["id"], TEST_USERS["port_dispatcher_headers"]),
            200,
        )
        assert job["version"] == 2
        job = validate_success(
            api.amend_job_order(
                job["id"],
                {
                    "expected_job_order_version": 2,
                    "scheduled_end": "2026-06-01T11:00:00Z",
                },
                make_vessel_agent_headers(vessel["id"]),
            ),
            200,
        )
        assert job["version"] == 3


class TestJobAmendOcc:
    def test_amend_with_stale_job_version_returns_412(self, api):
        """PRD §2.6: "Amending a job order requires the request to carry
        `expected_job_order_version` equal to that job's current `version` ... the
        write is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/endpoints/amend_with_stale_job_version_returns_412
        """
        vessel = create_vessel(name="MV Aurora", imo_number="IMO9074729")
        tariff = create_tariff_rate(tariff_code="TAR-DOCK-01")
        job = create_job_order(
            vessel["id"],
            tariff["id"],
            scheduled_start="2026-06-01T08:00:00Z",
            scheduled_end="2026-06-01T10:00:00Z",
        )
        assert job["version"] == 1
        validate_success(
            api.confirm_job_order(job["id"], TEST_USERS["port_dispatcher_headers"]),
            200,
        )
        # Current version is now 2; submit a stale expected version 1
        res = api.amend_job_order(
            job["id"],
            {
                "expected_job_order_version": 1,
                "scheduled_end": "2026-06-01T11:00:00Z",
            },
            make_vessel_agent_headers(vessel["id"]),
        )
        validate_error(res, "ERR_STALE_VERSION")


class TestJobWindowValidation:
    def test_job_scheduled_in_past_returns_window_in_past(self, api):
        """PRD §3.2: "at placement time the scheduled start must not lie strictly
        before the current logical-clock reading: a start exactly at the current
        instant is acceptable, anything earlier is rejected with
        `ERR_WINDOW_IN_PAST`."

        Design: Corner/validations/job_scheduled_in_past_returns_window_in_past
        """
        vessel = create_vessel(name="MV Aurora", imo_number="IMO9074729")
        tariff = create_tariff_rate(tariff_code="TAR-DOCK-01")
        set_clock("2026-06-01T00:00:00Z")
        res = api.create_job_order(
            create_job_order_payload(
                vessel["id"],
                tariff["id"],
                scheduled_start="2026-05-30T08:00:00Z",
                scheduled_end="2026-05-30T10:00:00Z",
            ),
            make_vessel_agent_headers(vessel["id"]),
        )
        validate_error(res, "ERR_WINDOW_IN_PAST")

    def test_job_end_not_after_start_returns_job_window_invalid(self, api):
        """PRD §3.2: "The scheduled end must be strictly after the scheduled start —
        a malformed window is rejected with `ERR_JOB_WINDOW_INVALID`."

        Design: Corner/validations/job_end_not_after_start_returns_job_window_invalid
        """
        vessel = create_vessel(name="MV Aurora", imo_number="IMO9074729")
        tariff = create_tariff_rate(tariff_code="TAR-DOCK-01")
        res = api.create_job_order(
            create_job_order_payload(
                vessel["id"],
                tariff["id"],
                scheduled_start="2026-06-01T08:00:00Z",
                scheduled_end="2026-06-01T08:00:00Z",
            ),
            make_vessel_agent_headers(vessel["id"]),
        )
        validate_error(res, "ERR_JOB_WINDOW_INVALID")


class TestTariffWindow:
    def test_tariff_outside_effective_window_returns_tariff_not_effective(self, api):
        """PRD §3.2: "The referenced tariff entry must be in force at the scheduled
        start, else `ERR_TARIFF_NOT_EFFECTIVE`."
        PRD §3.1: "a job priced against the entry must have its scheduled start on or
        after `effective_from` and on or before `effective_to`."

        Design: Corner/calculations/tariff_outside_effective_window_returns_tariff_not_effective
        """
        vessel = create_vessel(name="MV Aurora", imo_number="IMO9074729")
        tariff = create_tariff_rate(
            tariff_code="TAR-DOCK-H1",
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2026-06-30T23:59:59Z",
        )
        res = api.create_job_order(
            create_job_order_payload(
                vessel["id"],
                tariff["id"],
                scheduled_start="2026-08-01T08:00:00Z",
                scheduled_end="2026-08-01T10:00:00Z",
            ),
            make_vessel_agent_headers(vessel["id"]),
        )
        validate_error(res, "ERR_TARIFF_NOT_EFFECTIVE")


class TestLogicalClockDefault:
    def test_clock_default_is_2026_05_01_for_window_checks(self, api):
        """PRD §2.4: "Before it is ever set, the logical clock reads exactly
        2026-05-01T00:00:00Z."
        PRD §3.2: "at placement time the scheduled start must not lie strictly
        before the current logical-clock reading: a start exactly at the current
        instant is acceptable, anything earlier is rejected with
        `ERR_WINDOW_IN_PAST`."

        Design: Corner/endpoints/clock_default_is_2026_05_01_for_window_checks
        """
        vessel = create_vessel(name="MV Aurora", imo_number="IMO9074729")
        tariff = create_tariff_rate(tariff_code="TAR-DOCK-01")
        # Clock is NOT set: it must read 2026-05-01T00:00:00Z by default.
        past_res = api.create_job_order(
            create_job_order_payload(
                vessel["id"],
                tariff["id"],
                scheduled_start="2026-04-15T08:00:00Z",
                scheduled_end="2026-04-15T10:00:00Z",
            ),
            make_vessel_agent_headers(vessel["id"]),
        )
        validate_error(past_res, "ERR_WINDOW_IN_PAST")

        future_res = api.create_job_order(
            create_job_order_payload(
                vessel["id"],
                tariff["id"],
                scheduled_start="2026-06-01T08:00:00Z",
                scheduled_end="2026-06-01T10:00:00Z",
            ),
            make_vessel_agent_headers(vessel["id"]),
        )
        job = validate_success(future_res, 201)
        assert job["status"] == "REQUESTED"
