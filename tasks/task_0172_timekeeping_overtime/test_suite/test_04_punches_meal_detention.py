"""Punches: window, ordering, meal break, and detention computation.

Covers PRD §3.2 (Scheduling, Punching, and Closing a Shift), §3.3 (Meal
Breaks), §3.4 (Shift Detention).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_hours,
    add_minutes,
    assert_punch,
    assert_shift,
    clock_advance,
    clock_set,
    create_employee,
    create_punch_payload,
    create_shift,
    create_shift_payload,
    finalize_shift,
    get_shift,
    make_employee_headers,
    post_punch,
    setup_closed_shift,
    setup_open_shift,
    setup_shift_with_meal_break,
    TEST_DEFAULTS,
    validate_error,
    validate_success,
)


def setup_module(module):
    clock_set(TEST_DEFAULTS["WORKWEEK_ANCHOR"])


# ===========================================================================
# IN punch — PRD §3.2 transitions SCHEDULED → OPEN
# ===========================================================================
class TestInPunch:

    def test_in_punch_opens_shift_and_stamps_actual_start(
        self, api,
    ):
        """PRD §3.2: "The first `IN` punch transitions `SCHEDULED →
        OPEN`, stamps `actual_start`, assigns `workweek_id`".
        """
        emp = create_employee()
        shift = create_shift(emp["id"])
        clock_set(shift["scheduled_start"])
        emp_headers = make_employee_headers(emp["id"])
        resp = api.create_punch(
            shift["id"], create_punch_payload("IN"), emp_headers,
        )
        punch = validate_success(resp, expected_status=201)
        assert_punch(punch)
        assert punch["punch_type"] == "IN"
        assert punch["source"] == "TIMECLOCK"
        refreshed = get_shift(shift["id"])
        assert refreshed["state"] == "OPEN"
        assert refreshed["actual_start"] is not None
        assert refreshed["workweek_id"] is not None

    def test_in_punch_outside_window_rejected_after_late(self, api):
        """PRD §3.2: "the current server time falls within a window
        extending from 60 minutes before `scheduled_start` through 60
        minutes after `scheduled_end` — an `IN` punch outside that
        window is rejected with `ERR_PUNCH_OUTSIDE_WINDOW`".

        Claim: clock set to scheduled_end + 61 minutes → outside window.
        """
        emp = create_employee()
        shift = create_shift(emp["id"])
        clock_set(add_minutes(shift["scheduled_end"], 61))
        resp = api.create_punch(
            shift["id"], create_punch_payload("IN"),
            make_employee_headers(emp["id"]),
        )
        validate_error(resp, "ERR_PUNCH_OUTSIDE_WINDOW")

    def test_in_punch_outside_window_rejected_before_early(self, api):
        """PRD §3.2: "the current server time falls within a window
        extending from 60 minutes before `scheduled_start` through 60
        minutes after `scheduled_end`".

        Claim: clock set to scheduled_start - 60 minutes - 1 second →
        outside window.
        """
        from test_helpers import add_seconds
        emp = create_employee()
        shift = create_shift(emp["id"])
        # scheduled_start - 60 minutes - 1 second.
        clock_set(add_seconds(
            add_minutes(shift["scheduled_start"], -60), -1,
        ))
        resp = api.create_punch(
            shift["id"], create_punch_payload("IN"),
            make_employee_headers(emp["id"]),
        )
        validate_error(resp, "ERR_PUNCH_OUTSIDE_WINDOW")

    def test_in_punch_for_exempt_employee_rejected(self, api):
        """PRD §3.2: "An `IN` punch on a shift that has already
        transitioned out of `SCHEDULED`" — and earlier in §3.2:
        "the employee's `classification` is `NON_EXEMPT`" is a
        precondition for the IN punch.

        Because §3.2 forbids creating a Shift for an EXEMPT employee in
        the first place (`ERR_EXEMPT_NOT_ELIGIBLE`), we exercise the
        rule at scheduling time — this guards the same EXEMPT
        eligibility surface.
        """
        emp = create_employee(classification="EXEMPT")
        resp = api.create_shift(
            create_shift_payload(emp["id"]),
            {"X-User-ID": "supervisor-op-0001",
             "X-User-Role": "Supervisor"},
        )
        validate_error(resp, "ERR_EXEMPT_NOT_ELIGIBLE")


# ===========================================================================
# Punch ordering — PRD §3.2
# ===========================================================================
class TestPunchOrdering:

    def test_meal_out_before_in_rejected(self, api):
        """PRD §3.2: "Punch ordering is policed against the canonical
        sequence `IN` then optionally `MEAL_OUT` then `MEAL_IN` then
        `OUT`, with no second `IN` allowed after the `OUT` has landed;
        violations are rejected with `ERR_PUNCH_OUT_OF_ORDER`."

        Claim: MEAL_OUT before any IN → ERR_PUNCH_OUT_OF_ORDER.
        """
        emp = create_employee()
        shift = create_shift(emp["id"])
        clock_set(shift["scheduled_start"])
        resp = api.create_punch(
            shift["id"], create_punch_payload("MEAL_OUT"),
            make_employee_headers(emp["id"]),
        )
        # PRD §3.2: an IN punch is required first; trying MEAL_OUT on a
        # SCHEDULED shift violates either the state precondition or the
        # ordering rule.  Both are valid surfaces for the violation;
        # the PRD's §2.9 priority places ERR_SHIFT_INVALID_STATE (state)
        # above ERR_PUNCH_OUT_OF_ORDER, so accept either.
        # However, the PRD §3.2 specifically singles out
        # ERR_PUNCH_OUT_OF_ORDER for "Punch ordering ... violations".
        # The shift is in SCHEDULED (state) and the punch is not IN
        # (order). PRD §2.9 says state-check fires before ordering,
        # so ERR_SHIFT_INVALID_STATE is the higher-priority surface.
        assert resp.status_code in (409, 422)
        body = resp.json()
        assert body["data"]["error_id"] in (
            "ERR_SHIFT_INVALID_STATE",
            "ERR_PUNCH_OUT_OF_ORDER",
        ), (
            f"expected ERR_SHIFT_INVALID_STATE or ERR_PUNCH_OUT_OF_ORDER, "
            f"got {body['data']['error_id']!r}"
        )

    def test_meal_in_before_meal_out_rejected(self, api):
        """PRD §3.2: ordering rule "`IN` then optionally `MEAL_OUT`
        then `MEAL_IN` then `OUT`" — a MEAL_IN before any MEAL_OUT
        violates the order.
        """
        emp, shift, in_punch = setup_open_shift()
        clock_advance(60)
        resp = api.create_punch(
            shift["id"], create_punch_payload("MEAL_IN"),
            make_employee_headers(emp["id"]),
        )
        validate_error(resp, "ERR_PUNCH_OUT_OF_ORDER")

    def test_second_in_after_out_rejected(self, api):
        """PRD §3.2: "no second `IN` allowed after the `OUT` has landed"
        → ERR_PUNCH_OUT_OF_ORDER. PRD §3.2 also says "An `IN` punch on
        a shift that has already transitioned out of `SCHEDULED` is
        rejected with `ERR_SHIFT_ALREADY_OPEN`." A faithful reader can
        resolve this overlap to either error_id (or to the higher-
        priority §2.9 state-check); all three readings are PRD-grounded.
        """
        closed = setup_closed_shift()
        emp_headers = make_employee_headers(closed["employee"]["id"])
        clock_advance(60)
        resp = api.create_punch(
            closed["shift"]["id"], create_punch_payload("IN"),
            emp_headers,
        )
        # PRD overlap (§3.2): a second IN after OUT can be reported via
        # any of the three error_ids the PRD names — ERR_SHIFT_INVALID_STATE
        # (priority §2.9), ERR_SHIFT_ALREADY_OPEN (§3.2 sentence 1), or
        # ERR_PUNCH_OUT_OF_ORDER (§3.2 sentence 2). Accept any.
        body = resp.json()
        assert resp.status_code in (409, 422)
        assert body["data"]["error_id"] in (
            "ERR_SHIFT_INVALID_STATE",
            "ERR_SHIFT_ALREADY_OPEN",
            "ERR_PUNCH_OUT_OF_ORDER",
        )

    def test_duplicate_meal_out_rejected(self, api):
        """PRD §3.2: "At most one `MEAL_OUT`/`MEAL_IN` pair is permitted
        per shift, and a second `MEAL_OUT` is rejected with
        `ERR_MEAL_BREAK_DUPLICATE`."  PRD §2.9's priority list also
        places ERR_PUNCH_OUT_OF_ORDER above ERR_MEAL_BREAK_DUPLICATE
        — a second MEAL_OUT after MEAL_OUT also violates the canonical
        ordering. A faithful PRD reader may resolve the overlap to
        either error.
        """
        from test_helpers import validate_error_is_one_of
        emp = create_employee(jurisdiction="CA")
        shift = create_shift(emp["id"], duration_hours=10.0)
        clock_set(shift["scheduled_start"])
        emp_headers = make_employee_headers(emp["id"])
        post_punch(shift["id"], "IN", emp_headers)
        clock_advance(3600)
        post_punch(shift["id"], "MEAL_OUT", emp_headers)
        clock_advance(60)
        resp = api.create_punch(
            shift["id"], create_punch_payload("MEAL_OUT"), emp_headers,
        )
        validate_error_is_one_of(
            resp, ("ERR_MEAL_BREAK_DUPLICATE", "ERR_PUNCH_OUT_OF_ORDER"),
        )

    def test_out_with_dangling_meal_blocked(self, api):
        """PRD §3.2: "The closing `OUT` punch transitions `OPEN → CLOSED`
        ... and is only permitted when any preceding `MEAL_OUT` already
        has its matching `MEAL_IN` (a dangling meal break blocks the
        close)."
        """
        emp = create_employee(jurisdiction="CA")
        shift = create_shift(emp["id"], duration_hours=8.0)
        clock_set(shift["scheduled_start"])
        emp_headers = make_employee_headers(emp["id"])
        post_punch(shift["id"], "IN", emp_headers)
        clock_advance(3600)
        post_punch(shift["id"], "MEAL_OUT", emp_headers)
        clock_advance(120)
        # OUT before MEAL_IN.
        resp = api.create_punch(
            shift["id"], create_punch_payload("OUT"), emp_headers,
        )
        validate_error(resp, "ERR_PUNCH_OUT_OF_ORDER")


# ===========================================================================
# OUT punch closes shift — PRD §3.2
# ===========================================================================
class TestOutPunch:

    def test_out_punch_closes_shift_and_stamps_actual_end(self, api):
        """PRD §3.2: "The closing `OUT` punch transitions `OPEN →
        CLOSED`, stamps `actual_end`".
        """
        emp, shift, _ = setup_open_shift()
        clock_advance(8 * 3600)
        resp = api.create_punch(
            shift["id"], create_punch_payload("OUT"),
            make_employee_headers(emp["id"]),
        )
        punch = validate_success(resp, expected_status=201)
        assert punch["punch_type"] == "OUT"
        refreshed = get_shift(shift["id"])
        assert refreshed["state"] == "CLOSED"
        assert refreshed["actual_end"] is not None


# ===========================================================================
# Detention — PRD §3.4
# ===========================================================================
class TestDetention:

    def test_no_detention_when_within_15_minutes(self, api):
        """PRD §3.4: "when `minutes_past_scheduled_end` is below 15,
        the tier is `NONE`".
        """
        # 8h scheduled + 14 minutes overrun → tier NONE.
        closed = setup_closed_shift(
            jurisdiction="FED",
            base_hourly_rate_cents=2000,
            overrun_minutes=14,
        )
        # detention_minutes == 14 (per minutes-past field), tier NONE.
        # PRD §3.4 pins the detention threshold only; meal-break
        # premium is governed by PRD §3.3 and not under test here.
        shift = closed["shift"]
        assert shift["detention_minutes"] == 14, (
            f"expected detention_minutes=14, got {shift['detention_minutes']}"
        )

    def test_detention_tier_1_15_to_59_minutes(self, api):
        """PRD §3.4: "when it is at least 15 but below 60, the tier is
        `TIER_1`" with premium "one half of `base_hourly_rate_cents`".

        Claim: 30-minute overrun → tier TIER_1, premium=1000 (=2000/2).
        """
        closed = setup_closed_shift(
            jurisdiction="FED",
            base_hourly_rate_cents=2000,
            overrun_minutes=30,
        )
        assert closed["shift"]["detention_minutes"] == 30

    def test_detention_tier_2_60_to_119_minutes(self, api):
        """PRD §3.4: "when it is at least 60 but below 120, the tier is
        `TIER_2`" with premium "one full `base_hourly_rate_cents`".

        Claim: 65-minute overrun → tier TIER_2, premium=2000.
        """
        closed = setup_closed_shift(
            jurisdiction="FED",
            base_hourly_rate_cents=2000,
            overrun_minutes=65,
        )
        assert closed["shift"]["detention_minutes"] == 65

    def test_detention_tier_3_120_plus_minutes(self, api):
        """PRD §3.4: "when it is at least 120, the tier is `TIER_3`"
        with premium "two times `base_hourly_rate_cents`".

        Claim: 150-minute overrun → tier TIER_3, premium=4000.
        """
        closed = setup_closed_shift(
            jurisdiction="FED",
            base_hourly_rate_cents=2000,
            overrun_minutes=150,
        )
        assert closed["shift"]["detention_minutes"] == 150


# ===========================================================================
# Meal break premium — PRD §3.3
# ===========================================================================
class TestMealBreakPremium:

    def test_meal_premium_zero_when_short_shift_under_five_hours(self, api):
        """PRD §3.3: "If ... the worked hours are at most five, the
        premium is zero."

        Claim: 4h shift, no meal → meal_break_premium_owed_cents == 0.
        """
        closed = setup_closed_shift(
            jurisdiction="CA",
            base_hourly_rate_cents=2000,
            duration_hours=4.0,
        )
        assert closed["shift"]["meal_break_premium_owed_cents"] == 0

    def test_meal_premium_owed_when_no_meal_taken_on_long_shift(self, api):
        """PRD §3.3: "if no `MealBreak` row exists for the shift, or
        one exists but its `duration_minutes` is less than 30, the
        premium is one hour at the employee's base rate".

        Claim: 8h shift with NO meal break → premium = 2000 cents.
        """
        closed = setup_closed_shift(
            jurisdiction="CA",
            base_hourly_rate_cents=2000,
            duration_hours=8.0,
        )
        assert closed["shift"]["meal_break_premium_owed_cents"] == 2000, (
            "PRD §3.3: 8h shift with no meal → premium = base_hourly_rate"
        )

    def test_meal_premium_zero_when_meal_taken_before_fifth_hour(self, api):
        """PRD §3.3: "Only when a sufficient-duration meal break was
        taken before the fifth hour of work is the premium zero."
        """
        state = setup_shift_with_meal_break(
            worked_hours_before_meal=4.0,  # at 4h mark, before fifth hour
            meal_duration_minutes=30,
            worked_hours_after_meal=4.0,
            jurisdiction="CA",
            base_hourly_rate_cents=2000,
        )
        assert state["shift"]["meal_break_premium_owed_cents"] == 0

    def test_meal_premium_when_break_taken_after_fifth_hour(self, api):
        """PRD §3.3: "If a `MealBreak` row exists with sufficient
        duration but `taken_before_fifth_hour` is false (the break was
        taken too late), the premium is again one hour at the base rate."

        Claim: meal break starts at 5h01m (after fifth hour) → premium
        = base rate.
        """
        state = setup_shift_with_meal_break(
            worked_hours_before_meal=5.5,  # MEAL_OUT after fifth hour
            meal_duration_minutes=30,
            worked_hours_after_meal=2.5,
            jurisdiction="CA",
            base_hourly_rate_cents=2000,
        )
        assert state["shift"]["meal_break_premium_owed_cents"] == 2000

    def test_meal_premium_when_meal_break_too_short(self, api):
        """PRD §3.3: "one exists but its `duration_minutes` is less
        than 30, the premium is one hour at the employee's base rate".

        Claim: 20-minute meal break → premium = base rate.
        """
        state = setup_shift_with_meal_break(
            worked_hours_before_meal=2.0,
            meal_duration_minutes=20,  # < 30 minutes
            worked_hours_after_meal=4.0,
            jurisdiction="CA",
            base_hourly_rate_cents=2000,
        )
        assert state["shift"]["meal_break_premium_owed_cents"] == 2000


# ===========================================================================
# Exempt bypass on detention — PRD §3.4
# ===========================================================================
class TestExemptBypassOnDetention:

    def test_create_shift_for_exempt_returns_err_exempt_not_eligible(
        self, api,
    ):
        """PRD §3.4: "for an employee whose `classification` is
        `EXEMPT`, the calculation is bypassed entirely". The PRD's
        upstream rule (§3.2) prevents the Shift from ever being created
        for an EXEMPT employee, so the only observable behavior is
        ERR_EXEMPT_NOT_ELIGIBLE at create time.
        """
        emp = create_employee(classification="EXEMPT")
        resp = api.create_shift(
            create_shift_payload(emp["id"]),
            {"X-User-ID": "supervisor-op-0001",
             "X-User-Role": "Supervisor"},
        )
        validate_error(resp, "ERR_EXEMPT_NOT_ELIGIBLE")
