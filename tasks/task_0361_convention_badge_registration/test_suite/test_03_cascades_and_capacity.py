"""Payment / refund cascades, capacity counters, posture, and convention OCC.

Covers the depth-3 pay and refund cascades, the badge-count and booth-estimate
conservation invariants, the badge-void waitlist promotion, posture gating,
tier/convention capacity rejects, the state-beats-fiscal precedence, convention
OCC, and immediate consistency.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_error_is_one_of,
    set_clock,
    setup_convention_with_ticket_type,
    setup_session_capacity1_confirmed_and_waitlisted,
    create_attendee,
    create_submitted_order,
    create_paid_order,
    convention_version,
    first_badge_for_order,
    make_attendee_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
AGENT = TEST_USERS["agent_headers"]


def test_pay_cascade_issue_count_flips_soldout(api):
    """PRD §3.4: "it recomputes the convention's `badges_issued_count` and each affected ticket type's `tier_issued_count` from the authoritative badge set (counting badges whose `status` is one of `ISSUED`, `PICKED_UP`, or `PRINTED`); and, if the convention's `badges_issued_count` has reached its `total_badge_capacity`, it flips `posture` to `SOLD_OUT`."

    Design: Difficulty/transitive_cascade/pay_cascade_issue_count_soldout_depth3
    """
    conv, tt = setup_convention_with_ticket_type(
        conv_overrides={"total_badge_capacity": 1}, tt_overrides={"tier_capacity": 5})
    att = create_attendee()
    set_clock("2026-07-01T00:00:00Z")
    paid = create_paid_order(conv["id"], att["id"], [(tt["id"], 1)])
    assert paid["status"] == "PAID"

    after = validate_success(api.get_convention(conv["id"], AGENT), 200)
    assert after["badges_issued_count"] == 1
    assert after["posture"] == "SOLD_OUT"


def test_refund_cascade_void_cancel_promote_depth3(api):
    """PRD §3.4: "every non-`VOID` badge of the order is voided (`status` `VOID`, `rfid_status` `DEACTIVATED`); for each voided badge, that badge's `CONFIRMED` and `WAITLISTED` session reservations are cancelled; for each `CONFIRMED` seat thereby freed, the highest-`waitlist_score` `WAITLISTED` reservation on that same session is promoted to `CONFIRMED` and the session's `seats_taken` is recomputed".

    Design: Difficulty/transitive_cascade/refund_cascade_void_cancel_promote_depth3
    """
    ctx = setup_session_capacity1_confirmed_and_waitlisted(clock="2026-07-15T00:00:00Z")
    order_a = ctx["order_a"]
    badge_a = ctx["badge_a"]
    resv_a = ctx["reservation_a"]
    resv_b = ctx["reservation_b"]
    session_id = ctx["session"]["id"]
    headers_a = make_attendee_headers(ctx["attendee_a"]["id"])

    refunded = validate_success(api.refund_order(order_a["id"], AGENT), 200)
    assert refunded["status"] == "REFUNDED"

    badge_after = validate_success(api.get_badge(badge_a["id"], AGENT), 200)
    assert badge_after["status"] == "VOID"
    assert badge_after["rfid_status"] == "DEACTIVATED"

    resv_a_after = validate_success(api.get_session_reservation(resv_a["id"], headers_a), 200)
    assert resv_a_after["status"] == "CANCELLED"

    resv_b_after = validate_success(api.get_session_reservation(resv_b["id"], AGENT), 200)
    assert resv_b_after["status"] == "CONFIRMED"

    sess_after = validate_success(api.get_session(session_id, AGENT), 200)
    assert sess_after["seats_taken"] == 1


def test_badge_void_cascade_promotes_waitlist(api):
    """PRD §3.5: "Voiding a badge moves it to the terminal VOID state ... cancels
    that badge's CONFIRMED and WAITLISTED session reservations — which in turn
    promotes the top waitlisted reservation on each freed session".

    Design: Corner/cross_cutting_complexity_layers/badge_void_cascade_promotes_waitlist_depth2
    """
    ctx = setup_session_capacity1_confirmed_and_waitlisted()
    badge_a = ctx["badge_a"]
    resv_a = ctx["reservation_a"]
    resv_b = ctx["reservation_b"]
    session_id = ctx["session"]["id"]
    headers_a = make_attendee_headers(ctx["attendee_a"]["id"])

    voided = validate_success(api.void_badge(badge_a["id"], AGENT), 200)
    assert voided["status"] == "VOID"

    resv_a_after = validate_success(api.get_session_reservation(resv_a["id"], headers_a), 200)
    assert resv_a_after["status"] == "CANCELLED"
    resv_b_after = validate_success(api.get_session_reservation(resv_b["id"], AGENT), 200)
    assert resv_b_after["status"] == "CONFIRMED"
    sess_after = validate_success(api.get_session(session_id, AGENT), 200)
    assert sess_after["seats_taken"] == 1


def test_badge_count_conserved_across_pay_then_refund(api):
    """PRD §3.4: "it recomputes the convention's `badges_issued_count` and each affected ticket type's `tier_issued_count` from the authoritative badge set"
    PRD §3.4: "the convention's `badges_issued_count` and each affected ticket type's `tier_issued_count` are recomputed downward from the surviving badge set"

    Design: Difficulty/compensating_invariant/badge_count_conserved_across_pay_then_refund
    """
    conv, tt = setup_convention_with_ticket_type(conv_overrides={"total_badge_capacity": 100})
    att = create_attendee()
    set_clock("2026-07-15T00:00:00Z")
    order = create_paid_order(conv["id"], att["id"], [(tt["id"], 3)])

    after_pay = validate_success(api.get_convention(conv["id"], AGENT), 200)
    assert after_pay["badges_issued_count"] == 3

    validate_success(api.refund_order(order["id"], AGENT), 200)
    after_refund = validate_success(api.get_convention(conv["id"], AGENT), 200)
    assert after_refund["badges_issued_count"] == 0


def test_pay_cascade_visible_immediately(api):
    """PRD §2.5: "the system maintains immediate consistency with no deferred reconciliation."
    PRD §3.4: "it recomputes the convention's `badges_issued_count` and each affected ticket type's `tier_issued_count` from the authoritative badge set".

    Design: Corner/consistency_model/pay_cascade_visible_in_same_response_immediate
    """
    conv, tt = setup_convention_with_ticket_type(conv_overrides={"total_badge_capacity": 50})
    att = create_attendee()
    set_clock("2026-07-01T00:00:00Z")
    create_paid_order(conv["id"], att["id"], [(tt["id"], 2)])

    after = validate_success(api.get_convention(conv["id"], AGENT), 200)
    assert after["badges_issued_count"] == 2


def test_pay_blocked_when_convention_closed(api):
    """PRD §3.4: "The convention's `posture` must be `OPEN`, otherwise the pay is blocked with `ERR_POSTURE_BLOCKED`."

    Design: Difficulty/cross_entity_state_dependency/order_pay_requires_convention_posture_open
    """
    conv, tt = setup_convention_with_ticket_type(conv_overrides={"total_badge_capacity": 100})
    att = create_attendee()
    headers = make_attendee_headers(att["id"])
    set_clock("2026-07-01T00:00:00Z")
    order = create_submitted_order(conv["id"], att["id"], [(tt["id"], 1)])

    # Admin drives the convention to CLOSED.
    conv_v = convention_version(conv["id"])
    validate_success(api.close_convention(conv["id"], {"expected_convention_version": conv_v}, ADMIN), 200)

    conv_v2 = convention_version(conv["id"])
    res = api.pay_order(order["id"], {"expected_convention_version": conv_v2}, headers)
    validate_error(res, "ERR_POSTURE_BLOCKED", expected_status=409)
    after = validate_success(api.get_order(order["id"], headers), 200)
    assert after["status"] == "PENDING_PAYMENT"


def test_repay_already_paid_order_invalid_state_beats_fiscal(api):
    """PRD §2.9: "the target resource must currently be in a state from which the requested transition is defined, else `ERR_INVALID_STATE`."
    PRD §2.9: "After these foundational checks come the business-specific rules in
    the order presented below ... per-tier capacity, convention capacity".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_invalid_state_over_capacity
    """
    conv, tt = setup_convention_with_ticket_type(
        conv_overrides={"total_badge_capacity": 1}, tt_overrides={"tier_capacity": 5})
    att = create_attendee()
    headers = make_attendee_headers(att["id"])
    set_clock("2026-07-01T00:00:00Z")
    paid = create_paid_order(conv["id"], att["id"], [(tt["id"], 1)])
    assert paid["status"] == "PAID"

    # The order is already PAID (state violation) and the convention is at capacity
    # (fiscal violation); state precedence yields ERR_INVALID_STATE.
    conv_v2 = convention_version(conv["id"])
    res = api.pay_order(paid["id"], {"expected_convention_version": conv_v2}, headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_tier_sold_out_blocks_pay(api):
    """PRD §3.4: "For every line, the line's ticket type `tier_issued_count` plus the quantities being paid for that tier must not exceed that ticket type's `tier_capacity`, otherwise `ERR_TIER_SOLD_OUT`."

    Design: Corner/validations/tier_sold_out_blocks_pay
    """
    conv, tt = setup_convention_with_ticket_type(
        conv_overrides={"total_badge_capacity": 100}, tt_overrides={"tier_capacity": 1})
    att = create_attendee()
    headers = make_attendee_headers(att["id"])
    set_clock("2026-07-01T00:00:00Z")
    order = create_submitted_order(conv["id"], att["id"], [(tt["id"], 2)])
    conv_v = convention_version(conv["id"])
    res = api.pay_order(order["id"], {"expected_convention_version": conv_v}, headers)
    validate_error(res, "ERR_TIER_SOLD_OUT", expected_status=409)
    after = validate_success(api.get_order(order["id"], headers), 200)
    assert after["status"] == "PENDING_PAYMENT"


def test_convention_capacity_exceeded_blocks_pay(api):
    """PRD §3.4: "Across the whole order, the convention's `badges_issued_count` plus the sum of all line quantities must not exceed the convention's `total_badge_capacity`, otherwise `ERR_CAPACITY_EXCEEDED`."

    Design: Corner/validations/capacity_exceeded_when_convention_cap_below_tier_cap
    """
    conv, tt = setup_convention_with_ticket_type(
        conv_overrides={"total_badge_capacity": 2}, tt_overrides={"tier_capacity": 100})
    att = create_attendee()
    headers = make_attendee_headers(att["id"])
    set_clock("2026-07-01T00:00:00Z")
    order = create_submitted_order(conv["id"], att["id"], [(tt["id"], 3)])
    conv_v = convention_version(conv["id"])
    res = api.pay_order(order["id"], {"expected_convention_version": conv_v}, headers)
    validate_error(res, "ERR_CAPACITY_EXCEEDED", expected_status=409)


def test_convention_stale_pay_rejected(api):
    """PRD §2.7: "If that value does not match the convention's current version —
    because some other writer advanced it since the client last read it — the pay
    is rejected with ERR_STALE_CONVENTION_VERSION and HTTP status 412 ... a second
    pay carrying a version that an earlier successful pay already superseded is
    rejected the same way."

    Design: Corner/cross_cutting_complexity_layers/occ_convention_stale_pay_rejected
    """
    conv, tt = setup_convention_with_ticket_type(conv_overrides={"total_badge_capacity": 50})
    att_a = create_attendee()
    att_b = create_attendee()
    headers_a = make_attendee_headers(att_a["id"])
    headers_b = make_attendee_headers(att_b["id"])
    set_clock("2026-07-01T00:00:00Z")
    order_a = create_submitted_order(conv["id"], att_a["id"], [(tt["id"], 1)])
    order_b = create_submitted_order(conv["id"], att_b["id"], [(tt["id"], 1)])

    shared_v = convention_version(conv["id"])
    validate_success(api.pay_order(order_a["id"], {"expected_convention_version": shared_v}, headers_a), 200)

    # order_b reuses the now-superseded version.
    res = api.pay_order(order_b["id"], {"expected_convention_version": shared_v}, headers_b)
    validate_error(res, "ERR_STALE_CONVENTION_VERSION", expected_status=412)


def test_lottery_not_won_blocks_order_under_sold_out(api):
    """PRD §3.4: "when the convention's `posture` is `SOLD_OUT`, an attendee may only create a paid order if they hold a `WON` waitlist entry for that convention; an attempt to register under `SOLD_OUT` posture without a `WON` `WaitlistEntry` is rejected with `ERR_LOTTERY_NOT_WON`."
    PRD §3.4: "The convention's `posture` must be `OPEN`, otherwise the pay is blocked with `ERR_POSTURE_BLOCKED`."

    Design: Corner/validations/lottery_not_won_blocks_order_under_sold_out
    """
    conv, tt = setup_convention_with_ticket_type(
        conv_overrides={"total_badge_capacity": 1}, tt_overrides={"tier_capacity": 5})
    att_x = create_attendee()
    att_y = create_attendee()
    headers_y = make_attendee_headers(att_y["id"])
    set_clock("2026-07-01T00:00:00Z")
    # Y submits while the convention is still OPEN (submission requires OPEN
    # posture per PRD §3.3), leaving the order PENDING_PAYMENT.
    order_y = create_submitted_order(conv["id"], att_y["id"], [(tt["id"], 1)])

    # X buys the only badge -> convention flips to SOLD_OUT.
    create_paid_order(conv["id"], att_x["id"], [(tt["id"], 1)])

    # Y now attempts to pay under SOLD_OUT without a WON entry.
    conv_v = convention_version(conv["id"])
    res = api.pay_order(order_y["id"], {"expected_convention_version": conv_v}, headers_y)
    validate_error_is_one_of(res, ["ERR_LOTTERY_NOT_WON", "ERR_POSTURE_BLOCKED"])
    after = validate_success(api.get_order(order_y["id"], headers_y), 200)
    assert after["status"] == "PENDING_PAYMENT"
