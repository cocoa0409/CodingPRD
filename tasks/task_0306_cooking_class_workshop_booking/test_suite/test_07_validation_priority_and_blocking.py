"""Validation precedence conflicts and member-block gating.

Queue A: priority_pair_validation_conflict (state beats seat-capacity;
member-block beats private-buyout).
"""
from test_helpers import (
    validate_success,
    validate_error,
    create_member,
    create_open_session,
    create_booking,
    confirm_booking,
    create_confirmed_booking,
    setup_blocked_member,
    create_published_template,
    create_session,
    add_ingredient_line,
    set_clock,
    get_session_version,
    make_instructor_headers,
    make_member_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["studio_admin_headers"]


def test_state_check_beats_seat_capacity_on_reconfirm(api):
    """PRD §2.9: "Only after those pass does the system evaluate state validity for
    transition endpoints (ERR_INVALID_STATE), then the optimistic-concurrency
    version check ... and finally the domain-specific business rules described
    throughout §3. Within a single operation, this ordering means a state error
    surfaces before a stale-version error, and a stale-version error surfaces
    before a seat-count or other business error."

    A re-confirm of an already-CONFIRMED booking on a now-FULL planned_seats=1
    session fails the state check first: ERR_INVALID_STATE (409), not
    ERR_INSUFFICIENT_SEATS.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_seat_capacity_on_confirm
    """
    _instr, _tmpl, session = create_open_session(
        template_overrides={
            "skill_level": "BEGINNER", "base_price_cents": 5000, "default_capacity": 1,
            "station_fixed_cost_cents": 1000,
        },
        session_overrides={
            "planned_seats": 1, "station_id": "ST-PRI1",
            "start_at": "2026-09-10T14:00:00Z", "end_at": "2026-09-10T16:00:00Z",
        },
        ingredient_overrides={"name": "salt", "qty_per_seat": 0.01, "unit_cost_cents": 10},
    )
    member = create_member()
    booking = create_booking(session["id"], member["id"], 1)
    confirm_booking(booking["id"], session["id"], member["id"])  # now CONFIRMED, session FULL
    # Re-confirm the already-CONFIRMED booking with a fresh version.
    sv = get_session_version(session["id"])
    res = api.confirm_booking(booking["id"], sv, make_member_headers(member["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_state_beats_seat_capacity_on_cancelled_booking_confirm(api):
    """PRD §2.9: "Within a single operation, this ordering means a state error
    surfaces before a stale-version error, and a stale-version error surfaces
    before a seat-count or other business error."
    PRD §3.5: "A confirm is permitted only when the booking is PENDING".

    A second witness on the {state (p6) vs seat-capacity (p21)} pairing: a member's
    own booking that was CANCELLED, on a session now FULL, fails the state check
    first (ERR_INVALID_STATE), never reaching the seat-count path.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_seat_capacity_on_confirm
    """
    set_clock("2026-07-01T00:00:00Z")
    _instr, _tmpl, session = create_open_session(
        template_overrides={
            "skill_level": "BEGINNER", "base_price_cents": 5000, "default_capacity": 1,
            "station_fixed_cost_cents": 1000,
        },
        session_overrides={
            "planned_seats": 1, "station_id": "ST-PRI1B",
            "start_at": "2026-09-11T14:00:00Z", "end_at": "2026-09-11T16:00:00Z",
        },
        ingredient_overrides={"name": "salt", "qty_per_seat": 0.01, "unit_cost_cents": 10},
    )
    mem_a = create_member()
    mem_b = create_member()
    # Member A takes and cancels the only seat (booking A -> CANCELLED).
    bk_a = create_booking(session["id"], mem_a["id"], 1)
    confirm_booking(bk_a["id"], session["id"], mem_a["id"])
    validate_success(api.cancel_booking(bk_a["id"], make_member_headers(mem_a["id"])), 200)
    # Member B fills the only seat so the session is FULL again.
    create_confirmed_booking(session["id"], mem_b["id"], 1)
    # Re-confirming A's CANCELLED booking on a FULL session: state error first.
    sv = get_session_version(session["id"])
    res = api.confirm_booking(bk_a["id"], sv, make_member_headers(mem_a["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_member_block_beats_private_buyout_constraint(api):
    """PRD §3.5: "A confirm is permitted only when the booking is PENDING, the
    session is OPEN, the member's booking_status is GOOD_STANDING, the seat block
    fits ... A BLOCKED member attempting to confirm is rejected with
    ERR_MEMBER_BLOCKED."
    PRD §2.9: "then the optimistic-concurrency version check ... and finally the
    domain-specific business rules".

    A BLOCKED member (reliability 25 < 40 from 3 settled no-shows) confirming a
    valid 1-seat PRIVATE full-buyout booking is rejected ERR_MEMBER_BLOCKED (403).

    Design: Difficulty/priority_pair_validation_conflict/member_blocked_beats_private_buyout_constraint
    """
    instr, member = setup_blocked_member(num_no_shows=3)
    # Confirm the member really is BLOCKED.
    member_state = validate_success(api.get_member(member["id"], make_member_headers(member["id"])), 200)
    assert member_state["booking_status"] == "BLOCKED"
    assert member_state["reliability_score"] == 25

    # A valid PRIVATE full-buyout booking (planned_seats=1, 1 seat requested).
    tmpl = create_published_template(
        skill_level="BEGINNER", base_price_cents=1000, default_capacity=1,
        station_fixed_cost_cents=100,
    )
    session = create_session(
        tmpl["id"], instr["id"], station_id="ST-PRIV-BLK", event_type="PRIVATE",
        start_at="2026-09-15T14:00:00Z", end_at="2026-09-15T16:00:00Z",
        planned_seats=1, private_event_fee_cents=40000,
    )
    add_ingredient_line(session["id"], instr["id"], name="y", qty_per_seat=1, unit_cost_cents=1)
    validate_success(api.open_session(session["id"], make_instructor_headers(instr["id"])), 200)
    booking = create_booking(session["id"], member["id"], 1)  # valid full buyout
    sv = get_session_version(session["id"])
    res = api.confirm_booking(booking["id"], sv, make_member_headers(member["id"]))
    validate_error(res, "ERR_MEMBER_BLOCKED", expected_status=403)


def test_member_block_after_three_settled_no_shows(api):
    """PRD §3.2: "a member whose reliability score is below 40 is placed in
    BLOCKED, and a member whose score is 40 or above sits in GOOD_STANDING."
    PRD §3.2: "subtracting a penalty of 25 for each settled no-show".

    A second witness on the block gate's precondition: three settled NO_SHOW
    strikes drive reliability to 25 (100 - 3*25), below the 40 threshold, so
    booking_status is BLOCKED.

    Design: Difficulty/priority_pair_validation_conflict/member_blocked_beats_private_buyout_constraint
    """
    _instr, member = setup_blocked_member(num_no_shows=3)
    state = validate_success(api.get_member(member["id"], make_member_headers(member["id"])), 200)
    assert state["reliability_score"] == 25
    assert state["booking_status"] == "BLOCKED"
