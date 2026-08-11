"""Dispatch gates and validation-priority pairs: bollard pull, pilot confirmed,
weather clearance, terminal guard."""
import pytest

from test_helpers import (
    TEST_USERS,
    cancel_job_order,
    confirm_assignment,
    confirm_booking,
    confirm_job_order,
    create_job_order,
    create_pilot,
    create_tariff_rate,
    create_tug,
    create_vessel,
    create_weather_restriction,
    get_job,
    propose_assignment,
    propose_pilot_booking,
    record_failed_inspection,
    record_passed_inspection,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import make_tug_captain_headers


class TestBollardPullBoundary:
    """Boundary precision on the bollard-pull metric at dispatch."""

    def _setup_job_with_tug(
        self, tug_bollard, job_start, job_end, tug_name, tariff, vessel, pilot
    ):
        job = create_job_order(
            vessel["id"],
            tariff["id"],
            scheduled_start=job_start,
            scheduled_end=job_end,
        )
        job = confirm_job_order(job["id"])
        asg = propose_assignment(
            job["id"],
            tug_bollard["id"],
            job["version"],
            window_start=job_start,
            window_end=job_end,
        )
        confirm_assignment(asg["id"], tug_bollard["id"])
        booking = propose_pilot_booking(
            job["id"],
            pilot["id"],
            window_start=job_start,
            window_end=job_end,
        )
        confirm_booking(booking["id"], pilot["id"])
        return job

    def test_exact_equality_dispatches(self, api):
        """PRD §3.3: "the `bollard_pull_tons` of the tugs on the job's `CONFIRMED`
        assignments must sum to at least the job's `required_bollard_pull_tons`,
        with exact equality sufficient, else `ERR_INSUFFICIENT_BOLLARD_PULL`."

        Design: Difficulty/boundary_precision_check/bollard_pull_exact_equality_dispatches
        """
        # Vessel DWT 40000 LOA 180.0 -> required = 40000 * 1.5 / 1000 = 60.0
        tug_a = create_tug(name="Tug Atlas", bollard_pull_tons=60.0)
        vessel = create_vessel(
            name="MV Aurora", imo_number="IMO9074729",
            deadweight_tonnage=40000, loa_meters=180.0,
        )
        pilot = create_pilot(name="Pilot Reyes", license_class="CLASS_I")
        tariff = create_tariff_rate(tariff_code="TAR-DOCK-01")
        set_clock("2026-06-01T00:00:00Z")
        record_passed_inspection(tug_a["id"])
        job = self._setup_job_with_tug(
            tug_a, "2026-06-01T08:00:00Z", "2026-06-01T10:00:00Z",
            "Tug Atlas", tariff, vessel, pilot,
        )
        assert job["required_bollard_pull_tons"] == pytest.approx(60.0)
        res = api.dispatch_job_order(job["id"], TEST_USERS["port_dispatcher_headers"])
        dispatched = validate_success(res, 200)
        assert dispatched["status"] == "DISPATCHED"

    def test_one_tenth_below_required_rejected(self, api):
        """PRD §3.3: "the `bollard_pull_tons` of the tugs on the job's `CONFIRMED`
        assignments must sum to at least the job's `required_bollard_pull_tons`,
        with exact equality sufficient, else `ERR_INSUFFICIENT_BOLLARD_PULL`."

        Design: Difficulty/boundary_precision_check/bollard_pull_exact_equality_dispatches
        """
        tug_b = create_tug(
            name="Tug Brutus",
            bollard_pull_tons=59.9,
            horsepower=4900,
            hourly_rate_cents=110000,
            insured_value_cents=19000000,
        )
        vessel = create_vessel(
            name="MV Aurora", imo_number="IMO9074729",
            deadweight_tonnage=40000, loa_meters=180.0,
        )
        pilot = create_pilot(name="Pilot Reyes", license_class="CLASS_I")
        tariff = create_tariff_rate(tariff_code="TAR-DOCK-01")
        set_clock("2026-06-01T00:00:00Z")
        record_passed_inspection(tug_b["id"])
        job = self._setup_job_with_tug(
            tug_b, "2026-06-01T12:00:00Z", "2026-06-01T14:00:00Z",
            "Tug Brutus", tariff, vessel, pilot,
        )
        assert job["required_bollard_pull_tons"] == pytest.approx(60.0)
        res = api.dispatch_job_order(job["id"], TEST_USERS["port_dispatcher_headers"])
        validate_error(res, "ERR_INSUFFICIENT_BOLLARD_PULL")


class TestDispatchRequiresConfirmedPilot:
    """Cross-entity gate: JobOrder dispatch requires a CONFIRMED PilotBooking."""

    def _setup_job_with_unconfirmed_booking(self):
        tug = create_tug(name="Tug Atlas", bollard_pull_tons=60.0)
        vessel = create_vessel(name="MV Aurora", imo_number="IMO9074729")
        pilot = create_pilot(name="Pilot Reyes", license_class="CLASS_I")
        tariff = create_tariff_rate(tariff_code="TAR-DOCK-01")
        set_clock("2026-06-01T00:00:00Z")
        job = create_job_order(
            vessel["id"],
            tariff["id"],
            scheduled_start="2026-06-01T08:00:00Z",
            scheduled_end="2026-06-01T10:00:00Z",
        )
        job = confirm_job_order(job["id"])
        record_passed_inspection(tug["id"])
        asg = propose_assignment(
            job["id"],
            tug["id"],
            job["version"],
            window_start="2026-06-01T08:00:00Z",
            window_end="2026-06-01T10:00:00Z",
        )
        confirm_assignment(asg["id"], tug["id"])
        booking = propose_pilot_booking(
            job["id"],
            pilot["id"],
            window_start="2026-06-01T08:00:00Z",
            window_end="2026-06-01T10:00:00Z",
        )
        return job, booking

    def test_dispatch_rejected_when_booking_only_requested(self, api):
        """PRD §3.3: "At least one pilot booking on the job must be `CONFIRMED`,
        else `ERR_PILOT_BOOKING_NOT_CONFIRMED`."

        Design: Difficulty/cross_entity_state_dependency/dispatch_requires_confirmed_pilot_booking
        """
        job, booking = self._setup_job_with_unconfirmed_booking()
        res = api.dispatch_job_order(job["id"], TEST_USERS["port_dispatcher_headers"])
        validate_error(res, "ERR_PILOT_BOOKING_NOT_CONFIRMED")

    def test_job_remains_confirmed_after_rejected_dispatch(self, api):
        """PRD §3.3: "At least one pilot booking on the job must be `CONFIRMED`,
        else `ERR_PILOT_BOOKING_NOT_CONFIRMED`."
        PRD §3.2: a rejected dispatch leaves the job in its prior state.

        Design: Difficulty/cross_entity_state_dependency/dispatch_requires_confirmed_pilot_booking
        """
        job, booking = self._setup_job_with_unconfirmed_booking()
        res = api.dispatch_job_order(job["id"], TEST_USERS["port_dispatcher_headers"])
        validate_error(res, "ERR_PILOT_BOOKING_NOT_CONFIRMED")
        after = get_job(job["id"])
        assert after["status"] == "CONFIRMED"


class TestAssignmentConfirmRequiresTugAvailable:
    """Cross-entity gate: TugAssignment confirmation requires the tug AVAILABLE."""

    def _setup_assignment_then_restrict_tug(self):
        tug = create_tug(name="Tug Atlas", bollard_pull_tons=60.0)
        vessel = create_vessel(name="MV Aurora", imo_number="IMO9074729")
        tariff = create_tariff_rate(tariff_code="TAR-DOCK-01")
        set_clock("2026-06-01T00:00:00Z")
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
        record_failed_inspection(
            tug["id"],
            inspection_item="WINCH",
            inspected_at="2026-05-20T00:00:00Z",
            next_due_at="2026-06-20T00:00:00Z",
        )
        return tug, asg

    def test_confirm_rejected_when_tug_restricted(self, api):
        """PRD §3.3: "Confirmation re-verifies that the tug is `AVAILABLE` (else
        `ERR_TUG_UNAVAILABLE`)."

        Design: Difficulty/cross_entity_state_dependency/assignment_confirm_requires_tug_available
        """
        tug, asg = self._setup_assignment_then_restrict_tug()
        res = api.confirm_tug_assignment(asg["id"], make_tug_captain_headers(tug["id"]))
        validate_error(res, "ERR_TUG_UNAVAILABLE")

    def test_assignment_remains_proposed_after_rejected_confirm(self, api):
        """PRD §3.3: "Confirmation re-verifies that the tug is `AVAILABLE` (else
        `ERR_TUG_UNAVAILABLE`)" — a rejected confirmation leaves the assignment in
        `PROPOSED`.

        Design: Difficulty/cross_entity_state_dependency/assignment_confirm_requires_tug_available
        """
        tug, asg = self._setup_assignment_then_restrict_tug()
        res = api.confirm_tug_assignment(asg["id"], make_tug_captain_headers(tug["id"]))
        validate_error(res, "ERR_TUG_UNAVAILABLE")
        after = validate_success(
            api.get_tug_assignment(asg["id"], TEST_USERS["port_dispatcher_headers"]),
            200,
        )
        assert after["status"] == "PROPOSED"


class TestTerminalBeatsWeatherSafety:
    """Priority pair: terminal-state guard (stage 6) outranks weather safety (stage 8)."""

    def _setup_cancelled_job_with_active_restriction(self):
        vessel = create_vessel(name="MV Aurora", imo_number="IMO9074729")
        tariff = create_tariff_rate(tariff_code="TAR-DOCK-01")
        set_clock("2026-06-01T00:00:00Z")
        job = create_job_order(
            vessel["id"],
            tariff["id"],
            scheduled_start="2026-06-01T08:00:00Z",
            scheduled_end="2026-06-01T10:00:00Z",
        )
        confirm_job_order(job["id"])
        cancel_job_order(job["id"], cancel_reason="Vessel diverted")
        create_weather_restriction(
            restriction_type="WIND",
            threshold_value=35.0,
            port_area="NORTH_HARBOR",
            effective_start="2026-06-01T07:00:00Z",
            effective_end="2026-06-01T12:00:00Z",
        )
        return job

    def test_dispatch_on_cancelled_job_returns_already_terminal(self, api):
        """PRD §2.8: "A failure at any stage short-circuits all later stages, so the
        error a caller receives is always the earliest failing stage, never a later
        one." Stage 6 is "Terminal-state guard ... else `ERR_ALREADY_TERMINAL`" and
        stage 8 covers "weather clearance (`ERR_WEATHER_RESTRICTED`)".

        Design: Difficulty/priority_pair_validation_conflict/terminal_state_beats_weather_safety
        """
        job = self._setup_cancelled_job_with_active_restriction()
        res = api.dispatch_job_order(job["id"], TEST_USERS["port_dispatcher_headers"])
        validate_error(res, "ERR_ALREADY_TERMINAL")

    def test_weather_restriction_does_not_preempt_terminal_guard(self, api):
        """PRD §2.8 stage 6 precedes stage 8 in the fixed pipeline: "their relative
        order is fixed system-wide" — so with both conditions violated the caller
        receives ERR_ALREADY_TERMINAL, not ERR_WEATHER_RESTRICTED.

        Design: Difficulty/priority_pair_validation_conflict/terminal_state_beats_weather_safety
        """
        job = self._setup_cancelled_job_with_active_restriction()
        res = api.dispatch_job_order(job["id"], TEST_USERS["port_dispatcher_headers"])
        assert res.status_code == 409
        body = res.json()
        assert body["data"]["error_id"] == "ERR_ALREADY_TERMINAL"
        assert body["data"]["error_id"] != "ERR_WEATHER_RESTRICTED"


class TestTugSafetyBeatsDuplicateConstraint:
    """Priority pair: business_safety (stage 8) outranks business_constraint (stage 10)."""

    def _setup_restricted_tug_with_proposed_assignment(self):
        tug = create_tug(name="Tug Atlas", bollard_pull_tons=60.0)
        vessel = create_vessel(name="MV Aurora", imo_number="IMO9074729")
        tariff = create_tariff_rate(tariff_code="TAR-DOCK-01")
        set_clock("2026-06-01T00:00:00Z")
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
        # FAILED inspection drives the tug to RESTRICTED (PROPOSED assignments are
        # not superseded by the cascade — only CONFIRMED ones are).
        record_failed_inspection(
            tug["id"],
            inspection_item="WINCH",
            inspected_at="2026-05-20T00:00:00Z",
            next_due_at="2026-06-20T00:00:00Z",
        )
        job = get_job(job["id"])
        return tug, job

    def test_second_assignment_on_restricted_tug_returns_tug_unavailable(self, api):
        """PRD §2.8: "A failure at any stage short-circuits all later stages." Stage
        8 covers "tug availability (`ERR_TUG_UNAVAILABLE`)"; stage 10 covers
        "duplicate tugs on one job (`ERR_DUPLICATE_TUG_ASSIGNMENT`)".

        Design: Difficulty/priority_pair_validation_conflict/tug_safety_beats_duplicate_constraint
        """
        tug, job = self._setup_restricted_tug_with_proposed_assignment()
        res = api.create_tug_assignment(
            {
                "job_order_id": job["id"],
                "tug_id": tug["id"],
                "window_start": "2026-06-01T08:00:00Z",
                "window_end": "2026-06-01T10:00:00Z",
                "expected_job_order_version": job["version"],
            },
            TEST_USERS["port_dispatcher_headers"],
        )
        validate_error(res, "ERR_TUG_UNAVAILABLE")

    def test_safety_error_not_duplicate_error(self, api):
        """PRD §2.8: "their relative order is fixed system-wide" — with both the
        safety rule (tug not AVAILABLE) and the duplicate rule violated, the caller
        receives ERR_TUG_UNAVAILABLE (stage 8), not ERR_DUPLICATE_TUG_ASSIGNMENT
        (stage 10).

        Design: Difficulty/priority_pair_validation_conflict/tug_safety_beats_duplicate_constraint
        """
        tug, job = self._setup_restricted_tug_with_proposed_assignment()
        res = api.create_tug_assignment(
            {
                "job_order_id": job["id"],
                "tug_id": tug["id"],
                "window_start": "2026-06-01T08:00:00Z",
                "window_end": "2026-06-01T10:00:00Z",
                "expected_job_order_version": job["version"],
            },
            TEST_USERS["port_dispatcher_headers"],
        )
        assert res.status_code == 409
        body = res.json()
        assert body["data"]["error_id"] == "ERR_TUG_UNAVAILABLE"
        assert body["data"]["error_id"] != "ERR_DUPLICATE_TUG_ASSIGNMENT"


class TestConfirmWithWeatherRestriction:
    def test_confirm_with_overlapping_weather_restriction_returns_weather_restricted(self, api):
        """PRD §3.2: "no `ACTIVE` weather restriction may overlap the scheduled
        window (§3.7), else `ERR_WEATHER_RESTRICTED`."

        Design: Corner/validations/confirm_with_overlapping_weather_restriction_returns_weather_restricted
        """
        vessel = create_vessel(name="MV Aurora", imo_number="IMO9074729")
        tariff = create_tariff_rate(tariff_code="TAR-DOCK-01")
        job = create_job_order(
            vessel["id"],
            tariff["id"],
            scheduled_start="2026-06-01T08:00:00Z",
            scheduled_end="2026-06-01T10:00:00Z",
        )
        create_weather_restriction(
            restriction_type="WIND",
            threshold_value=35.0,
            port_area="NORTH_HARBOR",
            effective_start="2026-06-01T07:00:00Z",
            effective_end="2026-06-01T12:00:00Z",
        )
        res = api.confirm_job_order(job["id"], TEST_USERS["port_dispatcher_headers"])
        validate_error(res, "ERR_WEATHER_RESTRICTED")
        after = get_job(job["id"])
        assert after["status"] == "REQUESTED"
