"""Reschedule plans: projection, staleness, apply, and the losing siblings."""

from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    assert_hours,
    assert_pct,
    create_assignment,
    create_client,
    create_engagement,
    create_partner,
    create_phase,
    create_plan,
    create_senior,
    engagement_version,
    read_assignment,
    read_phase,
    read_plan,
    schedule_engagement,
    set_clock,
    simulate_plan,
    start_fieldwork,
    validate_error,
    validate_success,
)


def _scheduled_engagement_with_a_late_booking(
    api, expected_hours=45.00, allocated_hours=20.00
):
    """One phase across August with a booking sitting in its last full week."""

    set_clock(api, "2026-08-03T09:00:00Z")
    client = create_client(api, name="Meridian Manufacturing")
    partner = create_partner(api)
    senior = create_senior(api)
    engagement = create_engagement(api, client["id"], partner["id"])
    phase = create_phase(
        api,
        engagement["id"],
        expected_hours=expected_hours,
        window_start_date="2026-08-03",
        window_end_date="2026-08-31",
    )
    assignment = create_assignment(
        api,
        phase["id"],
        senior["id"],
        start_date="2026-08-24",
        end_date="2026-08-31",
        allocated_hours=allocated_hours,
    )
    schedule_engagement(api, engagement["id"])
    return {
        "client": client,
        "partner": partner,
        "senior": senior,
        "engagement": engagement,
        "phase": phase,
        "assignment": assignment,
    }


class TestSimulationIsAPureProjection:
    """The four projected figures are computed and nothing is written."""

    def test_the_projection_shifts_the_window_and_pours_in_the_added_hours(self, api):
        """Fifty-five projected hours against twenty-one kept ones leaves thirty-four.

        PRD 3.8: "The `target_phase_id` is the phase of this engagement with the
        greatest `window_start_date`, ties broken by earliest `created_at` and never
        by `id`. Each phase's window is projected forward by `shift_days` at both
        ends, and the target phase's projected expected hours are its
        `expected_hours` plus `added_hours` while every other phase keeps its
        `expected_hours` unchanged."

        PRD 3.8: "`projected_unstaffed_hours` is the sum over the engagement's
        phases of the projected expected hours minus the sum of `allocated_hours`
        over that phase's kept, non-released bookings (rounded to two decimals),
        each phase's shortfall floored at 0.00, with the total rounded to two
        decimals."

        PRD 3.8: "`projected_realization_pct` values the kept, non-released
        bookings: it is 0.00 when the projected standard value is 0.00, and
        otherwise the engagement's `budget_fee_amount` divided by the sum (rounded
        to two decimals) of each kept booking's `allocated_hours` multiplied by its
        effective rate and rounded to two decimals per booking, multiplied by 100
        and rounded to two decimals."

        Design: Corner/calculations/simulate_projects_shifted_window_added_hours_and_realization
        """

        world = _scheduled_engagement_with_a_late_booking(api, allocated_hours=21.00)
        assert_hours(read_assignment(api, world["assignment"]["id"])["daily_hours"], 3.00)
        plan = create_plan(
            api,
            world["engagement"]["id"],
            trigger_reason="SCOPE_EXPANSION",
            shift_days=7,
            added_hours=10.00,
        )
        assert plan["status"] == "DRAFT"

        simulated = simulate_plan(api, plan["id"])
        assert simulated["status"] == "SIMULATED"
        assert simulated["target_phase_id"] == world["phase"]["id"]
        assert simulated["projected_dropped_assignment_count"] == 0
        assert_hours(simulated["projected_unstaffed_hours"], 34.00)
        assert simulated["projected_cap_breach_count"] == 0
        assert_pct(simulated["projected_realization_pct"], 158.73)

    def test_the_simulation_writes_nothing_and_records_the_version_it_saw(self, api):
        """The phase still opens on the third of August and still expects forty-five hours.

        PRD 3.8: "Simulating the plan is a purely read-only projection that mutates
        no phase, booking or engagement row."

        PRD 3.8: "Simulation sets `simulated_at_engagement_version` to the
        engagement's current `version`, sets `simulation_stale` to false, and
        increments the plan's `version`."

        Design: Corner/calculations/simulate_projects_shifted_window_added_hours_and_realization
        """

        world = _scheduled_engagement_with_a_late_booking(api, allocated_hours=21.00)
        plan = create_plan(
            api,
            world["engagement"]["id"],
            trigger_reason="SCOPE_EXPANSION",
            shift_days=7,
            added_hours=10.00,
        )

        simulated = simulate_plan(api, plan["id"])
        assert simulated["simulation_stale"] is False
        assert simulated["simulated_at_engagement_version"] == engagement_version(
            api, world["engagement"]["id"]
        )

        phase_after = read_phase(api, world["phase"]["id"])
        assert phase_after["window_start_date"] == "2026-08-03"
        assert phase_after["window_end_date"] == "2026-08-31"
        assert_hours(phase_after["expected_hours"], 45.00)


class TestApplyRequiresASimulation:
    """A DRAFT plan has nothing to apply, and that is a state refusal."""

    def test_applying_a_never_simulated_plan_is_refused_on_its_state(
        self, api, manager_headers
    ):
        """The state check sits above the staleness check, so it is the one reported.

        PRD 3.8: "Applying a plan requires the plan to be `SIMULATED` and
        `simulation_stale` to be false — a stale projection is refused with
        `ERR_SIMULATION_STALE` — and requires the `expected_engagement_version`
        check of §2.11."

        PRD 2.10: "`ERR_PLAN_INVALID_STATE` for a reschedule plan (including
        `APPLIED` and `SUPERSEDED` lockdown)"

        PRD 2.9: "Validations are evaluated in a single, strictly ordered ladder.
        **The first check that fails determines the response, and no later check is
        evaluated.**"

        Design: Corner/state_machines/apply_before_simulate_rejected_as_plan_invalid_state
        """

        world = _scheduled_engagement_with_a_late_booking(api)
        plan = create_plan(api, world["engagement"]["id"], shift_days=7)
        assert plan["status"] == "DRAFT"

        error = validate_error(
            api.apply_reschedule_plan(
                plan["id"],
                manager_headers,
                engagement_version(api, world["engagement"]["id"]),
            ),
            ApiErrorId.PLAN_INVALID_STATE.value,
            409,
        )
        assert error["error_id"] != ApiErrorId.SIMULATION_STALE.value

        plan_after = read_plan(api, plan["id"])
        assert plan_after["status"] == "DRAFT"
        assert plan_after["simulation_stale"] is True
        assert plan_after["simulated_at_engagement_version"] is None
        assert plan_after["projected_unstaffed_hours"] is None

        phase_after = read_phase(api, world["phase"]["id"])
        assert phase_after["window_start_date"] == "2026-08-03"
        assert phase_after["window_end_date"] == "2026-08-31"


class TestStalenessGuardsTheProjection:
    """A projection taken against an older engagement may not be applied."""

    def test_an_engagement_that_moved_on_invalidates_the_projection(
        self, api, manager_headers
    ):
        """The supplied version is correct, and the refusal is about the stale figures.

        PRD 3.8: "Staleness is what keeps a projection honest: `simulation_stale` is
        true whenever `simulated_at_engagement_version` is null or differs from the
        engagement's current `version`."

        PRD 3.8: "Applying a plan requires the plan to be `SIMULATED` and
        `simulation_stale` to be false — a stale projection is refused with
        `ERR_SIMULATION_STALE` — and requires the `expected_engagement_version`
        check of §2.11."

        Design: Corner/validations/apply_after_engagement_moved_on_rejected_as_simulation_stale
        """

        world = _scheduled_engagement_with_a_late_booking(
            api, expected_hours=21.00, allocated_hours=21.00
        )
        plan = create_plan(api, world["engagement"]["id"], shift_days=7)
        simulated = simulate_plan(api, plan["id"])
        simulated_version = simulated["simulated_at_engagement_version"]

        start_fieldwork(api, world["engagement"]["id"])
        moved_version = engagement_version(api, world["engagement"]["id"])
        assert moved_version != simulated_version

        validate_error(
            api.apply_reschedule_plan(plan["id"], manager_headers, moved_version),
            ApiErrorId.SIMULATION_STALE.value,
            409,
        )

        plan_after = read_plan(api, plan["id"])
        assert plan_after["status"] == "SIMULATED"
        assert plan_after["simulation_stale"] is True
        assert plan_after["simulated_at_engagement_version"] == simulated_version

    def test_a_fresh_simulation_makes_the_same_plan_applicable(
        self, api, manager_headers
    ):
        """Re-simulating in place rebinds the projection and the apply then lands.

        PRD 3.8: "It is permitted while the plan is `DRAFT`, advancing it `DRAFT →
        SIMULATED`, and also while it is already `SIMULATED`, in which case it
        re-simulates in place as `SIMULATED → SIMULATED` after the engagement has
        moved."

        PRD 3.8: "On apply, the plan advances `SIMULATED → APPLIED` and the
        projection becomes reality: every phase of the engagement has
        `window_start_date` and `window_end_date` moved later by `shift_days`"

        Design: Corner/validations/apply_after_engagement_moved_on_rejected_as_simulation_stale
        """

        world = _scheduled_engagement_with_a_late_booking(
            api, expected_hours=21.00, allocated_hours=21.00
        )
        plan = create_plan(api, world["engagement"]["id"], shift_days=7)
        simulate_plan(api, plan["id"])
        start_fieldwork(api, world["engagement"]["id"])
        moved_version = engagement_version(api, world["engagement"]["id"])

        resimulated = simulate_plan(api, plan["id"])
        assert resimulated["status"] == "SIMULATED"
        assert resimulated["simulation_stale"] is False
        assert resimulated["simulated_at_engagement_version"] == moved_version

        applied = validate_success(
            api.apply_reschedule_plan(plan["id"], manager_headers, moved_version)
        )
        assert applied["status"] == "APPLIED"

        phase_after = read_phase(api, world["phase"]["id"])
        assert phase_after["window_start_date"] == "2026-08-10"
        assert phase_after["window_end_date"] == "2026-09-07"


class TestApplySettlesTheCompetition:
    """Only one plan on an engagement can win."""

    def test_the_applied_plan_supersedes_its_sibling(self, api, manager_headers):
        """The loser is closed out and its projection marked stale.

        PRD 3.8: "An apply also settles the competition between plans: every
        *other* reschedule plan on the same engagement whose status is `DRAFT` or
        `SIMULATED` moves to `SUPERSEDED`, has its `simulation_stale` set to true,
        and has its own `version` incremented. `APPLIED` and `SUPERSEDED` are both
        terminal for a plan."

        Design: Corner/state_machines/applied_plan_supersedes_sibling_plan_on_same_engagement
        """

        world = _scheduled_engagement_with_a_late_booking(api)
        winner = create_plan(api, world["engagement"]["id"], shift_days=7)
        loser = create_plan(api, world["engagement"]["id"], shift_days=7)
        simulate_plan(api, winner["id"])
        simulate_plan(api, loser["id"])

        applied = validate_success(
            api.apply_reschedule_plan(
                winner["id"],
                manager_headers,
                engagement_version(api, world["engagement"]["id"]),
            )
        )
        assert applied["status"] == "APPLIED"

        loser_after = read_plan(api, loser["id"])
        assert loser_after["status"] == "SUPERSEDED"
        assert loser_after["simulation_stale"] is True

    def test_the_shifted_window_still_contains_the_booking_it_had(
        self, api, manager_headers
    ):
        """The booking dates never move, and this one still fits the later window.

        PRD 3.8: "**Booking dates are not shifted** — only phase windows move, which
        is exactly why bookings can end up outside their own phase. A booking is
        *kept* when the phase's projected window start is on or before the booking's
        `start_date` **and** the booking's last worked day is on or before the
        phase's projected window end; the projection considers only bookings in
        `PROPOSED` or `CONFIRMED`, since `ACTIVE` and `COMPLETED` work is never
        dropped."

        PRD 3.8: "every booking in `PROPOSED` or `CONFIRMED` that no longer fits its
        shifted phase window moves to `RELEASED`, cascading into phase derivation
        and, when every phase reaches `NOT_STAFFED` while the engagement is
        `SCHEDULED`, into the engagement reverting `SCHEDULED → SETUP`"

        Design: Corner/state_machines/applied_plan_supersedes_sibling_plan_on_same_engagement
        """

        world = _scheduled_engagement_with_a_late_booking(api)
        winner = create_plan(api, world["engagement"]["id"], shift_days=7)
        loser = create_plan(api, world["engagement"]["id"], shift_days=7)
        simulate_plan(api, winner["id"])
        simulate_plan(api, loser["id"])

        validate_success(
            api.apply_reschedule_plan(
                winner["id"],
                manager_headers,
                engagement_version(api, world["engagement"]["id"]),
            )
        )

        phase_after = read_phase(api, world["phase"]["id"])
        assert phase_after["window_start_date"] == "2026-08-10"
        assert phase_after["window_end_date"] == "2026-09-07"

        booking_after = read_assignment(api, world["assignment"]["id"])
        assert booking_after["staffing_status"] == "PROPOSED"
        assert booking_after["start_date"] == "2026-08-24"
        assert booking_after["end_date"] == "2026-08-31"
