"""Enrollment parallel status axes, transitive cancellation cascades, badge-award
cascade to member, session completion settlement, and within-24h forfeit.

Covers difficulty rules non_linear_state_machine (parallel dimensions),
transitive_cascade (depth-3 session cancel, depth-2 badge award) plus corner
state-machine instances for completion and the within-24h forfeit path.
"""
import pytest
from test_helpers import (
    get_success_data,
    create_badge,
    setup_catalogue, create_guardian, credit_wallet, create_member,
    create_open_session, enroll_drop_in, current_session_version, set_clock,
    award_badge,
    make_guardian_headers, TEST_USERS,
    api_client,
)

ADMIN = TEST_USERS["center_admin_headers"]
INSTRUCTOR = TEST_USERS["instructor_headers"]


# ─── non_linear_state_machine / enrollment_parallel_attendance_and_billing_dimensions ─
def test_checkin_advances_attendance_only(api):
    """PRD §3.5: "These axes move independently; for instance, a check-in changes only
    the attendance axis and leaves the billing axis untouched."

    Design: Difficulty/non_linear_state_machine/enrollment_parallel_attendance_and_billing_dimensions
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=4000)
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])
    session, _ = create_open_session(center["id"], program["id"], assigned_instructor_count=5)
    enrollment = enroll_drop_in(guardian["id"], session["id"], member["id"])
    set_clock("2026-05-01T16:30:00Z")  # past starts_at 2026-05-01T16:00:00Z
    checked = get_success_data(api.check_in_enrollment(enrollment["id"], INSTRUCTOR))
    assert checked["attendance_status"] == "CHECKED_IN"


def test_checkin_leaves_billing_charged(api):
    """PRD §3.5: "Check-in changes only `attendance_status` and leaves `billing_status`
    unchanged, and it increments the enrollment's `version` by one."

    Design: Difficulty/non_linear_state_machine/enrollment_parallel_attendance_and_billing_dimensions
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=4000)
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])
    session, _ = create_open_session(center["id"], program["id"], assigned_instructor_count=5)
    enrollment = enroll_drop_in(guardian["id"], session["id"], member["id"])
    assert enrollment["billing_status"] == "CHARGED"
    set_clock("2026-05-01T16:30:00Z")
    checked = get_success_data(api.check_in_enrollment(enrollment["id"], INSTRUCTOR))
    assert checked["billing_status"] == "CHARGED"


# ─── transitive_cascade / session_cancel_cascade_to_enrollment_to_guardian_wallet_depth3 ─
def test_session_cancel_cascades_enrollment_to_cancelled_refunded(api):
    """PRD §3.4: "the session moving to `CANCELLED` drives every non-terminal enrollment
    on it — those whose attendance is `RESERVED` or `CHECKED_IN` — to a `CANCELLED`
    attendance state; each such enrollment then settles its billing as `REFUNDED`"

    Design: Difficulty/transitive_cascade/session_cancel_cascade_to_enrollment_to_guardian_wallet_depth3
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=4000)
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])
    session, _ = create_open_session(center["id"], program["id"], assigned_instructor_count=5)
    enrollment = enroll_drop_in(guardian["id"], session["id"], member["id"])
    cancelled_session = get_success_data(api.cancel_session(session["id"], ADMIN))
    assert cancelled_session["status"] == "CANCELLED"
    enroll_after = get_success_data(api.get_enrollment(enrollment["id"], ADMIN))
    assert enroll_after["attendance_status"] == "CANCELLED"
    assert enroll_after["billing_status"] == "REFUNDED"


def test_session_cancel_credits_guardian_wallet_depth3(api):
    """PRD §3.4: "for a drop-in enrollment the guardian's `wallet_credit_cents` is
    increased by the sum of that enrollment's `price_cents` and `wallet_applied_cents`
    (restoring both the cash paid and the wallet credit originally consumed, so money is
    conserved)"

    Design: Difficulty/transitive_cascade/session_cancel_cascade_to_enrollment_to_guardian_wallet_depth3
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=4000)
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])
    session, _ = create_open_session(center["id"], program["id"], assigned_instructor_count=5)
    enroll_drop_in(guardian["id"], session["id"], member["id"])  # price 4000, wallet 0
    api.cancel_session(session["id"], ADMIN)
    guardian_after = get_success_data(api.get_guardian(guardian["id"], ADMIN))
    assert guardian_after["wallet_credit_cents"] == 4000


# ─── transitive_cascade / badge_award_cascade_to_member_active_badge_count_depth2 ─
def test_badge_award_recomputes_member_badge_count(api):
    """PRD §3.7: "Creating an award recomputes the member's `active_badge_count` — the
    cascade runs from the new award to the member's count, which may in turn unblock a
    promotion — and increments the member's `version` by one."

    Design: Difficulty/transitive_cascade/badge_award_cascade_to_member_active_badge_count_depth2
    """
    center, program, belt1 = setup_catalogue(drop_in_fee_cents=4000, required_badge_count=2)
    badge = create_badge(belt1["id"], name="Loops")
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])
    session, _ = create_open_session(center["id"], program["id"], assigned_instructor_count=5)
    enrollment = enroll_drop_in(guardian["id"], session["id"], member["id"])
    award_badge(enrollment["id"], badge["id"])
    member_after = get_success_data(api.get_member(member["id"], ADMIN))
    assert member_after["active_badge_count"] == 1


def test_badge_award_status_active(api):
    """PRD §3.7: "A badge award's `status` begins at `ACTIVE`; only active awards count
    toward `active_badge_count` and toward promotion."

    Design: Difficulty/transitive_cascade/badge_award_cascade_to_member_active_badge_count_depth2
    """
    center, program, belt1 = setup_catalogue(drop_in_fee_cents=4000, required_badge_count=2)
    badge = create_badge(belt1["id"], name="Loops")
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])
    session, _ = create_open_session(center["id"], program["id"], assigned_instructor_count=5)
    enrollment = enroll_drop_in(guardian["id"], session["id"], member["id"])
    award = award_badge(enrollment["id"], badge["id"])
    assert award["status"] == "ACTIVE"


# ─── Corner / state_machines / complete_session_marks_reserved_no_show_and_checked_in_attended ─
def test_complete_session_settles_attended_and_no_show(api):
    """PRD §3.4: "On completion, every enrollment whose attendance is `CHECKED_IN`
    transitions to `ATTENDED`, and every enrollment still `RESERVED` transitions to
    `NO_SHOW` with no refund — and if such an enrollment's billing was `CHARGED`, its
    billing becomes `FORFEITED`"

    Design: Corner/state_machines/complete_session_marks_reserved_no_show_and_checked_in_attended
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=4000)
    guardian = create_guardian()
    member_a = create_member(guardian["id"], program["id"])
    member_b = create_member(guardian["id"], program["id"])
    session, _ = create_open_session(center["id"], program["id"], assigned_instructor_count=5)
    e_a = enroll_drop_in(guardian["id"], session["id"], member_a["id"], sibling_index=1)
    e_b = enroll_drop_in(guardian["id"], session["id"], member_b["id"], sibling_index=2)
    set_clock("2026-05-01T16:30:00Z")
    api.check_in_enrollment(e_a["id"], INSTRUCTOR)
    set_clock("2026-05-01T18:30:00Z")  # past ends_at 2026-05-01T18:00:00Z
    api.complete_session(session["id"], ADMIN)
    after_a = get_success_data(api.get_enrollment(e_a["id"], ADMIN))
    after_b = get_success_data(api.get_enrollment(e_b["id"], ADMIN))
    assert after_a["attendance_status"] == "ATTENDED"
    assert after_b["attendance_status"] == "NO_SHOW"
    assert after_b["billing_status"] == "FORFEITED"


# ─── Corner / state_machines / cancel_enrollment_within_24h_forfeits_no_refund ─
def test_cancel_within_24h_forfeits_no_refund(api):
    """PRD §3.5: "For a drop-in enrollment cancelled when the time until `starts_at` is
    less than 24 hours, the cancel is non-refundable: `billing_status` becomes `FORFEITED`
    and no wallet credit is returned, neither `price_cents` nor `wallet_applied_cents`."

    Design: Corner/state_machines/cancel_enrollment_within_24h_forfeits_no_refund
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=4000)
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])
    session, _ = create_open_session(center["id"], program["id"], assigned_instructor_count=5)
    enrollment = enroll_drop_in(guardian["id"], session["id"], member["id"])
    set_clock("2026-05-01T10:00:00Z")  # 6h before start 2026-05-01T16:00:00Z, < 24h
    cancelled = get_success_data(
        api.cancel_enrollment(enrollment["id"], make_guardian_headers(guardian["id"]))
    )
    assert cancelled["attendance_status"] == "CANCELLED"
    assert cancelled["billing_status"] == "FORFEITED"
    guardian_after = get_success_data(api.get_guardian(guardian["id"], ADMIN))
    assert guardian_after["wallet_credit_cents"] == 0
