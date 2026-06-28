"""Membership lifecycle: prorated cycle credit, ACTIVE<->PAUSED cyclic loop,
seat conservation on membership cancel, and the PAUSED-skip filter on the sweep.

Covers difficulty rules dual_variant_calc (membership branch),
non_linear_state_machine (membership loop), compensating_invariant (seat count),
plus corner calculation instance membership_credit_skips_paused_membership.
"""
import pytest
from test_helpers import (
    get_success_data,
    create_membership_payload, create_clock_payload,
    setup_catalogue, create_guardian, create_member, create_active_membership,
    create_open_session, enroll_membership,
    make_guardian_headers, TEST_USERS,
    api_client,
)

ADMIN = TEST_USERS["center_admin_headers"]


# ─── dual_variant_calc / membership_cycle_credit_prorated_vs_flat_on_membership ─
def _setup_membership_with_used(monthly_fee_cents, included, used_count):
    """Create an ACTIVE membership and consume `used_count` membership seats via
    enrollments across distinct WEEKLY sessions. Returns (guardian, member, membership)."""
    center, program, _ = setup_catalogue(drop_in_fee_cents=5000)
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])
    membership = create_active_membership(
        guardian["id"], member["id"],
        monthly_fee_cents=monthly_fee_cents, included_sessions_per_cycle=included,
    )
    base_day = 1
    for _ in range(used_count):
        starts = f"2026-05-{base_day:02d}T16:00:00Z"
        ends = f"2026-05-{base_day:02d}T18:00:00Z"
        session, _ = create_open_session(center["id"], program["id"], format="WEEKLY",
                                         week_count=1, starts_at=starts, ends_at=ends,
                                         assigned_instructor_count=5)
        enroll_membership(guardian["id"], session["id"], member["id"])
        base_day += 1
    return guardian, member, membership


def test_membership_cycle_credit_is_prorated(api):
    """PRD §3.3: "The credit is the number of unused sessions multiplied by the
    per-session value, rounded half up to whole cents once after the multiplication.
    This prorated credit — proportional to the unused sessions only — is authoritative;
    the system does not refund the entire monthly fee whenever any session is unused."

    Design: Difficulty/dual_variant_calc/membership_cycle_credit_prorated_vs_flat_on_membership
    """
    guardian, member, membership = _setup_membership_with_used(
        monthly_fee_cents=12000, included=10, used_count=4
    )
    api.advance_cycle({"member_id": member["id"]}, ADMIN)
    # unused = 10 - 4 = 6; per_session = 12000/10 = 1200; credit = round(6*1200) = 7200.
    guardian_after = get_success_data(api.get_guardian(guardian["id"], ADMIN))
    assert guardian_after["wallet_credit_cents"] == 7200


def test_membership_cycle_advance_resets_usage_and_bumps_index(api):
    """PRD §3.3: "The computed credit is added to the member's guardian's
    `wallet_credit_cents`, after which `sessions_used_this_cycle` is reset to 0 and
    `cycle_index` is incremented by one."

    Design: Difficulty/dual_variant_calc/membership_cycle_credit_prorated_vs_flat_on_membership
    """
    guardian, member, membership = _setup_membership_with_used(
        monthly_fee_cents=12000, included=10, used_count=4
    )
    api.advance_cycle({"member_id": member["id"]}, ADMIN)
    membership_after = get_success_data(api.get_membership(membership["id"], ADMIN))
    assert membership_after["sessions_used_this_cycle"] == 0
    assert membership_after["cycle_index"] == 1


# ─── non_linear_state_machine / membership_active_paused_cycle_loop ─
def test_membership_active_paused_cycle_returns_to_paused(api):
    """PRD §3.3: "The `ACTIVE → PAUSED → ACTIVE` cycle may repeat any number of times."

    Design: Difficulty/non_linear_state_machine/membership_active_paused_cycle_loop
    """
    center, program, _ = setup_catalogue()
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])
    membership = create_active_membership(guardian["id"], member["id"],
                                          monthly_fee_cents=8000, included_sessions_per_cycle=8)
    g = make_guardian_headers(guardian["id"])
    get_success_data(api.pause_membership(membership["id"], g))
    get_success_data(api.resume_membership(membership["id"], g))
    final = get_success_data(api.pause_membership(membership["id"], g))
    assert final["status"] == "PAUSED"


def test_membership_usage_preserved_across_pause_resume_cycle(api):
    """PRD §3.3: "the membership resumes covering enrollments with
    `sessions_used_this_cycle` left unchanged across the pause"

    Design: Difficulty/non_linear_state_machine/membership_active_paused_cycle_loop
    """
    center, program, _ = setup_catalogue()
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])
    membership = create_active_membership(guardian["id"], member["id"],
                                          monthly_fee_cents=8000, included_sessions_per_cycle=8)
    g = make_guardian_headers(guardian["id"])
    api.pause_membership(membership["id"], g)
    api.resume_membership(membership["id"], g)
    final = get_success_data(api.pause_membership(membership["id"], g))
    # No membership enrollments consumed in this test => usage stays 0 across the loop.
    assert final["sessions_used_this_cycle"] == 0


# ─── compensating_invariant / membership_consume_then_cancel_conserves_seat_count ─
def test_membership_cancel_returns_seat(api):
    """PRD §3.5: "For a membership enrollment, the cancel sets `billing_status` to
    `REFUNDED` and decrements the covering membership's `sessions_used_this_cycle` by one,
    returning the seat regardless of the window."

    Design: Difficulty/compensating_invariant/membership_consume_then_cancel_conserves_seat_count
    """
    center, program, _ = setup_catalogue()
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])
    membership = create_active_membership(guardian["id"], member["id"],
                                          monthly_fee_cents=8000, included_sessions_per_cycle=8)
    session, _ = create_open_session(center["id"], program["id"], format="WEEKLY",
                                     week_count=1, assigned_instructor_count=5)
    enrollment = enroll_membership(guardian["id"], session["id"], member["id"])
    cancelled = get_success_data(
        api.cancel_enrollment(enrollment["id"], make_guardian_headers(guardian["id"]))
    )
    assert cancelled["billing_status"] == "REFUNDED"
    membership_after = get_success_data(api.get_membership(membership["id"], ADMIN))
    assert membership_after["sessions_used_this_cycle"] == 0


def test_membership_enrollment_cancel_attendance_cancelled(api):
    """PRD §3.5: "From a `RESERVED` attendance state the cancel sets `attendance_status`
    to `CANCELLED`, and the billing outcome depends on coverage and the refund window."

    Design: Difficulty/compensating_invariant/membership_consume_then_cancel_conserves_seat_count
    """
    center, program, _ = setup_catalogue()
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])
    membership = create_active_membership(guardian["id"], member["id"],
                                          monthly_fee_cents=8000, included_sessions_per_cycle=8)
    session, _ = create_open_session(center["id"], program["id"], format="WEEKLY",
                                     week_count=1, assigned_instructor_count=5)
    enrollment = enroll_membership(guardian["id"], session["id"], member["id"])
    cancelled = get_success_data(
        api.cancel_enrollment(enrollment["id"], make_guardian_headers(guardian["id"]))
    )
    assert cancelled["attendance_status"] == "CANCELLED"


# ─── Corner / calculations / membership_credit_skips_paused_membership ─
def test_advance_cycle_skips_paused_membership(api):
    """PRD §3.3: "For each `ACTIVE` membership the sweep computes an unused-session credit;
    memberships that are `PAUSED` or `CANCELLED` are skipped entirely, receiving no credit
    and no reset."

    Design: Corner/calculations/membership_credit_skips_paused_membership
    """
    center, program, _ = setup_catalogue()
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])
    membership = create_active_membership(guardian["id"], member["id"],
                                          monthly_fee_cents=8000, included_sessions_per_cycle=8)
    g = make_guardian_headers(guardian["id"])
    get_success_data(api.pause_membership(membership["id"], g))
    api.advance_cycle({"member_id": member["id"]}, ADMIN)
    guardian_after = get_success_data(api.get_guardian(guardian["id"], ADMIN))
    assert guardian_after["wallet_credit_cents"] == 0
    membership_after = get_success_data(api.get_membership(membership["id"], ADMIN))
    assert membership_after["cycle_index"] == 0
    assert membership_after["status"] == "PAUSED"
