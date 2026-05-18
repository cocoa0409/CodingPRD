"""Concurrency: at-most-one-plan-per-case, duplicate
sequence_number, and meeting/dismiss race.

PRD §3.12.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_exactly_one_succeeds,
    create_payment_payload,
    create_plan_payload,
    make_debtor_headers,
    re_get_plan,
    run_race,
    setup_ch13_in_repayment,
    setup_ch13_plan_proposed,
    setup_meeting_scheduled_case,
    validate_error_is_one_of,
)


# ===========================================================================
# Concurrent plan submission — PRD §3.12
# ===========================================================================
class TestConcurrentPlanSubmission:
    """PRD §3.12: 'When two debtor processes attempt to submit a
    second plan against the same case while a first plan is still
    active, the second insert violates the at-most-one-plan-per-case
    rule and is rejected with ERR_PLAN_ALREADY_EXISTS.'"""

    def test_only_one_plan_succeeds_under_race(self, api):
        """PRD §3.12: "When two debtor processes attempt to submit a
        second plan against the same case while a first plan is
        still active, the second insert violates the
        at-most-one-plan-per-case rule and is rejected with
        ERR_PLAN_ALREADY_EXISTS."

        Claim: two concurrent POST /cases/{c}/plans with the first
        plan still PROPOSED -> exactly one succeeds and the other
        receives ERR_PLAN_ALREADY_EXISTS.
        """
        from test_helpers import (
            create_debtor, create_case, submit_all_schedules_for,
            run_means_test, file_case, schedule_341, advance_clock_to,
            conduct_341, iso_offset, parse_iso, MEETING_341_MIN_GAP_DAYS,
        )
        # Build to MEETING_HELD as CHAPTER_13 with no existing Plan.
        debtor = create_debtor(state_code="TX", household_size=1)
        case = create_case(
            debtor=debtor, chapter_requested="CHAPTER_13",
        )
        submit_all_schedules_for(
            case=case, debtor=debtor,
            monthly_income_cents=200_000,
            monthly_expenses_cents=400_000,
        )
        mtr = run_means_test(case=case, debtor=debtor)
        case_filed = file_case(case=case, debtor=debtor)
        meeting_date = iso_offset(
            days=MEETING_341_MIN_GAP_DAYS,
            base=parse_iso(case_filed["filing_date"]),
        )
        schedule_341(case=case_filed, meeting_date_iso=meeting_date)
        advance_clock_to(meeting_date)
        conduct_341(case=case_filed)

        headers = make_debtor_headers(debtor["id"])
        plan_payload = create_plan_payload(
            proposed_monthly_payment_cents=10_000,
            plan_months=mtr["required_plan_months"],
        )
        # Two concurrent submissions.
        results = run_race(
            lambda: api.create_plan(case_filed["id"],
                                    dict(plan_payload), headers),
            lambda: api.create_plan(case_filed["id"],
                                    dict(plan_payload), headers),
        )
        outcomes = assert_exactly_one_succeeds(results[0], results[1])
        # The failing one must carry ERR_PLAN_ALREADY_EXISTS per
        # PRD §3.12.
        loser = outcomes["failures"][0]
        validate_error_is_one_of(
            loser,
            [ApiErrorId.ERR_PLAN_ALREADY_EXISTS.value],
        )


# ===========================================================================
# Concurrent duplicate payment — PRD §3.12
# ===========================================================================
class TestConcurrentPaymentDuplicate:
    """PRD §3.12: 'When two duplicate trustee payments race the same
    (plan_id, sequence_number), exactly one commits and the other is
    rejected with ERR_PAYMENT_SEQUENCE_DUPLICATE.'"""

    def test_concurrent_duplicate_sequence_yields_one_winner(self, api):
        """PRD §3.12: "When two duplicate trustee payments race the
        same (plan_id, sequence_number), exactly one commits and the
        other is rejected with ERR_PAYMENT_SEQUENCE_DUPLICATE."

        Claim: two concurrent payment inserts at same sequence_number
        -> exactly one succeeds, the other gets
        ERR_PAYMENT_SEQUENCE_DUPLICATE.
        """
        # Build PLAN_CONFIRMED state so we can race seq=1.
        from test_helpers import setup_ch13_plan_confirmed
        debtor, case, _mtr, plan, _cr, _cl = setup_ch13_plan_confirmed(
            monthly_payment_cents=10_000, plan_months=36,
            monthly_income_cents=200_000, monthly_expenses_cents=400_000,
        )
        headers = make_debtor_headers(debtor["id"])
        pay_payload = create_payment_payload(
            sequence_number=1, amount_cents=10_000, status="APPLIED",
        )
        results = run_race(
            lambda: api.record_payment(case["id"], plan["id"],
                                       dict(pay_payload), headers),
            lambda: api.record_payment(case["id"], plan["id"],
                                       dict(pay_payload), headers),
        )
        outcomes = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcomes["failures"][0]
        validate_error_is_one_of(
            loser,
            [ApiErrorId.ERR_PAYMENT_SEQUENCE_DUPLICATE.value],
        )
        # And the plan ends with exactly one APPLIED payment counted.
        plan_after = re_get_plan(case["id"], plan["id"])
        assert plan_after["paid_to_date_cents"] == 10_000


# ===========================================================================
# Race conduct_341 vs dismiss from MEETING_SCHEDULED — PRD §3.12
# ===========================================================================
class TestConductVsDismissRace:
    """PRD §3.12: 'When the trustee races a meeting-conduct against a
    dismissal from MEETING_SCHEDULED, exactly one commits — the loser
    observes that the case is no longer in MEETING_SCHEDULED and is
    rejected with ERR_INVALID_STATE.'"""

    def test_only_one_of_conduct_or_dismiss_succeeds(self, api):
        """PRD §3.12: "When the trustee races a meeting-conduct
        against a dismissal from MEETING_SCHEDULED, exactly one
        commits — the loser observes that the case is no longer in
        MEETING_SCHEDULED and is rejected with ERR_INVALID_STATE."

        Claim: concurrent conduct_341 and dismiss against
        MEETING_SCHEDULED case -> exactly one succeeds; loser gets
        ERR_INVALID_STATE.
        """
        from test_helpers import advance_clock_to
        debtor, case, _mtr, meeting_date_iso = setup_meeting_scheduled_case()
        # Advance clock so conduct_341 won't fail on the
        # date-not-reached gate (otherwise dismiss would always win).
        advance_clock_to(meeting_date_iso)

        results = run_race(
            lambda: api.conduct_341(case["id"], None,
                                    TEST_USERS["trustee_headers"]),
            lambda: api.dismiss_case(case["id"], None,
                                     TEST_USERS["trustee_headers"]),
        )
        outcomes = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcomes["failures"][0]
        validate_error_is_one_of(
            loser, [ApiErrorId.ERR_INVALID_STATE.value],
        )
