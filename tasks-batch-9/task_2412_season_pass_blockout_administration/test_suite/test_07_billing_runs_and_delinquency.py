"""The monthly billing run: the delinquency ladder and its cascade."""

from test_helpers import (
    BRONZE,
    ApiErrorId,
    BillingStatus,
    GateCode,
    InstallmentStatus,
    PassStatus,
    PaymentMode,
    PlanStatus,
    ProgramStatus,
    ReservationStatus,
    VisitStatus,
    assert_billing_run_counts,
    assert_day_counters,
    assert_day_posture,
    assert_grant_count_conserved,
    assert_installment_statuses,
    assert_pass_dimensions,
    assert_version_unchanged,
    advance_program,
    book_reservation,
    build_active_pass,
    build_plan,
    build_program,
    clerk_headers,
    create_park_day,
    get_park_day,
    get_pass,
    get_plan,
    assert_ledger,
    plan_installments,
    record_visit,
    reinstate_pass,
    reinstate_payload,
    run_billing,
    set_clock,
    validate_error,
    validate_success,
)


def _reservation(api, reservation_id):
    return validate_success(api.get_reservation(reservation_id, headers=clerk_headers()))


class TestParallelBillingAndAccessDimensions:
    """One missed installment moves the billing dimension and nothing else."""

    def _delinquent_pass(self, api):
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SEASON_ACTIVE.value)
        day = create_park_day(api, program.id, "2026-09-20")
        pass_ctx = build_active_pass(
            api, program, tier_name="BRONZE", payment_mode=PaymentMode.PAYMENT_PLAN.value
        )
        plan_ctx = build_plan(api, pass_ctx.id, 3000, 4, "2026-09-01")
        set_clock(api, "2026-09-20T09:00:00Z")
        run = run_billing(api, program.id, "2026-09-15")
        return program, day, pass_ctx, plan_ctx, run

    def test_one_missed_installment_makes_the_pass_delinquent_but_leaves_it_active(self, api):
        """The two dimensions move independently on a single missed payment.

        PRD: "Note carefully that while `missed_count` remains below the suspension
        threshold, `pass_status` is not touched at all — one missed payment makes a pass
        delinquent but leaves the guest walking through the gate"

        Design: Difficulty/non_linear_state_machine/season_pass_parallel_billing_and_access_dimensions
        """
        _, _, pass_ctx, plan_ctx, run = self._delinquent_pass(api)

        assert_billing_run_counts(
            run,
            missed_installment_count=1,
            delinquent_pass_count=1,
            suspended_pass_count=0,
            defaulted_pass_count=0,
            released_reservation_count=0,
            no_show_reservation_count=0,
        )
        pass_row = get_pass(api, pass_ctx.id)
        assert_pass_dimensions(
            pass_row,
            pass_status=PassStatus.ACTIVE.value,
            billing_status=BillingStatus.DELINQUENT.value,
        )
        assert pass_row["suspension_count"] == 0, (
            f"one missed installment must not suspend the pass, got suspension_count {pass_row['suspension_count']!r}"
        )
        plan = get_plan(api, plan_ctx.id)
        assert (plan["missed_count"], plan["settled_count"]) == (1, 0), (
            f"the plan should report one missed and no settled rows, got {plan['missed_count']!r} and {plan['settled_count']!r}"
        )
        assert plan["plan_status"] == PlanStatus.ACTIVE.value, (
            f"the plan stays ACTIVE while it is merely behind, got {plan['plan_status']!r}"
        )
        assert_installment_statuses(
            plan_installments(api, plan_ctx.id),
            [
                InstallmentStatus.MISSED.value,
                InstallmentStatus.SCHEDULED.value,
                InstallmentStatus.SCHEDULED.value,
                InstallmentStatus.SCHEDULED.value,
            ],
        )

    def test_a_delinquent_pass_still_opens_a_turnstile(self, api):
        """The access dimension never moves on a billing event.

        PRD: "The **billing dimension**, `billing_status`, takes the values `UNBILLED`,
        `PLAN_CURRENT`, `DELINQUENT`, `DEFAULTED` and `PAID_IN_FULL`, has no terminal
        state at all, and moves only on plan enrolment, installment settlement, billing
        runs and reinstatement — never on a gate or access event."

        Design: Difficulty/non_linear_state_machine/season_pass_parallel_billing_and_access_dimensions
        """
        _, day, pass_ctx, _, _ = self._delinquent_pass(api)

        visit = record_visit(api, pass_ctx.id, day["id"], "2026-09-20T10:00:00Z", GateCode.NORTH.value)

        assert visit["status"] == VisitStatus.OPEN.value, (
            f"the gate entry should open a visit, got {visit['status']!r}"
        )
        pass_row = get_pass(api, pass_ctx.id)
        assert pass_row["visit_count"] == 1, (
            f"the entry should raise visit_count to 1, got {pass_row['visit_count']!r}"
        )
        assert_pass_dimensions(
            pass_row,
            pass_status=PassStatus.ACTIVE.value,
            billing_status=BillingStatus.DELINQUENT.value,
        )


class TestSuspensionCascadeReleasesReservations:
    """Two missed installments suspend the pass and take its bookings back."""

    def _suspended_pass(self, api):
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SEASON_ACTIVE.value)
        day = create_park_day(api, program.id, "2026-10-20")
        pass_ctx = build_active_pass(
            api, program, tier_name="BRONZE", payment_mode=PaymentMode.PAYMENT_PLAN.value
        )
        plan_ctx = build_plan(api, pass_ctx.id, 3000, 4, "2026-09-01")
        reservation = book_reservation(api, pass_ctx.id, day["id"], "09:00", "12:00")
        run = run_billing(api, program.id, "2026-10-02")
        return program, day, pass_ctx, plan_ctx, reservation, run

    def test_the_second_missed_installment_suspends_the_access_dimension(self, api):
        """The ladder moves the access dimension while billing stays delinquent.

        PRD: "A run as of the second of October marks the second, so `missed_count`
        reaches two, the pass remains `DELINQUENT` on the billing dimension but moves to
        `SUSPENDED` on the access dimension, and its future confirmed reservations are
        released."

        Design: Difficulty/transitive_cascade/billing_run_missed_to_delinquent_to_suspension_to_reservation_release
        """
        _, _, pass_ctx, plan_ctx, _, run = self._suspended_pass(api)

        assert_billing_run_counts(
            run,
            missed_installment_count=2,
            delinquent_pass_count=1,
            suspended_pass_count=1,
            defaulted_pass_count=0,
            released_reservation_count=1,
            no_show_reservation_count=0,
        )
        pass_row = get_pass(api, pass_ctx.id)
        assert_pass_dimensions(
            pass_row,
            pass_status=PassStatus.SUSPENDED.value,
            billing_status=BillingStatus.DELINQUENT.value,
        )
        assert pass_row["suspension_count"] == 1, (
            f"the suspension should be counted once, got {pass_row['suspension_count']!r}"
        )
        plan = get_plan(api, plan_ctx.id)
        assert plan["missed_count"] == 2, (
            f"the plan should report two missed installments, got {plan['missed_count']!r}"
        )
        assert plan["plan_status"] == PlanStatus.ACTIVE.value, (
            f"the plan is still ACTIVE at two missed rows, got {plan['plan_status']!r}"
        )
        assert_installment_statuses(
            plan_installments(api, plan_ctx.id),
            [
                InstallmentStatus.MISSED.value,
                InstallmentStatus.MISSED.value,
                InstallmentStatus.SCHEDULED.value,
                InstallmentStatus.SCHEDULED.value,
            ],
        )

    def test_the_suspension_releases_the_future_booking_and_rewrites_the_day(self, api):
        """Level three of the cascade lands on the park day's slot counters.

        PRD: "At level three, because the pass became `SUSPENDED`, every reservation of
        that pass still in `CONFIRMED` becomes `CANCELLED_BY_SUSPENSION` and each
        affected park day recomputes its `reserved_count`, `released_count` and
        `remaining_slot_count`."

        Design: Difficulty/transitive_cascade/billing_run_missed_to_delinquent_to_suspension_to_reservation_release
        """
        _, day, _, _, reservation, _ = self._suspended_pass(api)

        released = _reservation(api, reservation["id"])
        assert released["status"] == ReservationStatus.CANCELLED_BY_SUSPENSION.value, (
            f"the booking should be CANCELLED_BY_SUSPENSION, got {released['status']!r}"
        )
        day_row = get_park_day(api, day["id"])
        assert_day_posture(day_row, slot_capacity=100)
        assert_day_counters(day_row, reserved=0, released=1, redeemed=0, no_show=0, remaining=100, grant=1)
        assert_grant_count_conserved(day_row)


class TestSuccessiveRunsWalkTheScheduleInDueDateOrder:
    """Two runs a month apart mark exactly the rows their as-of date has passed."""

    def _plan_with_two_bookings(self, api):
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SALES_OPEN.value)
        september = create_park_day(api, program.id, "2026-09-20")
        october = create_park_day(api, program.id, "2026-10-25")
        pass_ctx = build_active_pass(
            api, program, tier_name="BRONZE", payment_mode=PaymentMode.PAYMENT_PLAN.value
        )
        plan_ctx = build_plan(api, pass_ctx.id, 3000, 4, "2026-09-01")
        advance_program(api, program.id, ProgramStatus.SEASON_ACTIVE.value)
        september_booking = book_reservation(api, pass_ctx.id, september["id"], "09:00", "12:00")
        october_booking = book_reservation(api, pass_ctx.id, october["id"], "09:00", "12:00")
        first_run = run_billing(api, program.id, "2026-10-02")
        return {
            "program": program,
            "september": september,
            "october": october,
            "pass_ctx": pass_ctx,
            "plan_ctx": plan_ctx,
            "september_booking": september_booking,
            "october_booking": october_booking,
            "first_run": first_run,
        }

    def test_the_first_run_splits_its_sweep_on_the_as_of_date(self, api, default_clock):
        """The past-dated booking is a no-show; the future-dated one is taken back.

        PRD: "First, reservations: every reservation still in `CONFIRMED` whose park day's
        `calendar_date` falls strictly before the run's `as_of_date` becomes `NO_SHOW`, and
        each affected day's `reserved_count` drops by one while its `no_show_count` rises by
        one and `remaining_slot_count` is recomputed; separately, reservations on days
        falling on or after `as_of_date` that belong to a pass this run suspended become
        `CANCELLED_BY_SUSPENSION` instead, with `reserved_count` dropping by one,
        `released_count` rising by one and `remaining_slot_count` recomputed."

        Design: Corner/calculations/billing_run_marks_the_third_missed_installment_defaulted_in_due_date_order
        """
        world = self._plan_with_two_bookings(api)

        assert_billing_run_counts(
            world["first_run"],
            missed_installment_count=2,
            delinquent_pass_count=1,
            defaulted_pass_count=0,
            suspended_pass_count=1,
            no_show_reservation_count=1,
            released_reservation_count=1,
        )
        assert (
            _reservation(api, world["september_booking"]["id"])["status"]
            == ReservationStatus.NO_SHOW.value
        ), "the booking on the day before the as-of date is a no-show"
        assert (
            _reservation(api, world["october_booking"]["id"])["status"]
            == ReservationStatus.CANCELLED_BY_SUSPENSION.value
        ), "the future-dated booking of the suspended pass is taken back"
        september_row = get_park_day(api, world["september"]["id"])
        assert_day_counters(september_row, reserved=0, no_show=1, released=0, grant=1)
        assert_grant_count_conserved(september_row)
        october_row = get_park_day(api, world["october"]["id"])
        assert_day_counters(october_row, reserved=0, released=1, no_show=0, grant=1)
        assert_grant_count_conserved(october_row)

    def test_the_second_run_marks_only_the_third_row_and_defaults_the_pass(self, api, default_clock):
        """Crossing the default threshold does not count a second suspension.

        PRD: "Note carefully that while `missed_count` remains below the suspension
        threshold, `pass_status` is not touched at all — one missed payment makes a pass
        delinquent but leaves the guest walking through the gate — and that when the default
        threshold is reached, `pass_status` is already `SUSPENDED` from the earlier rung."

        Design: Corner/calculations/billing_run_marks_the_third_missed_installment_defaulted_in_due_date_order
        """
        world = self._plan_with_two_bookings(api)

        second_run = run_billing(api, world["program"].id, "2026-11-02")

        assert_billing_run_counts(
            second_run,
            missed_installment_count=1,
            defaulted_pass_count=1,
            suspended_pass_count=0,
        )
        assert_installment_statuses(
            plan_installments(api, world["plan_ctx"].id),
            [
                InstallmentStatus.MISSED.value,
                InstallmentStatus.MISSED.value,
                InstallmentStatus.MISSED.value,
                InstallmentStatus.SCHEDULED.value,
            ],
        )
        plan_row = get_plan(api, world["plan_ctx"].id)
        assert plan_row["missed_count"] == 3, (
            f"three installments are now past due, got {plan_row['missed_count']!r}"
        )
        assert plan_row["settled_count"] == 0, (
            f"nothing has been paid on this plan, got {plan_row['settled_count']!r}"
        )
        pass_row = get_pass(api, world["pass_ctx"].id)
        assert_pass_dimensions(
            pass_row,
            pass_status=PassStatus.SUSPENDED.value,
            billing_status=BillingStatus.DEFAULTED.value,
        )
        assert pass_row["suspension_count"] == 1, (
            "the pass was already suspended, so the default must not count a second "
            f"suspension, got {pass_row['suspension_count']!r}"
        )


class TestReinstatementCuresWithoutRestoringSlots:
    """A cured pass walks back through the gate but not back into its booking."""

    def _suspended_world(self, api):
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SEASON_ACTIVE.value)
        day = create_park_day(api, program.id, "2026-10-20")
        pass_ctx = build_active_pass(
            api, program, tier_name="BRONZE", payment_mode=PaymentMode.PAYMENT_PLAN.value
        )
        plan_ctx = build_plan(api, pass_ctx.id, 3000, 4, "2026-09-01")
        reservation = book_reservation(api, pass_ctx.id, day["id"], "09:00", "12:00")
        run_billing(api, program.id, "2026-10-02")
        return program, day, pass_ctx, plan_ctx, reservation

    def test_the_cure_settles_every_missed_installment_and_reactivates_the_pass(
        self, api, default_clock
    ):
        """Tendering exactly the arrears returns both dimensions to good standing.

        PRD: "Every `MISSED` installment of the active plan moves `MISSED → SETTLED` with
        `settled_at` set to the logical clock's current instant, except the one named by
        `waive_installment_id`, which moves `MISSED → WAIVED` instead; a waived installment
        reduces the pass's `billed_total_cents` by its `amount_cents` rather than crediting
        anything to `paid_to_date_cents`, and the plan's `missed_count` is recomputed either
        way."

        Design: Corner/state_machines/reinstate_cures_missed_installments_without_restoring_reservations
        """
        _, _, pass_ctx, plan_ctx, _ = self._suspended_world(api)

        reinstated = reinstate_pass(api, pass_ctx.id, 5250)

        assert_pass_dimensions(
            reinstated,
            pass_status=PassStatus.ACTIVE.value,
            billing_status=BillingStatus.PLAN_CURRENT.value,
        )
        assert_ledger(reinstated, billed=13500, paid=8250, credited=0, outstanding=5250)
        assert reinstated["suspension_count"] == 1, (
            "the cure does not erase the fact of the suspension, got "
            f"{reinstated['suspension_count']!r}"
        )
        assert_installment_statuses(
            plan_installments(api, plan_ctx.id),
            [
                InstallmentStatus.SETTLED.value,
                InstallmentStatus.SETTLED.value,
                InstallmentStatus.SCHEDULED.value,
                InstallmentStatus.SCHEDULED.value,
            ],
        )
        plan_row = get_plan(api, plan_ctx.id)
        assert plan_row["missed_count"] == 0, (
            f"the arrears are cleared, got {plan_row['missed_count']!r} missed"
        )
        assert plan_row["settled_count"] == 2, (
            f"two installments have now been settled, got {plan_row['settled_count']!r}"
        )
        assert plan_row["plan_status"] == PlanStatus.ACTIVE.value, (
            f"two installments still remain, so the plan stays ACTIVE, got {plan_row['plan_status']!r}"
        )

    def test_the_released_slot_is_not_handed_back(self, api, default_clock):
        """The guest must book again; the day keeps the slot it took back.

        PRD: "Reservations cancelled by the suspension are **not** restored: released
        slots stay released, and the guest must book again."

        Design: Corner/state_machines/reinstate_cures_missed_installments_without_restoring_reservations
        """
        _, day, pass_ctx, _, reservation = self._suspended_world(api)

        reinstate_pass(api, pass_ctx.id, 5250)

        assert (
            _reservation(api, reservation["id"])["status"]
            == ReservationStatus.CANCELLED_BY_SUSPENSION.value
        ), "the cancelled booking stays cancelled after the cure"
        day_row = get_park_day(api, day["id"])
        assert_day_counters(day_row, reserved=0, released=1, remaining=100, grant=1)
        assert_grant_count_conserved(day_row)


class TestCureAmountMustMatchTheArrears:
    """The cure is exact arithmetic over the missed rows, less any waived one."""

    def _suspended_pass_with_two_missed_rows(self, api):
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SALES_OPEN.value)
        pass_ctx = build_active_pass(
            api, program, tier_name="BRONZE", payment_mode=PaymentMode.PAYMENT_PLAN.value
        )
        plan_ctx = build_plan(api, pass_ctx.id, 3000, 4, "2026-09-01")
        run_billing(api, program.id, "2026-10-02")
        return program, pass_ctx, plan_ctx

    def test_tendering_only_one_of_two_missed_installments_is_refused(self, api, default_clock):
        """Two missed rows of 2625 require 5250, not 2625.

        PRD: "A tendered `cure_amount_cents` that does not exactly equal that figure is
        rejected with `ERR_CURE_AMOUNT_MISMATCH` (HTTP 422), and at most one installment may
        be waived per reinstatement."

        Design: Corner/validations/reinstate_cure_amount_must_match_the_missed_total_minus_the_waived_row
        """
        _, pass_ctx, _ = self._suspended_pass_with_two_missed_rows(api)

        response = api.reinstate_season_pass(
            pass_ctx.id, reinstate_payload(2625), headers=clerk_headers()
        )

        validate_error(response, ApiErrorId.ERR_CURE_AMOUNT_MISMATCH.value, 422)
        pass_row = get_pass(api, pass_ctx.id)
        assert_pass_dimensions(pass_row, pass_status=PassStatus.SUSPENDED.value)
        assert_ledger(pass_row, paid=3000)

    def test_waiving_the_second_row_makes_the_same_tender_correct(self, api, default_clock):
        """The waived row is forgiven rather than collected.

        PRD: "The required cure amount is the sum of `amount_cents` over every installment
        of the pass's active plan whose `status` is `MISSED`, less the `amount_cents` of the
        waived installment when one is named."

        Design: Corner/validations/reinstate_cure_amount_must_match_the_missed_total_minus_the_waived_row
        """
        _, pass_ctx, plan_ctx = self._suspended_pass_with_two_missed_rows(api)
        rows = plan_installments(api, plan_ctx.id)

        reinstated = reinstate_pass(api, pass_ctx.id, 2625, waive_installment_id=rows[1]["id"])

        assert_pass_dimensions(
            reinstated,
            pass_status=PassStatus.ACTIVE.value,
            billing_status=BillingStatus.PLAN_CURRENT.value,
        )
        assert reinstated["paid_to_date_cents"] == 5625, (
            "the down payment plus the single cure payment is 5625, got "
            f"{reinstated['paid_to_date_cents']!r}"
        )
        assert_installment_statuses(
            plan_installments(api, plan_ctx.id),
            [
                InstallmentStatus.SETTLED.value,
                InstallmentStatus.WAIVED.value,
                InstallmentStatus.SCHEDULED.value,
                InstallmentStatus.SCHEDULED.value,
            ],
        )
        assert get_plan(api, plan_ctx.id)["missed_count"] == 0, (
            "the arrears are cleared by the settlement and the waiver together"
        )


class TestTheRunSkipsPassesWithNothingOwing:
    """One sweep over the programme touches only the rows that are actually late."""

    def _one_plan_and_one_paid_pass(self, api):
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SALES_OPEN.value)
        plan_pass = build_active_pass(
            api,
            program,
            tier_name="BRONZE",
            payment_mode=PaymentMode.PAYMENT_PLAN.value,
            holder_overrides={"full_name": "Ada Holder", "email": "bulk-plan@example.com"},
        )
        plan_ctx = build_plan(api, plan_pass.id, 3000, 4, "2026-09-01")
        paid_pass = build_active_pass(
            api,
            program,
            tier_name="BRONZE",
            payment_mode=PaymentMode.PAY_IN_FULL.value,
            holder_overrides={"full_name": "Ben Holder", "email": "bulk-paid@example.com"},
        )
        return program, plan_pass, paid_pass, plan_ctx

    def test_the_run_suspends_the_late_plan_and_leaves_the_paid_pass_alone(
        self, api, default_clock
    ):
        """Only plans in ACTIVE are examined, so a pass with no plan is never rewritten.

        PRD: "Installments belonging to every plan of the programme whose `plan_status` is
        `ACTIVE` are examined in ascending `due_date`, then within a due date in ascending
        `sequence_no`, then in ascending `created_at` — never by identifier — so that
        out-of-order record creation cannot change the outcome."

        Design: Corner/endpoints/billing_run_is_a_bulk_action_that_skips_healthy_passes
        """
        program, plan_pass, paid_pass, _ = self._one_plan_and_one_paid_pass(api)
        paid_before = get_pass(api, paid_pass.id)

        result = run_billing(api, program.id, "2026-10-02")

        assert_billing_run_counts(
            result,
            missed_installment_count=2,
            delinquent_pass_count=1,
            suspended_pass_count=1,
            defaulted_pass_count=0,
            released_reservation_count=0,
            no_show_reservation_count=0,
            expired_upgrade_order_count=0,
        )
        assert_pass_dimensions(
            get_pass(api, plan_pass.id),
            pass_status=PassStatus.SUSPENDED.value,
            billing_status=BillingStatus.DELINQUENT.value,
        )
        paid_after = get_pass(api, paid_pass.id)
        assert_pass_dimensions(
            paid_after,
            pass_status=PassStatus.ACTIVE.value,
            billing_status=BillingStatus.PAID_IN_FULL.value,
        )
        assert_version_unchanged(paid_before, paid_after, "the pass with nothing owing")

    def test_a_second_run_on_the_same_date_counts_nothing_twice(self, api, default_clock):
        """Only rows still in SCHEDULED are marked, so a repeat run reports zero.

        PRD: "For each installment whose `status` is `SCHEDULED` and whose `due_date` falls
        strictly before the run's `as_of_date`, taken in that order, the run drives
        `SCHEDULED → MISSED` and then walks a three-level cascade."

        Design: Corner/endpoints/billing_run_is_a_bulk_action_that_skips_healthy_passes
        """
        program, _, _, plan_ctx = self._one_plan_and_one_paid_pass(api)
        run_billing(api, program.id, "2026-10-02")

        second = run_billing(api, program.id, "2026-10-02")

        assert_billing_run_counts(
            second,
            missed_installment_count=0,
            delinquent_pass_count=0,
            suspended_pass_count=0,
            defaulted_pass_count=0,
        )
        assert_installment_statuses(
            plan_installments(api, plan_ctx.id),
            [
                InstallmentStatus.MISSED.value,
                InstallmentStatus.MISSED.value,
                InstallmentStatus.SCHEDULED.value,
                InstallmentStatus.SCHEDULED.value,
            ],
        )
