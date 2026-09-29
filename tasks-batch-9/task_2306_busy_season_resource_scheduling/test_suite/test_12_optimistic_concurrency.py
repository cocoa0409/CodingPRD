"""Version tokens on the two writes that change a parent's staffing composition."""

from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    assert_hours,
    create_assignment,
    create_client,
    create_engagement,
    create_partner,
    create_phase,
    create_plan,
    create_senior,
    engagement_version,
    phase_version,
    read_assignment,
    read_phase,
    read_plan,
    read_workload,
    schedule_engagement,
    set_clock,
    simulate_plan,
    validate_error,
    validate_success,
)


def _phase_with_one_booking(api, expected_hours=40.00):
    """One forty-hour phase carrying a single twenty-hour booking on a senior."""

    set_clock(api, "2026-08-03T09:00:00Z")
    client = create_client(api, name="Meridian Manufacturing")
    partner = create_partner(api)
    first = create_senior(api)
    second = create_senior(api, full_name="Dana Kirsch", hourly_bill_rate=165.00)
    engagement = create_engagement(
        api, client["id"], partner["id"], budget_fee_amount=12000.00
    )
    phase = create_phase(
        api,
        engagement["id"],
        expected_hours=expected_hours,
        window_start_date="2026-08-03",
        window_end_date="2026-08-31",
    )
    booking = create_assignment(
        api,
        phase["id"],
        first["id"],
        start_date="2026-08-03",
        end_date="2026-08-08",
        allocated_hours=20.00,
    )
    return {
        "engagement": engagement,
        "phase": phase,
        "booking": booking,
        "first": first,
        "second": second,
    }


class TestReassignmentIsALinkAndReleasePair:
    """Swapping people leaves two rows joined by a supersede pointer."""

    def test_the_original_row_survives_pointing_at_its_successor(
        self, api, manager_headers
    ):
        """A new booking in PROPOSED, and the old one RELEASED with the forward link.

        PRD 3.3: "The original booking moves `PROPOSED → RELEASED` or `CONFIRMED →
        RELEASED` with `superseded_by_assignment_id` set to the replacement's `id`,
        and a new booking is created on the same phase in `PROPOSED`."

        PRD 3.3: "The replacement's `daily_hours`, `calendar_day_count`,
        `rate_model`, `review_status`, `review_hours_charged` and
        `review_capacity_window_id` are all computed fresh."

        Design: Corner/endpoints/reassign_relinks_the_phase_to_a_new_staff_member
        """

        world = _phase_with_one_booking(api)
        observed_version = phase_version(api, world["phase"]["id"])

        replacement = validate_success(
            api.reassign_assignment(
                world["booking"]["id"],
                {
                    "expected_phase_version": observed_version,
                    "staff_member_id": world["second"]["id"],
                    "start_date": "2026-08-10",
                    "end_date": "2026-08-17",
                    "allocated_hours": 20.00,
                },
                manager_headers,
            ),
            201,
        )
        assert replacement["staff_member_id"] == world["second"]["id"]
        assert replacement["engagement_phase_id"] == world["phase"]["id"]
        assert replacement["staffing_status"] == "PROPOSED"
        assert replacement["calendar_day_count"] == 7
        assert_hours(replacement["daily_hours"], 2.86)

        original = read_assignment(api, world["booking"]["id"])
        assert original["staffing_status"] == "RELEASED"
        assert original["superseded_by_assignment_id"] == replacement["id"]

    def test_the_phase_counts_the_successor_only_and_unloads_the_first_person(
        self, api, manager_headers
    ):
        """Twenty hours are neither doubled nor lost, and the phase version moves on.

        PRD 3.3: "Both people's `committed_hours_current_week`, `workload_status`,
        both burnout scores and `turnover_risk_band` are recomputed; the phase's
        staffing figures, `staffing_status` and the engagement's
        `staffing_completion_pct` are re-derived; and the phase's `version`
        increments."

        PRD 3.2: "A phase's `staffed_hours` is the sum of `allocated_hours` over its
        bookings in `PROPOSED`, `CONFIRMED`, `ACTIVE` or `COMPLETED` — released
        bookings are excluded — rounded to two decimals."

        Design: Corner/endpoints/reassign_relinks_the_phase_to_a_new_staff_member
        """

        world = _phase_with_one_booking(api)
        observed_version = phase_version(api, world["phase"]["id"])

        validate_success(
            api.reassign_assignment(
                world["booking"]["id"],
                {
                    "expected_phase_version": observed_version,
                    "staff_member_id": world["second"]["id"],
                    "start_date": "2026-08-10",
                    "end_date": "2026-08-17",
                    "allocated_hours": 20.00,
                },
                manager_headers,
            ),
            201,
        )

        phase_after = read_phase(api, world["phase"]["id"])
        assert_hours(phase_after["staffed_hours"], 20.00)
        assert_hours(phase_after["unstaffed_hours"], 20.00)
        assert phase_after["staffing_status"] == "PARTIALLY_STAFFED"
        assert phase_after["version"] > observed_version

        workload = read_workload(api, world["first"]["id"], "2026-08-03")
        assert_hours(workload["committed_hours"], 0.00)
        assert_hours(workload["remaining_week_hours"], 50.00)


class TestReassignCarriesThePhaseVersion:
    """The token is the phase's version, so a sibling booking invalidates it."""

    def _stale_token_world(self, api):
        world = _phase_with_one_booking(api)
        world["third"] = create_senior(
            api, full_name="Owen Vasquez", hourly_bill_rate=170.00
        )
        world["observed_version"] = phase_version(api, world["phase"]["id"])
        world["sibling"] = create_assignment(
            api,
            world["phase"]["id"],
            world["third"]["id"],
            start_date="2026-08-10",
            end_date="2026-08-15",
            allocated_hours=5.00,
        )
        return world

    def _retry_payload(self, staff_id, expected_phase_version):
        return {
            "expected_phase_version": expected_phase_version,
            "staff_member_id": staff_id,
            "start_date": "2026-08-17",
            "end_date": "2026-08-24",
            "allocated_hours": 20.00,
        }

    def test_a_sibling_booking_invalidates_a_token_read_before_it(
        self, api, manager_headers
    ):
        """The stale attempt is refused and the original booking is left alone.

        PRD 2.11: "The reassignment request must therefore carry
        `expected_phase_version`, a non-optional integer field holding the `version`
        of the owning `EngagementPhase` that the client last observed. If that value
        does not equal the phase's current `version` — because another writer has
        staffed, released or expanded that phase since the client read it — the
        reassignment is rejected with `ERR_STALE_PHASE_VERSION` (HTTP 412)."

        PRD 2.9: "41. `expected_phase_version` matches — `ERR_STALE_PHASE_VERSION`.
        Reassignment only."

        Design: Corner/cross_cutting_complexity_layers/reassign_with_a_stale_phase_version_rejected_then_retried
        """

        world = self._stale_token_world(api)

        validate_error(
            api.reassign_assignment(
                world["booking"]["id"],
                self._retry_payload(world["second"]["id"], world["observed_version"]),
                manager_headers,
            ),
            ApiErrorId.STALE_PHASE_VERSION.value,
            412,
        )

        original = read_assignment(api, world["booking"]["id"])
        assert original["staffing_status"] == "PROPOSED"
        assert original["staff_member_id"] == world["first"]["id"]
        assert original["superseded_by_assignment_id"] is None

    def test_reading_the_version_back_makes_the_very_same_call_land(
        self, api, manager_headers
    ):
        """A fresh token is all that was missing; the twenty-five staffed hours persist.

        PRD 2.11: "Two write operations change the staffing composition of a parent
        row that the caller must have observed first, and both are therefore guarded
        by optimistic concurrency control against that parent's `version`."

        PRD 3.3: "The original booking moves `PROPOSED → RELEASED` or `CONFIRMED →
        RELEASED` with `superseded_by_assignment_id` set to the replacement's `id`,
        and a new booking is created on the same phase in `PROPOSED`."

        Design: Corner/cross_cutting_complexity_layers/reassign_with_a_stale_phase_version_rejected_then_retried
        """

        world = self._stale_token_world(api)
        validate_error(
            api.reassign_assignment(
                world["booking"]["id"],
                self._retry_payload(world["second"]["id"], world["observed_version"]),
                manager_headers,
            ),
            ApiErrorId.STALE_PHASE_VERSION.value,
            412,
        )

        fresh_version = phase_version(api, world["phase"]["id"])
        assert fresh_version > world["observed_version"]
        assert_hours(read_phase(api, world["phase"]["id"])["staffed_hours"], 25.00)

        replacement = validate_success(
            api.reassign_assignment(
                world["booking"]["id"],
                self._retry_payload(world["second"]["id"], fresh_version),
                manager_headers,
            ),
            201,
        )
        assert replacement["staff_member_id"] == world["second"]["id"]
        assert read_assignment(api, world["booking"]["id"])["staffing_status"] == "RELEASED"

        phase_after = read_phase(api, world["phase"]["id"])
        assert_hours(phase_after["staffed_hours"], 25.00)
        assert phase_after["version"] > fresh_version


class TestApplyCarriesTheEngagementVersion:
    """A fresh projection is not enough; the engagement token must match too."""

    def _simulated_plan_world(self, api):
        set_clock(api, "2026-08-03T09:00:00Z")
        client = create_client(api, name="Meridian Manufacturing")
        partner = create_partner(api)
        senior = create_senior(api)
        engagement = create_engagement(api, client["id"], partner["id"])
        phase = create_phase(
            api,
            engagement["id"],
            expected_hours=21.00,
            window_start_date="2026-08-03",
            window_end_date="2026-08-31",
        )
        create_assignment(
            api,
            phase["id"],
            senior["id"],
            start_date="2026-08-24",
            end_date="2026-08-31",
            allocated_hours=21.00,
        )
        schedule_engagement(api, engagement["id"])
        current_version = engagement_version(api, engagement["id"])
        plan = create_plan(api, engagement["id"], shift_days=7)
        simulated = simulate_plan(api, plan["id"])
        assert simulated["simulated_at_engagement_version"] == current_version
        assert simulated["simulation_stale"] is False
        return {
            "engagement": engagement,
            "phase": phase,
            "plan": plan,
            "engagement_version": current_version,
        }

    def test_a_wrong_version_is_refused_even_with_a_current_projection(
        self, api, manager_headers
    ):
        """The refusal is the version one, not the staleness one, and nothing moves.

        PRD 2.11: "Applying a reschedule plan shifts every phase window of an
        engagement and legitimately supersedes any other plan on the same
        engagement, so the apply request must carry `expected_engagement_version`, a
        non-optional integer field holding the `version` of the target `Engagement`
        that the client last observed. If that value does not equal the engagement's
        current `version`, the apply is rejected with
        `ERR_STALE_ENGAGEMENT_VERSION` (HTTP 412), because the projection the caller
        approved was computed against an engagement state that has since advanced."

        PRD 3.8: "Staleness is what keeps a projection honest: `simulation_stale` is
        true whenever `simulated_at_engagement_version` is null or differs from the
        engagement's current `version`."

        Design: Corner/cross_cutting_complexity_layers/plan_apply_with_a_stale_engagement_version_rejected_then_retried
        """

        world = self._simulated_plan_world(api)

        error = validate_error(
            api.apply_reschedule_plan(
                world["plan"]["id"],
                manager_headers,
                world["engagement_version"] - 1,
            ),
            ApiErrorId.STALE_ENGAGEMENT_VERSION.value,
            412,
        )
        assert error["error_id"] != ApiErrorId.SIMULATION_STALE.value

        plan_after = read_plan(api, world["plan"]["id"])
        assert plan_after["status"] == "SIMULATED"
        assert plan_after["simulation_stale"] is False

        phase_after = read_phase(api, world["phase"]["id"])
        assert phase_after["window_start_date"] == "2026-08-03"
        assert phase_after["window_end_date"] == "2026-08-31"

    def test_the_matching_version_applies_the_projection(self, api, manager_headers):
        """The same plan, the right token, and the window jumps a week at both ends.

        PRD 2.9: "42. `expected_engagement_version` matches —
        `ERR_STALE_ENGAGEMENT_VERSION`. Reschedule apply only."

        PRD 3.8: "On apply, the plan advances `SIMULATED → APPLIED` and the
        projection becomes reality: every phase of the engagement has
        `window_start_date` and `window_end_date` moved later by `shift_days`"

        Design: Corner/cross_cutting_complexity_layers/plan_apply_with_a_stale_engagement_version_rejected_then_retried
        """

        world = self._simulated_plan_world(api)
        validate_error(
            api.apply_reschedule_plan(
                world["plan"]["id"],
                manager_headers,
                world["engagement_version"] - 1,
            ),
            ApiErrorId.STALE_ENGAGEMENT_VERSION.value,
            412,
        )

        applied = validate_success(
            api.apply_reschedule_plan(
                world["plan"]["id"], manager_headers, world["engagement_version"]
            )
        )
        assert applied["status"] == "APPLIED"

        phase_after = read_phase(api, world["phase"]["id"])
        assert phase_after["window_start_date"] == "2026-08-10"
        assert phase_after["window_end_date"] == "2026-09-07"

        assert (
            engagement_version(api, world["engagement"]["id"])
            > world["engagement_version"]
        )
