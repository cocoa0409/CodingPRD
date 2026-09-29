"""Multi-hop cascades and the conserved ledgers they recompute."""

import pytest

from test_helpers import (
    BILLING_CLERK,
    DISPATCHER,
    SAFETY_MANAGER,
    build_critical_world,
    build_standard_world,
    close_standby,
    configure_plan,
    drive_field,
    open_permit,
    approve_permit,
    read_assignment,
    read_crane,
    read_customer,
    read_gear,
    read_permit,
    read_plan,
    read_review,
    setup_mobilized_standard_plan,
    setup_stamped_critical_plan,
    setup_surveyed_plan_with_gear,
    submit_permit,
    validate_paginated,
    validate_success,
)


class TestParallelDimensionsAcrossWindHoldCycles:
    """Difficulty rule: non_linear_state_machine."""

    @staticmethod
    def _lifting_plan(world):
        ctx = setup_mobilized_standard_plan(
            world, plan_overrides={"job_reference": "JOB-6102", "sail_area_sqft": 150.0}
        )
        drive_field(world, ctx["plan_id"], "START_LIFT")
        return ctx

    def test_two_wind_hold_cycles_never_move_the_readiness_dimension(self, api):
        """PRD 3.8: "Opening an event against a plan that is currently `LIFTING`
        drives that plan `LIFTING → WIND_HOLD` and increments the plan's `version`;
        when the cause was `WIND`, the event's `forced_wind_hold` is set true to
        record that this particular event is what stopped the pick."
        PRD 3.8: "The `LIFTING → WIND_HOLD → LIFTING` loop is a genuine cycle and may
        repeat any number of times in a single job."
        PRD 3.8: "`RESUME` moves `WIND_HOLD → LIFTING`."

        Design: Difficulty/non_linear_state_machine/lift_plan_parallel_dimensions_survive_repeated_wind_hold_cycle
        """
        world = build_standard_world()
        ctx = self._lifting_plan(world)

        first = validate_success(api.create_standby_event(
            {"lift_plan_id": ctx["plan_id"], "cause": "WIND", "wind_speed_mph": 24.0,
             "started_at": "2026-09-10T09:00:00Z"}, SAFETY_MANAGER), 201)
        held = read_plan(ctx["plan_id"])
        assert held["field_status"] == "WIND_HOLD"
        assert held["plan_status"] == "RELEASED"

        close_standby(first["id"], "2026-09-10T11:00:00Z")
        resumed = drive_field(world, ctx["plan_id"], "RESUME")
        assert resumed["field_status"] == "LIFTING"

        second = validate_success(api.create_standby_event(
            {"lift_plan_id": ctx["plan_id"], "cause": "WIND", "wind_speed_mph": 22.0,
             "started_at": "2026-09-10T11:00:00Z"}, SAFETY_MANAGER), 201)
        assert read_plan(ctx["plan_id"])["field_status"] == "WIND_HOLD"
        close_standby(second["id"], "2026-09-10T12:10:00Z")
        resumed_again = drive_field(world, ctx["plan_id"], "RESUME")

        assert resumed_again["field_status"] == "LIFTING"
        assert resumed_again["plan_status"] == "RELEASED", (
            "plan_status must not move across two full wind-hold cycles"
        )
        assert resumed_again["standby_hours_billable"] == pytest.approx(3.25, abs=0.0001)

    def test_wind_events_derate_the_envelope_and_flag_the_forced_hold(self, api):
        """PRD 3.5: "The plan's `allowable_wind_mph` is the crane's
        `rated_max_wind_mph` multiplied by that factor and then **floored** to a whole
        mile per hour."
        PRD 3.8: "when the cause was `WIND`, the event's `forced_wind_hold` is set
        true to record that this particular event is what stopped the pick."

        Design: Difficulty/non_linear_state_machine/lift_plan_parallel_dimensions_survive_repeated_wind_hold_cycle
        """
        world = build_standard_world()
        ctx = self._lifting_plan(world)
        assert ctx["plan"]["allowable_wind_mph"] == 21

        first = validate_success(api.create_standby_event(
            {"lift_plan_id": ctx["plan_id"], "cause": "WIND", "wind_speed_mph": 24.0,
             "started_at": "2026-09-10T09:00:00Z"}, SAFETY_MANAGER), 201)
        close_standby(first["id"], "2026-09-10T11:00:00Z")
        drive_field(world, ctx["plan_id"], "RESUME")
        second = validate_success(api.create_standby_event(
            {"lift_plan_id": ctx["plan_id"], "cause": "WIND", "wind_speed_mph": 22.0,
             "started_at": "2026-09-10T11:00:00Z"}, SAFETY_MANAGER), 201)

        assert first["forced_wind_hold"] is True
        assert second["forced_wind_hold"] is True


class TestGearFailureCascade:
    """Difficulty rule: transitive_cascade."""

    @staticmethod
    def _stamped_plan_on_one_sling(world):
        return setup_stamped_critical_plan(
            world, plan_overrides={"job_reference": "JOB-7781", "sail_area_sqft": 150.0}
        )

    def test_failed_inspection_quarantines_the_gear_and_voids_its_commitment(self, api):
        """PRD 3.2: "A `FAIL` moves the gear to `QUARANTINED`."
        PRD 3.2: "The first hop is the gear's own posture change to `QUARANTINED` or
        `RETIRED`. The second hop voids every commitment of that gear that was still
        active, moving each to `VOIDED` and recomputing the gear's
        `committed_assignment_count`."

        Design: Difficulty/transitive_cascade/gear_fail_inspection_cascades_four_hops_to_review_supersede
        """
        world = build_critical_world()
        ctx = self._stamped_plan_on_one_sling(world)

        crane_before = read_crane(world["crane_id"])
        assert crane_before["reserved_hours_total"] == pytest.approx(10.0)
        assert crane_before["status"] == "RESERVED"

        inspection = validate_success(api.create_gear_inspection(
            {"gear_id": world["gear_id"], "result": "FAIL",
             "inspector_note": "broken wire cluster at eye"}, SAFETY_MANAGER), 201)

        assert inspection["resulting_status"] == "QUARANTINED"
        gear = read_gear(world["gear_id"])
        assert gear["status"] == "QUARANTINED"
        assert gear["committed_assignment_count"] == 0
        assert read_assignment(ctx["ga_id"])["status"] == "VOIDED"

    def test_failed_inspection_demotes_the_plan_and_supersedes_its_stamped_review(self, api):
        """PRD 3.2: "The third hop reaches every lift plan that owned one of those
        voided commitments, whose readiness dimension stands at `CONFIGURED`,
        `PENDING_ENGINEERING`, `APPROVED` or `RELEASED`, and whose operational
        dimension is still `NOT_MOBILIZED`; each such plan is demoted back to
        `SURVEYED` with `rigging_verified` cleared to false."
        PRD 3.2: "The fourth hop reaches every engineering review on those demoted
        plans that stood at `UNDER_REVIEW`, `CHANGES_REQUESTED` or `STAMPED`, and
        moves each to `SUPERSEDED`."
        PRD 3.2: "and the crew and machine assignments `crane_id`, `operator_id` and
        `rigger_id` are all cleared to null, which in turn forces a recomputation of
        the released crane's `reserved_hours_total`, `active_plan_count` and derived
        `status`."

        Design: Difficulty/transitive_cascade/gear_fail_inspection_cascades_four_hops_to_review_supersede
        """
        world = build_critical_world()
        ctx = self._stamped_plan_on_one_sling(world)

        validate_success(api.create_gear_inspection(
            {"gear_id": world["gear_id"], "result": "FAIL",
             "inspector_note": "broken wire cluster at eye"}, SAFETY_MANAGER), 201)

        plan = read_plan(ctx["plan_id"])
        assert plan["plan_status"] == "SURVEYED"
        assert plan["rigging_verified"] is False
        assert plan["lift_class"] == "NOT_CLASSIFIED"
        assert plan["crane_id"] is None

        assert read_review(ctx["review_id"])["status"] == "SUPERSEDED"

        crane_after = read_crane(world["crane_id"])
        assert crane_after["reserved_hours_total"] == pytest.approx(0.0)
        assert crane_after["status"] == "AVAILABLE"


class TestCancellationCascade:
    """Difficulty rule: transitive_cascade."""

    @staticmethod
    def _approved_road_closure_plan(world):
        ctx = setup_stamped_critical_plan(
            world,
            plan_overrides={"job_reference": "JOB-7781", "sail_area_sqft": 150.0,
                            "road_closure_requested": True},
        )
        permit = open_permit(ctx["plan_id"], "ROAD_CLOSURE", world=world)
        submit_permit(permit["id"])
        approve_permit(permit["id"], "NJB-2026-1188")
        ctx["permit"] = permit
        ctx["permit_id"] = permit["id"]
        return ctx

    def test_cancel_voids_the_granted_permit_and_charges_the_cancellation_fee(self, api):
        """PRD 3.7: "The permit's `required_lead_days` is a base lead time determined
        by `permit_type` — 10 days for a `ROAD_CLOSURE`, 7 days for an
        `OVERSIZE_ESCORT`, and 3 days for a `CRANE_PLACEMENT` — plus a further 5 days
        when `escort_required` is true. Its `permit_fee_cents` is likewise a base fee
        by type — 85,000 cents for a `ROAD_CLOSURE`, 45,000 cents for an
        `OVERSIZE_ESCORT`, and 25,000 cents for a `CRANE_PLACEMENT` — plus a further
        60,000 cents when `escort_required` is true."
        PRD 3.9: "**Hop two** reaches the permits: every permit on the plan standing
        at `SUBMITTED`, `APPROVED` or `SUSPENDED` is moved to `VOIDED`, and a permit
        that was standing at `APPROVED` at that instant has its
        `cancellation_fee_cents` set to forty hundredths of its own
        `permit_fee_cents`, rounded half up to whole cents."

        Design: Difficulty/transitive_cascade/plan_cancel_cascades_four_hops_to_customer_receivable
        """
        world = build_critical_world()
        ctx = self._approved_road_closure_plan(world)

        assert ctx["permit"]["permit_fee_cents"] == 145_000
        assert ctx["permit"]["required_lead_days"] == 15

        cancelled = validate_success(api.cancel_lift_plan(
            ctx["plan_id"], {"reason": "customer pushed the outage window"}, DISPATCHER))
        assert cancelled["plan_status"] == "CANCELLED"

        permit = read_permit(ctx["permit_id"])
        assert permit["status"] == "VOIDED"
        assert permit["cancellation_fee_cents"] == 58_000

    def test_cancellation_fee_mints_an_issued_invoice_and_moves_the_receivable(self, api):
        """PRD 3.9: "**Hop three** fires only because at least one voided permit now
        carries a `cancellation_fee_cents` greater than zero: the system mints exactly
        one invoice against the plan, with `system_generated` true, `billing_mode`
        `LUMP_SUM`, `lump_sum_cents` at 0 and `line_permit_cancellation_cents` set to
        the sum of those fees, and moves that invoice straight to `ISSUED` without
        anyone drafting it."
        PRD 3.9: "**Hop four** fires only because that invoice reached `ISSUED`: the
        owning customer's `open_receivable_cents` and `invoice_count` are recomputed."
        PRD 3.9: "every engineering review on the plan standing at `UNDER_REVIEW`,
        `CHANGES_REQUESTED` or `STAMPED` is moved to `SUPERSEDED`, the crane's
        `reserved_hours_total`, `active_plan_count` and derived `status` are
        recomputed as the plan leaves the reserving set, and the plan's `version`
        increments."

        Design: Difficulty/transitive_cascade/plan_cancel_cascades_four_hops_to_customer_receivable
        """
        world = build_critical_world()
        ctx = self._approved_road_closure_plan(world)

        validate_success(api.cancel_lift_plan(
            ctx["plan_id"], {"reason": "customer pushed the outage window"}, DISPATCHER))

        invoices, meta = validate_paginated(
            api.list_invoices(BILLING_CLERK, params={"lift_plan_id": ctx["plan_id"]}))
        assert meta["total_count"] == 1, "exactly one invoice is minted by the cascade"
        auto = invoices[0]
        assert auto["system_generated"] is True
        assert auto["status"] == "ISSUED"
        assert auto["billing_mode"] == "LUMP_SUM"
        assert auto["line_permit_cancellation_cents"] == 58_000
        assert auto["total_cents"] == 62_060

        customer = read_customer(world["cust_id"])
        assert customer["open_receivable_cents"] == 62_060
        assert customer["invoice_count"] == 1

        assert read_review(ctx["review_id"])["status"] == "SUPERSEDED"
        crane = read_crane(world["crane_id"])
        assert crane["reserved_hours_total"] == pytest.approx(0.0)
        assert crane["status"] == "AVAILABLE"


class TestCraneReservedHoursConservation:
    """Difficulty rule: compensating_invariant."""

    def test_configure_puts_the_window_length_on_the_crane_books(self, api):
        """PRD 3.1: "A newly registered machine has `out_of_service_flag` false,
        `reserved_hours_total` at 0, `active_plan_count` at 0 and `status`
        `AVAILABLE`."
        PRD 3.4: "A crane's `reserved_hours_total` is the sum, over every plan on that
        crane whose readiness dimension is `CONFIGURED`, `PENDING_ENGINEERING`,
        `APPROVED` or `RELEASED`, of the plan's window length — `window_end` minus
        `window_start`, expressed in hours — rounded half up to two decimal places,
        and its `active_plan_count` is the number of plans in that same set."

        Design: Difficulty/compensating_invariant/crane_reserved_hours_conserved_across_configure_then_cancel
        """
        world = build_standard_world()
        at_create = read_crane(world["crane_id"])
        assert at_create["reserved_hours_total"] == pytest.approx(0.0)
        assert at_create["status"] == "AVAILABLE"

        ctx = setup_surveyed_plan_with_gear(world, plan_overrides={"job_reference": "JOB-6500"})
        configure_plan(world, ctx["plan_id"], ctx["plan_version"])

        mid = read_crane(world["crane_id"])
        assert mid["reserved_hours_total"] == pytest.approx(10.0)
        assert mid["active_plan_count"] == 1
        assert mid["status"] == "RESERVED"

    def test_cancelling_returns_the_crane_ledger_to_its_pre_configure_value(self, api):
        """PRD 2.9: "A crane's reserved hours and active plan count are recomputed
        from the set of plans currently holding that machine, so configuring a plan
        and then cancelling it must return the crane's reserved hours to the exact
        figure it held before."
        PRD 3.9: "The immediate effects are that every commitment on the plan still
        standing at `ACTIVE` is moved to `RELEASED` with each affected gear item's
        `committed_assignment_count` recomputed"
        PRD 3.1: "Failing that, it is `RESERVED` if `reserved_hours_total` is greater
        than zero. Otherwise it is `AVAILABLE`."

        Design: Difficulty/compensating_invariant/crane_reserved_hours_conserved_across_configure_then_cancel
        """
        world = build_standard_world()
        ctx = setup_surveyed_plan_with_gear(world, plan_overrides={"job_reference": "JOB-6500"})
        configure_plan(world, ctx["plan_id"], ctx["plan_version"])

        validate_success(api.cancel_lift_plan(
            ctx["plan_id"], {"reason": "outage window slipped"}, DISPATCHER))

        after = read_crane(world["crane_id"])
        assert after["reserved_hours_total"] == pytest.approx(0.0), (
            "the ledger must return to exactly 0.0, not drift"
        )
        assert after["active_plan_count"] == 0
        assert after["status"] == "AVAILABLE"

        assert read_assignment(ctx["ga_id"])["status"] == "RELEASED"
        assert read_gear(world["gear_id"])["committed_assignment_count"] == 0
        assert read_plan(ctx["plan_id"])["plan_status"] == "CANCELLED"
