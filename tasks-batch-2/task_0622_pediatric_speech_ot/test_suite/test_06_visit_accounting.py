"""Visit accounting: reserved vs committed divergence, the pinned booking
evaluation order, divergent terminal side-effects, exhaustion/recovery, and
visit-pool conservation.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    TEST_USERS, make_therapist_headers,
    set_clock, create_child, create_therapist, create_finalized_evaluation,
    create_active_plan, create_authorization, setup_active_care,
    setup_exhausted_authorization, book_appointment, book_appointment_ok,
    complete_appointment, get_authorization, get_appointment,
)

ADMIN = TEST_USERS["clinic_admin_headers"]


# ─── dual_variant_calc / visit_balance_reserved_vs_committed_divergence ──────

def test_complete_commits_and_cancel_releases_diverge(api):
    """PRD §2.6: "the very same visit moves out of `reserved_visits` and into
    `committed_visits`. Across that single move `available_visits` does not change
    at all (one is subtracted from reserved while one is added to committed)." PRD
    §2.6: "an appointment that is ultimately cancelled rather than completed
    releases its hold and leaves the cap untouched."

    Design: Difficulty/dual_variant_calc/visit_balance_reserved_vs_committed_divergence
    """
    ctx = setup_active_care(clock="2026-06-09T12:00:00Z", discipline="SLP", authorized_visits=3)
    appt_complete = book_appointment_ok(ctx, "2026-06-08T09:00:00Z", "2026-06-08T09:45:00Z")
    appt_cancel = book_appointment_ok(ctx, "2026-06-09T09:00:00Z", "2026-06-09T09:45:00Z")
    # reserved=2, available=1 now.
    get_success_data(complete_appointment(appt_complete["id"], ctx["therapist"]["id"]))
    validate_success(api.cancel_appointment(appt_cancel["id"], ADMIN), 200)

    auth = get_authorization(ctx["auth"]["id"])
    assert auth["committed_visits"] == 1, auth
    assert auth["reserved_visits"] == 0, auth
    assert auth["available_visits"] == 2, auth
    assert get_appointment(appt_complete["id"])["status"] == "COMPLETED"
    assert get_appointment(appt_cancel["id"])["status"] == "CANCELLED"


def test_completed_visit_cannot_be_released_only_reserved_can(api):
    """PRD §2.6: "a reserved visit can still be released, but a committed visit
    cannot." PRD §3.6: "the authorization's `reserved_visits` decreases by 1 and
    its `committed_visits` increases by 1, so the reservation converts to a
    commitment and `available_visits` is unchanged by that single move". After a
    completion the committed unit stays committed even though available is
    unchanged across the conversion.

    Design: Difficulty/dual_variant_calc/visit_balance_reserved_vs_committed_divergence
    """
    ctx = setup_active_care(clock="2026-06-09T12:00:00Z", discipline="SLP", authorized_visits=3)
    appt = book_appointment_ok(ctx, "2026-06-08T09:00:00Z", "2026-06-08T09:45:00Z")
    before = get_authorization(ctx["auth"]["id"])
    assert before["reserved_visits"] == 1
    assert before["available_visits"] == 2
    get_success_data(complete_appointment(appt["id"], ctx["therapist"]["id"]))
    after = get_authorization(ctx["auth"]["id"])
    # available unchanged across the convert; the unit is now committed, not reserved.
    assert after["available_visits"] == 2, after
    assert after["committed_visits"] == 1, after
    assert after["reserved_visits"] == 0, after


# ─── combinatorial_formula / visit_balance_eval_order_pinned_dependency ──────

def test_last_visit_books_then_authorization_exhausts(api):
    """PRD §2.6: "A new reservation is permitted only when `available_visits` is
    at least 1 before the reservation is taken." PRD §3.4: "When a reservation
    drives `available_visits` to exactly 0 ... the authorization automatically
    transitions from `ACTIVE` to `EXHAUSTED`." The visit that takes available to 0
    succeeds first and only then flips the authorization.

    Design: Difficulty/combinatorial_formula/visit_balance_eval_order_pinned_dependency
    """
    ctx = setup_active_care(clock="2026-06-05T12:00:00Z", discipline="SLP", authorized_visits=2)
    book_appointment_ok(ctx, "2026-06-08T09:00:00Z", "2026-06-08T09:45:00Z")
    # available=1; this second booking takes it to exactly 0.
    res = book_appointment(ctx, "2026-06-08T10:00:00Z", "2026-06-08T10:45:00Z")
    appt2 = validate_success(res, 201)
    assert appt2["status"] == "SCHEDULED", appt2
    auth = get_authorization(ctx["auth"]["id"])
    assert auth["reserved_visits"] == 2, auth
    assert auth["available_visits"] == 0, auth
    assert auth["status"] == "EXHAUSTED", auth


def test_reservation_at_zero_available_is_rejected_not_negative(api):
    """PRD §2.6: "Booking is rejected when the reservation would drive
    `available_visits` below zero." PRD §3.4: "while `EXHAUSTED` any new
    reservation against it is rejected with `ERR_VISIT_CAP_EXCEEDED`." Once the
    pool is at 0 the next reservation cannot proceed (it would go negative).

    Design: Difficulty/combinatorial_formula/visit_balance_eval_order_pinned_dependency
    """
    ctx = setup_active_care(clock="2026-06-05T12:00:00Z", discipline="SLP", authorized_visits=2)
    book_appointment_ok(ctx, "2026-06-08T09:00:00Z", "2026-06-08T09:45:00Z")
    book_appointment_ok(ctx, "2026-06-08T10:00:00Z", "2026-06-08T10:45:00Z")
    assert get_authorization(ctx["auth"]["id"])["available_visits"] == 0
    res = book_appointment(ctx, "2026-06-08T11:00:00Z", "2026-06-08T11:45:00Z")
    validate_error(res, "ERR_VISIT_CAP_EXCEEDED")


# ─── non_linear_state_machine / appointment_branching_divergent_terminal_effects ─

def test_appointment_three_terminal_branches_diverge(api):
    """PRD §3.6: "On completion ... the authorization's `reserved_visits`
    decreases by 1 and its `committed_visits` increases by 1". PRD §3.6:
    "Cancellation releases the held visit: the authorization's `reserved_visits`
    decreases by 1". PRD §3.6: "a no-show releases the held visit ... and the
    visit is released rather than committed, because the payer is not billed for a
    no-show."

    Design: Difficulty/non_linear_state_machine/appointment_branching_divergent_terminal_side_effects
    """
    ctx = setup_active_care(clock="2026-06-20T12:00:00Z", discipline="OT", authorized_visits=3)
    appt_c = book_appointment_ok(ctx, "2026-06-08T09:00:00Z", "2026-06-08T09:45:00Z")
    appt_x = book_appointment_ok(ctx, "2026-06-08T10:00:00Z", "2026-06-08T10:45:00Z")
    appt_n = book_appointment_ok(ctx, "2026-06-08T11:00:00Z", "2026-06-08T11:45:00Z")

    get_success_data(complete_appointment(appt_c["id"], ctx["therapist"]["id"]))
    validate_success(api.cancel_appointment(appt_x["id"], ADMIN), 200)
    validate_success(api.no_show_appointment(appt_n["id"], ADMIN), 200)

    assert get_appointment(appt_c["id"])["status"] == "COMPLETED"
    assert get_appointment(appt_x["id"])["status"] == "CANCELLED"
    assert get_appointment(appt_n["id"])["status"] == "NO_SHOW"
    auth = get_authorization(ctx["auth"]["id"])
    assert auth["committed_visits"] == 1, auth
    assert auth["reserved_visits"] == 0, auth
    assert auth["available_visits"] == 2, auth


def test_no_show_releases_without_committing(api):
    """PRD §3.6: "a no-show releases the held visit — `reserved_visits` decreases
    by 1, `available_visits` rises ... and the visit is released rather than
    committed, because the payer is not billed for a no-show." A no-show leaves
    committed_visits at 0 while restoring the pool.

    Design: Difficulty/non_linear_state_machine/appointment_branching_divergent_terminal_side_effects
    """
    ctx = setup_active_care(clock="2026-06-20T12:00:00Z", discipline="OT", authorized_visits=3)
    appt = book_appointment_ok(ctx, "2026-06-08T09:00:00Z", "2026-06-08T09:45:00Z")
    assert get_authorization(ctx["auth"]["id"])["reserved_visits"] == 1
    validate_success(api.no_show_appointment(appt["id"], ADMIN), 200)
    auth = get_authorization(ctx["auth"]["id"])
    assert get_appointment(appt["id"])["status"] == "NO_SHOW"
    assert auth["reserved_visits"] == 0, auth
    assert auth["committed_visits"] == 0, auth
    assert auth["available_visits"] == 3, auth


# ─── transitive_cascade / cancel_releases_visit_flips_exhausted_to_active_depth2 ─

def test_cancel_releases_visit_and_reactivates_exhausted(api):
    """PRD §3.6: "Cancellation releases the held visit: the authorization's
    `reserved_visits` decreases by 1, `available_visits` rises, an authorization
    that was `EXHAUSTED` returns to `ACTIVE`".

    Design: Difficulty/transitive_cascade/cancel_releases_visit_flips_exhausted_to_active_depth2
    """
    ctx, appt = setup_exhausted_authorization()
    assert get_authorization(ctx["auth"]["id"])["status"] == "EXHAUSTED"
    validate_success(api.cancel_appointment(appt["id"], ADMIN), 200)
    auth = get_authorization(ctx["auth"]["id"])
    assert get_appointment(appt["id"])["status"] == "CANCELLED"
    assert auth["reserved_visits"] == 0, auth
    assert auth["available_visits"] == 1, auth
    assert auth["status"] == "ACTIVE", auth


def test_exhausted_recovers_to_active_on_release(api):
    """PRD §3.4: "When a later release (a cancellation or a no-show) lifts
    `available_visits` back above 0, the authorization automatically transitions
    from `EXHAUSTED` back to `ACTIVE` and may be reserved against again." A
    no-show release also flips an EXHAUSTED authorization back to ACTIVE.

    Design: Difficulty/transitive_cascade/cancel_releases_visit_flips_exhausted_to_active_depth2
    """
    # Build EXHAUSTED with a past slot so a no-show is permitted.
    ctx = setup_active_care(clock="2026-06-20T12:00:00Z", discipline="SLP", authorized_visits=1)
    appt = book_appointment_ok(ctx, "2026-06-10T09:00:00Z", "2026-06-10T09:45:00Z")
    assert get_authorization(ctx["auth"]["id"])["status"] == "EXHAUSTED"
    validate_success(api.no_show_appointment(appt["id"], ADMIN), 200)
    auth = get_authorization(ctx["auth"]["id"])
    assert auth["available_visits"] == 1, auth
    assert auth["status"] == "ACTIVE", auth


# ─── compensating_invariant / visit_pool_conserved_book_then_cancel ──────────

def test_book_then_cancel_restores_pool(api):
    """PRD §2.6: "an appointment that is ultimately cancelled rather than
    completed releases its hold and leaves the cap untouched." PRD §3.6:
    "Cancellation releases the held visit: the authorization's `reserved_visits`
    decreases by 1, `available_visits` rises".

    Design: Difficulty/compensating_invariant/visit_pool_conserved_book_then_cancel
    """
    ctx = setup_active_care(clock="2026-06-05T12:00:00Z", discipline="OT", authorized_visits=2)
    appt = book_appointment_ok(ctx, "2026-06-10T09:00:00Z", "2026-06-10T09:45:00Z")
    validate_success(api.cancel_appointment(appt["id"], ADMIN), 200)
    auth = get_authorization(ctx["auth"]["id"])
    assert auth["authorized_visits"] == 2, auth
    assert auth["reserved_visits"] == 0, auth
    assert auth["committed_visits"] == 0, auth
    assert auth["available_visits"] == 2, auth


def test_pool_conserved_across_book_cancel_cycle(api):
    """PRD §2.6: "a cancelled or no-show appointment leaves the cap exactly as it
    was before that appointment ever held a visit." PRD §2.6: "`available_visits`
    is `authorized_visits` minus `reserved_visits` minus `committed_visits`."
    After a book→cancel cycle, available equals authorized exactly as at the start.

    Design: Difficulty/compensating_invariant/visit_pool_conserved_book_then_cancel
    """
    ctx = setup_active_care(clock="2026-06-05T12:00:00Z", discipline="OT", authorized_visits=2)
    start = get_authorization(ctx["auth"]["id"])
    assert start["available_visits"] == start["authorized_visits"] == 2
    appt = book_appointment_ok(ctx, "2026-06-10T09:00:00Z", "2026-06-10T09:45:00Z")
    assert get_authorization(ctx["auth"]["id"])["available_visits"] == 1
    validate_success(api.cancel_appointment(appt["id"], ADMIN), 200)
    end = get_authorization(ctx["auth"]["id"])
    assert end["available_visits"] == end["authorized_visits"] == 2, end
