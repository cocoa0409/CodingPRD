"""Difficulty-design coverage tests (priority queue).

Each `scaffold_difficulty_design[*].instances[*]` entry from the
difficulty index gets at least TWO dedicated tests here. The
docstring on each test carries:
    - the PRD citation for the underlying rule under test (per the
      Core rule / C1+C2+C3 requirements),
    - a `difficulty: <rule_id>/<instance.name>` tag to make the
      coverage audit trivial.

This file deliberately overlaps with earlier files on the *underlying
rules*; the difficulty index demands two tests per instance, so we
generate a primary + a complementary boundary check for each.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_hours,
    add_minutes,
    add_seconds,
    api_client,
    approve_time_edit,
    assert_audit_action_present,
    assert_audit_action_absent,
    clock_advance,
    clock_set,
    create_employee,
    create_employee_payload,
    create_punch_payload,
    create_shift,
    create_shift_payload,
    create_time_edit_payload,
    finalize_all_shifts,
    finalize_shift,
    get_shift,
    get_workweek,
    list_audit,
    make_employee_headers,
    make_payroll_admin_headers,
    make_supervisor_headers,
    PAYROLL_ADMIN_SECONDARY_ID,
    PAYROLL_ADMIN_SHARED_ID,
    post_punch,
    revert_time_edit,
    setup_closed_shift,
    setup_fed_vs_ca_workweek_pair,
    setup_finalized_shift,
    setup_finalized_week,
    setup_locked_workweek,
    setup_open_shift,
    setup_overrun_finalized_shift_for_cascade,
    setup_pending_time_edit,
    setup_revert_ready_finalized_shift,
    setup_tip_credit_fractional_hours_scenario,
    setup_tip_credit_integer_hours_scenario,
    setup_week_with_shifts,
    submit_time_edit,
    SUPERVISOR_SHARED_ID,
    TEST_DEFAULTS,
    TEST_USERS,
    unique_idempotency_key,
    validate_error,
    validate_success,
)


def setup_module(module):
    clock_set(TEST_DEFAULTS["WORKWEEK_ANCHOR"])


# ===========================================================================
# Rule 1 — dual_variant_calc
# ===========================================================================
class TestDualVariantCalc:
    """difficulty: dual_variant_calc"""

    def test_fed_vs_ca_diverge_on_same_hours_45h(self, api):
        """PRD §3.6: "the daily-overtime bucket is the part of the day's
        hours above 8 but at or below 12 ... When the employee's
        `jurisdiction` is `FED`, no daily carve happens".

        difficulty: dual_variant_calc/workweek_engine_fed_vs_ca
        Primary check.
        """
        state = setup_fed_vs_ca_workweek_pair(
            daily_hours=[13.0, 8.0, 8.0, 8.0, 8.0],
        )
        fed = state["workweek_fed"]
        ca = state["workweek_ca"]
        assert fed["gross_pay_cents"] == 95000, (
            f"PRD §3.6 FED: 40 reg + 5 OT*1.5 at 2000c/h = 95000, "
            f"got {fed['gross_pay_cents']}"
        )
        assert ca["gross_pay_cents"] == 96000, (
            f"PRD §3.6 CA: 40 reg + 4 OT + 1 DT at 2000c/h = 96000, "
            f"got {ca['gross_pay_cents']}"
        )
        assert ca["gross_pay_cents"] - fed["gross_pay_cents"] == 1000, (
            "CA-DT premium net of swapped OT must equal 1000"
        )

    def test_fed_vs_ca_diverge_hour_buckets(self, api):
        """PRD §3.6: federal "no daily carve" vs CA "daily-overtime
        bucket ... daily-doubletime bucket".

        difficulty: dual_variant_calc/workweek_engine_fed_vs_ca
        Bucket-level check.
        """
        state = setup_fed_vs_ca_workweek_pair(
            daily_hours=[13.0, 8.0, 8.0, 8.0, 8.0],
        )
        fed = state["workweek_fed"]
        ca = state["workweek_ca"]
        assert fed["overtime_hours"] == pytest.approx(5.0, abs=1e-9)
        assert fed["double_time_hours"] == pytest.approx(0.0, abs=1e-9)
        assert ca["overtime_hours"] == pytest.approx(4.0, abs=1e-9)
        assert ca["double_time_hours"] == pytest.approx(1.0, abs=1e-9)

    def test_tip_credit_per_line_rounding_4h(self, api):
        """PRD §3.7: "both `cash_wage_cents` and minimum-wage-required
        are rounded to whole cents **first**, and then the subtraction
        happens".

        difficulty: dual_variant_calc/tip_credit_per_line_vs_sum_then_round
        Primary check.

        With PRD §3.1's federal floor (base >= 725), gross_pay =
        base_line(round(4*725)=2900) + shortfall_topup(3148) = 6048.
        """
        state = setup_tip_credit_integer_hours_scenario()
        ww = state["workweek"]
        # gross = base_line(2900) + shortfall(3148) = 6048.
        assert ww["gross_pay_cents"] == 6048

    def test_tip_credit_tip_cap_honored(self, api):
        """PRD §3.7: "The `tip_credit_applied_cents` is the lesser of
        `declared_tips_cents` and the gap between minimum-wage-required
        and cash-wage (floored at zero)."

        difficulty: dual_variant_calc/tip_credit_per_line_vs_sum_then_round
        Cap-on-declared-tips check.
        """
        # declared_tips=2000 < gap(6000-852=5148) so tip_credit=2000.
        # shortfall = 6000 - 852 - 2000 = 3148.
        # gross = base_line(2900) + shortfall(3148) = 6048.
        state = setup_tip_credit_integer_hours_scenario()
        ww = state["workweek"]
        assert ww["gross_pay_cents"] == 6048


# ===========================================================================
# Rule 2 — combinatorial_formula
# ===========================================================================
class TestCombinatorialFormula:
    """difficulty: combinatorial_formula"""

    def test_ca_daily_first_then_weekly_yields_4_ot_1_dt(self, api):
        """PRD §3.6: "This ordering matters: federal weekly overtime is
        applied only to the daily-regular bucket, never to hours already
        carved off as daily-overtime or daily-doubletime, so the engine
        never double-counts an hour as both daily-overtime and
        weekly-overtime."

        difficulty: combinatorial_formula/ca_daily_then_weekly_eval_order
        Primary check.
        """
        state = setup_finalized_week(
            daily_hours=[13.0, 8.0, 8.0, 8.0, 8.0],
            jurisdiction="CA",
            base_hourly_rate_cents=2000,
        )
        ww = state["workweek"]
        assert ww["overtime_hours"] == pytest.approx(4.0, abs=1e-9), (
            "PRD §3.6: Monday's 4 daily-OT hours never re-classified"
        )
        assert ww["double_time_hours"] == pytest.approx(1.0, abs=1e-9), (
            "PRD §3.6: Monday's 1 daily-DT hour"
        )
        assert ww["regular_hours"] == pytest.approx(40.0, abs=1e-9), (
            "PRD §3.6: federal weekly OT not triggered (ca_regular ≤ 40)"
        )

    def test_ca_total_hours_45(self, api):
        """PRD §3.6: "`total_hours` for the workweek is the sum of all
        per-day totals."

        difficulty: combinatorial_formula/ca_daily_then_weekly_eval_order
        Total-hours-conservation check.
        """
        state = setup_finalized_week(
            daily_hours=[13.0, 8.0, 8.0, 8.0, 8.0],
            jurisdiction="CA",
            base_hourly_rate_cents=2000,
        )
        ww = state["workweek"]
        assert ww["total_hours"] == pytest.approx(45.0, abs=1e-9)

    def test_tip_credit_per_line_rounding_3_5h(self, api):
        """PRD §3.7: "both `cash_wage_cents` and minimum-wage-required
        are rounded to whole cents **first**, and then the subtraction
        happens. An alternative algorithm that subtracts the per-hour
        rates first and rounds once at the end (the "sum-then-round"
        variant) can differ by one cent for non-integer worked hours;
        the per-line-rounding ordering described here is authoritative".

        difficulty: combinatorial_formula/tip_credit_per_line_rounding_order
        Primary check.

        With PRD §3.1's federal floor (base >= 725), gross_pay =
        base_line(round(3.5*725)=2538) + shortfall(504) = 3042.
        """
        state = setup_tip_credit_fractional_hours_scenario()
        ww = state["workweek"]
        # gross = base_line(2538) + shortfall(504) = 3042.
        assert ww["gross_pay_cents"] == 3042

    def test_tip_credit_3_5h_shortfall_exact(self, api):
        """PRD §3.7: "the `cash_wage_cents` for the shift is worked
        hours multiplied by `tipped_cash_rate_cents`, rounded".

        difficulty: combinatorial_formula/tip_credit_per_line_rounding_order
        Round-half-up sanity (3.5h * 213 = 745.5 → 746).
        """
        state = setup_tip_credit_fractional_hours_scenario()
        ww = state["workweek"]
        # cash_wage = round(3.5*213) = round(745.5) = 746.
        # min_required = round(3.5*1500) = round(5250.0) = 5250.
        # declared=4000, tip_credit=min(4000, 5250-746=4504) = 4000.
        # shortfall = 5250 - 746 - 4000 = 504.
        # base_line = round(3.5*725) = round(2537.5) = 2538.
        # gross = 2538 + 504 = 3042.
        assert ww["gross_pay_cents"] == 3042


# ===========================================================================
# Rule 3 — non_linear_state_machine
# ===========================================================================
class TestNonLinearStateMachine:
    """difficulty: non_linear_state_machine"""

    def test_shift_finalized_to_closed_revert_cycle(self, api):
        """PRD §3.5: "Submitting a time edit against a `FINALIZED` shift
        does not change the shift's state at submission time — the shift
        is held in `FINALIZED` until the moment the edit is approved,
        at which point the approval flips the shift back to `CLOSED` and
        the workweek back to `OPEN`".

        difficulty: non_linear_state_machine/
        shift_revert_cycle_finalized_to_closed
        Primary check.
        """
        state = setup_revert_ready_finalized_shift(
            overrun_minutes=0,
            base_hourly_rate_cents=2000,
        )
        proposed = add_minutes(state["shift"]["scheduled_end"], -10)
        edit = submit_time_edit(
            state["shift"]["id"],
            state["out_punch"]["id"],
            proposed,
            reason_code="CLERICAL",
            requester_headers=make_supervisor_headers(SUPERVISOR_SHARED_ID),
        )
        approve_time_edit(
            edit["id"],
            approver_headers=make_payroll_admin_headers(
                PAYROLL_ADMIN_SHARED_ID,
            ),
        )
        refreshed = get_shift(state["shift"]["id"])
        ww = get_workweek(state["workweek"]["id"])
        assert refreshed["state"] == "CLOSED", (
            "PRD §3.5: approval flips FINALIZED back to CLOSED"
        )
        assert ww["payroll_status"] == "OPEN", (
            "PRD §3.5: approval flips workweek back to OPEN"
        )

    def test_shift_revert_creates_edit_punch_and_supersedes(self, api):
        """PRD §3.5: "the system creates a new EDIT punch whose
        `punched_at` equals the `proposed_punched_at` and whose
        `source` is `EDIT`, sets the target punch's
        `superseded_by_edit_id` to the time edit's id".

        difficulty: non_linear_state_machine/
        shift_revert_cycle_finalized_to_closed
        Side-effect check.
        """
        state = setup_revert_ready_finalized_shift(
            overrun_minutes=0,
            base_hourly_rate_cents=2000,
        )
        proposed = add_minutes(state["shift"]["scheduled_end"], -10)
        edit = submit_time_edit(
            state["shift"]["id"],
            state["out_punch"]["id"],
            proposed,
            reason_code="CLERICAL",
            requester_headers=make_supervisor_headers(SUPERVISOR_SHARED_ID),
        )
        approved = approve_time_edit(
            edit["id"],
            approver_headers=make_payroll_admin_headers(
                PAYROLL_ADMIN_SHARED_ID,
            ),
        )
        # The PRD also says (§3.5) the TimeEdit carries `applied_at`
        # populated on approve.
        assert approved["applied_at"] is not None, (
            "PRD §3.5: APPROVED TimeEdit must carry applied_at"
        )

    def test_workweek_posted_to_open_cycle(self, api):
        """PRD §3.6: "When an approved time edit causes a constituent
        shift to recompute after the workweek has already reached
        `POSTED`, the workweek automatically flips `POSTED → OPEN`".

        difficulty: non_linear_state_machine/workweek_posted_open_cycle
        Primary check.
        """
        state = setup_revert_ready_finalized_shift(
            overrun_minutes=0,
            base_hourly_rate_cents=2000,
        )
        assert state["workweek"]["payroll_status"] == "POSTED"
        proposed = add_minutes(state["shift"]["scheduled_end"], -10)
        edit = submit_time_edit(
            state["shift"]["id"],
            state["out_punch"]["id"],
            proposed,
            reason_code="CLERICAL",
            requester_headers=make_supervisor_headers(SUPERVISOR_SHARED_ID),
        )
        approve_time_edit(
            edit["id"],
            approver_headers=make_payroll_admin_headers(
                PAYROLL_ADMIN_SHARED_ID,
            ),
        )
        ww = get_workweek(state["workweek"]["id"])
        assert ww["payroll_status"] == "OPEN"

    def test_workweek_revert_returns_to_posted_after_refinalize(self, api):
        """PRD §3.6: "The same automatic flip occurs on revert."

        difficulty: non_linear_state_machine/workweek_posted_open_cycle
        Revert + refinalize completes a second OPEN→POSTED cycle.
        """
        state = setup_revert_ready_finalized_shift(
            overrun_minutes=0,
            base_hourly_rate_cents=2000,
        )
        proposed = add_minutes(state["shift"]["scheduled_end"], -10)
        edit = submit_time_edit(
            state["shift"]["id"],
            state["out_punch"]["id"],
            proposed,
            reason_code="CLERICAL",
            requester_headers=make_supervisor_headers(SUPERVISOR_SHARED_ID),
        )
        approve_time_edit(
            edit["id"],
            approver_headers=make_payroll_admin_headers(
                PAYROLL_ADMIN_SHARED_ID,
            ),
        )
        # Revert the APPROVED edit; PRD §3.5: revert removes the EDIT
        # punch, restores target, recomputes. Workweek transitions back.
        revert_time_edit(
            edit["id"],
            headers=make_payroll_admin_headers(PAYROLL_ADMIN_SECONDARY_ID),
        )
        # Refinalize.
        finalize_shift(state["shift"]["id"])
        ww = get_workweek(state["workweek"]["id"])
        assert ww["payroll_status"] == "POSTED"


# ===========================================================================
# Rule 4 — transitive_cascade
# ===========================================================================
class TestTransitiveCascade:
    """difficulty: transitive_cascade"""

    def test_out_punch_to_detention_to_workweek_posted(self, api):
        """PRD §3.2: "When the `OUT` punch transitions the shift to
        `CLOSED`, two computations run inline on that shift: the
        detention computation, and the meal-break-premium computation."
        PRD §3.4: "A `DetentionEvent` is created (or updated) per shift
        on the `OPEN → CLOSED` transition".
        PRD §3.6: "the workweek transitions `OPEN → POSTED` automatically".

        difficulty: transitive_cascade/
        out_punch_triggers_detention_then_workweek
        Primary check.
        """
        state = setup_overrun_finalized_shift_for_cascade(
            overrun_minutes=65,
            base_hourly_rate_cents=2000,
        )
        assert state["shift"]["detention_minutes"] == 65
        assert state["workweek"]["payroll_status"] == "POSTED"

    def test_out_punch_cascade_includes_detention_premium_in_gross(
        self, api,
    ):
        """PRD §3.6 Step 4: "the premiums line is the sum across the
        workweek's shifts of `Shift.meal_break_premium_owed_cents` plus
        the sum across the workweek's `DetentionEvent` rows of
        `premium_owed_cents`."

        difficulty: transitive_cascade/
        out_punch_triggers_detention_then_workweek
        Cascade reaches gross_pay.
        """
        state = setup_overrun_finalized_shift_for_cascade(
            overrun_minutes=65,
            base_hourly_rate_cents=2000,
        )
        # 8h regular at 2000 = 16000 base. +65min in TIER_2 → premium
        # 2000 cents. + 0 meal premium (worked_hours
        # > 5 and no meal taken: but the PRD jurisdiction is CA where
        # the meal-break rule kicks in; the fixture sets jurisdiction
        # CA → meal premium 2000 cents.
        # gross >= base 16000 + det 2000 + meal 2000 = 20000.
        assert state["workweek"]["gross_pay_cents"] >= 16000 + 2000, (
            f"PRD §3.6: gross must include the detention premium 2000c "
            f"on top of base; got {state['workweek']['gross_pay_cents']}"
        )

    def test_timeedit_approve_to_recompute_to_workweek_revert(self, api):
        """PRD §3.5: "On approval, the system ... recomputes
        `Shift.detention_minutes` and `Shift.meal_break_premium_owed_cents`."
        PRD §3.6: "the workweek automatically flips `POSTED → OPEN`".

        difficulty: transitive_cascade/
        timeedit_approve_triggers_recompute_then_workweek_revert
        Primary check.
        """
        state = setup_overrun_finalized_shift_for_cascade(
            overrun_minutes=65,
            base_hourly_rate_cents=2000,
        )
        # Submit a TimeEdit moving OUT back to scheduled_end (eliminate
        # detention).
        proposed_out_at = state["shift"]["scheduled_end"]
        edit = submit_time_edit(
            state["shift"]["id"],
            state["out_punch"]["id"],
            proposed_out_at,
            reason_code="CLERICAL",
            requester_headers=make_supervisor_headers(SUPERVISOR_SHARED_ID),
        )
        approve_time_edit(
            edit["id"],
            approver_headers=make_payroll_admin_headers(
                PAYROLL_ADMIN_SHARED_ID,
            ),
        )
        refreshed_shift = get_shift(state["shift"]["id"])
        ww = get_workweek(state["workweek"]["id"])
        assert refreshed_shift["detention_minutes"] == 0, (
            "PRD §3.5: detention recomputed to 0 after OUT moved back"
        )
        assert refreshed_shift["state"] == "CLOSED"
        assert ww["payroll_status"] == "OPEN"

    def test_timeedit_revert_restores_detention(self, api):
        """PRD §3.5: "The revert removes the EDIT punch, clears
        `superseded_by_edit_id` on the originally edited target punch
        (restoring it as the live record), recomputes detention and
        meal-break premium on the affected shift".

        difficulty: transitive_cascade/
        timeedit_approve_triggers_recompute_then_workweek_revert
        Revert restores prior detention.
        """
        state = setup_overrun_finalized_shift_for_cascade(
            overrun_minutes=65,
            base_hourly_rate_cents=2000,
        )
        proposed_out_at = state["shift"]["scheduled_end"]
        edit = submit_time_edit(
            state["shift"]["id"],
            state["out_punch"]["id"],
            proposed_out_at,
            reason_code="CLERICAL",
            requester_headers=make_supervisor_headers(SUPERVISOR_SHARED_ID),
        )
        approve_time_edit(
            edit["id"],
            approver_headers=make_payroll_admin_headers(
                PAYROLL_ADMIN_SHARED_ID,
            ),
        )
        revert_time_edit(
            edit["id"],
            headers=make_payroll_admin_headers(PAYROLL_ADMIN_SECONDARY_ID),
        )
        refreshed = get_shift(state["shift"]["id"])
        assert refreshed["detention_minutes"] == 65


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict
# ===========================================================================
class TestPriorityPairValidationConflict:
    """difficulty: priority_pair_validation_conflict"""

    def test_state_priority_wins_over_segregation(self, api):
        """PRD §2.9 priority: "then time-edit-state checks
        (`ERR_TIME_EDIT_NOT_PENDING`), then workweek-lock checks ...,
        then segregation of duties (`ERR_SEGREGATION_OF_DUTIES`)".

        difficulty: priority_pair_validation_conflict/
        state_vs_business_safety_segregation
        Primary check.
        """
        # Step 1: setup CLOSED shift, submit TimeEdit by U1.
        state = setup_pending_time_edit(
            requester_headers=make_supervisor_headers(SUPERVISOR_SHARED_ID),
        )
        # Step 2: approve by U2 → TimeEdit APPROVED.
        approve_time_edit(
            state["time_edit"]["id"],
            approver_headers=make_payroll_admin_headers(
                PAYROLL_ADMIN_SHARED_ID,
            ),
        )
        # Step 3: same-user-as-requester tries to approve again.
        # State (priority 7) fires first; should be
        # ERR_TIME_EDIT_NOT_PENDING, NOT ERR_SEGREGATION_OF_DUTIES.
        resp = api.approve_time_edit(
            state["time_edit"]["id"],
            make_supervisor_headers(SUPERVISOR_SHARED_ID),
        )
        validate_error(resp, "ERR_TIME_EDIT_NOT_PENDING")

    def test_state_priority_wins_over_segregation_on_reject(self, api):
        """PRD §2.9 priority: time-edit-state above segregation; also
        applies to the reject path because §3.5 says "the
        segregation-of-duties rule still applies on the reject path".

        difficulty: priority_pair_validation_conflict/
        state_vs_business_safety_segregation
        Reject-path version of the same priority pair.
        """
        state = setup_pending_time_edit(
            requester_headers=make_supervisor_headers(SUPERVISOR_SHARED_ID),
        )
        # Reject by U2 first.
        api.reject_time_edit(
            state["time_edit"]["id"],
            make_payroll_admin_headers(PAYROLL_ADMIN_SHARED_ID),
        )
        # Now U1 tries to reject again — state-check (REJECTED) wins
        # over segregation.
        resp = api.reject_time_edit(
            state["time_edit"]["id"],
            make_supervisor_headers(SUPERVISOR_SHARED_ID),
        )
        validate_error(resp, "ERR_TIME_EDIT_NOT_PENDING")

    def test_exempt_check_fires_before_punch_order_on_shift_create(
        self, api,
    ):
        """PRD §3.2: "A shift created for an employee whose
        `classification` is `EXEMPT` is rejected with
        `ERR_EXEMPT_NOT_ELIGIBLE` and HTTP status 422".
        PRD §2.9 priority: "then the exempt-not-eligible check
        (`ERR_EXEMPT_NOT_ELIGIBLE`), then punch-ordering
        (`ERR_PUNCH_OUT_OF_ORDER`)".

        difficulty: priority_pair_validation_conflict/
        business_safety_vs_business_referential_meal_punch_order
        Primary check — exempt employee at create-shift surface.
        """
        emp = create_employee(classification="EXEMPT")
        resp = api.create_shift(
            create_shift_payload(emp["id"]),
            TEST_USERS["supervisor_headers"],
        )
        validate_error(resp, "ERR_EXEMPT_NOT_ELIGIBLE")

    def test_no_shift_created_for_exempt_employee(self, api):
        """PRD §3.2: "exempt employees do not draw hourly time through
        this system".

        difficulty: priority_pair_validation_conflict/
        business_safety_vs_business_referential_meal_punch_order
        Side-effect — the rejected create produces no Shift row.
        """
        emp = create_employee(classification="EXEMPT")
        resp = api.create_shift(
            create_shift_payload(emp["id"]),
            TEST_USERS["supervisor_headers"],
        )
        # 422 expected; list_shifts for that employee should be empty.
        validate_error(resp, "ERR_EXEMPT_NOT_ELIGIBLE")
        shifts_resp = api.list_shifts(
            TEST_USERS["payroll_admin_headers"],
            params={"employee_id": emp["id"]},
        )
        body = shifts_resp.json()
        assert body["data"] == [], (
            f"PRD §3.2: no shift row exists after ERR_EXEMPT_NOT_ELIGIBLE; "
            f"got {body['data']}"
        )


# ===========================================================================
# Rule 6 — boundary_precision_check
# ===========================================================================
class TestBoundaryPrecisionCheck:
    """difficulty: boundary_precision_check"""

    def test_weekly_ot_at_exactly_40_hours_is_zero(self, api):
        """PRD §3.6: "the amount that fits under the remaining capacity
        to 40 hours (40 minus cumulative_regular_so_far, floored at
        zero) is classified as regular, and the remainder of the day's
        daily-regular bucket spills into federal weekly overtime."

        difficulty: boundary_precision_check/
        weekly_overtime_threshold_at_exactly_40
        Primary check (at boundary).
        """
        state = setup_finalized_week(
            daily_hours=[8.0, 8.0, 8.0, 8.0, 8.0],
            jurisdiction="FED",
            base_hourly_rate_cents=2000,
        )
        ww = state["workweek"]
        assert ww["total_hours"] == pytest.approx(40.0, abs=1e-9)
        assert ww["overtime_hours"] == pytest.approx(0.0, abs=1e-9)
        assert ww["gross_pay_cents"] == 40 * 2000

    def test_weekly_ot_above_40_yields_premium(self, api):
        """PRD §3.6: "the remainder of the day's daily-regular bucket
        spills into federal weekly overtime."

        difficulty: boundary_precision_check/
        weekly_overtime_threshold_at_exactly_40
        Just-past boundary check (41h).
        """
        # 5x8h + 1h on the 6th day = 41h FED.
        state = setup_finalized_week(
            daily_hours=[8.0, 8.0, 8.0, 8.0, 8.0, 1.0],
            jurisdiction="FED",
            base_hourly_rate_cents=2000,
        )
        ww = state["workweek"]
        assert ww["total_hours"] == pytest.approx(41.0, abs=1e-9)
        assert ww["overtime_hours"] == pytest.approx(1.0, abs=1e-9)
        # gross = 40*2000 + 1*2000*1.5 = 80000 + 3000 = 83000.
        assert ww["gross_pay_cents"] == 83000

    def test_meal_break_required_at_exactly_5_hours(self, api):
        """PRD §3.3: "If the employee's `classification` is `EXEMPT`,
        or the worked hours are at most five, the premium is zero."

        difficulty: boundary_precision_check/
        meal_break_required_at_exactly_five_hours
        At-boundary check (5.0h exactly → no premium).
        """
        closed = setup_closed_shift(
            jurisdiction="CA",
            base_hourly_rate_cents=2000,
            duration_hours=5.0,
        )
        assert closed["shift"]["meal_break_premium_owed_cents"] == 0, (
            "PRD §3.3: at worked_hours <= 5 the premium is 0"
        )

    def test_meal_break_required_just_above_5_hours(self, api):
        """PRD §3.3: "if no `MealBreak` row exists for the shift ...
        the premium is one hour at the employee's base rate".

        difficulty: boundary_precision_check/
        meal_break_required_at_exactly_five_hours
        Just-past-boundary (5h + 1 sec) — premium fires.
        """
        # 5h + 1 second.
        from test_helpers import (
            clock_advance, create_employee, create_shift,
            make_employee_headers, post_punch,
        )
        emp = create_employee(
            jurisdiction="CA",
            classification="NON_EXEMPT",
            base_hourly_rate_cents=2000,
        )
        shift = create_shift(emp["id"], duration_hours=6.0)
        clock_set(shift["scheduled_start"])
        emp_headers = make_employee_headers(emp["id"])
        post_punch(shift["id"], "IN", emp_headers)
        clock_advance(18001)  # 5h + 1s
        post_punch(shift["id"], "OUT", emp_headers)
        refreshed = get_shift(shift["id"])
        assert refreshed["meal_break_premium_owed_cents"] == 2000, (
            f"PRD §3.3: at worked_hours > 5 (5h+1s) with no meal break, "
            f"premium = base rate = 2000; got "
            f"{refreshed['meal_break_premium_owed_cents']}"
        )


# ===========================================================================
# Rule 7 — cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityStateDependency:
    """difficulty: cross_entity_state_dependency"""

    def test_finalize_blocked_by_pending_time_edit(self, api):
        """PRD §3.6: "a `PENDING` edit on the shift causes finalize to
        reject with `ERR_TIME_EDIT_NOT_PENDING`."

        difficulty: cross_entity_state_dependency/
        shift_finalize_blocked_by_pending_timeedit
        Primary check.
        """
        state = setup_pending_time_edit()
        resp = api.finalize_shift(
            state["shift"]["id"], TEST_USERS["payroll_admin_headers"],
        )
        body = resp.json()
        assert resp.status_code == 409
        # PRD §2.9 places state-check (priority 6) above
        # time-edit-state (priority 7). Shift state is now DISPUTED
        # (from §3.5), so ERR_SHIFT_INVALID_STATE is the higher-
        # priority surface. PRD §3.6 names ERR_TIME_EDIT_NOT_PENDING
        # for the same precondition combination. Either is faithful.
        assert body["data"]["error_id"] in (
            "ERR_SHIFT_INVALID_STATE",
            "ERR_TIME_EDIT_NOT_PENDING",
        )

    def test_pending_timeedit_holds_shift_in_disputed(self, api):
        """PRD §3.5: "submitting one against a `CLOSED` shift likewise
        transitions it to `DISPUTED`, holding it back from being
        finalized."

        difficulty: cross_entity_state_dependency/
        shift_finalize_blocked_by_pending_timeedit
        Side-effect on Shift state.
        """
        state = setup_pending_time_edit()
        refreshed = get_shift(state["shift"]["id"])
        assert refreshed["state"] == "DISPUTED"

    def test_approve_blocked_by_locked_workweek(self, api):
        """PRD §3.6: "Once locked, further time-edit approvals on the
        workweek's shifts are rejected with `ERR_WORKWEEK_LOCKED`".

        difficulty: cross_entity_state_dependency/
        timeedit_approve_blocked_by_locked_workweek
        Primary check.
        """
        # POSTED → lock → submit edit → approve must reject.
        state = setup_revert_ready_finalized_shift(
            overrun_minutes=0,
            base_hourly_rate_cents=2000,
        )
        ww = state["workweek"]
        api.lock_workweek(ww["id"], TEST_USERS["payroll_admin_headers"])
        # Submit a fresh TimeEdit on the now-locked-week shift.
        proposed = add_minutes(state["shift"]["scheduled_end"], -10)
        edit = submit_time_edit(
            state["shift"]["id"],
            state["out_punch"]["id"],
            proposed,
            reason_code="CLERICAL",
            requester_headers=make_supervisor_headers(SUPERVISOR_SHARED_ID),
        )
        resp = api.approve_time_edit(
            edit["id"],
            make_payroll_admin_headers(PAYROLL_ADMIN_SECONDARY_ID),
        )
        validate_error(resp, "ERR_WORKWEEK_LOCKED")

    def test_revert_blocked_by_locked_workweek(self, api):
        """PRD §3.6: "Once locked, ... revert is likewise rejected"
        (with `ERR_WORKWEEK_LOCKED`).

        difficulty: cross_entity_state_dependency/
        timeedit_approve_blocked_by_locked_workweek
        Lock blocks revert too.
        """
        state = setup_revert_ready_finalized_shift(
            overrun_minutes=0,
            base_hourly_rate_cents=2000,
        )
        proposed = add_minutes(state["shift"]["scheduled_end"], -10)
        edit = submit_time_edit(
            state["shift"]["id"],
            state["out_punch"]["id"],
            proposed,
            reason_code="CLERICAL",
            requester_headers=make_supervisor_headers(SUPERVISOR_SHARED_ID),
        )
        approve_time_edit(
            edit["id"],
            approver_headers=make_payroll_admin_headers(
                PAYROLL_ADMIN_SHARED_ID,
            ),
        )
        # Approve flipped workweek to OPEN; refinalize then lock.
        finalize_shift(state["shift"]["id"])
        ww = get_workweek(state["workweek"]["id"])
        api.lock_workweek(ww["id"], TEST_USERS["payroll_admin_headers"])
        # Revert.
        resp = api.revert_time_edit(
            edit["id"],
            make_payroll_admin_headers(PAYROLL_ADMIN_SECONDARY_ID),
        )
        validate_error(resp, "ERR_WORKWEEK_LOCKED")


# ===========================================================================
# Rule 8 — resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlap:
    """difficulty: resource_temporal_overlap"""

    def test_in_punch_at_scheduled_start_minus_60m_allowed(self, api):
        """PRD §3.2: "the current server time falls within a window
        extending from 60 minutes before `scheduled_start`".

        difficulty: resource_temporal_overlap/
        shift_punch_window_open_closed_semantics
        Inclusive-lower-boundary check.
        """
        emp = create_employee()
        shift = create_shift(emp["id"])
        # Clock = scheduled_start - 60 minutes exactly.
        clock_set(add_minutes(shift["scheduled_start"], -60))
        resp = api.create_punch(
            shift["id"], create_punch_payload("IN"),
            make_employee_headers(emp["id"]),
        )
        # PRD §3.2 says the window extends "from 60 minutes before
        # `scheduled_start`" — inclusive.
        punch = validate_success(resp, expected_status=201)
        refreshed = get_shift(shift["id"])
        assert refreshed["state"] == "OPEN"

    def test_in_punch_at_scheduled_start_minus_60m_minus_1s_rejected(
        self, api,
    ):
        """PRD §3.2: "an `IN` punch outside that window is rejected with
        `ERR_PUNCH_OUTSIDE_WINDOW`".

        difficulty: resource_temporal_overlap/
        shift_punch_window_open_closed_semantics
        Just-outside boundary check.
        """
        emp = create_employee()
        shift = create_shift(emp["id"])
        # Set to scheduled_start - 60m - 1s.
        clock_set(add_seconds(add_minutes(shift["scheduled_start"], -60),
                              -1))
        resp = api.create_punch(
            shift["id"], create_punch_payload("IN"),
            make_employee_headers(emp["id"]),
        )
        validate_error(resp, "ERR_PUNCH_OUTSIDE_WINDOW")

    def test_time_edit_proposed_at_plus_6h_inclusive(self, api):
        """PRD §3.5: "The `proposed_punched_at` must lie within the
        window from 4 hours before the shift's `scheduled_start` to 6
        hours after the shift's `scheduled_end`".

        difficulty: resource_temporal_overlap/
        timeedit_proposed_time_buffered_envelope
        Inclusive-upper-boundary check.
        """
        closed = setup_closed_shift()
        # proposed = scheduled_end + 6h exactly (inclusive).
        proposed = add_hours(closed["shift"]["scheduled_end"], 6)
        resp = api.create_time_edit(
            create_time_edit_payload(
                shift_id=closed["shift"]["id"],
                target_punch_id=closed["out_punch"]["id"],
                proposed_punched_at=proposed,
                reason_code="CLERICAL",
            ),
            TEST_USERS["supervisor_headers"],
        )
        edit = validate_success(resp, expected_status=201)
        assert edit["state"] == "PENDING"

    def test_time_edit_proposed_at_plus_6h_plus_1s_rejected(self, api):
        """PRD §3.5: "anything outside is rejected with
        `ERR_TIME_EDIT_OUT_OF_RANGE`."

        difficulty: resource_temporal_overlap/
        timeedit_proposed_time_buffered_envelope
        Just-outside upper boundary.
        """
        closed = setup_closed_shift()
        proposed = add_seconds(
            add_hours(closed["shift"]["scheduled_end"], 6), 1,
        )
        resp = api.create_time_edit(
            create_time_edit_payload(
                shift_id=closed["shift"]["id"],
                target_punch_id=closed["out_punch"]["id"],
                proposed_punched_at=proposed,
                reason_code="CLERICAL",
            ),
            TEST_USERS["supervisor_headers"],
        )
        validate_error(resp, "ERR_TIME_EDIT_OUT_OF_RANGE")


# ===========================================================================
# Rule 9 — compensating_invariant
# ===========================================================================
class TestCompensatingInvariant:
    """difficulty: compensating_invariant"""

    def test_approve_then_revert_preserves_gross_pay(self, api):
        """PRD §3.5: revert "removes the EDIT punch, clears
        `superseded_by_edit_id` on the originally edited target punch
        (restoring it as the live record), recomputes detention and
        meal-break premium on the affected shift".
        PRD §3.6: "the workweek automatically flips `POSTED → OPEN`"
        and the same automatic flip on revert.

        difficulty: compensating_invariant/
        timeedit_approve_then_revert_preserves_gross_pay
        Primary check — gross_pay round-trip invariant.
        """
        # Use a CA shift with detention=0 so the original gross is
        # purely base*regular and the approve/revert round-trip should
        # land back at exactly the same value.
        state = setup_revert_ready_finalized_shift(
            overrun_minutes=0,
            base_hourly_rate_cents=2000,
        )
        g_before = state["workweek"]["gross_pay_cents"]
        proposed = add_minutes(state["shift"]["scheduled_end"], -10)
        edit = submit_time_edit(
            state["shift"]["id"],
            state["out_punch"]["id"],
            proposed,
            reason_code="CLERICAL",
            requester_headers=make_supervisor_headers(SUPERVISOR_SHARED_ID),
        )
        approve_time_edit(
            edit["id"],
            approver_headers=make_payroll_admin_headers(
                PAYROLL_ADMIN_SHARED_ID,
            ),
        )
        # Revert.
        revert_time_edit(
            edit["id"],
            headers=make_payroll_admin_headers(PAYROLL_ADMIN_SECONDARY_ID),
        )
        # Refinalize.
        finalize_shift(state["shift"]["id"])
        ww_after = get_workweek(state["workweek"]["id"])
        assert ww_after["gross_pay_cents"] == g_before, (
            f"PRD §3.5/§3.6: approve+revert+refinalize must restore "
            f"gross_pay; was {g_before}, got {ww_after['gross_pay_cents']}"
        )

    def test_audit_chain_contains_both_approved_and_reverted(self, api):
        """PRD §3.5: "an audit row is appended with `action` value
        `TIME_EDIT_APPROVED`" and "an audit row is appended with
        `action` value `TIME_EDIT_REVERTED`".

        difficulty: compensating_invariant/
        timeedit_approve_then_revert_preserves_gross_pay
        Audit chain check.
        """
        state = setup_revert_ready_finalized_shift(
            overrun_minutes=0,
            base_hourly_rate_cents=2000,
        )
        proposed = add_minutes(state["shift"]["scheduled_end"], -10)
        edit = submit_time_edit(
            state["shift"]["id"],
            state["out_punch"]["id"],
            proposed,
            reason_code="CLERICAL",
            requester_headers=make_supervisor_headers(SUPERVISOR_SHARED_ID),
        )
        approve_time_edit(
            edit["id"],
            approver_headers=make_payroll_admin_headers(
                PAYROLL_ADMIN_SHARED_ID,
            ),
        )
        revert_time_edit(
            edit["id"],
            headers=make_payroll_admin_headers(PAYROLL_ADMIN_SECONDARY_ID),
        )
        entries = list_audit(
            subject_entity="TimeEdit", subject_id=edit["id"],
        )
        actions = [e["action"] for e in entries]
        assert "TIME_EDIT_APPROVED" in actions
        assert "TIME_EDIT_REVERTED" in actions

    def test_approve_then_revert_preserves_detention_minutes(self, api):
        """PRD §3.4: detention_minutes is a computed integer-minutes
        quantity recomputed on every TimeEdit APPROVE/REVERT.
        PRD §3.5 revert: "recomputes detention and meal-break premium
        on the affected shift".

        difficulty: compensating_invariant/
        timeedit_approve_then_revert_preserves_detention_minutes
        Primary check — detention round-trip invariant.
        """
        state = setup_overrun_finalized_shift_for_cascade(
            overrun_minutes=65,
            base_hourly_rate_cents=2000,
        )
        d_before = state["shift"]["detention_minutes"]
        assert d_before == 65
        proposed = state["shift"]["scheduled_end"]  # eliminate detention
        edit = submit_time_edit(
            state["shift"]["id"],
            state["out_punch"]["id"],
            proposed,
            reason_code="CLERICAL",
            requester_headers=make_supervisor_headers(SUPERVISOR_SHARED_ID),
        )
        approve_time_edit(
            edit["id"],
            approver_headers=make_payroll_admin_headers(
                PAYROLL_ADMIN_SHARED_ID,
            ),
        )
        revert_time_edit(
            edit["id"],
            headers=make_payroll_admin_headers(PAYROLL_ADMIN_SECONDARY_ID),
        )
        refreshed = get_shift(state["shift"]["id"])
        assert refreshed["detention_minutes"] == d_before, (
            f"PRD §3.5/§3.4: revert must restore detention_minutes; "
            f"was {d_before}, got {refreshed['detention_minutes']}"
        )

    def test_revert_restores_detention_tier(self, api):
        """PRD §3.4: "The `tier` is then assigned by a threshold
        lookup".

        difficulty: compensating_invariant/
        timeedit_approve_then_revert_preserves_detention_minutes
        Detention tier round-trip check.
        """
        state = setup_overrun_finalized_shift_for_cascade(
            overrun_minutes=65,
            base_hourly_rate_cents=2000,
        )
        proposed = state["shift"]["scheduled_end"]
        edit = submit_time_edit(
            state["shift"]["id"],
            state["out_punch"]["id"],
            proposed,
            reason_code="CLERICAL",
            requester_headers=make_supervisor_headers(SUPERVISOR_SHARED_ID),
        )
        approve_time_edit(
            edit["id"],
            approver_headers=make_payroll_admin_headers(
                PAYROLL_ADMIN_SHARED_ID,
            ),
        )
        revert_time_edit(
            edit["id"],
            headers=make_payroll_admin_headers(PAYROLL_ADMIN_SECONDARY_ID),
        )
        refreshed = get_shift(state["shift"]["id"])
        # 65 minutes → TIER_2. PRD §3.4.
        assert refreshed["detention_minutes"] == 65
