"""The reservation gate sequence: session bookability, member standing, membership
state, duplicate, waitlist capacity, and the credit-balance boundary — including the
two priority-pair conflicts where one gate pre-empts another. Translates
difficulty-design priority_pair_validation_conflict, boundary_precision_check
(credits), cross_entity_state_dependency plus the corner validation instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_network, setup_member_with_membership, create_member,
    create_active_membership, create_published_session, reserve, get_session,
    get_membership, drive_member_to_strikes, setup_full_session_with_waitlist,
    set_clock, get_member, api_client, make_member_headers, TEST_USERS,
)

ADMIN = TEST_USERS["network_admin_headers"]
MANAGER = TEST_USERS["studio_manager_headers"]


def test_not_bookable_state_beats_insufficient_credits(api):
    """PRD §3.6: "a `SCHEDULED`, `CANCELLED`, or `COMPLETED` session is not bookable and
    the attempt is rejected with `ERR_SESSION_NOT_BOOKABLE`."
    PRD §3.6: "The reservation request is gated by a sequence of checks. The session must
    be bookable — in `OPEN` or `FULL`".

    Design: Difficulty/priority_pair_validation_conflict/not_bookable_state_beats_insufficient_credits_fiscal
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(template_overrides={"credit_cost": 5, "late_cancel_window_hours": 12},
                        plan_overrides={"name": "Zero Pack", "price_cents": 0,
                                        "grant_credits": 1, "validity_days": 60})
    # member with an ACTIVE membership of balance 1 (< cost 5)
    m1, sub1 = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], active=True)
    session = create_published_session(
        net["studio"]["id"], net["room"]["id"], net["instructor"]["id"], net["template"]["id"],
        starts_at="2026-06-20T10:00:00Z", seat_capacity=5)
    validate_success(api.cancel_session(session["id"], MANAGER), 200)
    version = get_session(session["id"])["version"]

    res = api.create_reservation(
        session["id"], {"membership_id": sub1["id"], "expected_session_version": version},
        make_member_headers(m1["id"]))
    # State gate fires before the fiscal credit check.
    validate_error(res, "ERR_SESSION_NOT_BOOKABLE")


def test_member_restricted_beats_waitlist_full(api):
    """PRD §3.6: "The member's `standing` must be `GOOD`; a `RESTRICTED` member is
    refused with `ERR_MEMBER_RESTRICTED`. The funding membership must be `ACTIVE`,
    checked before the duplicate, waitlist, and credit checks".
    PRD §3.7: "a `RESTRICTED` member cannot create reservations."

    Design: Difficulty/priority_pair_validation_conflict/member_restricted_safety_beats_waitlist_full_constraint
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(template_overrides={"credit_cost": 5, "late_cancel_window_hours": 12},
                        plan_overrides={"name": "30 Pack", "price_cents": 9000,
                                        "grant_credits": 30, "validity_days": 90})
    m1, sub1 = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], email="m1@x.com", full_name="M One")
    # Drive m1 to RESTRICTED (3 strikes).
    drive_member_to_strikes(net, m1, sub1, 3, base_clock="2026-06-01T00:00:00Z")
    assert get_member(m1["id"])["standing"] == "RESTRICTED"

    # Target session: single-seat (m2 books) + waitlist_capacity 1 (m3 waitlists) -> both full.
    m2, sub2 = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], email="m2@x.com", full_name="M Two")
    m3, sub3 = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], email="m3@x.com", full_name="M Three")
    session_id, _r2, _wl = setup_full_session_with_waitlist(
        net, m2, sub2, [(m3, sub3)], starts_at="2026-06-25T10:00:00Z", waitlist_capacity=1)
    version = get_session(session_id)["version"]

    res = api.create_reservation(
        session_id, {"membership_id": sub1["id"], "expected_session_version": version},
        make_member_headers(m1["id"]))
    # Standing (safety) gate fires before the waitlist-full constraint.
    validate_error(res, "ERR_MEMBER_RESTRICTED")


def test_not_bookable_completed_session_beats_insufficient_credits(api):
    """PRD §3.6: "a `SCHEDULED`, `CANCELLED`, or `COMPLETED` session is not bookable and
    the attempt is rejected with `ERR_SESSION_NOT_BOOKABLE`."
    PRD §3.6: "This immediate-booking path requires that the membership's `credit_balance`
    is at least the template's `credit_cost`; if it is not, the booking is refused with
    `ERR_INSUFFICIENT_CREDITS`."

    Design: Difficulty/priority_pair_validation_conflict/not_bookable_state_beats_insufficient_credits_fiscal
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(template_overrides={"credit_cost": 5, "late_cancel_window_hours": 12},
                        plan_overrides={"name": "Zero Pack", "price_cents": 0,
                                        "grant_credits": 1, "validity_days": 60})
    m1, sub1 = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], active=True)  # balance 1 < 5
    session = create_published_session(
        net["studio"]["id"], net["room"]["id"], net["instructor"]["id"], net["template"]["id"],
        starts_at="2026-06-10T10:00:00Z", seat_capacity=5)
    # Drive the session to terminal COMPLETED via the ops sweep.
    set_clock("2026-06-10T11:30:00Z")
    validate_success(api.run_completion(ADMIN), 200)
    assert get_session(session["id"])["status"] == "COMPLETED"
    version = get_session(session["id"])["version"]

    res = api.create_reservation(
        session["id"], {"membership_id": sub1["id"], "expected_session_version": version},
        make_member_headers(m1["id"]))
    # Not-bookable state still pre-empts the fiscal credit check.
    validate_error(res, "ERR_SESSION_NOT_BOOKABLE")


def test_member_restricted_beats_waitlist_full_two_deep_waitlist(api):
    """PRD §3.6: "The member's `standing` must be `GOOD`; a `RESTRICTED` member is
    refused with `ERR_MEMBER_RESTRICTED`. The funding membership must be `ACTIVE`,
    checked before the duplicate, waitlist, and credit checks".

    Design: Difficulty/priority_pair_validation_conflict/member_restricted_safety_beats_waitlist_full_constraint
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(template_overrides={"credit_cost": 5, "late_cancel_window_hours": 12},
                        plan_overrides={"name": "30 Pack", "price_cents": 9000,
                                        "grant_credits": 30, "validity_days": 90})
    m1, sub1 = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], email="m1@x.com", full_name="M One")
    drive_member_to_strikes(net, m1, sub1, 3, base_clock="2026-06-01T00:00:00Z")
    assert get_member(m1["id"])["standing"] == "RESTRICTED"

    # Distinct full-config: single seat (m2) + waitlist_capacity 2 filled by m3 and m4.
    m2, sub2 = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], email="m2@x.com", full_name="M Two")
    m3, sub3 = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], email="m3@x.com", full_name="M Three")
    m4, sub4 = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], email="m4@x.com", full_name="M Four")
    session_id, _b, _wl = setup_full_session_with_waitlist(
        net, m2, sub2, [(m3, sub3), (m4, sub4)], starts_at="2026-06-25T10:00:00Z", waitlist_capacity=2)
    version = get_session(session_id)["version"]

    res = api.create_reservation(
        session_id, {"membership_id": sub1["id"], "expected_session_version": version},
        make_member_headers(m1["id"]))
    validate_error(res, "ERR_MEMBER_RESTRICTED")


def test_insufficient_credits_below_balance_boundary_rejected(api):
    """PRD §3.6: "This immediate-booking path requires that the membership's
    `credit_balance` is at least the template's `credit_cost`; if it is not, the booking
    is refused with `ERR_INSUFFICIENT_CREDITS`."

    Design: Difficulty/boundary_precision_check/insufficient_credits_at_exact_balance_boundary
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(template_overrides={"credit_cost": 5, "late_cancel_window_hours": 12})
    pack4 = get_success_data(api.create_package_plan(
        {"name": "4 Pack", "kind": "CREDIT_PACK", "price_cents": 4000, "grant_credits": 4, "validity_days": 60}, ADMIN))
    m1 = create_member(net["studio"]["id"], email="m1@x.com", full_name="M One")
    sub1 = create_active_membership(m1["id"], pack4["id"])  # balance 4 < cost 5
    session = create_published_session(
        net["studio"]["id"], net["room"]["id"], net["instructor"]["id"], net["template"]["id"],
        starts_at="2026-06-20T10:00:00Z", seat_capacity=5)
    version = get_session(session["id"])["version"]

    res = api.create_reservation(
        session["id"], {"membership_id": sub1["id"], "expected_session_version": version},
        make_member_headers(m1["id"]))
    validate_error(res, "ERR_INSUFFICIENT_CREDITS")
    assert get_membership(sub1["id"], m1["id"])["credit_balance"] == 4, "no debit on rejected booking"


def test_credits_at_exact_balance_boundary_books(api):
    """PRD §3.6: "This immediate-booking path requires that the membership's
    `credit_balance` is at least the template's `credit_cost`; if it is not, the booking
    is refused with `ERR_INSUFFICIENT_CREDITS`."

    Design: Difficulty/boundary_precision_check/insufficient_credits_at_exact_balance_boundary
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(template_overrides={"credit_cost": 5, "late_cancel_window_hours": 12})
    pack5 = get_success_data(api.create_package_plan(
        {"name": "5 Pack", "kind": "CREDIT_PACK", "price_cents": 5000, "grant_credits": 5, "validity_days": 60}, ADMIN))
    m2 = create_member(net["studio"]["id"], email="m2@x.com", full_name="M Two")
    sub2 = create_active_membership(m2["id"], pack5["id"])  # balance 5 == cost 5
    session = create_published_session(
        net["studio"]["id"], net["room"]["id"], net["instructor"]["id"], net["template"]["id"],
        starts_at="2026-06-20T10:00:00Z", seat_capacity=5)
    version = get_session(session["id"])["version"]

    res = validate_success(api.create_reservation(
        session["id"], {"membership_id": sub2["id"], "expected_session_version": version},
        make_member_headers(m2["id"])), 201)
    assert res["booking_status"] == "BOOKED"
    assert get_membership(sub2["id"], m2["id"])["credit_balance"] == 0, "balance 5 >= cost 5 books and debits"


def test_reservation_blocked_by_scheduled_session(api):
    """PRD §3.6: "a `SCHEDULED`, `CANCELLED`, or `COMPLETED` session is not bookable and
    the attempt is rejected with `ERR_SESSION_NOT_BOOKABLE`."

    Design: Difficulty/cross_entity_state_dependency/reservation_blocked_by_session_state
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(template_overrides={"credit_cost": 5, "late_cancel_window_hours": 12},
                        plan_overrides={"price_cents": 8000, "grant_credits": 20, "validity_days": 60})
    m1, sub1 = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], active=True)
    # Created but NOT published -> SCHEDULED.
    session = get_success_data(api.create_session(
        {"studio_id": net["studio"]["id"], "room_id": net["room"]["id"],
         "instructor_id": net["instructor"]["id"], "template_id": net["template"]["id"],
         "starts_at": "2026-06-20T10:00:00Z", "seat_capacity": 5}, MANAGER))

    res = api.create_reservation(
        session["id"], {"membership_id": sub1["id"], "expected_session_version": session["version"]},
        make_member_headers(m1["id"]))
    validate_error(res, "ERR_SESSION_NOT_BOOKABLE")
    assert get_membership(sub1["id"], m1["id"])["credit_balance"] == 20, "no debit on rejected booking"


def test_reservation_blocked_by_pending_payment_membership(api):
    """PRD §3.6: "The funding membership must be `ACTIVE`, checked before the duplicate,
    waitlist, and credit checks; an inactive membership yields `ERR_MEMBERSHIP_INACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/reservation_blocked_by_membership_state
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(template_overrides={"credit_cost": 5, "late_cancel_window_hours": 12},
                        plan_overrides={"price_cents": 8000, "grant_credits": 20, "validity_days": 60})
    # PENDING_PAYMENT membership (payment never captured).
    m1, sub1 = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], active=False)
    session = create_published_session(
        net["studio"]["id"], net["room"]["id"], net["instructor"]["id"], net["template"]["id"],
        starts_at="2026-06-20T10:00:00Z", seat_capacity=5)
    version = get_session(session["id"])["version"]

    res = api.create_reservation(
        session["id"], {"membership_id": sub1["id"], "expected_session_version": version},
        make_member_headers(m1["id"]))
    validate_error(res, "ERR_MEMBERSHIP_INACTIVE")
    assert get_session(session["id"])["booked_count"] == 0


def test_reservation_blocked_by_cancelled_session(api):
    """PRD §3.6: "a `SCHEDULED`, `CANCELLED`, or `COMPLETED` session is not bookable and
    the attempt is rejected with `ERR_SESSION_NOT_BOOKABLE`."

    Design: Difficulty/cross_entity_state_dependency/reservation_blocked_by_session_state
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(template_overrides={"credit_cost": 5, "late_cancel_window_hours": 12},
                        plan_overrides={"price_cents": 8000, "grant_credits": 20, "validity_days": 60})
    m1, sub1 = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], active=True)
    # Publish then cancel the session (-> terminal CANCELLED). Membership is healthy.
    session = create_published_session(
        net["studio"]["id"], net["room"]["id"], net["instructor"]["id"], net["template"]["id"],
        starts_at="2026-06-20T10:00:00Z", seat_capacity=5)
    validate_success(api.cancel_session(session["id"], MANAGER), 200)
    version = get_session(session["id"])["version"]

    res = api.create_reservation(
        session["id"], {"membership_id": sub1["id"], "expected_session_version": version},
        make_member_headers(m1["id"]))
    validate_error(res, "ERR_SESSION_NOT_BOOKABLE")
    assert get_membership(sub1["id"], m1["id"])["credit_balance"] == 20, "no debit on rejected booking"


def test_reservation_blocked_by_cancelled_membership(api):
    """PRD §3.6: "The funding membership must be `ACTIVE`, checked before the duplicate,
    waitlist, and credit checks; an inactive membership yields `ERR_MEMBERSHIP_INACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/reservation_blocked_by_membership_state
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(template_overrides={"credit_cost": 5, "late_cancel_window_hours": 12},
                        plan_overrides={"price_cents": 8000, "grant_credits": 20, "validity_days": 60})
    m1, sub1 = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], active=True)
    # Cancel the membership -> not ACTIVE -> an inactive membership for reservation.
    validate_success(api.cancel_membership(sub1["id"], make_member_headers(m1["id"])), 200)
    session = create_published_session(
        net["studio"]["id"], net["room"]["id"], net["instructor"]["id"], net["template"]["id"],
        starts_at="2026-06-20T10:00:00Z", seat_capacity=5)
    version = get_session(session["id"])["version"]

    res = api.create_reservation(
        session["id"], {"membership_id": sub1["id"], "expected_session_version": version},
        make_member_headers(m1["id"]))
    validate_error(res, "ERR_MEMBERSHIP_INACTIVE")
    assert get_session(session["id"])["booked_count"] == 0


def test_duplicate_reservation_same_session_rejected(api):
    """PRD §3.6: "The member may not already hold a non-`RELEASED` reservation on the
    same session; a second one is rejected with `ERR_DUPLICATE_RESERVATION`."

    Design: Corner/validations/error_duplicate_reservation_same_session
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(template_overrides={"credit_cost": 5, "late_cancel_window_hours": 12},
                        plan_overrides={"price_cents": 8000, "grant_credits": 20, "validity_days": 60})
    m1, sub1 = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], active=True)
    session = create_published_session(
        net["studio"]["id"], net["room"]["id"], net["instructor"]["id"], net["template"]["id"],
        starts_at="2026-06-20T10:00:00Z", seat_capacity=5)
    reserve(session["id"], m1["id"], sub1["id"])
    version = get_session(session["id"])["version"]

    res = api.create_reservation(
        session["id"], {"membership_id": sub1["id"], "expected_session_version": version},
        make_member_headers(m1["id"]))
    validate_error(res, "ERR_DUPLICATE_RESERVATION")
    assert get_session(session["id"])["booked_count"] == 1, "booked_count unchanged by the duplicate"


def test_waitlist_full_blocks_reservation(api):
    """PRD §3.6: "If instead no free seat exists, the reservation joins the waitlist as
    `WAITLISTED`, but only while `waitlisted_count` is below the session's
    `waitlist_capacity`; once the waitlist is full the attempt is rejected with
    `ERR_WAITLIST_FULL`."

    Design: Corner/validations/error_waitlist_full_blocks_reservation
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(template_overrides={"credit_cost": 5, "late_cancel_window_hours": 12},
                        plan_overrides={"price_cents": 8000, "grant_credits": 20, "validity_days": 60})
    m2, sub2 = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], email="m2@x.com", full_name="M Two")
    m3, sub3 = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], email="m3@x.com", full_name="M Three")
    m4, sub4 = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], email="m4@x.com", full_name="M Four")
    # seat filled by m2, waitlist_capacity 1 filled by m3 -> full.
    session_id, _booked, _wl = setup_full_session_with_waitlist(
        net, m2, sub2, [(m3, sub3)], starts_at="2026-06-20T10:00:00Z", waitlist_capacity=1)
    version = get_session(session_id)["version"]

    res = api.create_reservation(
        session_id, {"membership_id": sub4["id"], "expected_session_version": version},
        make_member_headers(m4["id"]))
    validate_error(res, "ERR_WAITLIST_FULL")


def test_existence_beats_state_on_unknown_session(api):
    """PRD §2.7: "The system validates every referenced identifier — whether it appears
    in the path or the body — left to right, and rejects the request with `ERR_NOT_FOUND`
    the moment it reaches an identifier that resolves to nothing."
    PRD §2.7: "This existence pass runs after authentication and authorization but before
    any business-rule evaluation."

    Design: Corner/validations/priority_existence_beats_state_unknown_session
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(plan_overrides={"price_cents": 8000, "grant_credits": 20, "validity_days": 60})
    m1, sub1 = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], active=True)

    res = api.create_reservation(
        "00000000-0000-4000-8000-000000000999",
        {"membership_id": sub1["id"], "expected_session_version": sub1["version"]},
        make_member_headers(m1["id"]))
    validate_error(res, "ERR_NOT_FOUND")
