"""Weather-restriction holds and the amend cycle — non-linear JobOrder state paths."""
import pytest

from test_helpers import (
    TEST_USERS,
    confirm_assignment,
    confirm_booking,
    confirm_job_order,
    create_job_order,
    create_pilot,
    create_tariff_rate,
    create_tug,
    create_vessel,
    create_weather_restriction,
    dispatch_job,
    get_job,
    lift_weather_restriction,
    propose_assignment,
    propose_pilot_booking,
    record_passed_inspection,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import make_vessel_agent_headers


class TestWeatherWindowValidation:
    def test_weather_end_not_after_start_returns_weather_window_invalid(self, api, port_admin_headers):
        """PRD §3.7: "the effective span `effective_start` to `effective_end`, the
        end strictly after the start else `ERR_WEATHER_WINDOW_INVALID`."

        Design: Corner/validations/weather_end_not_after_start_returns_weather_window_invalid
        """
        res = api.create_weather_restriction(
            {
                "restriction_type": "CURRENT",
                "threshold_value": 4.5,
                "port_area": "NORTH_HARBOR",
                "effective_start": "2026-06-01T12:00:00Z",
                "effective_end": "2026-06-01T06:00:00Z",
            },
            port_admin_headers,
        )
        validate_error(res, "ERR_WEATHER_WINDOW_INVALID")


class TestAmendCycleAndWeatherHoldCycle:
    """JobOrder exhibits two cycles: CONFIRMED -> REQUESTED via amend, and
    DISPATCHED -> ON_HOLD -> DISPATCHED via weather restriction create/lift."""

    def _setup_confirmed_job_for_cycle(self):
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
        confirm_booking(booking["id"], pilot["id"])
        job = get_job(job["id"])
        return {
            "tug": tug, "vessel": vessel, "pilot": pilot, "tariff": tariff,
            "job": job, "assignment": asg, "booking": booking,
        }

    def test_amend_from_confirmed_supersedes_children_and_returns_to_requested(self, api):
        """PRD §3.2: "Amending a `CONFIRMED` job is more disruptive: the job falls
        back to `REQUESTED`, every `CONFIRMED` tug assignment on it becomes
        `SUPERSEDED` (§3.3), and every still-open pilot booking — one in `REQUESTED`
        or `CONFIRMED` status — becomes `SUPERSEDED` as well (§3.4)."

        Design: Difficulty/non_linear_state_machine/job_order_amend_cycle_and_weather_hold_cycle
        """
        ctx = self._setup_confirmed_job_for_cycle()
        job = ctx["job"]
        res = api.amend_job_order(
            job["id"],
            {
                "expected_job_order_version": job["version"],
                "scheduled_end": "2026-06-01T11:00:00Z",
            },
            make_vessel_agent_headers(ctx["vessel"]["id"]),
        )
        amended = validate_success(res, 200)
        assert amended["status"] == "REQUESTED"
        asg_after = validate_success(
            api.get_tug_assignment(
                ctx["assignment"]["id"], TEST_USERS["port_dispatcher_headers"]
            ),
            200,
        )
        assert asg_after["status"] == "SUPERSEDED"
        booking_after = validate_success(
            api.get_pilot_booking(
                ctx["booking"]["id"], TEST_USERS["port_dispatcher_headers"]
            ),
            200,
        )
        assert booking_after["status"] == "SUPERSEDED"

    def test_weather_hold_and_resume_cycle(self, api):
        """PRD §3.7: "Every job in `DISPATCHED` status whose scheduled window
        overlaps the restriction's effective span — a half-open intersection per
        §2.4 — is placed `ON_HOLD` at the moment the restriction is declared, and
        each such job's `had_weather_hold` flag is set true."
        PRD §3.7: "Lifting a restriction moves it `ACTIVE` → `LIFTED`, which is
        terminal, and releases the holds conservatively: each `ON_HOLD` job returns
        to `DISPATCHED` only if, after the lift, no remaining `ACTIVE` restriction
        still overlaps its scheduled window."

        Design: Difficulty/non_linear_state_machine/job_order_amend_cycle_and_weather_hold_cycle
        """
        ctx = self._setup_confirmed_job_for_cycle()
        job = ctx["job"]
        # Re-plan after amend cycle: amend back to a longer window, re-confirm,
        # re-assign, re-book, then dispatch.
        amend_res = api.amend_job_order(
            job["id"],
            {
                "expected_job_order_version": job["version"],
                "scheduled_end": "2026-06-01T11:00:00Z",
            },
            make_vessel_agent_headers(ctx["vessel"]["id"]),
        )
        validate_success(amend_res, 200)
        job = confirm_job_order(job["id"])
        asg2 = propose_assignment(
            job["id"],
            ctx["tug"]["id"],
            job["version"],
            window_start="2026-06-01T08:00:00Z",
            window_end="2026-06-01T11:00:00Z",
        )
        confirm_assignment(asg2["id"], ctx["tug"]["id"])
        booking2 = propose_pilot_booking(
            job["id"],
            ctx["pilot"]["id"],
            window_start="2026-06-01T08:00:00Z",
            window_end="2026-06-01T11:00:00Z",
        )
        confirm_booking(booking2["id"], ctx["pilot"]["id"])
        dispatched = dispatch_job(job["id"])
        assert dispatched["status"] == "DISPATCHED"

        # DISPATCHED -> ON_HOLD via restriction creation
        wr = create_weather_restriction(
            restriction_type="WIND",
            threshold_value=35.0,
            port_area="NORTH_HARBOR",
            effective_start="2026-06-01T09:00:00Z",
            effective_end="2026-06-01T11:00:00Z",
        )
        held = get_job(job["id"])
        assert held["status"] == "ON_HOLD"
        assert held["had_weather_hold"] is True

        # ON_HOLD -> DISPATCHED via lift
        lift_weather_restriction(wr["id"])
        resumed = get_job(job["id"])
        assert resumed["status"] == "DISPATCHED"


class TestRequiredBollardPullCalculation:
    """Combinatorial formula: DWT * maneuver factor, LOA multiplier, 20.0 floor."""

    def test_loa_multiplier_branch_fires(self, api):
        """PRD §3.2: "The computation starts from the vessel's `deadweight_tonnage`,
        scaled by a maneuver factor per thousand tons of deadweight: 1.5 for
        `DOCKING` ... If the vessel's `loa_meters` exceeds 200 meters, the
        intermediate figure is then multiplied by 1.25 to account for the larger
        hull."

        Design: Difficulty/combinatorial_formula/required_bollard_pull_three_input_floor_and_multiplier
        """
        vessel_a = create_vessel(
            name="MV Titan",
            imo_number="IMO1111111",
            deadweight_tonnage=60000,
            loa_meters=210.0,
        )
        tariff = create_tariff_rate(tariff_code="TAR-DOCK-01", maneuver_type="DOCKING")
        set_clock("2026-06-01T00:00:00Z")
        job = create_job_order(
            vessel_a["id"],
            tariff["id"],
            maneuver_type="DOCKING",
            scheduled_start="2026-06-01T08:00:00Z",
            scheduled_end="2026-06-01T10:00:00Z",
        )
        # 60000 * 1.5 / 1000 = 90.0; LOA 210 > 200 -> 90.0 * 1.25 = 112.5
        assert job["required_bollard_pull_tons"] == pytest.approx(112.5)

    def test_min_floor_clamps_small_vessel(self, api):
        """PRD §3.2: "the requirement is never allowed to fall below 20.0 tons,
        even when the formula would yield less."

        Design: Difficulty/combinatorial_formula/required_bollard_pull_three_input_floor_and_multiplier
        """
        vessel_b = create_vessel(
            name="MV Sprite",
            imo_number="IMO2222222",
            deadweight_tonnage=15000,
            loa_meters=150.0,
        )
        tariff = create_tariff_rate(tariff_code="TAR-SHIFT-01", maneuver_type="SHIFTING")
        set_clock("2026-06-01T00:00:00Z")
        job = create_job_order(
            vessel_b["id"],
            tariff["id"],
            maneuver_type="SHIFTING",
            scheduled_start="2026-06-02T08:00:00Z",
            scheduled_end="2026-06-02T09:00:00Z",
        )
        # 15000 * 1.0 / 1000 = 15.0 -> clamped to 20.0 by the floor
        assert job["required_bollard_pull_tons"] == pytest.approx(20.0)
