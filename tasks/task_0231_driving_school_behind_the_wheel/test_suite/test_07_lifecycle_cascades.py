"""Non-linear certificate cycles and transitive cascades from refund / no-show /
cancel, plus the road-hour conservation invariant.

Difficulty queue A: rules `non_linear_state_machine`, `transitive_cascade`,
`compensating_invariant` (road-hour ledger).
"""
from test_helpers import (
    validate_success, validate_paginated,
    TEST_USERS,
    make_student_headers,
    set_clock,
    setup_issued_certificate, setup_road_scheduling_context,
    schedule_lesson,
    assert_road_hours_conserved, api_client,
)

ADMIN = TEST_USERS["admin_headers"]


# ===========================================================================
# non_linear_state_machine / certificate_submitted_rejected_resubmit_cycle
# ===========================================================================
def test_certificate_resubmitted_after_rejection_returns_to_submitted(api):
    """PRD §3.10: "A rejected certificate is not dead: it can be resubmitted,
    moving from `REJECTED` back to `SUBMITTED` and re-minting its
    `dmv_reference`, which reopens the `SUBMITTED → REJECTED → SUBMITTED`
    negotiation loop with the DMV."

    Design: Difficulty/non_linear_state_machine/certificate_submitted_rejected_resubmit_cycle
    """
    ctx = setup_issued_certificate()
    cert_id = ctx["certificate"]["id"]
    validate_success(api.submit_certificate(cert_id, ADMIN))
    validate_success(api.dmv_callback(cert_id, {"outcome": "REJECTED"}, ADMIN))
    resubmitted = validate_success(api.submit_certificate(cert_id, ADMIN))
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["dmv_reference"] is not None


def test_certificate_rejected_state_reached_before_resubmit(api):
    """PRD §3.10: "a `REJECTED` outcome moves it from `SUBMITTED` to
    `REJECTED`. Submission is legal from `ISSUED` and from `REJECTED`, and
    recording a decision is legal only from `SUBMITTED`."

    Design: Difficulty/non_linear_state_machine/certificate_submitted_rejected_resubmit_cycle
    """
    ctx = setup_issued_certificate()
    cert_id = ctx["certificate"]["id"]
    validate_success(api.submit_certificate(cert_id, ADMIN))
    rejected = validate_success(api.dmv_callback(cert_id, {"outcome": "REJECTED"}, ADMIN))
    assert rejected["status"] == "REJECTED"


# NOTE: Difficulty/non_linear_state_machine/student_road_ready_reverts_to_permitted_cycle
# is SKIPPED. Its recipe triggers POST /lessons/{id}/cancel on an already
# COMPLETED road lesson and asserts CANCELLED + a ROAD_READY -> PERMITTED
# regression. But PRD §3.9 states the student cancel "is legal only from
# `SCHEDULED`" and "only ever touches a `SCHEDULED` lesson", and exposes no
# endpoint that reverses a COMPLETED lesson. A faithful PRD-only implementer
# would reject the cancel with ERR_INVALID_STATE and the regression would never
# fire, so the asserted outcome is not uniquely derivable from PRD prose
# (Core rule, unique derivability fails).


# ===========================================================================
# transitive_cascade / refund_cascade_depth3_lesson_ledger_wallet
# ===========================================================================
def test_refund_cascade_cancels_lesson_releases_hours_credits_wallet(api):
    """PRD §3.5: "it first cascade-cancels every still-`SCHEDULED` lesson under
    the enrollment, each road lesson releasing its hours back from
    `scheduled_road_hours`. It then computes the refund amount ..., records the
    chosen `refund_method` and the resulting `refunded_cents` on the enrollment,
    and posts a wallet credit ... which raises the student's
    `wallet_balance_cents`."
    PRD §3.5: "if that is at most 3 days the refund percentage is one hundred
    percent".

    Design: Difficulty/transitive_cascade/refund_cascade_depth3_lesson_ledger_wallet
    """
    set_clock("2026-06-01T00:00:00.000Z")
    ctx = setup_road_scheduling_context(package_overrides={
        "price_cents": 90000, "enrollment_fee_cents": 5000,
        "included_classroom_hours": 30, "included_online_hours": 8,
        "included_road_hours": 6, "bundle_discount_cents": 5000,
    })
    stu, enr = ctx["student"], ctx["enrollment"]
    inst, veh = ctx["instructor"], ctx["vehicle"]
    lesson = schedule_lesson(stu["id"], enr["id"], "ROAD",
                            "2026-06-20T09:00:00.000Z", "2026-06-20T11:00:00.000Z",
                            instructor_id=inst["id"], vehicle_id=veh["id"])
    set_clock("2026-06-02T00:00:00.000Z")  # 1 day elapsed -> SCHEDULE_TIER 100%
    refunded = validate_success(
        api.refund_enrollment(enr["id"],
                              {"refund_method": "SCHEDULE_TIER",
                               "refund_destination": "WALLET"}, ADMIN)
    )
    # refundable base 85000 - 5000 == 80000, * 100% == 80000.
    assert refunded["refunded_cents"] == 80000
    lesson_after = validate_success(api.get_lesson(lesson["id"], ADMIN))
    assert lesson_after["status"] == "CANCELLED"
    student = validate_success(api.get_student(stu["id"], ADMIN))
    assert student["scheduled_road_hours"] == 0
    assert student["wallet_balance_cents"] == 80000


def test_refund_cascade_single_credit_entry(api):
    """PRD §2.9: "Money never appears or disappears outside this ledger: refunds
    enter as positive credits."
    PRD §3.5: "posts a wallet credit — a wallet entry against the student for a
    positive `amount_cents` equal to `refunded_cents`, with `reason`
    `REFUND_CREDIT`."

    Design: Difficulty/transitive_cascade/refund_cascade_depth3_lesson_ledger_wallet
    """
    set_clock("2026-06-01T00:00:00.000Z")
    ctx = setup_road_scheduling_context(package_overrides={
        "price_cents": 90000, "enrollment_fee_cents": 5000,
        "included_classroom_hours": 30, "included_online_hours": 8,
        "included_road_hours": 6, "bundle_discount_cents": 5000,
    })
    stu, enr = ctx["student"], ctx["enrollment"]
    schedule_lesson(stu["id"], enr["id"], "ROAD",
                   "2026-06-20T09:00:00.000Z", "2026-06-20T11:00:00.000Z",
                   instructor_id=ctx["instructor"]["id"], vehicle_id=ctx["vehicle"]["id"])
    set_clock("2026-06-02T00:00:00.000Z")
    validate_success(
        api.refund_enrollment(enr["id"],
                              {"refund_method": "SCHEDULE_TIER",
                               "refund_destination": "WALLET"}, ADMIN)
    )
    entries, _ = validate_paginated(
        api.list_wallet_entries(ADMIN, params={"student_id": stu["id"]})
    )
    assert len(entries) == 1
    assert entries[0]["amount_cents"] == 80000
    assert entries[0]["reason"] == "REFUND_CREDIT"


# ===========================================================================
# transitive_cascade / no_show_cascade_depth2_strike_wallet
# ===========================================================================
def _student_with_one_forgiven_strike():
    """PERMITTED student who has already taken one forgiven no-show (strike 1,
    fee 0) and has a second SCHEDULED road lesson whose start has passed.
    Returns (student, enrollment, second_lesson)."""
    set_clock("2026-06-01T00:00:00.000Z")
    ctx = setup_road_scheduling_context(package_overrides={
        "price_cents": 60000, "enrollment_fee_cents": 0,
        "included_classroom_hours": 0, "included_online_hours": 0,
        "included_road_hours": 10, "bundle_discount_cents": 0,
    })
    stu, enr = ctx["student"], ctx["enrollment"]
    inst, veh = ctx["instructor"], ctx["vehicle"]
    l1 = schedule_lesson(stu["id"], enr["id"], "ROAD",
                        "2026-06-05T09:00:00.000Z", "2026-06-05T11:00:00.000Z",
                        instructor_id=inst["id"], vehicle_id=veh["id"])
    l2 = schedule_lesson(stu["id"], enr["id"], "ROAD",
                        "2026-06-06T09:00:00.000Z", "2026-06-06T11:00:00.000Z",
                        instructor_id=inst["id"], vehicle_id=veh["id"])
    # First no-show (forgiven, strike 1, fee 0).
    set_clock("2026-06-05T09:30:00.000Z")
    validate_success(api_client.no_show_lesson(l1["id"], ADMIN))
    # Advance past the second lesson's start so it too can be no-showed.
    set_clock("2026-06-06T09:30:00.000Z")
    return stu, enr, l2


def test_second_no_show_charges_base_fee_and_debits_wallet(api):
    """PRD §3.8: "the second strike charges the base no-show fee of 4000 cents
    (forty dollars) ... Whenever the charged fee is above zero, the system posts
    a wallet debit: a wallet entry against the student for a negative
    `amount_cents` equal to that fee, with `reason` `NO_SHOW_DEBIT`, which lowers
    the student's `wallet_balance_cents`."

    Design: Difficulty/transitive_cascade/no_show_cascade_depth2_strike_wallet
    """
    stu, enr, l2 = _student_with_one_forgiven_strike()
    lesson_after = validate_success(api.no_show_lesson(l2["id"], ADMIN))
    assert lesson_after["status"] == "NO_SHOW"
    strikes, _ = validate_paginated(
        api.list_no_show_strikes(ADMIN, params={"student_id": stu["id"],
                                                "lesson_id": l2["id"]})
    )
    assert len(strikes) == 1
    assert strikes[0]["strike_index"] == 2
    assert strikes[0]["fee_charged_cents"] == 4000
    student = validate_success(api.get_student(stu["id"], ADMIN))
    assert student["wallet_balance_cents"] == -4000


def test_second_no_show_only_one_debit_entry(api):
    """PRD §3.8: "the first strike is forgiven and charges nothing; the second
    strike charges the base no-show fee of 4000 cents (forty dollars)".
    PRD §2.9: "no-show fees enter as negative debits ... the student's
    `wallet_balance_cents` is re-derived from the entries."

    Design: Difficulty/transitive_cascade/no_show_cascade_depth2_strike_wallet
    """
    stu, enr, l2 = _student_with_one_forgiven_strike()
    validate_success(api.no_show_lesson(l2["id"], ADMIN))
    entries, _ = validate_paginated(
        api.list_wallet_entries(ADMIN, params={"student_id": stu["id"],
                                               "reason": "NO_SHOW_DEBIT"})
    )
    # Only the second strike charged (the first was forgiven, posting nothing).
    assert len(entries) == 1
    assert entries[0]["amount_cents"] == -4000


# ===========================================================================
# compensating_invariant / road_hour_ledger_conserved_on_lesson_cancel
# ===========================================================================
def test_road_hour_ledger_conserved_on_lesson_cancel(api):
    """PRD §3.9: "A cancelled road lesson releases its `duration_hours` back out
    of `scheduled_road_hours`, returning those hours to the enrollment."
    PRD §3.6: "For a road lesson, that `duration_hours` is added to the
    student's `scheduled_road_hours` at creation."

    Design: Difficulty/compensating_invariant/road_hour_ledger_conserved_on_lesson_cancel
    """
    set_clock("2026-06-01T00:00:00.000Z")
    ctx = setup_road_scheduling_context(package_overrides={
        "price_cents": 60000, "enrollment_fee_cents": 0,
        "included_classroom_hours": 0, "included_online_hours": 0,
        "included_road_hours": 6, "bundle_discount_cents": 0,
    })
    stu, enr = ctx["student"], ctx["enrollment"]
    lesson = schedule_lesson(stu["id"], enr["id"], "ROAD",
                            "2026-06-20T09:00:00.000Z", "2026-06-20T11:00:00.000Z",
                            instructor_id=ctx["instructor"]["id"],
                            vehicle_id=ctx["vehicle"]["id"])
    before = validate_success(api.get_student(stu["id"], ADMIN))
    assert before["scheduled_road_hours"] == 2
    # Clock is 2026-06-01, the lesson starts 2026-06-20 — far outside any
    # cancellation cutoff window, so the student cancel is permitted.
    cancelled = validate_success(
        api.cancel_lesson(lesson["id"], make_student_headers(stu["id"]))
    )
    assert cancelled["status"] == "CANCELLED"
    after = validate_success(api.get_student(stu["id"], ADMIN))
    assert after["scheduled_road_hours"] == 0
    assert after["completed_road_hours"] == 0
    # completed 0 + scheduled 0 + available 6 == included 6.
    assert_road_hours_conserved(after["completed_road_hours"],
                                after["scheduled_road_hours"], 6, 6)


def test_road_hour_cancel_does_not_change_completed(api):
    """PRD §3.9: "the student cancel path itself only ever touches a `SCHEDULED`
    lesson."
    PRD §3.9: "A cancelled road lesson releases its `duration_hours` back out of
    `scheduled_road_hours`."

    Design: Difficulty/compensating_invariant/road_hour_ledger_conserved_on_lesson_cancel
    """
    set_clock("2026-06-01T00:00:00.000Z")
    ctx = setup_road_scheduling_context(package_overrides={
        "price_cents": 60000, "enrollment_fee_cents": 0,
        "included_classroom_hours": 0, "included_online_hours": 0,
        "included_road_hours": 6, "bundle_discount_cents": 0,
    })
    stu, enr = ctx["student"], ctx["enrollment"]
    lesson = schedule_lesson(stu["id"], enr["id"], "ROAD",
                            "2026-06-20T09:00:00.000Z", "2026-06-20T11:00:00.000Z",
                            instructor_id=ctx["instructor"]["id"],
                            vehicle_id=ctx["vehicle"]["id"])
    validate_success(api.cancel_lesson(lesson["id"], make_student_headers(stu["id"])))
    after = validate_success(api.get_student(stu["id"], ADMIN))
    assert after["completed_road_hours"] == 0
