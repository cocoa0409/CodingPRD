"""Badge lifecycle and session-reservation behavior.

Covers the badge status/rfid parallel dimensions, the waitlist promotion cycle on
cancel, half-open session overlap vs adjacency, the VIP-tier requirement, session
OCC, badge transfer, transfer limit, invalid badge transitions, and the
confirmed_only session-full check.
"""
from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    setup_convention_with_ticket_type,
    setup_paid_order_with_badge,
    setup_session_capacity1_confirmed_and_waitlisted,
    create_attendee,
    create_session,
    create_paid_order,
    first_badge_for_order,
    reserve_session,
    session_version,
    make_attendee_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
AGENT = TEST_USERS["agent_headers"]


def test_badge_pickup_then_print_parallel_dimensions(api):
    """PRD §3.5: "A successful pickup sets `rfid_status` to `ENCODED`, assigns the badge an `rfid_uid`, and increments the badge's `version` by one — the RFID dimension advancing independently of the `status` dimension."
    PRD §3.5: "Taken together, the two dimensions advance as `ISSUED → PICKED_UP → PRINTED` on the `status` axis and `UNASSIGNED → ENCODED → DEACTIVATED` on the `rfid_status` axis."

    Design: Difficulty/non_linear_state_machine/badge_parallel_status_and_rfid_dimensions
    """
    ctx = setup_paid_order_with_badge(clock="2026-07-01T00:00:00Z")
    badge_id = ctx["badge"]["id"]
    set_clock("2026-08-31T00:00:00Z")  # inside pickup window (>= event_start - 48h)

    after_pickup = validate_success(api.pickup_badge(badge_id, AGENT), 200)
    assert after_pickup["status"] == "PICKED_UP"
    assert after_pickup["rfid_status"] == "ENCODED"
    assert after_pickup["rfid_uid"] is not None

    after_print = validate_success(api.print_badge(badge_id, AGENT), 200)
    assert after_print["status"] == "PRINTED"
    assert after_print["rfid_status"] == "ENCODED"


def test_cancel_confirmed_promotes_waitlisted(api):
    """PRD §3.6: "Cancelling a `CONFIRMED` reservation moves it to `CANCELLED`, decrements the session's `seats_taken` by one, then promotes the highest-`waitlist_score` `WAITLISTED` reservation on the same session to `CONFIRMED` — breaking ties by earliest `created_at` — and recomputes the session's `seats_taken`; this is cascade C."

    Design: Difficulty/non_linear_state_machine/session_reservation_waitlist_promotion_cycle
    """
    ctx = setup_session_capacity1_confirmed_and_waitlisted()
    resv_a = ctx["reservation_a"]
    resv_b = ctx["reservation_b"]
    session_id = ctx["session"]["id"]
    headers_a = make_attendee_headers(ctx["attendee_a"]["id"])

    cancelled = validate_success(api.cancel_session_reservation(resv_a["id"], headers_a), 200)
    assert cancelled["status"] == "CANCELLED"

    promoted = validate_success(api.get_session_reservation(resv_b["id"], AGENT), 200)
    assert promoted["status"] == "CONFIRMED"

    sess = validate_success(api.get_session(session_id, AGENT), 200)
    assert sess["seats_taken"] == 1


def test_session_half_open_adjacency_allowed_overlap_rejected(api):
    """PRD §3.6: "the badge must not already hold another `CONFIRMED` reservation whose half-open interval overlaps this session's half-open interval; two sessions that merely abut (one ending exactly when the other starts) do not overlap and are allowed, but a genuine overlap is rejected with `ERR_SESSION_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/session_half_open_adjacency_allowed_overlap_rejected
    """
    conv, tt = setup_convention_with_ticket_type()
    sess_a = create_session(conv["id"], title="A", start_utc="2026-09-01T10:00:00Z",
                            end_utc="2026-09-01T11:00:00Z", seat_capacity=5)
    sess_b = create_session(conv["id"], title="B", start_utc="2026-09-01T11:00:00Z",
                            end_utc="2026-09-01T12:00:00Z", seat_capacity=5)
    sess_c = create_session(conv["id"], title="C", start_utc="2026-09-01T10:30:00Z",
                            end_utc="2026-09-01T11:30:00Z", seat_capacity=5)
    att = create_attendee()
    headers = make_attendee_headers(att["id"])
    set_clock("2026-07-01T00:00:00Z")
    order = create_paid_order(conv["id"], att["id"], [(tt["id"], 1)])
    badge = first_badge_for_order(order["id"], att["id"])

    # Hold A 10:00-11:00.
    reserve_session(sess_a["id"], badge["id"], att["id"])

    # Adjacent B 11:00-12:00 (end == start) is allowed.
    sv_b = session_version(sess_b["id"])
    res_b = api.create_session_reservation(
        {"session_id": sess_b["id"], "badge_id": badge["id"], "expected_session_version": sv_b}, headers)
    confirmed_b = validate_success(res_b, 201)
    assert confirmed_b["status"] == "CONFIRMED"

    # Overlapping C 10:30-11:30 is rejected.
    sv_c = session_version(sess_c["id"])
    res_c = api.create_session_reservation(
        {"session_id": sess_c["id"], "badge_id": badge["id"], "expected_session_version": sv_c}, headers)
    validate_error(res_c, "ERR_SESSION_TIME_CONFLICT", expected_status=409)


def test_vip_session_rejects_general_badge(api):
    """PRD §3.6: "if the target session's `requires_vip` is true, the badge's ticket tier must be `VIP`, otherwise the reservation is rejected with `ERR_VIP_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/session_reservation_requires_badge_vip_tier
    """
    conv, tt = setup_convention_with_ticket_type(tt_overrides={"tier": "GENERAL", "base_price_cents": 9900})
    sess = create_session(conv["id"], title="VIP Panel", start_utc="2026-09-01T10:00:00Z",
                          end_utc="2026-09-01T11:00:00Z", seat_capacity=5, requires_vip=True)
    att = create_attendee()
    headers = make_attendee_headers(att["id"])
    set_clock("2026-07-01T00:00:00Z")
    order = create_paid_order(conv["id"], att["id"], [(tt["id"], 1)])
    badge = first_badge_for_order(order["id"], att["id"])

    sv = session_version(sess["id"])
    res = api.create_session_reservation(
        {"session_id": sess["id"], "badge_id": badge["id"], "expected_session_version": sv}, headers)
    validate_error(res, "ERR_VIP_REQUIRED", expected_status=409)

    after = validate_success(api.get_session(sess["id"], AGENT), 200)
    assert after["seats_taken"] == 0


def test_session_reservation_stale_version_rejected(api):
    """PRD §2.7: "If that value does not match the session's current `version`, the create is rejected with `ERR_STALE_SESSION_VERSION` and HTTP status 412 — the client's view of available seats is stale and the seat it expected to claim as `CONFIRMED` may already be gone, so the request is refused rather than silently routed to the waitlist."

    Design: Corner/cross_cutting_complexity_layers/occ_session_stale_version_rejected
    """
    conv, tt = setup_convention_with_ticket_type()
    sess = create_session(conv["id"], title="OCC Panel", start_utc="2026-09-01T10:00:00Z",
                          end_utc="2026-09-01T11:00:00Z", seat_capacity=5)
    att_a = create_attendee()
    att_b = create_attendee()
    headers_b = make_attendee_headers(att_b["id"])
    set_clock("2026-07-01T00:00:00Z")
    order_a = create_paid_order(conv["id"], att_a["id"], [(tt["id"], 1)])
    order_b = create_paid_order(conv["id"], att_b["id"], [(tt["id"], 1)])
    badge_a = first_badge_for_order(order_a["id"], att_a["id"])
    badge_b = first_badge_for_order(order_b["id"], att_b["id"])

    stale_version = session_version(sess["id"])
    # First reservation succeeds and advances Session.version.
    reserve_session(sess["id"], badge_a["id"], att_a["id"])

    # Second reservation carries the now-stale version.
    res = api.create_session_reservation(
        {"session_id": sess["id"], "badge_id": badge_b["id"], "expected_session_version": stale_version},
        headers_b)
    validate_error(res, "ERR_STALE_SESSION_VERSION", expected_status=412)


def test_session_reservation_correct_version_succeeds(api):
    """PRD §3.6: "if the session's `seats_taken` is below its `seat_capacity` the reservation is `CONFIRMED` (and `seats_taken` is incremented), otherwise it is `WAITLISTED`. Creating a `CONFIRMED` reservation increments the session's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_session_correct_version_succeeds
    """
    conv, tt = setup_convention_with_ticket_type()
    sess = create_session(conv["id"], title="OCC OK Panel", start_utc="2026-09-01T10:00:00Z",
                          end_utc="2026-09-01T11:00:00Z", seat_capacity=5)
    att = create_attendee()
    headers = make_attendee_headers(att["id"])
    set_clock("2026-07-01T00:00:00Z")
    order = create_paid_order(conv["id"], att["id"], [(tt["id"], 1)])
    badge = first_badge_for_order(order["id"], att["id"])

    sv = session_version(sess["id"])
    res = api.create_session_reservation(
        {"session_id": sess["id"], "badge_id": badge["id"], "expected_session_version": sv}, headers)
    resv = validate_success(res, 201)
    assert resv["status"] == "CONFIRMED"

    after = validate_success(api.get_session(sess["id"], AGENT), 200)
    assert after["seats_taken"] == 1
    assert after["version"] == sv + 1


def test_confirmed_only_full_session_returns_session_full(api):
    """PRD §3.6: "Only when the caller passes `confirmed_only` as true and no seat is free does the create fail outright with `ERR_SESSION_FULL`."

    Design: Corner/validations/confirmed_only_full_session_returns_session_full
    """
    ctx = setup_session_capacity1_confirmed_and_waitlisted()
    # reservation_a already holds the only CONFIRMED seat; reservation_b is WAITLISTED.
    # Build a third badge that asks confirmed_only on the now-full session.
    conv = ctx["convention"]
    tt = ctx["ticket_type"]
    sess = ctx["session"]
    att_c = create_attendee()
    headers_c = make_attendee_headers(att_c["id"])
    order_c = create_paid_order(conv["id"], att_c["id"], [(tt["id"], 1)])
    badge_c = first_badge_for_order(order_c["id"], att_c["id"])

    sv = session_version(sess["id"])
    res = api.create_session_reservation(
        {"session_id": sess["id"], "badge_id": badge_c["id"],
         "expected_session_version": sv, "confirmed_only": True}, headers_c)
    validate_error(res, "ERR_SESSION_FULL", expected_status=409)

    after = validate_success(api.get_session(sess["id"], AGENT), 200)
    assert after["seats_taken"] == 1


def test_badge_transfer_increments_count_keeps_issued(api):
    """PRD §3.5: "A transfer carries a `new_holder_attendee_id`, updates the badge's `holder_attendee_id` to it, and increments `transfer_count` by one without changing the badge's `status`."

    Design: Corner/state_machines/badge_transfer_increments_count_no_status_change
    """
    ctx = setup_paid_order_with_badge(clock="2026-07-01T00:00:00Z")
    badge_id = ctx["badge"]["id"]
    att_a = ctx["attendee"]
    headers_a = make_attendee_headers(att_a["id"])
    att_b = create_attendee()

    res = api.transfer_badge(badge_id, {"new_holder_attendee_id": att_b["id"]}, headers_a)
    transferred = validate_success(res, 200)
    assert transferred["holder_attendee_id"] == att_b["id"]
    assert transferred["transfer_count"] == 1
    assert transferred["status"] == "ISSUED"


def test_transfer_limit_blocks_third_transfer(api):
    """PRD §3.5: "Transfers are allowed only while the badge's `status` is `ISSUED` and its `transfer_count` is below the maximum of two completed transfers; a transfer attempted when the badge is not `ISSUED` or whose `transfer_count` already stands at that limit of two is rejected with `ERR_TRANSFER_LIMIT`."

    Design: Corner/validations/transfer_limit_blocks_third_transfer
    """
    ctx = setup_paid_order_with_badge(clock="2026-07-01T00:00:00Z")
    badge_id = ctx["badge"]["id"]
    att_a = ctx["attendee"]
    att_b = create_attendee()
    att_c = create_attendee()
    att_d = create_attendee()

    validate_success(api.transfer_badge(badge_id, {"new_holder_attendee_id": att_b["id"]},
                                        make_attendee_headers(att_a["id"])), 200)
    validate_success(api.transfer_badge(badge_id, {"new_holder_attendee_id": att_c["id"]},
                                        make_attendee_headers(att_b["id"])), 200)
    res = api.transfer_badge(badge_id, {"new_holder_attendee_id": att_d["id"]},
                             make_attendee_headers(att_c["id"]))
    validate_error(res, "ERR_TRANSFER_LIMIT", expected_status=409)

    after = validate_success(api.get_badge(badge_id, AGENT), 200)
    assert after["transfer_count"] == 2


def test_pickup_already_picked_up_invalid_state(api):
    """PRD §3.5: "On-site pickup is a `RegistrationAgent` operation that advances a badge from `ISSUED` to `PICKED_UP`. It is permitted only when the badge is currently `ISSUED` and the on-site window is open".

    Design: Corner/state_machines/pickup_from_already_picked_up_returns_invalid_state
    """
    ctx = setup_paid_order_with_badge(clock="2026-07-01T00:00:00Z")
    badge_id = ctx["badge"]["id"]
    set_clock("2026-08-31T00:00:00Z")
    validate_success(api.pickup_badge(badge_id, AGENT), 200)

    res = api.pickup_badge(badge_id, AGENT)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(api.get_badge(badge_id, AGENT), 200)
    assert after["status"] == "PICKED_UP"


def test_print_before_pickup_invalid_state(api):
    """PRD §3.5: "Printing advances a badge from `PICKED_UP` to `PRINTED` and is also a `RegistrationAgent` operation. It requires the badge to be `PICKED_UP` and its `rfid_status` to be `ENCODED".

    Design: Corner/state_machines/print_before_pickup_returns_invalid_state
    """
    ctx = setup_paid_order_with_badge(clock="2026-08-31T00:00:00Z")
    badge_id = ctx["badge"]["id"]
    res = api.print_badge(badge_id, AGENT)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(api.get_badge(badge_id, AGENT), 200)
    assert after["status"] == "ISSUED"


def test_pickup_before_window_returns_window_closed(api):
    """PRD §3.5: "It is permitted only when the badge is currently `ISSUED` and the on-site window is open, meaning the current clock is at or after the instant 48 hours before the convention's `event_start_utc`; the boundary instant itself counts as open. An attempt before that window opens is rejected with `ERR_PICKUP_WINDOW_CLOSED`."

    Design: Corner/validations/pickup_before_window_returns_window_closed
    """
    ctx = setup_paid_order_with_badge(clock="2026-07-01T00:00:00Z")
    badge_id = ctx["badge"]["id"]
    # event_start = 2026-09-01T00:00; window opens 2026-08-30T00:00; 2026-08-29 is before.
    set_clock("2026-08-29T00:00:00Z")
    res = api.pickup_badge(badge_id, AGENT)
    validate_error(res, "ERR_PICKUP_WINDOW_CLOSED", expected_status=409)
    after = validate_success(api.get_badge(badge_id, AGENT), 200)
    assert after["status"] == "ISSUED"
