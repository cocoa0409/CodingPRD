"""Premium optimization: strategy selection, OCC supersede, grace/miss lapse
cascade (PRD §3.6, §3.7)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_finance_headers, make_compliance_headers,
    setup_case_acquired, create_schedule, list_payments, set_clock,
)

CM = TEST_USERS["case_manager_headers"]
PM = TEST_USERS["portfolio_manager_headers"]
FO_1 = make_finance_headers("fo_1")


class TestStrategySelection:
    def test_minimum_funding_fixed_point_month_ordered_projection(self, api):
        """PRD §3.7: "**MINIMUM_FUNDING.** The monthly funding m is the smallest
        level amount that keeps the policy's cash value non-negative through month
        k, found by projecting the cash value month by month in order from month 1
        through month k: each month's cost of insurance is the larger of zero and
        face minus the prior month's cash value, multiplied by a monthly rate of
        0.006, rounded half-up; the month's ending cash value is the prior cash
        value grown at a monthly crediting rate of 0.0033333333333333335 and
        rounded half-up, plus m, minus the month's cost of insurance. The solving m
        is found by bisection over the interval from 0 to four times the billed
        monthly premium, using exactly 40 iterations, then rounded half-up."
        PRD §3.7: "the remaining expectancy k is the case's `blended_le_months`
        minus the whole 30-day months elapsed between the latest eligible
        life-expectancy report's `delivered_at` and the current clock (days divided
        by 30, floored), floored at 1"
        PRD §3.7: "The chosen `reduced_face_cents` is recorded on the schedule;
        under the other strategies it stays unset."
        PRD §3.7: "the first `due_date` is the schedule's creation clock plus 30
        days, and each subsequent row is 30 days after the previous"

        Design: Difficulty/combinatorial_formula/minimum_funding_fixed_point_month_ordered_projection
        """
        ctx = setup_case_acquired(
            start_clock="2026-07-20T00:00:00Z",
            fund_clock="2026-08-15T00:00:00Z",
            release_clock="2026-09-05T00:00:00Z",
            policy_overrides={"policy_type": "UNIVERSAL_LIFE", "cash_value_cents": 2000000},
            insured_overrides={"gender": "F", "smoker_status": "UNKNOWN"},
        )
        case = ctx["case"]
        assert case["blended_le_months"] == 86
        # LE delivered 2026-07-20; schedule created at 2026-09-05: months_elapsed
        # floor(47/30) = 1 -> k = 85.
        sched = create_schedule(case["id"])
        assert sched["strategy"] == "MINIMUM_FUNDING"
        assert sched["optimized_monthly_premium_cents"] == 25812
        assert sched["planned_months"] == 85
        assert sched["expected_net_value_cents"] == 2818943
        assert sched["reduced_face_cents"] is None

        rows = list_payments(sched["id"])
        assert len(rows) == 85
        assert all(r["amount_cents"] == 25812 for r in rows)
        assert rows[0]["due_date"] == "2026-10-05T00:00:00Z"

    def test_minimum_funding_strategy_beats_pay_as_due_with_thin_cash_value(self, api):
        """PRD §3.7: "The optimizer evaluates three strategies and picks the one
        with the highest expected net value; ties break by the fixed priority
        PAY_AS_DUE first, then REDUCED_PAID_UP, then MINIMUM_FUNDING."
        PRD §3.7: "The created schedule records the case's `case_id`, the chosen
        `strategy`, the `optimized_monthly_premium_cents` for that strategy,
        `planned_months` equal to the remaining expectancy k, the
        `expected_net_value_cents` rounded half-up, and starts with
        `missed_payment_count` 0, `total_paid_cents` 0, and `status` `ACTIVE`."
        PRD §3.7: "each row's `grace_deadline` is its `due_date` plus 31 days"

        Design: Difficulty/combinatorial_formula/minimum_funding_fixed_point_month_ordered_projection
        """
        ctx = setup_case_acquired(
            start_clock="2026-07-20T00:00:00Z",
            fund_clock="2026-08-15T00:00:00Z",
            release_clock="2026-09-05T00:00:00Z",
            policy_overrides={"policy_type": "UNIVERSAL_LIFE", "cash_value_cents": 2000000},
            insured_overrides={"gender": "F", "smoker_status": "UNKNOWN"},
        )
        case_before = validate_success(api.get_case(ctx["case"]["id"], PM))
        sched = create_schedule(ctx["case"]["id"])
        case_after = validate_success(api.get_case(ctx["case"]["id"], PM))
        assert case_after["version"] == case_before["version"] + 1, (
            "the case's version increments on schedule creation"
        )
        # Same fixture shape as the sibling test: the month-ordered projection
        # resolves m = 25812 and MINIMUM_FUNDING wins the argmax.
        assert sched["strategy"] == "MINIMUM_FUNDING"
        assert sched["optimized_monthly_premium_cents"] == 25812
        assert sched["expected_net_value_cents"] == 2818943
        assert sched["planned_months"] == 85
        assert sched["missed_payment_count"] == 0
        assert sched["total_paid_cents"] == 0
        assert sched["status"] == "ACTIVE"
        rows = list_payments(sched["id"])
        assert len(rows) == 85
        first, second = rows[0], rows[1]
        assert first["due_date"] == "2026-10-05T00:00:00Z"
        assert first["grace_deadline"] == "2026-11-05T00:00:00Z"
        assert second["due_date"] == "2026-11-04T00:00:00Z"

    def test_rpu_winner_zero_premium_no_payments(self, api):
        """PRD §3.7: "If the solved premium rounds to 0 — the cash value fully
        self-funds the coverage — MINIMUM_FUNDING is infeasible, because carriers
        require a positive modal premium, and it is excluded from the argmax."
        PRD §3.7: "**REDUCED_PAID_UP.** The present value of premiums is the
        unrounded billed monthly premium times the annuity factor. The reduced face
        is the face times CV divided by the sum of CV and that premium present
        value, rounded half-up — or 0 when that sum is not positive. Expected net
        value is the reduced face times v-to-the-k, and the monthly premium under
        this strategy is 0."
        PRD §3.7: "Creation also generates `PremiumPayment` rows — each carrying
        the schedule's `schedule_id` — one per planned month, capped at 360 rows,
        where rows of zero amount are never generated."

        Design: Corner/calculations/rpu_winner_zero_premium_no_payments
        """
        ctx = setup_case_acquired(
            start_clock="2026-07-20T00:00:00Z",
            fund_clock="2026-08-15T00:00:00Z",
            release_clock="2026-09-05T00:00:00Z",
            policy_overrides={"policy_type": "UNIVERSAL_LIFE", "cash_value_cents": 6000000},
            insured_overrides={"smoker_status": "UNKNOWN"},
        )
        sched = create_schedule(ctx["case"]["id"])
        assert sched["strategy"] == "REDUCED_PAID_UP"
        assert sched["reduced_face_cents"] == 6776687
        assert sched["optimized_monthly_premium_cents"] == 0
        assert sched["expected_net_value_cents"] == 2908712
        assert sched["planned_months"] == 85
        rows = list_payments(sched["id"])
        assert rows == [], "zero-amount payment rows are never generated"


class TestScheduleOCCAndSupersede:
    def test_occ_schedule_create_stale_version_and_supersede(self, api):
        """PRD §2.6: "Creating a premium schedule on a case requires
        `expected_case_version` matching the case's current `version`. Because
        creation supersedes the currently `ACTIVE` schedule, a supersede decision
        made against a stale case view must not silently succeed; a mismatch is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.7: "Creating a schedule supersedes the case's currently `ACTIVE`
        schedule, which moves to `SUPERSEDED`"

        Design: Corner/cross_cutting_layers/occ_schedule_create_stale_version_and_supersede
        """
        ctx = setup_case_acquired()  # default-clock chain, released 2026-08-16
        case = ctx["case"]
        v1 = validate_success(api.get_case(case["id"], PM))["version"]

        first = validate_success(api.create_premium_schedule(
            case["id"], {"expected_case_version": v1}, PM), expected_status=201)
        assert first["status"] == "ACTIVE"

        resp = api.create_premium_schedule(case["id"], {"expected_case_version": v1}, PM)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        v2 = validate_success(api.get_case(case["id"], PM))["version"]
        second = validate_success(api.create_premium_schedule(
            case["id"], {"expected_case_version": v2}, PM), expected_status=201)
        assert second["status"] == "ACTIVE"

        first_after = validate_success(api.get_premium_schedule(first["id"], PM))
        assert first_after["status"] == "SUPERSEDED"


class TestLapseCascade:
    def test_premium_grace_miss_lapse_cascade(self, api):
        """PRD §3.7: "A finance officer pays a `SCHEDULED` payment by supplying
        `amount_cents` equal to the payment's scheduled `amount_cents` — any other
        figure is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422)"
        PRD §3.7: "A payment left unpaid past its `grace_deadline` becomes
        `MISSED` automatically when the clock advances. Each miss increments the
        schedule's `missed_payment_count` by 1. When the count reaches 2, the lapse
        cascade fires: the schedule moves from `ACTIVE` to `TERMINATED`, the case
        moves from `ACQUIRED` to `LAPSED`, the policy's `status` becomes `LAPSED`,
        and the portfolio's `nav_stale` becomes true."

        Design: Corner/cross_cutting_layers/premium_grace_miss_lapse_cascade
        """
        ctx = setup_case_acquired(
            start_clock="2026-07-20T00:00:00Z",
            fund_clock="2026-08-15T00:00:00Z",
            release_clock="2026-09-05T00:00:00Z",
            insured_overrides={"smoker_status": "UNKNOWN"},
        )
        sched = create_schedule(ctx["case"]["id"])
        assert sched["strategy"] == "PAY_AS_DUE", "cash_value 0: billed premium wins the argmax"
        assert sched["optimized_monthly_premium_cents"] == 50000
        rows = list_payments(sched["id"])
        pay1, pay2 = rows[0], rows[1]
        assert pay1["due_date"] == "2026-10-05T00:00:00Z"
        assert pay2["due_date"] == "2026-11-04T00:00:00Z"

        resp = api.pay_premium(pay1["id"], {"amount_cents": 49999}, FO_1)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)

        set_clock("2026-11-06T00:00:00Z")  # past pay1 grace 2026-11-05
        p1_after = validate_success(api.get_premium_payment(pay1["id"], FO_1))
        assert p1_after["status"] == "MISSED"
        sched_mid = validate_success(api.get_premium_schedule(sched["id"], FO_1))
        assert sched_mid["missed_payment_count"] == 1

        set_clock("2026-12-06T00:00:00Z")  # past pay2 grace 2026-12-05
        p2_after = validate_success(api.get_premium_payment(pay2["id"], FO_1))
        assert p2_after["status"] == "MISSED"

        sched_end = validate_success(api.get_premium_schedule(sched["id"], FO_1))
        assert sched_end["status"] == "TERMINATED"
        assert sched_end["missed_payment_count"] == 2
        case_after = validate_success(api.get_case(ctx["case"]["id"], CM))
        assert case_after["status"] == "LAPSED"
        policy_after = validate_success(api.get_policy(ctx["policy"]["id"], CM))
        assert policy_after["status"] == "LAPSED"
        pf_after = validate_success(api.get_portfolio(ctx["portfolio"]["id"], PM))
        assert pf_after["nav_stale"] is True


class TestAcquiredGate:
    def test_tracking_rejected_before_acquisition(self, api):
        """PRD §3.8: "On an `ACQUIRED` case — and only there, otherwise
        `ERR_POLICY_NOT_ACQUIRED` — a case manager records tracking events on the
        insured."

        Design: Corner/validations/tracking_rejected_before_acquisition
        """
        from test_helpers import setup_case_marketed
        ctx = setup_case_marketed(with_disclosures=False, with_offer=False,
                                  insured_overrides={"smoker_status": "UNKNOWN"})
        resp = api.create_tracking_event(
            ctx["case"]["id"],
            {"event_type": "WELLNESS_CALL", "outcome": "ALIVE_CONFIRMED",
             "source_channel": "CALL", "event_date": "2026-08-01"},
            CM,
        )
        validate_error(resp, ApiErrorId.ERR_POLICY_NOT_ACQUIRED)
