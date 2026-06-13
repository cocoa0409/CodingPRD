"""Session booking lifecycle: the cyclic OPEN<->FULL loop, parallel reservation
dimensions, waitlist auto-promotion (including the skip-insufficient-credit-head
path), the late-cancel->promotion->refill cascade, session-cancel cascade, and
immediate-consistency booking. Translates difficulty-design non_linear_state_machine
and transitive_cascade (promotion chain) plus the relevant corner instances.
"""
from test_helpers import (
    validate_success, get_success_data,
    setup_network, setup_member_with_membership, create_member,
    create_active_membership, create_published_session, reserve, get_session,
    get_membership, setup_full_session_with_waitlist, set_clock,
    api_client, make_member_headers, TEST_USERS,
)

ADMIN = TEST_USERS["network_admin_headers"]
MANAGER = TEST_USERS["studio_manager_headers"]


def test_session_cycles_open_full_open_full_via_promotion(api):
    """PRD §3.6: "if that increment makes `booked_count` equal `seat_capacity`, the
    session transitions `OPEN → FULL`."
    PRD §3.7: "Whenever a `BOOKED` seat is released on a `FULL` session, the waitlist is
    walked to fill the freed seat(s) before capacity is re-evaluated, transitioning the
    session `FULL → OPEN` only if a seat remains free after promotion."

    Design: Difficulty/non_linear_state_machine/session_cyclic_open_full_open_via_promotion
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(template_overrides={"credit_cost": 5, "late_cancel_window_hours": 12},
                        plan_overrides={"price_cents": 8000, "grant_credits": 20, "validity_days": 60})
    m1, sub1 = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], email="m1@x.com", full_name="M One")
    m2, sub2 = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], email="m2@x.com", full_name="M Two")

    session = create_published_session(
        net["studio"]["id"], net["room"]["id"], net["instructor"]["id"], net["template"]["id"],
        starts_at="2026-06-10T10:00:00Z", seat_capacity=1, waitlist_capacity=5)
    r1 = reserve(session["id"], m1["id"], sub1["id"])  # books -> FULL
    assert get_session(session["id"])["status"] == "FULL"
    r2 = reserve(session["id"], m2["id"], sub2["id"])  # waitlisted

    # m1 cancels -> seat frees -> r2 auto-promoted -> single seat refilled -> FULL again.
    validate_success(api.cancel_reservation(r1["id"], make_member_headers(m1["id"])), 200)
    r2_after = validate_success(api.get_reservation(r2["id"], ADMIN), 200)
    assert r2_after["booking_status"] == "BOOKED", "head-of-line waitlister must be promoted"
    assert r2_after["credits_charged"] == 5
    assert get_session(session["id"])["status"] == "FULL", "promotion re-filled the single seat"
    assert get_membership(sub2["id"], m2["id"])["credit_balance"] == 15


def test_session_flips_open_to_full_when_only_seat_taken(api):
    """PRD §3.6: "if that increment makes `booked_count` equal `seat_capacity`, the
    session transitions `OPEN → FULL`."

    Design: Difficulty/non_linear_state_machine/session_cyclic_open_full_open_via_promotion
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(template_overrides={"credit_cost": 5, "late_cancel_window_hours": 12},
                        plan_overrides={"price_cents": 8000, "grant_credits": 20, "validity_days": 60})
    m1, sub1 = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], active=True)
    session = create_published_session(
        net["studio"]["id"], net["room"]["id"], net["instructor"]["id"], net["template"]["id"],
        starts_at="2026-06-10T10:00:00Z", seat_capacity=1, waitlist_capacity=5)
    assert session["status"] == "OPEN"

    reserve(session["id"], m1["id"], sub1["id"])  # booked_count -> 1 == seat_capacity
    after = get_session(session["id"])
    assert after["status"] == "FULL", "single seat taken must flip OPEN -> FULL"
    assert after["booked_count"] == 1


def test_check_in_advances_attendance_axis_only(api):
    """PRD §3.7: "A successful check-in sets `attendance_status` to `CHECKED_IN` while
    leaving `booking_status` at `BOOKED` — the seat stays held; only the attendance
    dimension advances."
    PRD §3.7: "Check-in is permitted only when the reservation's `booking_status` is
    `BOOKED` and its `attendance_status` is `PENDING`, the session is `OPEN` or `FULL`,
    and the current clock is at or after the session's `starts_at` minus 2 hours".

    Design: Difficulty/non_linear_state_machine/reservation_parallel_booking_and_attendance_axes
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(template_overrides={"credit_cost": 5, "late_cancel_window_hours": 12},
                        plan_overrides={"price_cents": 8000, "grant_credits": 20, "validity_days": 60})
    m1, sub1 = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], active=True)
    session = create_published_session(
        net["studio"]["id"], net["room"]["id"], net["instructor"]["id"], net["template"]["id"],
        starts_at="2026-06-10T10:00:00Z", seat_capacity=5)
    r1 = reserve(session["id"], m1["id"], sub1["id"])

    set_clock("2026-06-10T08:30:00Z")  # >= starts_at - 2h (08:00)
    checked = validate_success(api.check_in_reservation(r1["id"], MANAGER), 200)
    assert checked["attendance_status"] == "CHECKED_IN"
    assert checked["booking_status"] == "BOOKED", "seat axis must be unchanged by check-in"
    assert get_session(session["id"])["booked_count"] == 1


def test_fresh_booking_starts_pending_with_booked_seat(api):
    """PRD §3.6: "it carries two independent status dimensions. The first dimension,
    `booking_status`, tracks seat holding through `WAITLISTED`, `BOOKED`, and the
    terminal `RELEASED`. The second dimension, `attendance_status`, tracks the outcome
    through `PENDING`, `CHECKED_IN`, `NO_SHOW`, `CANCELLED`, and `LATE_CANCELLED`, and
    evolves independently of the first."

    Design: Difficulty/non_linear_state_machine/reservation_parallel_booking_and_attendance_axes
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(template_overrides={"credit_cost": 5, "late_cancel_window_hours": 12},
                        plan_overrides={"price_cents": 8000, "grant_credits": 20, "validity_days": 60})
    m1, sub1 = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], active=True)
    session = create_published_session(
        net["studio"]["id"], net["room"]["id"], net["instructor"]["id"], net["template"]["id"],
        starts_at="2026-06-10T10:00:00Z", seat_capacity=5)
    r1 = reserve(session["id"], m1["id"], sub1["id"])

    # On a free seat the two axes start independently: BOOKED on the seat axis,
    # PENDING on the attendance axis.
    fresh = validate_success(api.get_reservation(r1["id"], ADMIN), 200)
    assert fresh["booking_status"] == "BOOKED"
    assert fresh["attendance_status"] == "PENDING"


def test_cancel_promotion_chain_depth3(api):
    """PRD §3.7: "the freed seat triggers the auto-promotion path below."
    PRD §3.7: "if that member's funding membership is `ACTIVE` and its `credit_balance`
    is at least the template's `credit_cost`, the reservation is promoted — its
    `credit_cost` is debited through a `RESERVE_DEBIT` line, `credits_charged` is set,
    `booking_status` becomes `BOOKED`, `promoted_at` is stamped to the current clock,
    and `booked_count` is incremented."

    Design: Difficulty/transitive_cascade/late_cancel_promotion_chain_depth3
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(template_overrides={"credit_cost": 5, "late_cancel_window_hours": 12},
                        plan_overrides={"price_cents": 8000, "grant_credits": 20, "validity_days": 60})
    m1, sub1 = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], email="m1@x.com", full_name="M One")
    m2, sub2 = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], email="m2@x.com", full_name="M Two")
    session_id, r1, waitlist = setup_full_session_with_waitlist(
        net, m1, sub1, [(m2, sub2)], starts_at="2026-06-20T10:00:00Z", waitlist_capacity=5)
    r2 = waitlist[0]

    # Clock 2026-06-01 is well before the 06-20 session: an early cancel that frees the
    # seat and chains the promotion (the cascade is identical regardless of timing).
    validate_success(api.cancel_reservation(r1["id"], make_member_headers(m1["id"])), 200)

    r1_after = validate_success(api.get_reservation(r1["id"], ADMIN), 200)
    assert r1_after["booking_status"] == "RELEASED"  # hop 1
    r2_after = validate_success(api.get_reservation(r2["id"], ADMIN), 200)
    assert r2_after["booking_status"] == "BOOKED" and r2_after["credits_charged"] == 5  # hop 2
    assert get_membership(sub2["id"], m2["id"])["credit_balance"] == 15  # hop 2 wallet
    assert get_session(session_id)["status"] == "FULL"  # hop 3 re-fill


def test_cancel_promotion_chain_stamps_promoted_at(api):
    """PRD §3.7: "the reservation is promoted — its `credit_cost` is debited through a
    `RESERVE_DEBIT` line, `credits_charged` is set, `booking_status` becomes `BOOKED`,
    `promoted_at` is stamped to the current clock, and `booked_count` is incremented."

    Design: Difficulty/transitive_cascade/late_cancel_promotion_chain_depth3
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(template_overrides={"credit_cost": 5, "late_cancel_window_hours": 12},
                        plan_overrides={"price_cents": 8000, "grant_credits": 20, "validity_days": 60})
    m1, sub1 = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], email="m1@x.com", full_name="M One")
    m2, sub2 = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], email="m2@x.com", full_name="M Two")
    session_id, r1, waitlist = setup_full_session_with_waitlist(
        net, m1, sub1, [(m2, sub2)], starts_at="2026-06-20T10:00:00Z", waitlist_capacity=5)
    r2 = waitlist[0]
    assert r2["promoted_at"] in (None, "", "null") or r2.get("promoted_at") is None, (
        "a still-waitlisted reservation must not yet carry promoted_at")

    validate_success(api.cancel_reservation(r1["id"], make_member_headers(m1["id"])), 200)

    r2_after = validate_success(api.get_reservation(r2["id"], ADMIN), 200)
    assert r2_after["booking_status"] == "BOOKED"
    assert r2_after["promoted_at"], "promotion must stamp promoted_at"
    assert get_session(session_id)["booked_count"] == 1, "booked_count incremented by the promotion"


def test_waitlist_promotion_skips_insufficient_credit_head(api):
    """PRD §3.7: "If instead the head cannot pay — an inactive membership or insufficient
    credit — that reservation is released (`booking_status` `RELEASED`,
    `attendance_status` `CANCELLED`), `waitlisted_count` is decremented, and promotion
    proceeds to the next in line."

    Design: Corner/calculations/waitlist_promotion_skips_insufficient_credit_head
    """
    set_clock("2026-06-25T00:00:00Z")
    net = setup_network(template_overrides={"credit_cost": 5, "late_cancel_window_hours": 12},
                        plan_overrides={"name": "20 Pack", "price_cents": 8000,
                                        "grant_credits": 20, "validity_days": 60})
    pack4 = get_success_data(api.create_package_plan(
        {"name": "4 Pack", "kind": "CREDIT_PACK", "price_cents": 4000, "grant_credits": 4, "validity_days": 60}, ADMIN))
    m1, sub1 = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], email="m1@x.com", full_name="M One")
    m2 = create_member(net["studio"]["id"], email="m2@x.com", full_name="M Two")
    sub2 = create_active_membership(m2["id"], pack4["id"])  # balance 4 < cost 5
    m3, sub3 = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], email="m3@x.com", full_name="M Three")

    # Single-seat session FULL via m1; waitlist order r2 (balance 4) then r3 (balance 20).
    session_id, r1, waitlist = setup_full_session_with_waitlist(
        net, m1, sub1, [(m2, sub2), (m3, sub3)], starts_at="2026-07-01T10:00:00Z", waitlist_capacity=5)
    r2, r3 = waitlist[0], waitlist[1]

    validate_success(api.cancel_reservation(r1["id"], make_member_headers(m1["id"])), 200)

    r2_after = validate_success(api.get_reservation(r2["id"], ADMIN), 200)
    assert r2_after["booking_status"] == "RELEASED", "head with balance 4 < cost 5 must be skipped/released"
    r3_after = validate_success(api.get_reservation(r3["id"], ADMIN), 200)
    assert r3_after["booking_status"] == "BOOKED" and r3_after["credits_charged"] == 5
    assert get_membership(sub3["id"], m3["id"])["credit_balance"] == 15
    assert get_membership(sub2["id"], m2["id"])["credit_balance"] == 4, "skipped member never charged"
    assert get_session(session_id)["status"] == "FULL"


def test_session_cancel_cascade_refunds_and_no_fees(api):
    """PRD §3.7: "From `OPEN` or `FULL` the cancellation cascades: every reservation
    whose `booking_status` is `BOOKED` or `WAITLISTED` is released — `booking_status` to
    `RELEASED`, `attendance_status` to `CANCELLED` — and for each released `BOOKED`
    reservation the `credits_charged` are refunded through a `CANCEL_REFUND` line.
    Because the studio initiated the cancellation, no late fee is charged regardless of
    timing. The session's `booked_count` and `waitlisted_count` are recomputed to zero."

    Design: Corner/state_machines/session_cancel_cascade_refunds_and_no_fees
    """
    set_clock("2026-06-19T00:00:00Z")
    net = setup_network(template_overrides={"credit_cost": 5, "late_cancel_window_hours": 12},
                        plan_overrides={"price_cents": 8000, "grant_credits": 20, "validity_days": 60})
    m1, sub1 = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], email="m1@x.com", full_name="M One")
    m2, sub2 = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], email="m2@x.com", full_name="M Two")
    session_id, r1, waitlist = setup_full_session_with_waitlist(
        net, m1, sub1, [(m2, sub2)], starts_at="2026-06-20T10:00:00Z", waitlist_capacity=5)
    r2 = waitlist[0]
    set_clock("2026-06-20T01:00:00Z")  # inside the 12h late window of the 10:00 session

    validate_success(api.cancel_session(session_id, MANAGER), 200)

    sess = get_session(session_id)
    assert sess["status"] == "CANCELLED" and sess["booked_count"] == 0 and sess["waitlisted_count"] == 0
    r1_after = validate_success(api.get_reservation(r1["id"], ADMIN), 200)
    assert r1_after["booking_status"] == "RELEASED" and r1_after["attendance_status"] == "CANCELLED"
    assert r1_after["late_fee_cents"] == 0
    r2_after = validate_success(api.get_reservation(r2["id"], ADMIN), 200)
    assert r2_after["booking_status"] == "RELEASED" and r2_after["attendance_status"] == "CANCELLED"
    assert get_membership(sub1["id"], m1["id"])["credit_balance"] == 20, "BOOKED seat credit refunded"
    fees = get_success_data(api.list_fees(ADMIN, params={"reservation_id": r1["id"]}))
    rows = fees if isinstance(fees, list) else fees.get("data", fees)
    assert len(rows) == 0, "studio-initiated cancel must assess no fee"


def test_immediate_book_debit_visible_in_same_response(api):
    """PRD §2.5: "When that happens, every consequence resolves synchronously inside the
    triggering request, and each mutated entity independently refreshes its own
    `updated_at` and increments its own `version`."
    PRD §3.6: "it is created already `BOOKED` (skipping `WAITLISTED`), the template's
    `credit_cost` is debited from the membership through a `RESERVE_DEBIT` wallet line
    carrying a negative `delta`, `credits_charged` is set to that cost, and `booked_count`
    is incremented".

    Design: Corner/consistency_model/immediate_book_debit_visible_in_same_response
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(template_overrides={"credit_cost": 5, "late_cancel_window_hours": 12},
                        plan_overrides={"price_cents": 8000, "grant_credits": 20, "validity_days": 60})
    m1, sub1 = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], active=True)
    session = create_published_session(
        net["studio"]["id"], net["room"]["id"], net["instructor"]["id"], net["template"]["id"],
        starts_at="2026-06-20T10:00:00Z", seat_capacity=5)
    version = get_session(session["id"])["version"]

    res = validate_success(api.create_reservation(
        session["id"], {"membership_id": sub1["id"], "expected_session_version": version},
        make_member_headers(m1["id"])), 201)
    assert res["booking_status"] == "BOOKED" and res["credits_charged"] == 5
    assert get_membership(sub1["id"], m1["id"])["credit_balance"] == 15
