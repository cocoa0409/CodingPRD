"""Second tests for each depth (difficulty) instance.

Each test below asserts a distinct, PRD-derivable facet of the same difficulty
instance already exercised in test_01–test_06, so every difficulty instance is
covered by at least two tests.
"""
from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    create_convention,
    create_attendee,
    create_booth,
    create_exhibitor,
    create_booth_booking,
    create_waitlist_entry,
    get_exhibitor,
    setup_convention_with_ticket_type,
    setup_paid_order_with_badge,
    setup_session_capacity1_confirmed_and_waitlisted,
    create_draft_order,
    create_submitted_order,
    create_paid_order,
    convention_version,
    first_badge_for_order,
    reserve_session,
    session_version,
    create_session,
    make_attendee_headers,
    make_exhibitor_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
AGENT = TEST_USERS["agent_headers"]


def test_refund_provisional_equals_final_same_tier(api):
    """PRD §3.4: "This is the FINAL variant of the refund calculation, computed from the penalty tier implied by the clock at execution time."
    PRD §3.4: "that read computes the provisional refund from the penalty tier implied by the current clock and writes it to the order's `provisional_refund_cents".

    Design: Difficulty/dual_variant_calc/refund_provisional_vs_final_diverges_on_order
    """
    conv, tt = setup_convention_with_ticket_type(
        conv_overrides={"event_start_utc": "2026-09-01T00:00:00Z"},
        tt_overrides={"base_price_cents": 9900})
    att = create_attendee()
    headers = make_attendee_headers(att["id"])
    set_clock("2026-07-01T00:00:00Z")
    create_paid_order(conv["id"], att["id"], [(tt["id"], 5)])
    order_id = api.list_orders(headers, params={"purchaser_attendee_id": att["id"]}).json()["data"][0]["id"]

    # Both quote and refund executed at the same clock (12 days before; 25% tier).
    set_clock("2026-08-20T00:00:00Z")
    quote = validate_success(api.get_refund_quote(order_id, headers), 200)
    assert quote["provisional_refund_cents"] == 35269
    refunded = validate_success(api.refund_order(order_id, AGENT), 200)
    assert refunded["refund_amount_cents"] == 35269


def test_booth_actual_zero_when_no_checkin(api):
    """PRD §3.7: "The chronological `actual_booth_cents` is the sum, over only those bookings whose `status` is `CHECKED_IN`, of the booth zone daily rate multiplied by the booking's `occupied_days`."

    Design: Difficulty/dual_variant_calc/booth_estimated_vs_actual_diverges_on_exhibitor
    """
    conv = create_convention(event_end_utc="2026-09-05T23:59:59Z")
    booth = create_booth(conv["id"], booth_code="S2", zone="STANDARD", setup_buffer_hours=0)
    exh = create_exhibitor(conv["id"])
    create_booth_booking(booth["id"], exh["id"],
                         occupy_start_utc="2026-09-01T00:00:00Z",
                         occupy_end_utc="2026-09-03T00:00:00Z", requested_days=2)
    after = get_exhibitor(exh["id"])
    assert after["estimated_booth_cents"] == 100000  # STANDARD(50000) * 2
    assert after["actual_booth_cents"] == 0


def test_order_pricing_per_line_rounding_two_lines(api):
    """PRD §2.6: "each line is rounded to whole cents individually before the lines are summed, and the processing fee is then rounded once on its own".
    PRD §3.3: "otherwise 10.0% when it is at least 10".

    Design: Difficulty/combinatorial_formula/order_pricing_rounding_order_per_line_then_sum
    """
    conv, tt_gen = setup_convention_with_ticket_type(tt_overrides={"tier": "GENERAL", "base_price_cents": 9900})
    tt_vip = validate_success(api.create_ticket_type(
        conv["id"], {"tier": "VIP", "base_price_cents": 49900, "tier_capacity": 100}, ADMIN), 201)
    att = create_attendee()
    headers = make_attendee_headers(att["id"])
    # 5 GENERAL + 5 VIP = 10 badges -> 10% discount.
    order = create_draft_order(conv["id"], att["id"], [(tt_gen["id"], 5), (tt_vip["id"], 5)])
    submitted = validate_success(api.submit_order(order["id"], headers), 200)
    # GENERAL line: round(49500 * 0.90) = 44550 ; VIP line: round(249500 * 0.90) = 224550.
    assert submitted["ticket_subtotal_cents"] == 44550 + 224550
    assert submitted["is_group"] is True


def test_waitlist_priority_loyalty_only_outside_early_window(api):
    """PRD §3.8: "The first is loyalty points drawn from the entering attendee's `loyalty_tier`: 0 for `NONE`, 100 for `SILVER`, 200 for `GOLD`, and 300 for `PLATINUM`."
    PRD §3.8: "an early-bird bonus of 50 points, granted only when the entry's `created_at` is at or after the convention's `lottery_open_utc` and at the same time no later than 24 hours after that instant; outside that window the bonus is 0."

    Design: Difficulty/combinatorial_formula/waitlist_priority_weighted_score_with_group_cap
    """
    conv = create_convention(lottery_open_utc="2026-06-01T00:00:00Z")
    att = create_attendee(loyalty_tier="GOLD")
    set_clock("2026-06-10T00:00:00Z")  # well outside the 24h early window
    entry = create_waitlist_entry(conv["id"], att["id"], requested_quantity=3, group_size=3)
    # GOLD(200) + early(0) + min(3*5=15, 60)=15 = 215
    assert entry["priority_score"] == 215


def test_void_printed_badge_deactivates_rfid_axis(api):
    """PRD §3.5: "Voiding a badge moves it to the terminal VOID state ... Voiding
    sets rfid_status to DEACTIVATED".
    PRD §3.5: "the two dimensions advance as `ISSUED → PICKED_UP → PRINTED` on the `status` axis and `UNASSIGNED → ENCODED → DEACTIVATED` on the `rfid_status` axis."

    Design: Difficulty/non_linear_state_machine/badge_parallel_status_and_rfid_dimensions
    """
    ctx = setup_paid_order_with_badge(clock="2026-07-01T00:00:00Z")
    badge_id = ctx["badge"]["id"]
    set_clock("2026-08-31T00:00:00Z")
    validate_success(api.pickup_badge(badge_id, AGENT), 200)
    printed = validate_success(api.print_badge(badge_id, AGENT), 200)
    assert printed["status"] == "PRINTED" and printed["rfid_status"] == "ENCODED"

    voided = validate_success(api.void_badge(badge_id, AGENT), 200)
    assert voided["status"] == "VOID"
    assert voided["rfid_status"] == "DEACTIVATED"


def test_cancel_waitlisted_no_promotion(api):
    """PRD §3.6: "Cancelling a `WAITLISTED` reservation simply moves it to `CANCELLED`."

    Design: Difficulty/non_linear_state_machine/session_reservation_waitlist_promotion_cycle
    """
    ctx = setup_session_capacity1_confirmed_and_waitlisted()
    resv_a = ctx["reservation_a"]  # CONFIRMED
    resv_b = ctx["reservation_b"]  # WAITLISTED
    session_id = ctx["session"]["id"]
    headers_b = make_attendee_headers(ctx["attendee_b"]["id"])

    cancelled = validate_success(api.cancel_session_reservation(resv_b["id"], headers_b), 200)
    assert cancelled["status"] == "CANCELLED"

    # The CONFIRMED reservation is untouched and the seat count is unchanged.
    a_after = validate_success(api.get_session_reservation(resv_a["id"], AGENT), 200)
    assert a_after["status"] == "CONFIRMED"
    sess = validate_success(api.get_session(session_id, AGENT), 200)
    assert sess["seats_taken"] == 1


def test_refund_cascade_recomputes_counters_downward(api):
    """PRD §3.4: "the convention's `badges_issued_count` and each affected ticket type's `tier_issued_count` are recomputed downward from the surviving badge set".

    Design: Difficulty/transitive_cascade/refund_cascade_void_cancel_promote_depth3
    """
    conv, tt = setup_convention_with_ticket_type(conv_overrides={"total_badge_capacity": 100})
    att = create_attendee()
    set_clock("2026-07-15T00:00:00Z")
    order = create_paid_order(conv["id"], att["id"], [(tt["id"], 2)])

    tt_after_pay = validate_success(api.get_ticket_type(tt["id"], AGENT), 200)
    assert tt_after_pay["tier_issued_count"] == 2

    validate_success(api.refund_order(order["id"], AGENT), 200)
    tt_after_refund = validate_success(api.get_ticket_type(tt["id"], AGENT), 200)
    assert tt_after_refund["tier_issued_count"] == 0


def test_pay_below_capacity_keeps_posture_open(api):
    """PRD §3.4: "if the convention's `badges_issued_count` has reached its `total_badge_capacity`, it flips `posture` to `SOLD_OUT`."

    Design: Difficulty/transitive_cascade/pay_cascade_issue_count_soldout_depth3
    """
    conv, tt = setup_convention_with_ticket_type(conv_overrides={"total_badge_capacity": 50})
    att = create_attendee()
    set_clock("2026-07-01T00:00:00Z")
    create_paid_order(conv["id"], att["id"], [(tt["id"], 1)])
    after = validate_success(api.get_convention(conv["id"], AGENT), 200)
    assert after["badges_issued_count"] == 1
    assert after["posture"] == "OPEN"


def test_repay_paid_order_invalid_state_even_below_capacity(api):
    """PRD §2.9: "the target resource must currently be in a state from which the requested transition is defined, else `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_invalid_state_over_capacity
    """
    # Convention with ample capacity: the only failing precondition is the state.
    conv, tt = setup_convention_with_ticket_type(
        conv_overrides={"total_badge_capacity": 100}, tt_overrides={"tier_capacity": 100})
    att = create_attendee()
    headers = make_attendee_headers(att["id"])
    set_clock("2026-07-01T00:00:00Z")
    paid = create_paid_order(conv["id"], att["id"], [(tt["id"], 1)])
    conv_v = convention_version(conv["id"])
    res = api.pay_order(paid["id"], {"expected_convention_version": conv_v}, headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_refund_at_event_end_window_closed_boundary(api):
    """PRD §3.4: "A refund is permitted only while the current clock is strictly before the convention's `event_end_utc`; at or after that instant refunds are closed and the attempt is rejected with `ERR_REFUND_WINDOW_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_refund_window_over_vip
    """
    conv, tt = setup_convention_with_ticket_type(
        conv_overrides={"event_start_utc": "2026-09-01T00:00:00Z",
                        "event_end_utc": "2026-09-03T23:59:59Z"},
        tt_overrides={"base_price_cents": 9900})
    att = create_attendee()
    headers = make_attendee_headers(att["id"])
    set_clock("2026-07-01T00:00:00Z")
    create_paid_order(conv["id"], att["id"], [(tt["id"], 1)])
    order_id = api.list_orders(headers, params={"purchaser_attendee_id": att["id"]}).json()["data"][0]["id"]

    set_clock("2026-09-03T23:59:59Z")  # exactly at event_end_utc -> "at or after" is closed
    res = api.refund_order(order_id, AGENT)
    validate_error(res, "ERR_REFUND_WINDOW_CLOSED", expected_status=409)


def test_group_discount_boundary_qty9_vs_qty10(api):
    """PRD §3.3: "the discount is 15.0% when the total quantity is at least 50, otherwise 12.5% when it is at least 25, otherwise 10.0% when it is at least 10, otherwise 5.0% when it is at least 5 (the group minimum), and otherwise 0%."

    Design: Difficulty/boundary_precision_check/group_discount_tier_boundary_qty4_vs_qty5
    """
    conv, tt = setup_convention_with_ticket_type(tt_overrides={"base_price_cents": 9900})
    att = create_attendee()
    headers = make_attendee_headers(att["id"])

    order9 = create_draft_order(conv["id"], att["id"], [(tt["id"], 9)])
    sub9 = validate_success(api.submit_order(order9["id"], headers), 200)
    # 9 badges -> 5% : round(89100 * 0.95) = 84645
    assert sub9["ticket_subtotal_cents"] == 84645

    order10 = create_draft_order(conv["id"], att["id"], [(tt["id"], 10)])
    sub10 = validate_success(api.submit_order(order10["id"], headers), 200)
    # 10 badges -> 10% : round(99000 * 0.90) = 89100
    assert sub10["ticket_subtotal_cents"] == 89100


def test_refund_penalty_boundary_8_vs_7_days(api):
    """PRD §3.4: "The penalty percentage is then 0% when more than 30 days remain, 25% when at least 8 days (but not more than 30) remain, 50% when at least 1 day (but fewer than 8) remains".

    Design: Difficulty/boundary_precision_check/refund_penalty_tier_boundary_30_vs_31_days
    """
    conv, tt = setup_convention_with_ticket_type(
        conv_overrides={"event_start_utc": "2026-09-01T00:00:00Z"},
        tt_overrides={"base_price_cents": 9900})
    att = create_attendee()
    headers = make_attendee_headers(att["id"])
    set_clock("2026-07-01T00:00:00Z")
    create_paid_order(conv["id"], att["id"], [(tt["id"], 5)])
    order_id = api.list_orders(headers, params={"purchaser_attendee_id": att["id"]}).json()["data"][0]["id"]

    set_clock("2026-08-24T00:00:00Z")  # exactly 8 days before -> 25%
    q8 = validate_success(api.get_refund_quote(order_id, headers), 200)
    assert q8["provisional_refund_cents"] == 35269

    set_clock("2026-08-25T00:00:00Z")  # 7 days before -> 50%
    q7 = validate_success(api.get_refund_quote(order_id, headers), 200)
    assert q7["provisional_refund_cents"] == 23513


def test_pay_succeeds_under_open_posture(api):
    """PRD §3.4: "The convention's `posture` must be `OPEN`, otherwise the pay is blocked with `ERR_POSTURE_BLOCKED`."

    Design: Difficulty/cross_entity_state_dependency/order_pay_requires_convention_posture_open
    """
    conv, tt = setup_convention_with_ticket_type(conv_overrides={"total_badge_capacity": 100})
    att = create_attendee()
    headers = make_attendee_headers(att["id"])
    set_clock("2026-07-01T00:00:00Z")
    order = create_submitted_order(conv["id"], att["id"], [(tt["id"], 1)])
    conv_v = convention_version(conv["id"])
    paid = validate_success(api.pay_order(order["id"], {"expected_convention_version": conv_v}, headers), 200)
    assert paid["status"] == "PAID"


def test_vip_session_accepts_vip_badge(api):
    """PRD §3.6: "if the target session's `requires_vip` is true, the badge's ticket tier must be `VIP`, otherwise the reservation is rejected with `ERR_VIP_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/session_reservation_requires_badge_vip_tier
    """
    conv, tt = setup_convention_with_ticket_type(tt_overrides={"tier": "VIP", "base_price_cents": 49900})
    sess = create_session(conv["id"], title="VIP OK Panel", start_utc="2026-09-01T10:00:00Z",
                          end_utc="2026-09-01T11:00:00Z", seat_capacity=5, requires_vip=True)
    att = create_attendee()
    set_clock("2026-07-01T00:00:00Z")
    order = create_paid_order(conv["id"], att["id"], [(tt["id"], 1)])
    badge = first_badge_for_order(order["id"], att["id"])

    resv = reserve_session(sess["id"], badge["id"], att["id"])
    assert resv["status"] == "CONFIRMED"


def test_session_identical_interval_overlap_rejected(api):
    """PRD §3.6: "the badge must not already hold another `CONFIRMED` reservation whose half-open interval overlaps this session's half-open interval; two sessions that merely abut (one ending exactly when the other starts) do not overlap and are allowed, but a genuine overlap is rejected with `ERR_SESSION_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/session_half_open_adjacency_allowed_overlap_rejected
    """
    conv, tt = setup_convention_with_ticket_type()
    sess_a = create_session(conv["id"], title="A", start_utc="2026-09-01T10:00:00Z",
                            end_utc="2026-09-01T11:00:00Z", seat_capacity=5)
    sess_dup = create_session(conv["id"], title="Dup", start_utc="2026-09-01T10:00:00Z",
                              end_utc="2026-09-01T11:00:00Z", seat_capacity=5)
    att = create_attendee()
    headers = make_attendee_headers(att["id"])
    set_clock("2026-07-01T00:00:00Z")
    order = create_paid_order(conv["id"], att["id"], [(tt["id"], 1)])
    badge = first_badge_for_order(order["id"], att["id"])

    reserve_session(sess_a["id"], badge["id"], att["id"])
    sv = session_version(sess_dup["id"])
    res = api.create_session_reservation(
        {"session_id": sess_dup["id"], "badge_id": badge["id"], "expected_session_version": sv}, headers)
    validate_error(res, "ERR_SESSION_TIME_CONFLICT", expected_status=409)


def test_booth_non_overlapping_bookings_both_allowed(api):
    """PRD §3.7: "the requested window, expanded by the booth's setup_buffer_hours on
    each side ... must not overlap the similarly buffer-expanded window of any other
    RESERVED or CHECKED_IN booking on the same booth".

    Design: Difficulty/resource_temporal_overlap/booth_buffered_closed_interval_overlap_rejected
    """
    conv = create_convention(event_end_utc="2026-09-10T23:59:59Z")
    booth = create_booth(conv["id"], booth_code="B2", zone="STANDARD", setup_buffer_hours=0)
    exh = create_exhibitor(conv["id"])
    create_booth_booking(booth["id"], exh["id"],
                         occupy_start_utc="2026-09-01T00:00:00Z",
                         occupy_end_utc="2026-09-02T00:00:00Z", requested_days=1)
    # Zero buffer; second window starts well after the first ends -> no overlap.
    headers = make_exhibitor_headers(exh["id"])
    res = api.create_booth_booking(
        {"booth_id": booth["id"], "exhibitor_id": exh["id"],
         "occupy_start_utc": "2026-09-05T00:00:00Z",
         "occupy_end_utc": "2026-09-06T00:00:00Z", "requested_days": 1}, headers)
    second = validate_success(res, 201)
    assert second["status"] == "RESERVED"


def test_tier_count_conserved_across_pay_then_refund(api):
    """PRD §3.4: "it recomputes the convention's `badges_issued_count` and each affected ticket type's `tier_issued_count` from the authoritative badge set"
    PRD §3.4: "each affected ticket type's `tier_issued_count` are recomputed downward from the surviving badge set".

    Design: Difficulty/compensating_invariant/badge_count_conserved_across_pay_then_refund
    """
    conv, tt = setup_convention_with_ticket_type(conv_overrides={"total_badge_capacity": 100})
    att = create_attendee()
    set_clock("2026-07-15T00:00:00Z")
    order = create_paid_order(conv["id"], att["id"], [(tt["id"], 3)])

    tt_after_pay = validate_success(api.get_ticket_type(tt["id"], AGENT), 200)
    assert tt_after_pay["tier_issued_count"] == 3

    validate_success(api.refund_order(order["id"], AGENT), 200)
    tt_after_refund = validate_success(api.get_ticket_type(tt["id"], AGENT), 200)
    assert tt_after_refund["tier_issued_count"] == 0


def test_standard_estimate_conserved_across_book_then_release(api):
    """PRD §3.7: "Creating a booking recomputes the exhibitor's `estimated_booth_cents`."
    PRD §3.7: "Releasing recomputes the exhibitor's `estimated_booth_cents` with this booking excluded".

    Design: Difficulty/compensating_invariant/estimated_booth_cents_conserved_across_book_then_release
    """
    conv = create_convention(event_end_utc="2026-09-05T23:59:59Z")
    booth = create_booth(conv["id"], booth_code="S3", zone="STANDARD", setup_buffer_hours=0)
    exh = create_exhibitor(conv["id"])
    bk = create_booth_booking(booth["id"], exh["id"],
                              occupy_start_utc="2026-09-01T00:00:00Z",
                              occupy_end_utc="2026-09-03T00:00:00Z", requested_days=2)
    after_book = get_exhibitor(exh["id"])
    assert after_book["estimated_booth_cents"] == 100000  # STANDARD(50000) * 2

    validate_success(api.release_booth_booking(bk["id"], make_exhibitor_headers(exh["id"])), 200)
    after_release = get_exhibitor(exh["id"])
    assert after_release["estimated_booth_cents"] == 0
