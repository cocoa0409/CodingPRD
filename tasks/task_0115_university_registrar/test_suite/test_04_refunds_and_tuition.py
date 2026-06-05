"""Refund calculation and tuition reconciliation.

Translates Difficulty queue instances dual_variant_calc (refund),
combinatorial_formula (per-item rounding), boundary_precision_check
(drop-deadline inclusive boundary), and compensating_invariant (net tuition).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_paginated,
    TEST_USERS,
    make_student_headers,
)
from test_helpers import fixtures as fx

REG = TEST_USERS["registrar_headers"]


def test_drop_full_vs_withdraw_partial_refund(api):
    """PRD §3.7: "Otherwise, if the current instant is at or before the term's
    `drop_deadline` — an inclusive boundary — the tier is `FULL` and the fraction
    is `refund_full_pct`. Otherwise, if the current instant is at or before the
    term's `withdraw_deadline`, the tier is `PARTIAL` and the fraction is
    `refund_partial_pct`."

    Two students with the same frozen 150000 charge: one drops in the full window
    (refund 150000), the other withdraws in the partial window (refund 75000).

    Design: Difficulty/dual_variant_calc/refund_drop_full_vs_withdraw_partial
    """
    base = fx.setup_registration_open_section(seat_capacity=2,
                                              course_overrides={"credit_hours": 3})
    drop_stu, _ = fx.setup_student_ready(base["term"]["id"], base["program"]["id"])
    wd_stu, _ = fx.setup_student_ready(base["term"]["id"], base["program"]["id"])
    fx.set_clock(fx.CLOCK_REGISTRATION)
    enr_drop = fx.enroll(base["term"]["id"], base["section"]["id"], drop_stu["id"])
    enr_wd = fx.enroll(base["term"]["id"], base["section"]["id"], wd_stu["id"])

    # DROP within full-refund window.
    fx.drop(enr_drop["id"], drop_stu["id"])
    # WITHDRAW after drop_deadline (partial window).
    fx.set_clock("2026-02-20T00:00:00Z")
    fx.withdraw(enr_wd["id"], wd_stu["id"])

    drop_final = validate_success(api.get_enrollment(enr_drop["id"], REG), 200)
    wd_final = validate_success(api.get_enrollment(enr_wd["id"], REG), 200)
    assert drop_final["registration_status"] == "DROPPED"
    assert drop_final["refund_cents"] == 150000
    assert wd_final["registration_status"] == "WITHDRAWN"
    assert wd_final["refund_cents"] == 75000


def test_section_cancel_full_refund_records_tier(api):
    """PRD §3.7: "If the refund was triggered by a section cancellation, the tier
    is `FULL` and the fraction is the term's `refund_full_pct`, regardless of the
    clock."

    A second probe of the dual refund variants: the SECTION_CANCEL branch records
    refund_tier FULL with triggered_by SECTION_CANCEL on the ledger record.

    Design: Difficulty/dual_variant_calc/refund_drop_full_vs_withdraw_partial
    """
    base = fx.setup_one_enrolled_student(credit_hours=3)  # charged 150000
    fx.set_clock("2026-04-01T00:00:00Z")  # past every deadline
    fx.set_section_status(base["section"]["id"], "CANCELLED")
    data, _meta = validate_paginated(api.list_enrollment_refunds(base["enrollment"]["id"], REG))
    assert len(data) == 1
    assert data[0]["refund_tier"] == "FULL"
    assert data[0]["amount_cents"] == 150000
    assert data[0]["triggered_by"] == "SECTION_CANCEL"


def test_refund_rounded_per_item_then_owed(api):
    """PRD §2.7: "Where a refund computation produces a non-integer cent value, it
    is rounded half up to the nearest whole cent."
    PRD §3.9: "It is the sum of the frozen `tuition_charged_cents` over the
    student's enrollments that were ever charged ... minus the sum of the
    `amount_cents` of all that student's refund transactions."

    A 99999-cent charge withdrawn at 0.5 yields round_half_up(49999.5)=50000, so
    owed = 99999 - 50000 = 49999.

    Design: Difficulty/combinatorial_formula/refund_per_item_round_then_sum_order
    """
    base = fx.setup_registration_open_section(
        seat_capacity=5,
        course_overrides={"credit_hours": 3},
        term_overrides={"per_credit_cost_cents": 33333},  # 3 * 33333 = 99999
    )
    stu, _ = fx.setup_student_ready(base["term"]["id"], base["program"]["id"])
    fx.set_clock(fx.CLOCK_REGISTRATION)
    enr = fx.enroll(base["term"]["id"], base["section"]["id"], stu["id"])
    assert enr["tuition_charged_cents"] == 99999

    fx.set_clock("2026-02-20T00:00:00Z")  # partial window
    fx.withdraw(enr["id"], stu["id"])

    enr_final = validate_success(api.get_enrollment(enr["id"], REG), 200)
    assert enr_final["refund_cents"] == 50000  # round_half_up(99999 * 0.5)
    stu_final = validate_success(api.get_student(stu["id"], REG), 200)
    assert stu_final["tuition_owed_cents"] == 49999


def test_refund_amount_rounded_half_up_on_ledger(api):
    """PRD §2.7: "Where a refund computation produces a non-integer cent value, it
    is rounded half up to the nearest whole cent."

    A second probe of the per-item rounding rule, observed on the RefundTransaction
    ledger: a 99999-cent charge at 0.5 yields amount_cents 50000 (round_half_up of
    49999.5), independent of the owed aggregation.

    Design: Difficulty/combinatorial_formula/refund_per_item_round_then_sum_order
    """
    base = fx.setup_registration_open_section(
        seat_capacity=5,
        course_overrides={"credit_hours": 3},
        term_overrides={"per_credit_cost_cents": 33333},
    )
    stu, _ = fx.setup_student_ready(base["term"]["id"], base["program"]["id"])
    fx.set_clock(fx.CLOCK_REGISTRATION)
    enr = fx.enroll(base["term"]["id"], base["section"]["id"], stu["id"])
    fx.set_clock("2026-02-20T00:00:00Z")  # partial window
    fx.withdraw(enr["id"], stu["id"])
    data, _meta = validate_paginated(api.list_enrollment_refunds(enr["id"], REG))
    assert len(data) == 1
    assert data[0]["refund_tier"] == "PARTIAL"
    assert data[0]["amount_cents"] == 50000


def test_drop_deadline_inclusive_full_refund_boundary(api):
    """PRD §3.7: "Otherwise, if the current instant is at or before the term's
    `drop_deadline` — an inclusive boundary — the tier is `FULL` and the fraction
    is `refund_full_pct`."

    A drop at exactly now == drop_deadline is FULL (refund 150000).

    Design: Difficulty/boundary_precision_check/drop_deadline_inclusive_full_refund_boundary
    """
    base = fx.setup_one_enrolled_student(credit_hours=3)  # charged 150000
    fx.set_clock("2026-02-15T00:00:00Z")  # exactly drop_deadline
    fx.drop(base["enrollment"]["id"], base["student"]["id"])
    enr = validate_success(api.get_enrollment(base["enrollment"]["id"], REG), 200)
    assert enr["registration_status"] == "DROPPED"
    assert enr["refund_cents"] == 150000


def test_partial_refund_just_past_drop_deadline(api):
    """PRD §3.7: "Otherwise, if the current instant is at or before the term's
    `withdraw_deadline`, the tier is `PARTIAL` and the fraction is
    `refund_partial_pct`."

    Just past the inclusive boundary, the same charge drops to a PARTIAL refund of
    75000 (distinguishing the inclusive boundary from the partial window).

    Design: Difficulty/boundary_precision_check/drop_deadline_inclusive_full_refund_boundary
    """
    base = fx.setup_one_enrolled_student(credit_hours=3)  # charged 150000
    fx.set_clock("2026-02-20T00:00:00Z")  # after drop_deadline, within withdraw window
    fx.withdraw(base["enrollment"]["id"], base["student"]["id"])
    enr = validate_success(api.get_enrollment(base["enrollment"]["id"], REG), 200)
    assert enr["registration_status"] == "WITHDRAWN"
    assert enr["refund_cents"] == 75000  # round_half_up(150000 * 0.5)


def test_drop_conserves_section_occupancy(api):
    """PRD §3.5: "Whenever a seat is released by an `ENROLLED → DROPPED` or
    `ENROLLED → WITHDRAWN` transition and a seat is now available, the head of that
    section's waitlist is promoted ... This system promotion increments the
    section's `seats_taken` by one, decrements its `waitlist_count` by one".

    Releasing a seat and promoting the waitlist head leaves seats_taken at exactly
    the capacity of 1 (conserved).

    Design: Difficulty/compensating_invariant/drop_conserves_section_occupancy
    """
    base = fx.setup_enrolled_plus_waitlisted(waitlist_capacity=5)
    fx.drop(base["enrollment_a"]["id"], base["student_a"]["id"])
    sec = validate_success(api.get_section(base["section"]["id"], REG), 200)
    assert sec["seats_taken"] == 1, f"occupancy conserved at capacity, got {sec['seats_taken']}"
    enr_b = validate_success(api.get_enrollment(base["enrollment_b"]["id"], REG), 200)
    assert enr_b["registration_status"] == "ENROLLED"


def test_waitlist_drop_conserves_occupancy_no_double_count(api):
    """PRD §3.5: "the head of that section's waitlist is promoted ... This system
    promotion increments the section's `seats_taken` by one, decrements its
    `waitlist_count` by one".

    A second probe of the seat-occupancy conservation invariant: after the
    drop-and-promote, waitlist_count drops back to 0 (the promoted entry left the
    waitlist), so committed seats plus waitlisted entries are not double-counted.

    Design: Difficulty/compensating_invariant/drop_conserves_section_occupancy
    """
    base = fx.setup_enrolled_plus_waitlisted(waitlist_capacity=5)
    fx.drop(base["enrollment_a"]["id"], base["student_a"]["id"])
    sec = validate_success(api.get_section(base["section"]["id"], REG), 200)
    assert sec["seats_taken"] == 1, "occupancy conserved at capacity"
    assert sec["waitlist_count"] == 0, "promoted entry must leave the waitlist"


def test_full_drop_conserves_student_net_tuition(api):
    """PRD §3.9: "a full-refund drop therefore nets to zero for that enrollment".
    PRD §3.9: "It is the sum of the frozen `tuition_charged_cents` over the
    student's enrollments that were ever charged ... minus the sum of the
    `amount_cents` of all that student's refund transactions."

    A full-refund DROP charges 150000 then credits 150000, leaving owed 0.

    Design: Difficulty/compensating_invariant/full_drop_conserves_student_net_tuition
    """
    base = fx.setup_one_enrolled_student(credit_hours=3)  # owed 150000, clock in full window
    fx.drop(base["enrollment"]["id"], base["student"]["id"])
    enr = validate_success(api.get_enrollment(base["enrollment"]["id"], REG), 200)
    assert enr["refund_cents"] == 150000
    stu = validate_success(api.get_student(base["student"]["id"], REG), 200)
    assert stu["tuition_owed_cents"] == 0


def test_partial_withdraw_net_tuition_is_charge_minus_partial(api):
    """PRD §3.9: "a partial withdraw nets to the charge minus the partial refund".
    PRD §3.9: "It is the sum of the frozen `tuition_charged_cents` over the
    student's enrollments that were ever charged ... minus the sum of the
    `amount_cents` of all that student's refund transactions."

    A second probe of net-tuition conservation on a different branch: a partial
    WITHDRAW of a 150000 charge nets to 150000 - 75000 = 75000 owed.

    Design: Difficulty/compensating_invariant/full_drop_conserves_student_net_tuition
    """
    base = fx.setup_one_enrolled_student(credit_hours=3)  # charged 150000
    fx.set_clock("2026-02-20T00:00:00Z")  # partial window
    fx.withdraw(base["enrollment"]["id"], base["student"]["id"])
    stu = validate_success(api.get_student(base["student"]["id"], REG), 200)
    assert stu["tuition_owed_cents"] == 75000
