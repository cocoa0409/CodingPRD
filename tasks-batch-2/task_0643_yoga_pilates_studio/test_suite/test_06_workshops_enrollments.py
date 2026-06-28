"""Workshops and enrollments: seat-occupancy conservation across confirm/withdraw/auto-promote,
workshop terminal-state lockdown, and the enrollment-confirm OCC guard.

Translates difficulty instance `seat_conservation_confirm_then_withdraw_promotes` and corner
instances from sections `state_machines` and `cross_cutting_complexity_layers`.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS, make_member_headers,
    set_clock, create_room, create_teacher, create_member,
    create_workshop, create_published_workshop, current_workshop_version,
    apply_to_workshop, confirm_enrollment,
)

MGR = TEST_USERS["studio_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty: seat_conservation_confirm_then_withdraw_promotes
# ---------------------------------------------------------------------------
def _setup_full_workshop_with_waitlister():
    """Workshop seat_capacity 1 (deposit 2000, price 8000), published OPEN. M1 CONFIRMED (fills
    the seat -> FULL); M2 WAITLISTED. Returns (workshop, m1, m2, en1, en2)."""
    set_clock("2026-02-01T00:00:00Z")
    room = create_room(name="Mat A", room_type="MAT", station_capacity=10)
    teacher = create_teacher(full_name="Tia", certifications=["VINYASA"])
    m1 = create_member(email="s1@x.com", full_name="S1")
    m2 = create_member(email="s2@x.com", full_name="S2")
    workshop = create_published_workshop(room["id"], teacher["id"], kind="TEACHER_TRAINING",
                                         start_utc="2026-03-01T09:00:00Z",
                                         end_utc="2026-03-05T17:00:00Z",
                                         seat_capacity=1, deposit_cents=2000, price_cents=8000)
    en1 = apply_to_workshop(m1["id"], workshop["id"])
    confirm_enrollment(m1["id"], en1["id"], current_workshop_version(workshop["id"]))  # -> FULL
    en2 = apply_to_workshop(m2["id"], workshop["id"])
    confirm_enrollment(m2["id"], en2["id"], current_workshop_version(workshop["id"]))  # -> WAITLISTED
    return workshop, m1, m2, en1, en2


def test_confirmed_withdraw_forfeits_deposit_and_promotes_waitlister(api):
    """PRD §3.9: "Withdrawing a `CONFIRMED` enrollment moves it to `WITHDRAWN`, does **not** refund
    the captured deposit (a member-initiated withdrawal forfeits it) and sets `balance_due_cents`
    to 0; the workshop's `confirmed_seat_count` drops by one, and the system auto-promotes the
    earliest-created `WAITLISTED` enrollment to `CONFIRMED`, capturing that enrollment's deposit
    and recomputing its `balance_due_cents`."

    Design: Difficulty/compensating_invariant/seat_conservation_confirm_then_withdraw_promotes
    """
    workshop, m1, m2, en1, en2 = _setup_full_workshop_with_waitlister()
    withdrawn = validate_success(api.withdraw_enrollment(en1["id"], make_member_headers(m1["id"])), 200)
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["deposit_paid_cents"] == 2000, "deposit forfeited, not refunded"
    promoted = validate_success(api.get_enrollment(en2["id"], MGR), 200)
    assert promoted["status"] == "CONFIRMED", "waitlisted enrollment auto-promoted"


def test_seat_count_conserved_after_withdraw_and_promote(api):
    """PRD §3.9: "when `confirmed_seat_count` reaches `seat_capacity` the workshop moves from
    `OPEN` to `FULL`, after which a newly confirmed applicant is routed to the waitlist"

    Design: Difficulty/compensating_invariant/seat_conservation_confirm_then_withdraw_promotes
    """
    workshop, m1, m2, en1, en2 = _setup_full_workshop_with_waitlister()
    api.withdraw_enrollment(en1["id"], make_member_headers(m1["id"]))
    data = validate_success(api.get_workshop(workshop["id"], MGR), 200)
    assert data["confirmed_seat_count"] == 1, "withdraw (-1) + promote (+1) -> back to capacity"


# ---------------------------------------------------------------------------
# Corner: workshop terminal lockdown + enrollment-confirm OCC
# ---------------------------------------------------------------------------
def test_cancelled_workshop_terminal_lockdown(api):
    """PRD §3.9: "A manager may cancel a `DRAFT`, `OPEN`, or `FULL` workshop, moving it to
    `CANCELLED`. `CLOSED` and `CANCELLED` are terminal."
    PRD §3.9: "Publishing a workshop moves it from `DRAFT` to `OPEN` and accepts enrollments.
    Publication requires the workshop to be `DRAFT`"

    Design: Corner/state_machines/cancelled_workshop_terminal_lockdown
    """
    room = create_room(name="Mat A", room_type="MAT", station_capacity=10)
    teacher = create_teacher(full_name="Tia", certifications=["VINYASA"])
    workshop = create_workshop(room["id"], teacher["id"], kind="WORKSHOP",
                               start_utc="2026-03-01T09:00:00Z", end_utc="2026-03-01T12:00:00Z",
                               seat_capacity=8, deposit_cents=2000, price_cents=8000)
    api.cancel_workshop(workshop["id"], MGR)  # -> CANCELLED (terminal)
    resp = api.publish_workshop(workshop["id"], MGR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_occ_stale_version_on_enrollment_confirm(api):
    """PRD §2.7: "If the workshop's `version` has advanced since then — for example because
    another applicant confirmed the final seat and moved the workshop from `OPEN` to `FULL` — the
    confirm is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_enrollment_confirm
    """
    set_clock("2026-02-01T00:00:00Z")
    room = create_room(name="Mat A", room_type="MAT", station_capacity=10)
    teacher = create_teacher(full_name="Tia", certifications=["VINYASA"])
    m1 = create_member(email="o1@x.com", full_name="O1")
    m2 = create_member(email="o2@x.com", full_name="O2")
    workshop = create_published_workshop(room["id"], teacher["id"], kind="WORKSHOP",
                                         start_utc="2026-03-01T09:00:00Z",
                                         end_utc="2026-03-01T12:00:00Z",
                                         seat_capacity=2, deposit_cents=2000, price_cents=8000)
    stale_version = workshop["version"]
    en1 = apply_to_workshop(m1["id"], workshop["id"])
    en2 = apply_to_workshop(m2["id"], workshop["id"])
    # M1 confirm bumps workshop.version; m2 still holds the stale (pre-confirm) version.
    confirm_enrollment(m1["id"], en1["id"], stale_version)
    resp = api.confirm_enrollment(
        en2["id"], {"expected_workshop_version": stale_version}, make_member_headers(m2["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)
