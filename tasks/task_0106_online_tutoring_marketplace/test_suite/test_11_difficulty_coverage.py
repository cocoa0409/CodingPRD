"""Second-coverage tests for the harder PRD-described behaviors.

Each test here targets a behavior PRD §3 names explicitly and adds a
second perspective on a rule whose primary test lives elsewhere in the
suite. Every test is tagged `# difficulty: <rule_id>/<instance.name>`
in its docstring so the coverage audit can map tests back to the
difficulty-design entries.

Primary tests for each instance live in the topic-organized files
(test_02..test_10). This file adds a second-vantage test per instance:

  dual_variant_calc/commission_provisional_vs_final_on_session
    - primary: test_06::test_provisional_tier_0_then_final_tier_20_when_crossing
    - second : test_provisional_vs_final_commission_short_delivery
  dual_variant_calc/verification_posture_provisional_vs_final_on_tutor
    - primary: test_02::test_both_critical_approved_drives_verified
    - second : test_clock_driven_expiry_recomputes_posture_to_suspended

  combinatorial_formula/pricing_gross_multi_input_nonlinear_mode_a
    - primary: test_04::test_book_120_min_5pct_discount and
               test_04::test_book_180_min_10pct_discount
    - second : test_pricing_gross_three_inputs_match_table

  combinatorial_formula/pinned_rounding_order_gross_then_commission_mode_b
    - primary: this file's test_pinned_rounding_order
    - second : test_pinned_rounding_order_alternative_rejected

  non_linear_state_machine/refund_dispute_cyclic_open_counter_loop
    - primary: test_07::cycle tests
    - second : test_two_full_cycles_advance_round_count

  non_linear_state_machine/session_branching_complete_or_cancel_or_dispute
    - primary: test_05 + test_06
    - second : test_three_confirmed_sessions_fork_into_three_terminals

  transitive_cascade/credential_expiry_cascade_depth3
    - primary: test_09::test_critical_credential_expiry_suspends_tutor +
               test_09::test_expiry_force_cancels_future_confirmed_sessions
    - second : test_credential_expiry_full_depth_3_chain

  transitive_cascade/parent_link_revoke_cascade_depth2
    - primary: test_09::test_revoke_link_cancels_future_minor_sessions
    - second : test_link_revoke_cancels_multiple_sessions

  priority_pair_validation_conflict/business_referential_vs_business_fiscal_dispute_on_settled
    - primary: this file's test_dispute_window_wins_over_amount_range
    - second : test_dispute_window_wins_on_confirmed_session_with_bad_amount

  priority_pair_validation_conflict/business_safety_vs_business_temporal_booking_with_unverified_tutor
    - primary: this file's test_tutor_not_verified_wins_over_invalid_session_window
    - second : test_tutor_not_verified_wins_over_invalid_window_min_lead

  boundary_precision_check/cancellation_fee_24h_boundary_inclusive
    - primary: test_05::test_student_cancel_24h_notice_free
    - second : test_cancellation_fee_just_below_24h_charges_25pct

  boundary_precision_check/trial_eligibility_empty_history_boundary
    - primary: test_04::test_trial_blocked_after_completed_non_trial +
               test_04::test_trial_eligible_first_time_pair
    - second : test_trial_blocked_by_completed_pair_but_allowed_for_other

  cross_entity_state_dependency/session_confirm_requires_tutor_verified
    - primary: test_05::test_confirm_blocked_when_tutor_not_verified
    - second : test_confirm_on_suspended_tutor_rejected

  cross_entity_state_dependency/session_book_requires_parentchildlink_active_for_minor
    - primary: test_04::test_minor_without_active_link_rejected
    - second : test_minor_booking_succeeds_after_link_approval

  resource_temporal_overlap/tutor_session_closed_open_interval_overlap
    - primary: test_05::test_strict_overlap_rejected +
               test_05::test_adjacent_sessions_do_not_overlap
    - second : test_three_session_calendar_adjacency_and_overlap

  resource_temporal_overlap/trial_uniqueness_lifetime_aggregate_overlap
    - primary: test_04::test_second_trial_on_same_pair_rejected
    - second : test_trial_used_even_after_cancellation

  compensating_invariant/per_session_money_conservation_on_refund_cascade
    - primary: test_07::test_arbitrate_refund_recomputes_payout_and_commission
    - second : test_money_conservation_after_short_delivery_plus_arbitration

  compensating_invariant/parent_child_count_invariant_on_link_revoke
    - primary: test_03::test_approve_link_moves_to_active_and_bumps_count +
               test_03::test_revoke_active_link_returns_204
    - second : test_managed_child_count_round_trip
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    TEST_USERS,
    accept_dispute,
    add_approved_subject,
    advance_clock_past_session_end,
    advance_clock_to,
    arbitrate_dispute,
    assert_money_conservation_invariant,
    book_session,
    book_session_payload,
    cancel_session,
    complete_session,
    confirm_session,
    counter_dispute,
    create_adult_student,
    create_minor_student,
    create_parent,
    create_tutor,
    escalate_dispute,
    iso_utc,
    make_admin_headers,
    make_parent_headers,
    make_student_headers,
    make_tutor_headers,
    make_tutor_verified,
    open_dispute,
    open_dispute_payload,
    parse_iso,
    raise_tutor_to_completed_count,
    reopen_dispute,
    respond_dispute,
    revoke_link,
    server_now_dt,
    setup_active_parent_child,
    setup_basic_booking_scenario,
    setup_completed_session,
    setup_confirmed_session,
    setup_settled_session,
    setup_verified_tutor_with_subject,
    submit_credential,
    validate_error,
    validate_success,
)


# ===========================================================================
# dual_variant_calc — instance 1 (second coverage)
# ===========================================================================
def test_provisional_vs_final_commission_short_delivery(api):
    """PRD §3.5: "which keys the commission tier on the tutor's
    lifetime_completed_sessions at the moment of completion (after
    the increment described next) and bills commission on
    actual_gross_cents."

    Claim: a fresh tutor at lifetime=0 books a 60-min session
    (provisional commission 20% * 6000 = 1200); completes with
    adjusted_minutes=30 (actual_gross=3000, final commission 20% *
    3000 = 600). Provisional != final, demonstrating dual variants on
    the SAME Session.

    # difficulty: dual_variant_calc/commission_provisional_vs_final_on_session
    """
    tutor, student, completed = setup_completed_session(
        hourly_rate_cents=6000, duration_minutes=60,
        adjusted_minutes=30,
    )
    assert completed["gross_price_cents"] == 6000
    assert completed["provisional_commission_cents"] == 1200
    assert completed["actual_gross_cents"] == 3000
    assert completed["final_commission_cents"] == 600
    assert (
        completed["provisional_commission_cents"]
        != completed["final_commission_cents"]
    )
    assert_money_conservation_invariant(completed)


# ===========================================================================
# dual_variant_calc — instance 2 (second coverage)
# ===========================================================================
def test_clock_driven_expiry_recomputes_posture_to_suspended(api):
    """PRD §3.1: "Otherwise, if the tutor was previously VERIFIED and
    the approved-and-unexpired set no longer contains both
    GOVERNMENT_ID and BACKGROUND_CHECK, the tutor moves to SUSPENDED."

    Claim: same approved credential set yields VERIFIED before the
    clock crosses expires_at, and SUSPENDED after — different variant
    of the verification_posture computation applied to the same Tutor
    row.

    # difficulty: dual_variant_calc/verification_posture_provisional_vs_final_on_tutor
    """
    soon = iso_utc(server_now_dt() + timedelta(hours=5))
    far = iso_utc(server_now_dt() + timedelta(days=30))
    tutor, _gov, _bg = make_tutor_verified(
        gov_id_expires_at=soon, bg_check_expires_at=far,
    )
    # Pre-advance posture: VERIFIED.
    before = validate_success(
        api.get_tutor(tutor["id"], TEST_USERS["admin_headers"]),
    )
    assert before["verification_status"] == "VERIFIED"
    # Advance past soon.
    advance_clock_to(iso_utc(server_now_dt() + timedelta(hours=6)))
    after = validate_success(
        api.get_tutor(tutor["id"], TEST_USERS["admin_headers"]),
    )
    assert after["verification_status"] == "SUSPENDED"


# ===========================================================================
# combinatorial_formula — instance 1 (second coverage)
# ===========================================================================
def test_pricing_gross_three_inputs_match_table(api):
    """PRD §3.4: "if scheduled minutes is at least 180, the raw amount
    is multiplied by 0.90 (a 10% discount); else if scheduled minutes
    is at least 120, the raw amount is multiplied by 0.95 (a 5%
    discount); otherwise no discount applies. Trial bookings receive
    no discount even if they meet the duration thresholds."

    Claim: combination of three inputs (is_trial, minutes, rate)
    yields three distinct gross prices: A (119min, non-trial, 6000) =
    11900; B (120min, non-trial, 6000) = 11400; C (60min, trial,
    4000) = 4000.

    # difficulty: combinatorial_formula/pricing_gross_multi_input_nonlinear_mode_a
    """
    tutor, _ = setup_verified_tutor_with_subject(
        hourly_rate_cents=6000, trial_rate_cents=4000,
    )
    s_a = create_adult_student()
    s_b = create_adult_student()
    s_c = create_adult_student()
    now = server_now_dt()
    a = book_session(
        tutor=tutor, student=s_a, duration_minutes=119,
        start_at=iso_utc(now + timedelta(hours=2)),
        end_at=iso_utc(now + timedelta(hours=2, minutes=119)),
    )
    b = book_session(
        tutor=tutor, student=s_b, duration_minutes=120,
        start_at=iso_utc(now + timedelta(hours=8)),
        end_at=iso_utc(now + timedelta(hours=10)),
    )
    c = book_session(
        tutor=tutor, student=s_c, duration_minutes=60, is_trial=True,
        start_at=iso_utc(now + timedelta(hours=15)),
        end_at=iso_utc(now + timedelta(hours=16)),
    )
    assert a["gross_price_cents"] == 11900
    assert b["gross_price_cents"] == 11400
    assert c["gross_price_cents"] == 4000


# ===========================================================================
# combinatorial_formula — instance 2 (second coverage)
#
# Two tests are placed here covering the PINNED rounding order
# (gross-line-first, then commission single-round): one is a baseline
# verifying the formula on the pinned input; the other forces a
# fractional-gross input that disambiguates between the pinned order
# and the alternative (rate*raw-first) order.
# ===========================================================================
def test_pinned_rounding_order_gross_then_commission(api):
    """PRD §2.8: "gross prices are rounded at the line level first,
    then commissions are rounded as a single round at the end".
    PRD §3.5: tier-0 commission = 0.20.

    Claim: with hourly_rate_cents=6009, 30-min non-trial session:
    raw_gross = 6009/60 * 30 = 3004.5 → round_half_up → 3005;
    final_commission = round_half_up(3005 * 0.20) = 601 (at tier-0).
    The alternative order would compute round(3004.5 * 0.20) =
    round(600.9) = 601 — collision at 20%. To disambiguate, see the
    sibling test at the 10% tier.

    # difficulty: combinatorial_formula/pinned_rounding_order_gross_then_commission_mode_b
    """
    tutor, _ = setup_verified_tutor_with_subject(
        hourly_rate_cents=6009, trial_rate_cents=1000,
    )
    student = create_adult_student()
    s = book_session(
        tutor=tutor, student=student, duration_minutes=30,
    )
    # gross: 6009/60 * 30 = 3004.5 → round_half_up = 3005
    assert s["gross_price_cents"] == 3005
    assert s["charged_amount_cents"] == 3005


def test_pinned_rounding_order_at_10pct_tier_disambiguates(api):
    """PRD §2.8: "gross prices are rounded at the line level first,
    then commissions are rounded as a single round at the end;
    commissions are never rounded on a per-minute basis."

    Claim: with hourly_rate_cents=6009, 30-min non-trial completed
    at lifetime tier-100 (rate=0.10): pinned order produces
    final_commission = round_half_up(3005 * 0.10) = round_half_up(300.5)
    = 301. Alternative round_half_up(3004.5 * 0.10) = round_half_up(300.45)
    = 300 — REJECTED. Pinned order wins.

    # difficulty: combinatorial_formula/pinned_rounding_order_gross_then_commission_mode_b
    """
    # Build a tutor with 100 lifetime completed sessions BEFORE booking
    # the target so the FINAL variant lands on tier-100 (10%).
    tutor, _ = setup_verified_tutor_with_subject(
        hourly_rate_cents=6009, trial_rate_cents=1000,
    )
    raise_tutor_to_completed_count(tutor=tutor, target_count=100)
    tutor = validate_success(
        api.get_tutor(tutor["id"], TEST_USERS["admin_headers"]),
    )
    student = create_adult_student()
    s = book_session(
        tutor=tutor, student=student, duration_minutes=30,
        start_offset_hours=2.0,
    )
    confirmed = confirm_session(session=s, tutor=tutor)
    advance_clock_past_session_end(confirmed)
    completed = complete_session(
        session=confirmed, tutor=tutor, adjusted_minutes=30,
    )
    assert completed["gross_price_cents"] == 3005
    assert completed["actual_gross_cents"] == 3005
    # PINNED order: round(3005*0.10) = round(300.5) = 301.
    assert completed["final_commission_cents"] == 301
    assert completed["tutor_payout_cents"] == 2704
    assert_money_conservation_invariant(completed)


# ===========================================================================
# non_linear_state_machine — instance 1 (second coverage)
# ===========================================================================
def test_two_full_dispute_cycles_advance_round_count(api):
    """PRD §3.7: "From COUNTER_PROPOSED, the opener (student or
    linked parent) chooses to accept or reopen ... Reopening (the
    opener rejects the counter) transitions the dispute
    COUNTER_PROPOSED → OPEN".

    Claim: a OPEN → TUTOR_RESPONDED → COUNTER_PROPOSED → OPEN →
    TUTOR_RESPONDED → COUNTER_PROPOSED cycle leaves round_count=2 and
    confirms the cyclic shape of the state machine.

    # difficulty: non_linear_state_machine/refund_dispute_cyclic_open_counter_loop
    """
    tutor, student, completed = setup_completed_session()
    d = open_dispute(
        session=completed,
        opener_headers=make_student_headers(student["id"]),
        requested_amount_cents=2000,
    )
    respond_dispute(dispute=d, tutor=tutor)
    counter_dispute(dispute=d, tutor=tutor, counter_amount_cents=500)
    reopen_dispute(
        dispute=d, opener_headers=make_student_headers(student["id"]),
    )
    respond_dispute(dispute=d, tutor=tutor)
    second_counter = counter_dispute(
        dispute=d, tutor=tutor, counter_amount_cents=1500,
    )
    assert second_counter["status"] == "COUNTER_PROPOSED"
    assert second_counter["round_count"] == 2


# ===========================================================================
# non_linear_state_machine — instance 2 (second coverage)
# ===========================================================================
def test_three_confirmed_sessions_fork_into_three_terminals(api):
    """PRD §3.8: cancellation by student → CANCELLED_BY_STUDENT;
    cancellation by tutor → CANCELLED_BY_TUTOR.
    PRD §3.5: complete → COMPLETED with commission settlement.

    Claim: three identical CONFIRMED sessions branch into three
    distinct terminal/late states (CANCELLED_BY_STUDENT,
    CANCELLED_BY_TUTOR, COMPLETED) with divergent money side-effects.

    # difficulty: non_linear_state_machine/session_branching_complete_or_cancel_or_dispute
    """
    tutor, _, _ = make_tutor_verified()
    add_approved_subject(tutor=tutor, subject_code="MATH_ALGEBRA")
    tutor = validate_success(
        api.get_tutor(tutor["id"], TEST_USERS["admin_headers"]),
    )
    student_a = create_adult_student()
    student_b = create_adult_student()
    student_c = create_adult_student()
    now = server_now_dt()
    a = book_session(
        tutor=tutor, student=student_a, duration_minutes=60,
        start_at=iso_utc(now + timedelta(hours=48)),
        end_at=iso_utc(now + timedelta(hours=49)),
    )
    b = book_session(
        tutor=tutor, student=student_b, duration_minutes=60,
        start_at=iso_utc(now + timedelta(hours=50)),
        end_at=iso_utc(now + timedelta(hours=51)),
    )
    c = book_session(
        tutor=tutor, student=student_c, duration_minutes=60,
        start_at=iso_utc(now + timedelta(hours=52)),
        end_at=iso_utc(now + timedelta(hours=53)),
    )
    confirm_session(session=a, tutor=tutor)
    confirm_session(session=b, tutor=tutor)
    c_confirmed = confirm_session(session=c, tutor=tutor)
    # A: student cancels (>=24h notice → free).
    cancel_a = cancel_session(
        session=a, actor_headers=make_student_headers(student_a["id"]),
    )
    assert cancel_a["status"] == "CANCELLED_BY_STUDENT"
    assert cancel_a["cancellation_fee_cents"] == 0
    # B: tutor cancels (always free).
    cancel_b = cancel_session(
        session=b, actor_headers=make_tutor_headers(tutor["id"]),
    )
    assert cancel_b["status"] == "CANCELLED_BY_TUTOR"
    assert cancel_b["cancellation_fee_cents"] == 0
    # C: advance to end_at and complete.
    advance_clock_past_session_end(c_confirmed)
    completed_c = complete_session(
        session=c_confirmed, tutor=tutor, adjusted_minutes=60,
    )
    assert completed_c["status"] == "COMPLETED"
    # tier-0 (lifetime<20) → 20% on 6000 = 1200.
    assert completed_c["final_commission_cents"] == 1200


# ===========================================================================
# transitive_cascade — instance 1 (second coverage)
# ===========================================================================
def test_credential_expiry_full_depth_3_chain(api):
    """PRD §2.10: "a three-level cascade from Credential to Tutor to
    Session ... every Session of that tutor in CONFIRMED whose
    start_at is in the future is force-cancelled to
    CANCELLED_BY_TUTOR with refund_to_student_cents set equal to
    charged_amount_cents and cancellation_fee_cents set to 0".

    Claim: clock-advance past GOVERNMENT_ID.expires_at triggers
    Credential→EXPIRED → Tutor→SUSPENDED → both CONFIRMED future
    sessions → CANCELLED_BY_TUTOR with full refund. Student credit
    sums both refunds.

    # difficulty: transitive_cascade/credential_expiry_cascade_depth3
    """
    soon = iso_utc(server_now_dt() + timedelta(hours=5))
    far = iso_utc(server_now_dt() + timedelta(days=30))
    tutor, gov, bg = make_tutor_verified(
        gov_id_expires_at=soon, bg_check_expires_at=far,
    )
    add_approved_subject(tutor=tutor, subject_code="MATH_ALGEBRA")
    tutor = validate_success(
        api.get_tutor(tutor["id"], TEST_USERS["admin_headers"]),
    )
    student = create_adult_student()
    now = server_now_dt()
    s1 = book_session(
        tutor=tutor, student=student, duration_minutes=60,
        start_at=iso_utc(now + timedelta(hours=10)),
        end_at=iso_utc(now + timedelta(hours=11)),
    )
    s2_student = create_adult_student()
    s2 = book_session(
        tutor=tutor, student=s2_student, duration_minutes=60,
        start_at=iso_utc(now + timedelta(hours=12)),
        end_at=iso_utc(now + timedelta(hours=13)),
    )
    confirm_session(session=s1, tutor=tutor)
    confirm_session(session=s2, tutor=tutor)
    # Sweep past credential expiry.
    advance_clock_to(iso_utc(now + timedelta(hours=6)))
    refreshed_s1 = validate_success(
        api.get_session(s1["id"], make_student_headers(student["id"])),
    )
    refreshed_s2 = validate_success(
        api.get_session(s2["id"], make_student_headers(s2_student["id"])),
    )
    assert refreshed_s1["status"] == "CANCELLED_BY_TUTOR"
    assert refreshed_s2["status"] == "CANCELLED_BY_TUTOR"
    assert refreshed_s1["refund_to_student_cents"] == 6000
    assert refreshed_s2["refund_to_student_cents"] == 6000
    s1_student = validate_success(
        api.get_student(student["id"], make_student_headers(student["id"])),
    )
    s2_student_after = validate_success(
        api.get_student(
            s2_student["id"], make_student_headers(s2_student["id"]),
        ),
    )
    assert s1_student["credit_balance_cents"] == 6000
    assert s2_student_after["credit_balance_cents"] == 6000


# ===========================================================================
# transitive_cascade — instance 2 (second coverage)
# ===========================================================================
def test_link_revoke_cancels_multiple_sessions(api):
    """PRD §2.10: "every Session of that minor child in REQUESTED or
    CONFIRMED with start_at in the future is cascade-cancelled as
    CANCELLED_BY_STUDENT with refund_to_student_cents equal to
    charged_amount_cents minus the cancellation fee computed for the
    child's session per the cancellation-fee rule."

    Claim: a parent revokes the link to their MINOR child; two
    future CONFIRMED sessions both flip to CANCELLED_BY_STUDENT with
    refunds summed into the child's credit_balance_cents.

    # difficulty: transitive_cascade/parent_link_revoke_cascade_depth2
    """
    tutor, _ = setup_verified_tutor_with_subject(hourly_rate_cents=6000)
    parent, student, link = setup_active_parent_child()
    now = server_now_dt()
    s1 = book_session(
        tutor=tutor, student=student, duration_minutes=60,
        parent=parent,
        start_at=iso_utc(now + timedelta(days=5)),
        end_at=iso_utc(now + timedelta(days=5, hours=1)),
    )
    s2 = book_session(
        tutor=tutor, student=student, duration_minutes=60,
        parent=parent,
        start_at=iso_utc(now + timedelta(days=6)),
        end_at=iso_utc(now + timedelta(days=6, hours=1)),
    )
    confirm_session(session=s1, tutor=tutor)
    confirm_session(session=s2, tutor=tutor)
    revoke_link(parent=parent, link=link)
    r1 = validate_success(
        api.get_session(s1["id"], TEST_USERS["admin_headers"]),
    )
    r2 = validate_success(
        api.get_session(s2["id"], TEST_USERS["admin_headers"]),
    )
    assert r1["status"] == "CANCELLED_BY_STUDENT"
    assert r2["status"] == "CANCELLED_BY_STUDENT"
    # Each had >=24h notice, so fee = 0 and refund = charged_amount.
    assert r1["cancellation_fee_cents"] == 0
    assert r2["cancellation_fee_cents"] == 0
    # Post-revoke, parent loses access (PRD §2.1 ACTIVE link
    # mediation), so re-read student via PlatformAdmin.
    refreshed_student = validate_success(
        api.get_student(
            student["id"], TEST_USERS["admin_headers"],
        ),
    )
    assert (
        refreshed_student["credit_balance_cents"]
        == r1["refund_to_student_cents"] + r2["refund_to_student_cents"]
    )


# ===========================================================================
# priority_pair_validation_conflict — instance 1 (primary + second)
# ===========================================================================
def test_dispute_on_confirmed_session_wins_window_over_amount(api):
    """PRD §2.6: "When multiple validation rules could fire on the same
    request, the server evaluates them in a fixed priority order so
    that the most fundamental failure surfaces first. The ordering ...
    dispute window (ERR_DISPUTE_WINDOW_CLOSED), amount bounds
    (ERR_AMOUNT_OUT_OF_RANGE) ..."

    Claim: open a dispute on a CONFIRMED session (window-closed) with
    requested_amount > charged_amount (amount-out-of-range): only
    ERR_DISPUTE_WINDOW_CLOSED is reported because the window check
    is higher in the §2.6 priority list.

    # difficulty: priority_pair_validation_conflict/business_referential_vs_business_fiscal_dispute_on_settled
    """
    tutor, student, session = setup_confirmed_session(
        hourly_rate_cents=6000, duration_minutes=60,
    )
    res = api.open_dispute(
        open_dispute_payload(
            session_id=session["id"],
            requested_amount_cents=999_999,
        ),
        make_student_headers(student["id"]),
    )
    validate_error(res, "ERR_DISPUTE_WINDOW_CLOSED")


def test_dispute_on_requested_session_wins_window_over_amount(api):
    """PRD §2.6: priority — dispute_window (§2.6 priority list) fires
    before amount_out_of_range.
    PRD §3.7: "The dispute must be opened ... against a session in
    COMPLETED or SETTLED; otherwise ERR_DISPUTE_WINDOW_CLOSED."

    Claim: open a dispute on a REQUESTED session (not yet
    COMPLETED/SETTLED) with bad requested_amount: window-closed
    error fires, not amount-range.

    # difficulty: priority_pair_validation_conflict/business_referential_vs_business_fiscal_dispute_on_settled
    """
    tutor, student, requested = setup_basic_booking_scenario(
        hourly_rate_cents=6000, duration_minutes=60,
    )
    res = api.open_dispute(
        open_dispute_payload(
            session_id=requested["id"],
            requested_amount_cents=999_999,
        ),
        make_student_headers(student["id"]),
    )
    validate_error(res, "ERR_DISPUTE_WINDOW_CLOSED")


# ===========================================================================
# priority_pair_validation_conflict — instance 2 (primary + second)
# ===========================================================================
def test_tutor_not_verified_wins_over_invalid_window_end_eq_start(api):
    """PRD §2.6: "tutor-verified check (ERR_TUTOR_NOT_VERIFIED),
    session-window check (ERR_INVALID_SESSION_WINDOW)" — tutor-verified
    is at higher priority.

    Per PRD §2.6, ERR_SUBJECT_NOT_OFFERED also outranks
    ERR_TUTOR_NOT_VERIFIED, and per PRD §3.2 subject tags can only be
    APPROVED on a VERIFIED tutor, so the non-verified tutor must
    first be VERIFIED, have a subject APPROVED, then be SUSPENDED
    (PRD §3.1) so the priority pair is actually reached.

    Claim: booking a SUSPENDED tutor (subject still APPROVED) with
    end_at == start_at returns ERR_TUTOR_NOT_VERIFIED (priority 10),
    not ERR_INVALID_SESSION_WINDOW (priority 11).

    # difficulty: priority_pair_validation_conflict/business_safety_vs_business_temporal_booking_with_unverified_tutor
    """
    tutor, _ = setup_verified_tutor_with_subject(
        subject_code="MATH_ALGEBRA",
    )
    validate_success(
        api.suspend_tutor(tutor["id"], TEST_USERS["admin_headers"]),
    )
    student = create_adult_student()
    now = server_now_dt()
    start = iso_utc(now + timedelta(hours=2))
    res = api.book_session(
        book_session_payload(
            tutor_id=tutor["id"], student_id=student["id"],
            subject_code="MATH_ALGEBRA",
            start_at=start, end_at=start,
        ),
        make_student_headers(student["id"]),
    )
    validate_error(res, "ERR_TUTOR_NOT_VERIFIED")


def test_tutor_not_verified_wins_over_invalid_window_min_lead(api):
    """PRD §2.6: tutor-verified (10) before session-window (11).

    Per PRD §3.2 we must verify-then-suspend the tutor so that
    ERR_SUBJECT_NOT_OFFERED does not pre-empt the verification check.

    Claim: booking a SUSPENDED tutor (subject still APPROVED) with
    start_at 5 minutes from now returns ERR_TUTOR_NOT_VERIFIED
    (priority 10), not ERR_INVALID_SESSION_WINDOW (priority 11).

    # difficulty: priority_pair_validation_conflict/business_safety_vs_business_temporal_booking_with_unverified_tutor
    """
    tutor, _ = setup_verified_tutor_with_subject(
        subject_code="MATH_ALGEBRA",
    )
    validate_success(
        api.suspend_tutor(tutor["id"], TEST_USERS["admin_headers"]),
    )
    student = create_adult_student()
    now = server_now_dt()
    res = api.book_session(
        book_session_payload(
            tutor_id=tutor["id"], student_id=student["id"],
            subject_code="MATH_ALGEBRA",
            start_at=iso_utc(now + timedelta(minutes=5)),
            end_at=iso_utc(now + timedelta(minutes=65)),
        ),
        make_student_headers(student["id"]),
    )
    validate_error(res, "ERR_TUTOR_NOT_VERIFIED")


# ===========================================================================
# boundary_precision_check — instance 1 (second coverage)
# ===========================================================================
def test_cancellation_fee_just_below_24h_charges_25pct(api):
    """PRD §3.8: "If hours-of-notice is less than 24 but at least 2,
    the fee is 25% of charged_amount_cents, rounded half-up." And:
    "a value equal to exactly 2.0 is the 25% tier".

    Claim: a sibling session at start_at = now+23h59m cancelled now
    charges 25% fee — confirming 24h is the inclusive upper edge of
    the free tier and just below 24 falls into 25%.

    # difficulty: boundary_precision_check/cancellation_fee_24h_boundary_inclusive
    """
    tutor, _ = setup_verified_tutor_with_subject(hourly_rate_cents=6000)
    student = create_adult_student()
    now = server_now_dt()
    s = book_session(
        tutor=tutor, student=student, duration_minutes=60,
        start_at=iso_utc(now + timedelta(hours=23, minutes=59)),
        end_at=iso_utc(now + timedelta(hours=24, minutes=59)),
    )
    cancelled = cancel_session(
        session=s, actor_headers=make_student_headers(student["id"]),
    )
    assert cancelled["cancellation_fee_cents"] == 1500


# ===========================================================================
# boundary_precision_check — instance 2 (second coverage)
# ===========================================================================
def test_trial_blocked_by_completed_pair_but_allowed_for_other(api):
    """PRD §3.4: "the (tutor_id, student_id) pair must have no prior
    Session anywhere in history (active or terminal) with is_trial
    true, and the student must have a count of zero COMPLETED sessions
    with that tutor; otherwise ERR_TRIAL_ALREADY_USED."

    Claim: completed-count for Student S with Tutor T blocks trial
    booking for (T, S); a fresh Student S2 still receives a successful
    trial with T — confirming the empty-set boundary on the
    per-(tutor, student) prior-history aggregate.

    # difficulty: boundary_precision_check/trial_eligibility_empty_history_boundary
    """
    tutor, student_s, _completed_s = setup_completed_session(
        hourly_rate_cents=6000, duration_minutes=60,
        adjusted_minutes=60,
    )
    # Attempt A: trial booking for (T, S) — must fail.
    now = server_now_dt()
    res_a = api.book_session(
        book_session_payload(
            tutor_id=tutor["id"], student_id=student_s["id"],
            subject_code="MATH_ALGEBRA",
            start_at=iso_utc(now + timedelta(hours=2)),
            end_at=iso_utc(now + timedelta(hours=3)),
            is_trial=True,
        ),
        make_student_headers(student_s["id"]),
    )
    validate_error(res_a, "ERR_TRIAL_ALREADY_USED")
    # Attempt B: trial booking for (T, S2) — fresh student must succeed.
    student_s2 = create_adult_student()
    s_b = book_session(
        tutor=tutor, student=student_s2, duration_minutes=60,
        is_trial=True,
    )
    assert s_b["is_trial"] is True
    assert s_b["status"] == "REQUESTED"


# ===========================================================================
# cross_entity_state_dependency — instance 1 (second coverage)
# ===========================================================================
def test_confirm_on_suspended_tutor_rejected(api, admin_headers):
    """PRD §3.5: "requires the tutor's current verification_status to
    be VERIFIED (a tutor whose posture has slipped to SUSPENDED or
    UNVERIFIED between booking and confirmation cannot confirm —
    ERR_TUTOR_NOT_VERIFIED)".

    Claim: a REQUESTED session for tutor T; admin suspends T; confirm
    by T returns ERR_TUTOR_NOT_VERIFIED — Session and Tutor state
    are coupled at the confirm boundary.

    # difficulty: cross_entity_state_dependency/session_confirm_requires_tutor_verified
    """
    tutor, _student, session = setup_basic_booking_scenario()
    api.suspend_tutor(tutor["id"], admin_headers)
    res = api.confirm_session(
        session["id"], make_tutor_headers(tutor["id"]),
    )
    validate_error(res, "ERR_TUTOR_NOT_VERIFIED")


# ===========================================================================
# cross_entity_state_dependency — instance 2 (second coverage)
# ===========================================================================
def test_minor_booking_succeeds_after_link_approval(api):
    """PRD §3.3: "Bookings on behalf of a MINOR are always initiated
    by the linked Parent through an ACTIVE ParentChildLink." And:
    PRD §3.3: "The owning parent approves the link, which moves it
    PENDING_PARENT_APPROVAL → ACTIVE".

    Claim: same booking is blocked while link is PENDING_PARENT_APPROVAL
    and succeeds once parent approves the link.

    # difficulty: cross_entity_state_dependency/session_book_requires_parentchildlink_active_for_minor
    """
    tutor, _ = setup_verified_tutor_with_subject()
    parent = create_parent()
    student, link = create_minor_student(parent=parent)
    # Pre-approval: blocked.
    now = server_now_dt()
    payload = book_session_payload(
        tutor_id=tutor["id"], student_id=student["id"],
        subject_code="MATH_ALGEBRA",
        start_at=iso_utc(now + timedelta(hours=2)),
        end_at=iso_utc(now + timedelta(hours=3)),
    )
    blocked = api.book_session(
        payload, make_parent_headers(parent["id"]),
    )
    validate_error(blocked, "ERR_MINOR_REQUIRES_PARENT")
    # Approve link.
    from test_helpers import approve_link
    approve_link(parent=parent, link=link)
    # Re-book — must succeed now.
    later = iso_utc(server_now_dt() + timedelta(hours=4))
    later_end = iso_utc(server_now_dt() + timedelta(hours=5))
    success_payload = book_session_payload(
        tutor_id=tutor["id"], student_id=student["id"],
        subject_code="MATH_ALGEBRA",
        start_at=later, end_at=later_end,
    )
    res2 = api.book_session(
        success_payload, make_parent_headers(parent["id"]),
    )
    body = validate_success(res2, expected_status=201)
    assert body["status"] == "REQUESTED"


# ===========================================================================
# resource_temporal_overlap — instance 1 (second coverage)
# ===========================================================================
def test_three_session_calendar_adjacency_and_overlap(api):
    """PRD §3.5: "two sessions overlap if the open interval of one
    contains any instant of the closed-open interval of the other.
    An overlap is rejected with ERR_SESSION_OVERLAP."

    Claim: among three sessions A=[10:00,11:00), B=[11:00,12:00),
    C=[10:30,11:30) for the same tutor: A and B both confirm
    (adjacency at 11:00 is allowed), C overlaps A and is rejected.

    # difficulty: resource_temporal_overlap/tutor_session_closed_open_interval_overlap
    """
    tutor, _, _ = make_tutor_verified()
    add_approved_subject(tutor=tutor, subject_code="MATH_ALGEBRA")
    tutor = validate_success(
        api.get_tutor(tutor["id"], TEST_USERS["admin_headers"]),
    )
    sa = create_adult_student()
    sb = create_adult_student()
    sc = create_adult_student()
    # Pick a base time at least 2h ahead of now and aligned to whole hours.
    base = server_now_dt() + timedelta(hours=10)
    a = book_session(
        tutor=tutor, student=sa, duration_minutes=60,
        start_at=iso_utc(base),
        end_at=iso_utc(base + timedelta(hours=1)),
    )
    b = book_session(
        tutor=tutor, student=sb, duration_minutes=60,
        start_at=iso_utc(base + timedelta(hours=1)),
        end_at=iso_utc(base + timedelta(hours=2)),
    )
    c = book_session(
        tutor=tutor, student=sc, duration_minutes=60,
        start_at=iso_utc(base + timedelta(minutes=30)),
        end_at=iso_utc(base + timedelta(hours=1, minutes=30)),
    )
    confirm_session(session=a, tutor=tutor)
    b_confirmed = confirm_session(session=b, tutor=tutor)
    assert b_confirmed["status"] == "CONFIRMED"
    res_c = api.confirm_session(
        c["id"], make_tutor_headers(tutor["id"]),
    )
    validate_error(res_c, "ERR_SESSION_OVERLAP")


# ===========================================================================
# resource_temporal_overlap — instance 2 (second coverage)
# ===========================================================================
def test_trial_used_even_after_cancellation(api):
    """PRD §3.4: "the (tutor_id, student_id) pair must have no prior
    Session anywhere in history (active or terminal) with is_trial
    true ... otherwise ERR_TRIAL_ALREADY_USED."

    Claim: a CANCELLED trial Session still counts as having used the
    lifetime trial slot — a second trial for the same pair returns
    ERR_TRIAL_ALREADY_USED even though the prior one is terminal.

    # difficulty: resource_temporal_overlap/trial_uniqueness_lifetime_aggregate_overlap
    """
    tutor, _ = setup_verified_tutor_with_subject()
    student = create_adult_student()
    now = server_now_dt()
    trial = book_session(
        tutor=tutor, student=student, duration_minutes=60,
        is_trial=True,
        start_at=iso_utc(now + timedelta(days=2)),
        end_at=iso_utc(now + timedelta(days=2, hours=1)),
    )
    # Student cancels the trial (>=24h notice → free).
    cancel_session(
        session=trial, actor_headers=make_student_headers(student["id"]),
    )
    # Attempt second trial.
    res = api.book_session(
        book_session_payload(
            tutor_id=tutor["id"], student_id=student["id"],
            subject_code="MATH_ALGEBRA",
            start_at=iso_utc(now + timedelta(days=3)),
            end_at=iso_utc(now + timedelta(days=3, hours=1)),
            is_trial=True,
        ),
        make_student_headers(student["id"]),
    )
    validate_error(res, "ERR_TRIAL_ALREADY_USED")


# ===========================================================================
# compensating_invariant — instance 1 (second coverage)
# ===========================================================================
def test_money_conservation_after_short_delivery_plus_arbitration(api):
    """PRD §2.9: "gross_price_cents equals tutor_payout_cents plus
    final_commission_cents plus refund_to_student_cents." And:
    PRD §3.7 DISPUTED → REFUNDED: "refund_to_student_cents is
    increased by arbitration_refund_cents (adding to any short-delivery
    refund already present)".

    Claim: a session completed short (gross=6000, actual_gross=4500,
    short-delivery refund 1500), then an arbitration REFUND of 1500
    on top, holds the per-session money invariant. Final state:
    refund_to_student=3000, retained=3000, final_commission=600,
    payout=2400 — and 6000 == 2400 + 600 + 3000.

    # difficulty: compensating_invariant/per_session_money_conservation_on_refund_cascade
    """
    tutor, student, completed = setup_completed_session(
        hourly_rate_cents=6000, duration_minutes=60,
        adjusted_minutes=45,
    )
    # After completion:
    assert completed["gross_price_cents"] == 6000
    assert completed["actual_gross_cents"] == 4500
    assert completed["refund_to_student_cents"] == 1500
    assert completed["final_commission_cents"] == 900
    assert completed["tutor_payout_cents"] == 3600
    assert_money_conservation_invariant(completed)
    # Open dispute and drive to arbitration REFUND for 1500.
    d = open_dispute(
        session=completed,
        opener_headers=make_student_headers(student["id"]),
        requested_amount_cents=1500,
    )
    created_dt = parse_iso(d["created_at"])
    advance_clock_to(iso_utc(created_dt + timedelta(days=14, hours=1)))
    d_after = validate_success(
        api.get_dispute(d["id"], make_student_headers(student["id"])),
    )
    assert d_after["status"] == "ARBITRATION"
    arbitrate_dispute(
        dispute=d_after, decision="REFUND", refund_amount_cents=1500,
    )
    refreshed = validate_success(
        api.get_session(
            completed["id"], make_student_headers(student["id"]),
        ),
    )
    assert refreshed["status"] == "REFUNDED"
    assert refreshed["arbitration_refund_cents"] == 1500
    # refund_to_student total = short_delivery 1500 + arbitration 1500.
    assert refreshed["refund_to_student_cents"] == 3000
    # service_revenue_retained = 4500 - 1500 = 3000.
    # final_commission = round(3000 * 0.20) = 600 (tier 0).
    assert refreshed["final_commission_cents"] == 600
    # tutor_payout = 3000 - 600 = 2400.
    assert refreshed["tutor_payout_cents"] == 2400
    assert_money_conservation_invariant(refreshed)


# ===========================================================================
# compensating_invariant — instance 2 (second coverage)
# ===========================================================================
def test_managed_child_count_round_trip(api):
    """PRD §3.3: "The parent row carries a computed managed_child_count
    ... reflecting the number of Student rows whose parent_id equals
    the parent's id, whose account_type is MINOR ...". And:
    PRD §3.3: approve increments managed_child_count by 1; revoke
    decrements managed_child_count by 1.

    Claim: starting with managed_child_count=2 (two ACTIVE links),
    approving a third link drives count to 3; revoking it drives
    count back to 2 — the conserved-quantity invariant is restored
    after the paired actions.

    # difficulty: compensating_invariant/parent_child_count_invariant_on_link_revoke
    """
    parent = create_parent()
    # Build 2 initial ACTIVE links.
    from test_helpers import approve_link, create_minor_student
    for _ in range(2):
        _s, link = create_minor_student(parent=parent)
        approve_link(parent=parent, link=link)
    refreshed_parent = validate_success(
        api.get_parent(parent["id"], make_parent_headers(parent["id"])),
    )
    assert refreshed_parent["managed_child_count"] == 2
    # Add a third pending link and approve.
    _s3, link3 = create_minor_student(parent=parent)
    approve_link(parent=parent, link=link3)
    refreshed_parent_after_approve = validate_success(
        api.get_parent(parent["id"], make_parent_headers(parent["id"])),
    )
    assert refreshed_parent_after_approve["managed_child_count"] == 3
    # Revoke and confirm baseline.
    revoke_link(parent=parent, link=link3)
    refreshed_parent_after_revoke = validate_success(
        api.get_parent(parent["id"], make_parent_headers(parent["id"])),
    )
    assert refreshed_parent_after_revoke["managed_child_count"] == 2
