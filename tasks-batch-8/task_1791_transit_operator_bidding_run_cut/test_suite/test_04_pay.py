"""Pay pricing: PROVISIONAL vs FINAL variants, tiered OT split, boundaries,
and the parallel pay-status dimension."""
import pytest

from test_helpers import (
    ApiErrorId,
    close_out,
    create_run_piece,
    find_assignment,
    find_pay_record,
    get_assignment,
    get_pay_records,
    make_operator_headers,
    setup_implemented_with_award,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

PC = TEST_USERS["payroll_clerk_headers"]
SO = TEST_USERS["scheduling_officer_headers"]


class TestProvisionalVsFinal:
    def _setup(self, api):
        return setup_implemented_with_award(
            run_pieces=[create_run_piece(300, 800, 470)],  # spread 500 <600 -> paid 470
            period_overrides={
                "name": "Fall",
                "daily_ot_threshold_minutes": 480,
                "weekly_ot_threshold_minutes": 2400,
            },
            operator_overrides={"vacation_hours_balance": 200},
        )

    def test_provisional_priced_from_scheduled_minutes(self, api):
        """PRD §3.8: "The basis is `scheduled_minutes` for the `PROVISIONAL`
        variant, priced when the assignment is created, and
        `actual_platform_minutes` for the `FINAL` variant, which replaces the
        provisional record's numbers for the same assignment."
        PRD §2.7: "The base pay rate is fifty cents per paid minute; minutes
        classified as overtime are paid at one and a half times that base
        rate."

        Design: Difficulty/dual_variant_calc/pay_record_provisional_vs_final_divergence
        """
        ctx = self._setup(api)
        asg = ctx["assignment"]
        prov = find_pay_record(asg["id"], "PROVISIONAL")
        # scheduled_minutes = run paid_minutes = 470; 470 < 480 daily threshold
        assert prov["straight_minutes"] == 470
        assert prov["overtime_minutes"] == 0
        assert prov["gross_cents"] == 23500  # 470 * 50

    def test_final_diverges_from_provisional_on_actual_minutes(self, api):
        """PRD §3.8: "The basis is `scheduled_minutes` for the `PROVISIONAL`
        variant, priced when the assignment is created, and
        `actual_platform_minutes` for the `FINAL` variant, which replaces the
        provisional record's numbers for the same assignment."
        PRD §3.8: "Close-out moves the assignment from `SCHEDULED` to `WORKED`,
        writes a `FINAL` pay record priced on the actual minutes, and adds that
        record's `overtime_minutes` to the operator's
        `weekly_ot_minutes_accum`."

        Design: Difficulty/dual_variant_calc/pay_record_provisional_vs_final_divergence
        """
        ctx = self._setup(api)
        asg = ctx["assignment"]
        close_out(asg["id"], 430)
        prov = find_pay_record(asg["id"], "PROVISIONAL")
        final = find_pay_record(asg["id"], "FINAL")
        assert prov["variant"] == "PROVISIONAL"
        assert final["variant"] == "FINAL"
        assert final["straight_minutes"] == 430
        assert final["overtime_minutes"] == 0
        assert final["gross_cents"] == 21500  # 430 * 50
        assert final["gross_cents"] != prov["gross_cents"]


class TestTieredPricing:
    def test_weekly_and_daily_tiers_split_three_inputs(self, api):
        """PRD §3.8: "The weekly room remaining is the period's
        `weekly_ot_threshold_minutes` minus the operator's prior straight time
        for the week, floored at zero; prior straight time is the sum of
        `straight_minutes` across the operator's `FINAL` pay records whose
        service dates fall in the same ISO week, computed before this record —
        provisional records never count toward it. Any post-daily straight time
        exceeding that remaining weekly room is reclassified as additional
        weekly overtime. The record's `straight_minutes` are what remains of
        the post-daily straight time after that reclassification, and its
        `overtime_minutes` are the daily overtime plus the weekly
        reclassification."

        Design: Difficulty/combinatorial_formula/pay_price_three_input_tiered_split
        """
        from test_helpers import setup_operator_with_two_assignments_same_week
        ctx = setup_operator_with_two_assignments_same_week(
            daily_ot_threshold_minutes=480, weekly_ot_threshold_minutes=2400
        )
        # Monday cover: basis 900 -> daily_ot 420, post-daily straight 480;
        # weekly room 2400 -> no weekly reclassification.
        close_out(ctx["monday_assignment"]["id"], 900)
        final1 = find_pay_record(ctx["monday_assignment"]["id"], "FINAL")
        assert final1["straight_minutes"] == 480
        assert final1["overtime_minutes"] == 420

        # Tuesday award: basis 500 -> daily_ot 20, post-daily straight 480;
        # weekly room = 2400 - 480 (prior FINAL straight) = 1920 -> no weekly OT.
        close_out(ctx["tuesday_assignment"]["id"], 500)
        final2 = find_pay_record(ctx["tuesday_assignment"]["id"], "FINAL")
        assert final2["straight_minutes"] == 480
        assert final2["overtime_minutes"] == 20
        assert final2["gross_cents"] == 480 * 50 + 20 * 75  # 25500

    def test_weekly_reclassification_when_room_exhausted(self, api):
        """PRD §3.8: "Any post-daily straight time exceeding that remaining
        weekly room is reclassified as additional weekly overtime. The record's
        `straight_minutes` are what remains of the post-daily straight time
        after that reclassification, and its `overtime_minutes` are the daily
        overtime plus the weekly reclassification. Finally, `gross_cents` is
        the straight minutes times the base rate plus the overtime minutes
        times the base rate times one and a half, rounded half-up to whole
        cents at the final sum only, per §2.7."

        Design: Difficulty/combinatorial_formula/pay_price_three_input_tiered_split
        """
        from test_helpers import setup_operator_with_five_assignments_same_week
        # Weekly threshold 2100 — the PRD §3.1 minimum — with four prior FINAL
        # records at 480 straight minutes each (the most a 480 daily threshold
        # leaves under the 960-minute close-out cap) exhausts the weekly room
        # to 180 minutes for the fifth record.
        ctx = setup_operator_with_five_assignments_same_week(
            daily_ot_threshold_minutes=480, weekly_ot_threshold_minutes=2100
        )
        # Mon-Thu covers: basis 500 -> daily_ot 20, post-daily straight 480;
        # weekly room >= 660 -> straight 480, no weekly reclassification.
        for cover in ctx["cover_assignments"]:
            close_out(cover["id"], 500)
            final = find_pay_record(cover["id"], "FINAL")
            assert final["straight_minutes"] == 480
            assert final["overtime_minutes"] == 20

        # Friday award: basis 500 -> daily_ot 20, post-daily straight 480;
        # weekly room = 2100 - 1920 = 180 -> weekly_ot_extra = 480 - 180 = 300.
        close_out(ctx["friday_assignment"]["id"], 500)
        final5 = find_pay_record(ctx["friday_assignment"]["id"], "FINAL")
        assert final5["straight_minutes"] == 180
        assert final5["overtime_minutes"] == 320  # 20 daily + 300 weekly
        assert final5["gross_cents"] == 180 * 50 + 320 * 75  # 9000 + 24000 = 33000


class TestOvertimeBoundary:
    def test_basis_exactly_at_daily_threshold_yields_zero_ot(self, api):
        """PRD §3.8: "Daily overtime is the portion of the basis lying beyond
        the period's `daily_ot_threshold_minutes` — zero when the basis does
        not exceed the threshold"
        PRD §2.7: "The base pay rate is fifty cents per paid minute; minutes
        classified as overtime are paid at one and a half times that base
        rate."

        Design: Difficulty/boundary_precision_check/daily_ot_threshold_exact_boundary
        """
        ctx = setup_implemented_with_award(
            run_pieces=[create_run_piece(300, 780, 480)],  # platform 480
            period_overrides={"daily_ot_threshold_minutes": 480,
                              "weekly_ot_threshold_minutes": 2400},
        )
        asg = ctx["assignment"]
        close_out(asg["id"], 480)
        final = find_pay_record(asg["id"], "FINAL")
        assert final["overtime_minutes"] == 0
        assert final["straight_minutes"] == 480
        assert final["gross_cents"] == 24000  # 480 * 50

    def test_basis_one_above_daily_threshold_yields_one_ot_minute(self, api):
        """PRD §3.8: "Daily overtime is the portion of the basis lying beyond
        the period's `daily_ot_threshold_minutes` — zero when the basis does
        not exceed the threshold"

        Design: Difficulty/boundary_precision_check/daily_ot_threshold_exact_boundary
        """
        ctx = setup_implemented_with_award(
            run_pieces=[create_run_piece(300, 781, 481)],  # platform 481
            period_overrides={"daily_ot_threshold_minutes": 480,
                              "weekly_ot_threshold_minutes": 2400},
        )
        asg = ctx["assignment"]
        close_out(asg["id"], 481)
        final = find_pay_record(asg["id"], "FINAL")
        assert final["overtime_minutes"] == 1
        assert final["straight_minutes"] == 480
        assert final["gross_cents"] == 480 * 50 + 75  # 24075


class TestPricingConstants:
    def test_ot_multiplier_applied_at_one_and_a_half(self, api):
        """PRD §2.7: "The base pay rate is fifty cents per paid minute; minutes
        classified as overtime are paid at one and a half times that base
        rate."
        PRD §3.8: "Finally, `gross_cents` is the straight minutes times the
        base rate plus the overtime minutes times the base rate times one and a
        half, rounded half-up to whole cents at the final sum only, per §2.7."

        Design: Corner/calculations/pay_price_constants_applied
        """
        ctx = setup_implemented_with_award(
            run_pieces=[create_run_piece(300, 880, 580)],  # platform 580
            period_overrides={"daily_ot_threshold_minutes": 480,
                              "weekly_ot_threshold_minutes": 2400},
        )
        asg = ctx["assignment"]
        close_out(asg["id"], 580)
        final = find_pay_record(asg["id"], "FINAL")
        assert final["straight_minutes"] == 480
        assert final["overtime_minutes"] == 100
        assert final["gross_cents"] == 31500  # 480*50 + 100*75


class TestCloseOutValidation:
    def test_zero_actual_minutes_rejected(self, api):
        """PRD §3.8: "The minutes are validated next: the value must be present
        in the payload, greater than zero, and no more than 960 — sixteen hours
        — with any failure rejected as `ERR_INVALID_ACTUAL_MINUTES`."

        Design: Corner/validations/close_out_invalid_actual_minutes
        """
        ctx = setup_implemented_with_award()
        asg = ctx["assignment"]
        resp = api.close_out_assignment(asg["id"], {"actual_platform_minutes": 0}, PC)
        validate_error(resp, ApiErrorId.ERR_INVALID_ACTUAL_MINUTES)


class TestParallelPayDimension:
    def _worked_assignment(self, api):
        ctx = setup_implemented_with_award(
            run_pieces=[create_run_piece(300, 700, 400)],
            period_overrides={"daily_ot_threshold_minutes": 480,
                              "weekly_ot_threshold_minutes": 2400},
        )
        asg = ctx["assignment"]
        close_out(asg["id"], 400)
        return ctx, get_assignment(asg["id"])

    def test_dispute_then_finalize_leaves_work_status_untouched(self, api):
        """PRD §3.8: "An assignment carries two parallel state dimensions that
        evolve independently: `status` tracks the work lifecycle through
        `SCHEDULED`, `WORKED`, `NO_SHOW`, and `CANCELLED`, while `pay_status`
        tracks pay validation through `PROVISIONAL`, `FINALIZED`, and
        `DISPUTED`."
        PRD §3.8: "A disputed assignment can subsequently be finalized by the
        clerk once a `FINAL` pay record exists, moving `pay_status` from
        `DISPUTED` to `FINALIZED`."

        Design: Difficulty/non_linear_state_machine/daily_assignment_parallel_pay_dimension
        """
        ctx, worked = self._worked_assignment(api)
        assert worked["status"] == "WORKED"
        assert worked["pay_status"] == "PROVISIONAL"
        op_headers = make_operator_headers(ctx["operator"]["id"])
        resp = api.dispute_pay(worked["id"], op_headers)
        validate_success(resp)
        disputed = get_assignment(worked["id"])
        assert disputed["pay_status"] == "DISPUTED"
        assert disputed["status"] == "WORKED"
        resp = api.finalize_pay(worked["id"], PC)
        finalized = validate_success(resp)
        assert finalized["pay_status"] == "FINALIZED"
        assert finalized["status"] == "WORKED"

    def test_finalize_sets_pay_status_finalized_after_dispute(self, api):
        """PRD §3.8: "The assigned operator — and only that operator, by the
        identity rule of §2.1 — may dispute the pay, moving `pay_status` from
        `PROVISIONAL` or `FINALIZED` to `DISPUTED`. A disputed assignment can
        subsequently be finalized by the clerk once a `FINAL` pay record
        exists, moving `pay_status` from `DISPUTED` to `FINALIZED`."

        Design: Difficulty/non_linear_state_machine/daily_assignment_parallel_pay_dimension
        """
        ctx, worked = self._worked_assignment(api)
        op_headers = make_operator_headers(ctx["operator"]["id"])
        validate_success(api.dispute_pay(worked["id"], op_headers))
        validate_success(api.finalize_pay(worked["id"], PC))
        after = get_assignment(worked["id"])
        assert after["status"] == "WORKED"
        assert after["pay_status"] == "FINALIZED"
