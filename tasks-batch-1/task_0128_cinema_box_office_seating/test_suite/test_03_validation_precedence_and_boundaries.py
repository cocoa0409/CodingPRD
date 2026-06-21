"""Validation precedence pairs, numeric/empty boundaries, cross-entity state
dependencies, and resource temporal-overlap checks (auditorium buffer vs member
zero-buffer).
"""
from test_helpers import TEST_USERS, get_success_data, validate_error
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import create_showtime_payload

MANAGER = TEST_USERS["manager_headers"]
AGENT = TEST_USERS["agent_headers"]


# ===========================================================================
# Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_refund_past_terminal
# ===========================================================================

def test_refund_already_refunded_past_showtime_returns_invalid_state(api):
    """PRD §2.7: "then the target's state being valid for the requested transition
    (ERR_INVALID_STATE), then the optimistic-concurrency version check
    (ERR_STALE_SHOWTIME_VERSION), and only then the domain-specific business rules."
    PRD §3.7: "A refund attempted at or after the screening's start, outside a
    cancel cascade, is rejected with ERR_PAST_SHOWTIME."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_refund_past_terminal
    """
    ctx = fx.setup_paid_order(base_price_cents=1000, num_seats=1, starts_at="2026-06-10T20:00:00.000Z")
    order = ctx["order"]

    # First refund succeeds (order is PAID, showtime not yet started).
    get_success_data(api.refund_order(order["id"], {"refund_destination": "ORIGINAL"}, AGENT))

    # Advance past the showtime's start so the temporal check would also fail.
    fx.advance_clock("2026-06-10T21:00:00.000Z")

    # Second refund: order is REFUNDED (state, higher precedence) AND past start (temporal).
    resp = api.refund_order(order["id"], {"refund_destination": "ORIGINAL"}, AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_refund_terminal_order_alone_returns_invalid_state(api):
    """PRD §3.7: "A refund is permitted only while the order is PAID, and — outside
    of a showtime-cancel cascade — only while the showtime is in ON_SALE or
    CANCELLED status and the current time is strictly before the showtime's
    starts_at."
    PRD §2.7: "then the target's state being valid for the requested transition
    (ERR_INVALID_STATE), then the optimistic-concurrency version check
    (ERR_STALE_SHOWTIME_VERSION), and only then the domain-specific business rules."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_refund_past_terminal
    """
    # Refund a CANCELLED (HELD-then-cancelled) order: not PAID, showtime still future.
    ctx = fx.setup_on_sale_showtime(base_price_cents=1000)
    member = fx.make_member()
    held = fx.create_held_order(ctx["showtime"], member, ctx["seat_ids"][:1])
    get_success_data(api.cancel_order(held["id"], AGENT))

    resp = api.refund_order(held["id"], {"refund_destination": "ORIGINAL"}, AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Difficulty/priority_pair_validation_conflict/double_booked_beats_rental_fee_on_schedule
# ===========================================================================

def test_double_booked_takes_precedence_over_rental_fee(api):
    """PRD §2.7: "the matinee-window check precedes the auditorium double-booking
    check, which precedes the rental-fee check"

    Design: Difficulty/priority_pair_validation_conflict/double_booked_beats_rental_fee_on_schedule
    """
    base = fx.setup_base(seat_count=4)
    aud_id = base["auditorium"]["id"]
    film_id = base["film"]["id"]
    # Existing showtime 20:00 (ends 21:45).
    fx.schedule_showtime(aud_id, film_id, starts_at="2026-06-10T20:00:00.000Z",
                         pricing_profile="STANDARD", base_price_cents=1000)
    # Overlapping RENTAL at 20:30 with invalid fee 0 — both p8 and p9 would fire.
    payload = create_showtime_payload(
        film_id, "2026-06-10T20:30:00.000Z",
        pricing_profile="STANDARD", base_price_cents=1000,
        rental_basis="RENTAL", private_rental_fee_cents=0,
    )
    resp = api.create_showtime(aud_id, payload, MANAGER)
    validate_error(resp, ApiErrorId.ERR_AUDITORIUM_DOUBLE_BOOKED.value)


def test_rental_fee_invalid_alone_when_no_overlap(api):
    """PRD §3.2: "a RENTAL screening must carry a positive private_rental_fee_cents,
    while a BOX_OFFICE screening must carry a fee of exactly 0, and any other
    combination is rejected with ERR_RENTAL_FEE_INVALID (the field defaults to 0
    when omitted)."

    Design: Difficulty/priority_pair_validation_conflict/double_booked_beats_rental_fee_on_schedule
    """
    base = fx.setup_base(seat_count=4)
    # No existing showtime, so only the rental-fee rule can fire.
    payload = create_showtime_payload(
        base["film"]["id"], "2026-06-10T20:30:00.000Z",
        pricing_profile="STANDARD", base_price_cents=1000,
        rental_basis="RENTAL", private_rental_fee_cents=0,
    )
    resp = api.create_showtime(base["auditorium"]["id"], payload, MANAGER)
    validate_error(resp, ApiErrorId.ERR_RENTAL_FEE_INVALID.value)


# ===========================================================================
# Difficulty/boundary_precision_check/loyalty_tier_silver_boundary_exactly_50
# ===========================================================================

def test_tier_silver_at_exactly_fifty_points(api):
    """PRD §3.3: "otherwise SILVER when the balance is at least 50 points,
    otherwise BRONZE."

    Design: Difficulty/boundary_precision_check/loyalty_tier_silver_boundary_exactly_50
    """
    # 2 STANDARD seats base 2500 -> subtotal 5000 -> exactly 50 points.
    ctx = fx.setup_paid_order(base_price_cents=2500, num_seats=2)
    member = get_success_data(api.get_member(ctx["member"]["id"], MANAGER))
    assert member["loyalty_points"] == 50
    assert member["tier"] == "SILVER"


def test_tier_stays_bronze_below_fifty_points(api):
    """PRD §3.3: "otherwise SILVER when the balance is at least 50 points,
    otherwise BRONZE."

    Design: Difficulty/boundary_precision_check/loyalty_tier_silver_boundary_exactly_50
    """
    # 1 STANDARD seat base 4900 -> subtotal 4900 -> 49 points (below 50).
    ctx = fx.setup_paid_order(base_price_cents=4900, num_seats=1)
    member = get_success_data(api.get_member(ctx["member"]["id"], MANAGER))
    assert member["loyalty_points"] == 49
    assert member["tier"] == "BRONZE"


# ===========================================================================
# Difficulty/boundary_precision_check/empty_seat_ids_rejected_on_order_create
# ===========================================================================

def test_empty_seat_ids_rejected_on_order_create(api):
    """PRD §3.4: "the system requires that at least one seat be requested — an empty
    seat_ids array is rejected with ERR_NO_SEATS_SELECTED."

    Design: Difficulty/boundary_precision_check/empty_seat_ids_rejected_on_order_create
    """
    ctx = fx.setup_on_sale_showtime(base_price_cents=1000)
    member = fx.make_member()
    resp = api.create_order(
        ctx["showtime"]["id"],
        {"member_id": member["id"], "seat_ids": [], "expected_showtime_version": ctx["showtime"]["version"]},
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_NO_SEATS_SELECTED.value)


def test_single_seat_order_create_succeeds(api):
    """PRD §3.4: "When these checks pass, the system places one HELD Ticket per
    requested seat and flips each of those seats from FREE to HELD occupancy."

    Design: Difficulty/boundary_precision_check/empty_seat_ids_rejected_on_order_create
    """
    ctx = fx.setup_on_sale_showtime(base_price_cents=1000)
    member = fx.make_member()
    order = fx.create_held_order(ctx["showtime"], member, ctx["seat_ids"][:1])
    assert order["status"] == "HELD"
    assert len(order["seat_ids"]) == 1


# ===========================================================================
# Difficulty/cross_entity_state_dependency/exchange_target_showtime_must_be_on_sale
# ===========================================================================

def test_exchange_to_scheduled_target_rejected(api):
    """PRD §3.7: "The target showtime must be ON_SALE with the current time before
    its starts_at, and every requested new seat must currently be FREE on the
    target"

    Design: Difficulty/cross_entity_state_dependency/exchange_target_showtime_must_be_on_sale
    """
    # Source: PAID order on an ON_SALE showtime; target: a SCHEDULED (never opened) showtime.
    ctx = fx.setup_paid_order(base_price_cents=1000, num_seats=1, starts_at="2026-06-10T20:00:00.000Z")
    order = ctx["order"]

    aud_t = fx.make_auditorium(name="Hall 2", seat_count=4, turnaround_minutes=20)
    target_st = fx.schedule_showtime(aud_t["id"], ctx["film"]["id"], starts_at="2026-06-11T20:00:00.000Z")
    target_seats = fx.get_seat_ids(target_st["id"], count=1)

    resp = api.exchange_order(
        order["id"], {"new_showtime_id": target_st["id"], "new_seat_ids": target_seats}, AGENT
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    reread = get_success_data(api.get_order(order["id"], MANAGER))
    assert reread["status"] == "PAID"


def test_exchange_to_cancelled_target_rejected(api):
    """PRD §3.7: "The target showtime must be ON_SALE with the current time before
    its starts_at, and every requested new seat must currently be FREE on the
    target"
    PRD §3.8: "The screening moves to CANCELLED, a terminal status, and the
    consequences differ by where it started."

    Design: Difficulty/cross_entity_state_dependency/exchange_target_showtime_must_be_on_sale
    """
    # Source: PAID order on an ON_SALE showtime. Target: a showtime that was opened
    # then CANCELLED, so it is no longer ON_SALE.
    ctx = fx.setup_paid_order(base_price_cents=1000, num_seats=1, starts_at="2026-06-10T20:00:00.000Z")
    order = ctx["order"]

    aud_t = fx.make_auditorium(name="Hall 2", seat_count=4, turnaround_minutes=20)
    target_st = fx.schedule_showtime(aud_t["id"], ctx["film"]["id"], starts_at="2026-06-11T20:00:00.000Z")
    target_open = fx.open_showtime(target_st["id"])
    target_seats = fx.get_seat_ids(target_st["id"], count=1)
    get_success_data(
        api.cancel_showtime(target_st["id"], {"expected_showtime_version": target_open["version"]}, MANAGER)
    )

    resp = api.exchange_order(
        order["id"], {"new_showtime_id": target_st["id"], "new_seat_ids": target_seats}, AGENT
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    reread = get_success_data(api.get_order(order["id"], MANAGER))
    assert reread["status"] == "PAID"


# ===========================================================================
# Difficulty/cross_entity_state_dependency/film_end_run_blocked_by_open_showtime
# ===========================================================================

def test_film_end_run_blocked_while_showtime_on_sale(api):
    """PRD §3.1: "A manager may end a film's run, moving it from RUNNING to ENDED;
    this is permitted only while the film is RUNNING and only when no screening of
    that film remains in either SCHEDULED or ON_SALE state, otherwise the request is
    rejected with ERR_INVALID_STATE."

    Design: Difficulty/cross_entity_state_dependency/film_end_run_blocked_by_open_showtime
    """
    # Film becomes RUNNING when its first showtime opens; that showtime stays ON_SALE.
    ctx = fx.setup_on_sale_showtime(base_price_cents=1000)
    resp = api.end_film_run(ctx["film"]["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    reread = get_success_data(api.get_film(ctx["film"]["id"], MANAGER))
    assert reread["status"] == "RUNNING"


def test_film_end_run_blocked_while_showtime_scheduled(api):
    """PRD §3.1: "this is permitted only while the film is RUNNING and only when no
    screening of that film remains in either SCHEDULED or ON_SALE state, otherwise
    the request is rejected with ERR_INVALID_STATE."

    Design: Difficulty/cross_entity_state_dependency/film_end_run_blocked_by_open_showtime
    """
    # Open one showtime (film -> RUNNING), then schedule a second that stays SCHEDULED.
    ctx = fx.setup_on_sale_showtime(base_price_cents=1000)
    aud2 = fx.make_auditorium(name="Hall 2", seat_count=4, turnaround_minutes=20)
    fx.schedule_showtime(aud2["id"], ctx["film"]["id"], starts_at="2026-06-12T20:00:00.000Z")

    resp = api.end_film_run(ctx["film"]["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Difficulty/resource_temporal_overlap/auditorium_double_book_with_turnaround_buffer
# ===========================================================================

def test_new_showtime_within_turnaround_buffer_rejected(api):
    """PRD §2.10: "the system treats each screening's occupancy as the half-open
    interval from its starts_at up to but not including its ends_at, and additionally
    reserves the turnaround buffer after the end. A new screening may not overlap any
    existing non-cancelled screening in the same auditorium once the buffer is taken
    into account."

    Design: Difficulty/resource_temporal_overlap/auditorium_double_book_with_turnaround_buffer
    """
    base = fx.setup_base(seat_count=4)  # turnaround_minutes default 20
    aud_id = base["auditorium"]["id"]
    film_id = base["film"]["id"]
    # Existing 20:00, runtime 90 + pad 15 -> ends 21:45; +20 turnaround -> blocked to 22:05.
    fx.schedule_showtime(aud_id, film_id, starts_at="2026-06-10T20:00:00.000Z",
                         pricing_profile="STANDARD", base_price_cents=1000)
    # New start at 22:00 is inside the 22:05 buffer boundary.
    payload = create_showtime_payload(film_id, "2026-06-10T22:00:00.000Z",
                                      pricing_profile="STANDARD", base_price_cents=1000)
    resp = api.create_showtime(aud_id, payload, MANAGER)
    validate_error(resp, ApiErrorId.ERR_AUDITORIUM_DOUBLE_BOOKED.value)


def test_new_showtime_after_turnaround_buffer_allowed(api):
    """PRD §3.2: "The new screening, together with its trailing turnaround buffer
    drawn from the auditorium's turnaround_minutes, must not overlap the half-open
    interval of any existing non-cancelled screening in the same room; an overlap
    is rejected with ERR_AUDITORIUM_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/auditorium_double_book_with_turnaround_buffer
    """
    base = fx.setup_base(seat_count=4)
    aud_id = base["auditorium"]["id"]
    film_id = base["film"]["id"]
    fx.schedule_showtime(aud_id, film_id, starts_at="2026-06-10T20:00:00.000Z",
                         pricing_profile="STANDARD", base_price_cents=1000)
    # 22:05 is exactly at the buffer boundary (ends 21:45 + 20m); half-open so allowed.
    payload = create_showtime_payload(film_id, "2026-06-10T22:05:00.000Z",
                                      pricing_profile="STANDARD", base_price_cents=1000)
    second = get_success_data(api.create_showtime(aud_id, payload, MANAGER))
    assert second["status"] == "SCHEDULED"


# ===========================================================================
# Difficulty/resource_temporal_overlap/member_double_book_zero_buffer_overlap
# ===========================================================================

def test_member_double_book_overlapping_showtimes_rejected(api):
    """PRD §3.4: "the purchasing member must not already hold a live order — one in
    HELD or PAID status — on a different showtime whose half-open interval overlaps
    this screening's interval, because a member cannot be seated at two films
    simultaneously; such a clash is rejected with ERR_MEMBER_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/member_double_book_zero_buffer_overlap
    """
    # Two showtimes in different auditoriums: X 20:00-21:45, Y 20:30-22:15 (overlap).
    ctx = fx.setup_two_on_sale_showtimes(
        base_price_cents=1000,
        starts_at_x="2026-06-10T20:00:00.000Z",
        starts_at_y="2026-06-10T20:30:00.000Z",
    )
    member = fx.make_member()
    # Member holds a live order on X.
    fx.create_held_order(ctx["showtime_x"], member, ctx["seats_x"][:1])
    # Attempt an order on Y (overlapping interval).
    resp = api.create_order(
        ctx["showtime_y"]["id"],
        {"member_id": member["id"], "seat_ids": ctx["seats_y"][:1],
         "expected_showtime_version": ctx["showtime_y"]["version"]},
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_MEMBER_DOUBLE_BOOKED.value)


def test_member_non_overlapping_showtimes_allowed(api):
    """PRD §3.4: "Note that this member overlap is a pure half-open interval test
    with no buffer, distinct from the auditorium double-booking check, which
    additionally reserves the turnaround buffer."

    Design: Difficulty/resource_temporal_overlap/member_double_book_zero_buffer_overlap
    """
    # X 20:00-21:45; Y starts 21:45 (exactly at X's end; half-open -> no overlap).
    ctx = fx.setup_two_on_sale_showtimes(
        base_price_cents=1000,
        starts_at_x="2026-06-10T20:00:00.000Z",
        starts_at_y="2026-06-10T21:45:00.000Z",
    )
    member = fx.make_member()
    fx.create_held_order(ctx["showtime_x"], member, ctx["seats_x"][:1])
    order_y = fx.create_held_order(ctx["showtime_y"], member, ctx["seats_y"][:1])
    assert order_y["status"] == "HELD"
