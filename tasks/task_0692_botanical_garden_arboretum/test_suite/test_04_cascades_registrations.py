"""Cascade and cross-entity dependency tests: lapse/cancel cascades, waitlist
promotion chains, the membership-active check-in gate, and session waitlisting.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_visitor_headers,
    set_clock,
    create_garden,
    create_plan,
    create_active_membership,
    create_program_session,
    create_registration,
    create_time_slot,
    setup_household_member_with_slot,
    setup_session_with_enrolled_and_waitlist,
    lapse_membership,
)

STAFF = TEST_USERS["staff_headers"]
VISITOR = TEST_USERS["visitor_headers"]


# =============================================================================
# transitive_cascade — lapse -> withdraw -> promote (depth 3)
# =============================================================================
def test_lapse_withdraws_enrolled_and_promotes_waitlister(api):
    """PRD §2.5: "Every `ENROLLED` future registration owned by the lapsing
    membership is withdrawn to `WITHDRAWN`, which decrements the session's
    `enrolled_count` and, in turn, promotes that session's head waitlister." PRD
    §3.5: "on promotion the registration's status becomes `ENROLLED`, its
    `waitlist_rank` becomes 0, the session's `enrolled_count` increments... and
    tuition is charged at that moment under the same member-discount rule."

    Member m1 ENROLLED (capacity 1, tuition 10000), non-member r2 WAITLISTED rank
    1. Lapsing m1 withdraws reg1, promoting reg2 to ENROLLED with charged 10000;
    enrolled_count stays 1.

    Design: Difficulty/transitive_cascade/tc_lapse_withdraws_registration_promotes_waitlister_depth3
    """
    garden = create_garden(name="Gardenia Court")
    plan = create_plan(garden["id"], tier="INDIVIDUAL", annual_fee_cents=12000)
    membership = create_active_membership(garden["id"], plan["id"], primary_member_name="Hana")
    m_id = membership["id"]
    session = create_program_session(garden["id"], title="Junior Botanists Camp",
                                     starts_at="2026-07-01T09:00:00Z", capacity=1, tuition_cents=10000)
    reg1 = create_registration(garden["id"], session["id"], participant_name="Hana Jr",
                               membership_id=m_id, headers=make_visitor_headers(m_id))
    reg2 = create_registration(garden["id"], session["id"], participant_name="Walt",
                               headers=make_visitor_headers("anon-walt"))
    lapsed = lapse_membership(m_id)
    assert lapsed["status"] == "LAPSED"
    reg1_after = validate_success(api.get_registration(reg1["id"], STAFF))
    reg2_after = validate_success(api.get_registration(reg2["id"], STAFF))
    assert reg1_after["status"] == "WITHDRAWN"
    assert reg2_after["status"] == "ENROLLED"
    assert reg2_after["waitlist_rank"] == 0
    assert reg2_after["charged_cents"] == 10000, f"promoted non-member charged full tuition, got {reg2_after['charged_cents']}"
    session_after = validate_success(api.get_program_session(session["id"], STAFF))
    assert session_after["enrolled_count"] == 1


def test_lapse_cascade_promotion_keeps_enrolled_count_at_capacity(api):
    """PRD §2.5: "Lapsing is not a quiet status flip; it triggers a cascade." PRD
    §3.5: "Withdrawing an `ENROLLED` registration decrements the session's
    `enrolled_count` and then promotes the head of that session's waitlist".

    After the 3-hop chain (lapse -> withdraw enrolled -> promote waitlister), the
    session's enrolled_count is conserved at capacity (1): the seat freed by the
    withdrawal is immediately refilled by the promotion.

    Design: Difficulty/transitive_cascade/tc_lapse_withdraws_registration_promotes_waitlister_depth3
    """
    garden = create_garden(name="Gardenia Court 2")
    plan = create_plan(garden["id"], tier="INDIVIDUAL", annual_fee_cents=12000)
    membership = create_active_membership(garden["id"], plan["id"], primary_member_name="Hana")
    m_id = membership["id"]
    session = create_program_session(garden["id"], title="Junior Botanists Camp",
                                     starts_at="2026-07-01T09:00:00Z", capacity=1, tuition_cents=10000)
    create_registration(garden["id"], session["id"], participant_name="Hana Jr",
                        membership_id=m_id, headers=make_visitor_headers(m_id))
    create_registration(garden["id"], session["id"], participant_name="Walt",
                        headers=make_visitor_headers("anon-walt"))
    lapse_membership(m_id)
    session_after = validate_success(api.get_program_session(session["id"], STAFF))
    assert session_after["enrolled_count"] == 1, "enrolled_count conserved at capacity through the cascade"


# =============================================================================
# transitive_cascade — cancel membership -> cancel reservation -> release slot
# =============================================================================
def test_cancel_membership_cancels_reservation_releases_slot(api):
    """PRD §3.2: "a membership in `PENDING`, `ACTIVE`, or `LAPSED` may be
    cancelled to the terminal `CANCELLED` state; cancellation cascades to cancel
    every `HELD` reservation owned by the membership — releasing each
    reservation's heads from its slot's `held_count`".

    A HELD member reservation (member_heads 2) on a capacity-5 slot is cancelled
    when its membership is cancelled, returning held_count to 0.

    Design: Difficulty/transitive_cascade/tc_cancel_membership_cancels_reservation_releases_slot_depth2
    """
    garden, plan, membership, slot = setup_household_member_with_slot(
        guest_pass_grant_household=4, slot_capacity=5,
        slot_starts="2026-04-03T10:00:00Z", slot_ends="2026-04-03T12:00:00Z",
    )
    m_id = membership["id"]
    h = make_visitor_headers(m_id)
    res = validate_success(api.create_reservation(
        {"garden_id": garden["id"], "time_slot_id": slot["id"], "membership_id": m_id,
         "member_heads": 2, "expected_membership_version": membership["version"]}, h,
    ), expected_status=201)
    cancelled_m = validate_success(api.cancel_membership(m_id, h))
    assert cancelled_m["status"] == "CANCELLED"
    res_after = validate_success(api.get_reservation(res["id"], STAFF))
    assert res_after["status"] == "CANCELLED"
    slot_after = validate_success(api.get_time_slot(slot["id"], STAFF))
    assert slot_after["held_count"] == 0


def test_cancel_membership_zeroes_guest_passes_and_cancels_hold(api):
    """PRD §3.2: "cancellation cascades to cancel every `HELD` reservation owned
    by the membership — releasing each reservation's heads from its slot's
    `held_count` — and sets `guest_passes_remaining` to 0."

    Cancellation sets guest_passes_remaining to 0 (a 2-hop chain from a different
    trigger than lapse) while cancelling the dependent HELD reservation.

    Design: Difficulty/transitive_cascade/tc_cancel_membership_cancels_reservation_releases_slot_depth2
    """
    garden, plan, membership, slot = setup_household_member_with_slot(
        guest_pass_grant_household=4, slot_capacity=5,
        slot_starts="2026-04-03T10:00:00Z", slot_ends="2026-04-03T12:00:00Z",
    )
    m_id = membership["id"]
    h = make_visitor_headers(m_id)
    validate_success(api.create_reservation(
        {"garden_id": garden["id"], "time_slot_id": slot["id"], "membership_id": m_id,
         "member_heads": 2, "expected_membership_version": membership["version"]}, h,
    ), expected_status=201)
    cancelled_m = validate_success(api.cancel_membership(m_id, h))
    assert cancelled_m["guest_passes_remaining"] == 0, "cancellation zeroes guest_passes_remaining"


# =============================================================================
# cross_entity_state_dependency — check-in requires Membership ACTIVE
# =============================================================================
def test_checkin_blocked_when_membership_lapsed(api):
    """PRD §3.3: "if a membership is attached — only when that membership is
    `ACTIVE`, else `ERR_MEMBERSHIP_NOT_ACTIVE`."

    A HELD member reservation on a past-dated slot (so the lapse cascade does not
    cancel it) cannot be checked in once its membership LAPSES — the Reservation
    transition is gated on the linked Membership.status.

    Design: Difficulty/cross_entity_state_dependency/cesd_checkin_requires_membership_active
    """
    garden = create_garden(name="Magnolia Mews", guest_pass_grant_household=4)
    plan = create_plan(garden["id"], tier="HOUSEHOLD", annual_fee_cents=9000, admission_included=True)
    membership = create_active_membership(garden["id"], plan["id"], primary_member_name="Nell")
    m_id = membership["id"]
    h = make_visitor_headers(m_id)
    slot = create_time_slot(garden["id"], "2026-04-06T10:00:00Z", "2026-04-06T12:00:00Z",
                           capacity=5, ga_price_cents=2000)
    res = validate_success(api.create_reservation(
        {"garden_id": garden["id"], "time_slot_id": slot["id"], "membership_id": m_id,
         "member_heads": 1, "expected_membership_version": membership["version"]}, h,
    ), expected_status=201)
    set_clock("2026-04-06T10:30:00Z")  # inside the slot window
    lapsed = lapse_membership(m_id)  # slot already started, so the HELD reservation survives
    assert lapsed["status"] == "LAPSED"
    res_after = validate_success(api.get_reservation(res["id"], STAFF))
    assert res_after["status"] == "HELD", "a started-slot HELD reservation survives the lapse cascade"
    resp = api.check_in_reservation(res["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE.value, expected_status=409)


def test_checkin_succeeds_when_membership_active(api):
    """PRD §3.3: "A `GardenStaff` member checks a reservation in at the gate,
    advancing `HELD` to `CHECKED_IN`... if a membership is attached — only when
    that membership is `ACTIVE`".

    With the membership still ACTIVE and clock inside the window, check-in of a
    member reservation succeeds — the positive side of the cross-entity gate.

    Design: Difficulty/cross_entity_state_dependency/cesd_checkin_requires_membership_active
    """
    garden = create_garden(name="Magnolia Mews OK", guest_pass_grant_household=4)
    plan = create_plan(garden["id"], tier="HOUSEHOLD", annual_fee_cents=9000, admission_included=True)
    membership = create_active_membership(garden["id"], plan["id"], primary_member_name="Nell")
    m_id = membership["id"]
    h = make_visitor_headers(m_id)
    slot = create_time_slot(garden["id"], "2026-04-06T10:00:00Z", "2026-04-06T12:00:00Z",
                           capacity=5, ga_price_cents=2000)
    res = validate_success(api.create_reservation(
        {"garden_id": garden["id"], "time_slot_id": slot["id"], "membership_id": m_id,
         "member_heads": 1, "expected_membership_version": membership["version"]}, h,
    ), expected_status=201)
    set_clock("2026-04-06T10:30:00Z")
    checked = validate_success(api.check_in_reservation(res["id"], STAFF))
    assert checked["status"] == "CHECKED_IN"


# =============================================================================
# cross_entity_state_dependency — promotion requires session capacity
# =============================================================================
def test_withdraw_waitlister_does_not_promote_lower_waitlister(api):
    """PRD §3.5: "Withdrawing a registration that is itself `WAITLISTED` does not
    touch `enrolled_count`; it simply re-ranks the session's remaining waitlisted
    registrations below the withdrawn position, each dropping by one rank."

    Capacity 1: reg1 ENROLLED, reg2 WAITLISTED rank 1, reg3 WAITLISTED rank 2.
    Withdrawing reg2 (a waitlister, not the enrolled) opens NO seat, so reg1
    stays ENROLLED and reg3 is merely re-ranked to 1 (not promoted).

    Design: Difficulty/cross_entity_state_dependency/cesd_promotion_requires_session_capacity
    """
    garden = create_garden(name="Nasturtium Nook")
    session = create_program_session(garden["id"], title="Bonsai Basics",
                                     starts_at="2026-08-01T09:00:00Z", capacity=1, tuition_cents=8000)
    reg1 = create_registration(garden["id"], session["id"], participant_name="P1",
                               headers=make_visitor_headers("anon-p1"))
    reg2 = create_registration(garden["id"], session["id"], participant_name="P2",
                               headers=make_visitor_headers("anon-p2"))
    reg3 = create_registration(garden["id"], session["id"], participant_name="P3",
                               headers=make_visitor_headers("anon-p3"))
    validate_success(api.withdraw_registration(reg2["id"], make_visitor_headers("anon-p2")))
    reg2_after = validate_success(api.get_registration(reg2["id"], STAFF))
    reg1_after = validate_success(api.get_registration(reg1["id"], STAFF))
    reg3_after = validate_success(api.get_registration(reg3["id"], STAFF))
    assert reg2_after["status"] == "WITHDRAWN"
    assert reg1_after["status"] == "ENROLLED"
    assert reg3_after["status"] == "WAITLISTED"
    assert reg3_after["waitlist_rank"] == 1, "reg3 re-ranked to 1, not promoted (no seat opened)"
    session_after = validate_success(api.get_program_session(session["id"], STAFF))
    assert session_after["enrolled_count"] == 1


def test_withdraw_enrolled_promotes_head_waitlister(api):
    """PRD §3.5: "Withdrawing an `ENROLLED` registration decrements the session's
    `enrolled_count` and then promotes the head of that session's waitlist — the
    `WAITLISTED` registration whose `waitlist_rank` is 1 — to `ENROLLED`."

    Capacity 1: reg1 ENROLLED, reg2 WAITLISTED rank 1. Withdrawing reg1 (the
    enrolled) opens a seat, promoting reg2 to ENROLLED — the positive contrast to
    the waitlister-withdrawal case where no seat opened.

    Design: Difficulty/cross_entity_state_dependency/cesd_promotion_requires_session_capacity
    """
    garden, session, enrolled, waitlisted = setup_session_with_enrolled_and_waitlist(
        capacity=1, tuition_cents=8000, num_waitlisted=1,
    )
    reg2 = waitlisted[0]
    validate_success(api.withdraw_registration(enrolled["id"], make_visitor_headers("anon-enr")))
    enrolled_after = validate_success(api.get_registration(enrolled["id"], STAFF))
    reg2_after = validate_success(api.get_registration(reg2["id"], STAFF))
    assert enrolled_after["status"] == "WITHDRAWN"
    assert reg2_after["status"] == "ENROLLED", "withdrawing the enrolled promotes the rank-1 waitlister"
    assert reg2_after["waitlist_rank"] == 0


# =============================================================================
# Corner: errors/state_machines — session closed & overflow waitlist
# =============================================================================
def test_register_against_closed_session_rejected(api):
    """PRD §3.5: "Registration is refused outright with `ERR_SESSION_CLOSED` when
    the session's `status` is `CLOSED`."

    A registration against a CLOSED session is rejected.

    Design: Corner/errors/registration_against_closed_session_returns_session_closed
    """
    garden = create_garden(name="Weigela Wood")
    session = create_program_session(garden["id"], title="Closed Camp",
                                     starts_at="2026-10-01T09:00:00Z", capacity=5, tuition_cents=8000)
    validate_success(api.close_program_session(session["id"], STAFF))
    resp = api.create_registration(
        {"garden_id": garden["id"], "program_session_id": session["id"], "participant_name": "Late"},
        make_visitor_headers("anon-late"),
    )
    validate_error(resp, ApiErrorId.ERR_SESSION_CLOSED.value, expected_status=409)


def test_register_into_full_open_session_waitlists(api):
    """PRD §3.5: "if the session is full, the registration is *not* an error — it
    is placed `WAITLISTED` with a 1-based `waitlist_rank` equal to its position
    at the back of that session's waitlist." PRD §3.5: "A `WAITLISTED`
    registration is charged nothing — `charged_cents` is set only when its status
    becomes `ENROLLED`."

    Capacity 1 with one ENROLLED: a second registration is WAITLISTED rank 1 with
    a 201 (not an error) and charged_cents 0.

    Design: Corner/errors/registration_overflow_waitlists_not_errors
    """
    garden = create_garden(name="Yucca Yard")
    session = create_program_session(garden["id"], title="Tiny Camp",
                                     starts_at="2026-10-02T09:00:00Z", capacity=1, tuition_cents=8000)
    create_registration(garden["id"], session["id"], participant_name="First",
                        headers=make_visitor_headers("anon-f"))
    reg2 = validate_success(api.create_registration(
        {"garden_id": garden["id"], "program_session_id": session["id"], "participant_name": "Second"},
        make_visitor_headers("anon-s"),
    ), expected_status=201)
    assert reg2["status"] == "WAITLISTED"
    assert reg2["waitlist_rank"] == 1
    assert reg2["charged_cents"] == 0
