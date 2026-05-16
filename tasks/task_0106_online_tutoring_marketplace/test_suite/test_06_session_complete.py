"""Session complete: actual_gross, final commission, money invariant.

Covers PRD §3.5: complete action — adjusted_minutes clamping,
short_delivery refund, FINAL commission (tier at completion), tutor
payout pinning, lifetime_completed_sessions increment, and money
conservation invariant.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    COMMISSION_TIER_0_RATE,
    COMMISSION_TIER_20_RATE,
    NON_EXISTENT_UUID,
    TEST_USERS,
    advance_clock_past_session_end,
    advance_clock_to,
    assert_money_conservation_invariant,
    assert_session,
    book_session,
    cancel_session,
    complete_session,
    complete_session_payload,
    confirm_session,
    create_adult_student,
    iso_utc,
    make_tutor_headers,
    parse_iso,
    raise_tutor_to_completed_count,
    server_now_dt,
    setup_basic_booking_scenario,
    setup_completed_session,
    setup_confirmed_session,
    setup_verified_tutor_with_subject,
    validate_error,
    validate_success,
)


# ===========================================================================
# Completion happy path
# ===========================================================================
class TestCompleteHappyPath:
    def test_complete_60min_at_tier_0_yields_20pct_commission(self, api):
        """PRD §3.5: "otherwise 0.20 (20%)" — at tier 0 (lifetime < 20),
        commission rate is 0.20. PRD §3.5: "tutor_payout_cents is then
        pinned to actual_gross_cents minus final_commission_cents".

        Claim: a 60-min completion at hourly_rate=6000 with
        adjusted_minutes=60 yields actual_gross=6000,
        final_commission=1200, tutor_payout=4800.
        """
        tutor, student, completed = setup_completed_session(
            hourly_rate_cents=6000, duration_minutes=60,
            adjusted_minutes=60,
        )
        assert completed["status"] == "COMPLETED"
        assert completed["actual_gross_cents"] == 6000
        assert completed["final_commission_cents"] == 1200
        assert completed["tutor_payout_cents"] == 4800
        assert completed["refund_to_student_cents"] == 0
        assert_money_conservation_invariant(completed)

    def test_complete_increments_lifetime_count(self, api):
        """PRD §3.5: "The tutor's lifetime_completed_sessions is
        incremented by 1."

        Claim: after one COMPLETED transition, tutor's
        lifetime_completed_sessions increases by 1.
        """
        tutor, _student, completed = setup_completed_session()
        refreshed = validate_success(
            api.get_tutor(tutor["id"], TEST_USERS["admin_headers"]),
        )
        assert refreshed["lifetime_completed_sessions"] == 1

    def test_complete_with_short_delivery_refunds_student(self, api):
        """PRD §3.5: "a short-delivery refund equal to the maximum of
        zero and gross_price_cents minus actual_gross_cents is
        computed; if this short-delivery refund is positive,
        refund_to_student_cents is increased by it and the student's
        credit_balance_cents is increased by the same amount."

        Claim: 60-min booking completed with adjusted_minutes=45 at
        hourly=6000 yields actual_gross=4500,
        short_delivery_refund=1500 added to refund_to_student_cents
        and to student credit.
        """
        tutor, student, completed = setup_completed_session(
            hourly_rate_cents=6000, duration_minutes=60,
            adjusted_minutes=45,
        )
        assert completed["gross_price_cents"] == 6000
        assert completed["actual_gross_cents"] == 4500
        assert completed["refund_to_student_cents"] == 1500
        # Commission at tier 0 = 20% of actual_gross.
        assert completed["final_commission_cents"] == 900
        # Payout = actual_gross - commission = 4500 - 900 = 3600.
        assert completed["tutor_payout_cents"] == 3600
        assert_money_conservation_invariant(completed)
        # Student credit increases by 1500.
        from test_helpers import make_student_headers
        refreshed_student = validate_success(
            api.get_student(student["id"], make_student_headers(student["id"])),
        )
        assert refreshed_student["credit_balance_cents"] == 1500

    def test_complete_discount_keyed_on_scheduled_not_actual(self, api):
        """PRD §3.5: "Note that the discount tier is keyed on
        scheduled minutes (not actual), so a tutor cannot shed the
        multi-hour discount by reporting fewer actual minutes."

        Claim: scheduled=180min @ rate=6000 → discount 0.90 applies;
        adjusted=120min still uses 0.90 discount:
        actual_gross = round(6000/60 * 120 * 0.90) = round(10800) = 10800.
        """
        tutor, student, completed = setup_completed_session(
            hourly_rate_cents=6000, duration_minutes=180,
            adjusted_minutes=120,
        )
        # scheduled-tier discount=0.90 applied to actual 120 min:
        # 6000/60 * 120 * 0.90 = 10800
        assert completed["gross_price_cents"] == 16200  # 180-min discounted
        assert completed["actual_gross_cents"] == 10800


# ===========================================================================
# Completion validations
# ===========================================================================
class TestCompleteValidations:
    def test_complete_with_adjusted_minutes_above_scheduled_rejected(self, api):
        """PRD §3.5: "The supplied value must lie in the range 0
        through scheduled minutes inclusive ... otherwise
        ERR_ADJUSTED_MINUTES_OUT_OF_RANGE."

        Claim: adjusted_minutes=61 on a 60-min scheduled session
        returns ERR_ADJUSTED_MINUTES_OUT_OF_RANGE.
        """
        tutor, _student, session = setup_confirmed_session(
            duration_minutes=60,
        )
        # Advance to end_at, threading IN_PROGRESS first per PRD §3.5.
        advance_clock_past_session_end(session)
        res = api.complete_session(
            session["id"],
            complete_session_payload(adjusted_minutes=61),
            make_tutor_headers(tutor["id"]),
        )
        validate_error(res, "ERR_ADJUSTED_MINUTES_OUT_OF_RANGE")

    def test_complete_with_negative_adjusted_minutes_rejected(self, api):
        """PRD §3.5: "The supplied value must lie in the range 0
        through scheduled minutes inclusive".

        Claim: adjusted_minutes=-1 returns
        ERR_ADJUSTED_MINUTES_OUT_OF_RANGE.
        """
        tutor, _student, session = setup_confirmed_session(
            duration_minutes=60,
        )
        advance_clock_past_session_end(session)
        res = api.complete_session(
            session["id"],
            complete_session_payload(adjusted_minutes=-1),
            make_tutor_headers(tutor["id"]),
        )
        validate_error(res, "ERR_ADJUSTED_MINUTES_OUT_OF_RANGE")

    def test_complete_requires_acting_tutor(self, api):
        """PRD §3.5: "The complete action requires the acting tutor's
        X-User-ID to equal the session's tutor_id".

        Claim: a different tutor completing returns
        ERR_NOT_AUTHORIZED_FOR_RESOURCE.
        """
        tutor, _student, session = setup_confirmed_session()
        advance_clock_past_session_end(session)
        from test_helpers import make_tutor_verified
        other_tutor, _, _ = make_tutor_verified()
        res = api.complete_session(
            session["id"],
            complete_session_payload(),
            make_tutor_headers(other_tutor["id"]),
        )
        validate_error(res, "ERR_NOT_AUTHORIZED_FOR_RESOURCE")

    def test_complete_invalid_state_when_not_in_progress(self, api):
        """PRD §2.6 priority 5: ERR_INVALID_STATE when transition not
        legal from current state. The complete transition is
        IN_PROGRESS → COMPLETED (PRD §3.5), but the early-finish
        proviso lets a tutor complete from CONFIRMED before clock
        reaches end_at if adjusted_minutes >= scheduled - 10.

        Claim: completing a REQUESTED (not yet confirmed) session
        returns ERR_INVALID_STATE.
        """
        tutor, _student, session = setup_basic_booking_scenario()
        res = api.complete_session(
            session["id"],
            complete_session_payload(),
            make_tutor_headers(tutor["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# Tier transition between booking and completion (commission variant FINAL)
# ===========================================================================
class TestCompletionTierTransition:
    def test_provisional_tier_0_then_final_tier_20_when_crossing(self, api):
        """PRD §3.5: "which keys the commission tier on the tutor's
        lifetime_completed_sessions at the moment of completion (after
        the increment described next) and bills commission on
        actual_gross_cents."

        Claim: book at lifetime=19 (provisional tier=0 → 20%);
        complete 20 helper sessions to bring lifetime to 20;
        complete the target at lifetime=20 → final tier 15%.
        Provisional commission and final commission differ.

        # difficulty: dual_variant_calc/commission_provisional_vs_final_on_session
        """
        # Book the target session first at lifetime=0 (will be tier 0).
        # The helper iterations advance the clock substantially; the
        # target.start_at must stay strictly later than the post-helper
        # clock so we can still advance forward into IN_PROGRESS.
        # raise_tutor_to_completed_count consumes ~ Σ(offset+1h) per
        # iteration; for 20 iterations with offset 2+3i (max 59h) the
        # total clock advance is ~630h. Park the target ~10 weeks out.
        tutor, target_student, target_session = setup_basic_booking_scenario(
            hourly_rate_cents=6000, duration_minutes=60,
            start_offset_hours=24.0 * 70,  # ~70 days out — well past helpers
        )
        # Confirm target.
        target_confirmed = confirm_session(
            session=target_session, tutor=tutor,
        )
        # provisional_commission for a 6000-cent gross at tier 0 (20%)
        # = round_half_up(6000 * 0.20) = 1200.
        assert target_confirmed["provisional_commission_cents"] == 1200
        # Run helper sessions to raise lifetime to 20.
        raise_tutor_to_completed_count(tutor=tutor, target_count=20)
        # Now we must advance clock past target.end_at to complete.
        advance_clock_past_session_end(target_confirmed)
        completed = complete_session(
            session=target_confirmed, tutor=tutor, adjusted_minutes=60,
        )
        # At lifetime=20 → tier 15%; final_commission = round(6000*0.15)
        # = 900.
        assert completed["final_commission_cents"] == 900
        assert completed["tutor_payout_cents"] == 5100
        # Confirms provisional != final.
        assert (
            completed["provisional_commission_cents"]
            != completed["final_commission_cents"]
        )
