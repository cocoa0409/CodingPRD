"""Inventory holds, dynamic seat pricing, presale/capacity gates, seat-hold overlap,
seat-count conservation, and hold-create optimistic concurrency."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
    create_hold_payload,
    make_buyer_headers,
    register_buyer, create_event, create_price_level, create_seat,
    setup_onsale_event, setup_presale_event, setup_admitted_buyer_on_onsale_event,
    admit_buyer, hold_seats, create_order, pay_order, tickets_for_order,
    event_version, get_event, set_clock,
)

BOX = TEST_USERS["box_office_headers"]


# ─── local helpers ────────────────────────────────────────────────────────
def _buy_seat(api, ev_id, seat_id, delivery_method="MOBILE"):
    """Fresh buyer purchases a single seat end-to-end. Returns (buyer, order, tickets)."""
    buyer = register_buyer()
    admit_buyer(ev_id, buyer["id"])
    hold = hold_seats(ev_id, [seat_id], buyer["id"])
    order = create_order(hold["id"], buyer["id"], delivery_method)
    pay_order(order["id"], buyer["id"])
    tickets = tickets_for_order(order["id"], buyer["id"])
    return buyer, order, tickets


def _setup_two_sold_dynamic(api):
    """Dynamic base-10000 level, 4 seats; two seats sold to drive pct_sold to 50.
    Returns (event_dict, first_buyer_ticket)."""
    env = setup_onsale_event(num_seats=4, base_face_value_cents=10000,
                             dynamic_pricing_enabled=True)
    ev_id = env["event"]["id"]
    _, _, t1_list = _buy_seat(api, ev_id, env["seats"][0]["id"])  # sold at pct 0 -> locked 10000
    _buy_seat(api, ev_id, env["seats"][1]["id"])                  # drives pct_sold to 50
    return env, t1_list[0]


# ─── Difficulty: locked_final vs current_dynamic ──────────────────────────
def test_ticket_face_is_locked_at_order_creation_tier(api):
    """PRD §3.3: "a hold's `face_subtotal_cents`, an order's `face_total_cents`, and a
    ticket's `face_value_cents` are all snapshotted at their creation against the then-current
    tier". A ticket bought at pct_sold 0 keeps face 10000 even after the show sells through.

    Design: Difficulty/dual_variant_calc/seat_price_locked_final_vs_current_dynamic
    """
    env, t1 = _setup_two_sold_dynamic(api)
    ticket = validate_success(api.get_ticket(t1["id"], BOX), 200)
    assert ticket["face_value_cents"] == 10000, (
        f"locked ticket face should stay 10000, got {ticket['face_value_cents']}"
    )


def test_available_seat_reflects_current_dynamic_tier(api):
    """PRD §3.3: "from 50 percent up to but not including 80 percent it is 1.25". A still
    AVAILABLE base-10000 seat, read live at pct_sold 50, prices to 12500.

    Design: Difficulty/dual_variant_calc/seat_price_locked_final_vs_current_dynamic
    """
    env, _ = _setup_two_sold_dynamic(api)
    still_available = env["seats"][2]["id"]
    seat = validate_success(api.get_seat(still_available, BOX), 200)
    assert seat["current_face_value_cents"] == 12500, (
        f"available seat at pct_sold 50 should read 12500, got {seat['current_face_value_cents']}"
    )
    event = validate_success(api.get_event(env["event"]["id"], BOX), 200)
    assert event["pct_sold"] == 50.0


# ─── Difficulty: boundary at exactly 50% ──────────────────────────────────
def test_dynamic_price_enters_125_tier_at_exactly_50_pct(api):
    """PRD §3.3: "from 50 percent up to but not including 80 percent it is 1.25". PRD §3.3:
    "The 50-percent and 80-percent figures are the tier boundaries, each inclusive at its
    lower edge."

    Design: Difficulty/boundary_precision_check/dynamic_price_tier_at_exactly_50_pct
    """
    env, _ = _setup_two_sold_dynamic(api)
    seat = validate_success(api.get_seat(env["seats"][2]["id"], BOX), 200)
    assert seat["current_face_value_cents"] == 12500


def test_pct_sold_is_exactly_50_after_two_of_four_sold(api):
    """PRD §2.8: "The event's `pct_sold` is derived from them and drives dynamic pricing".
    PRD §2.8: "for any event the counts always satisfy: available seats plus held seats plus
    sold seats equals total capacity." Two of four seats sold is exactly the 50-percent point.

    Design: Difficulty/boundary_precision_check/dynamic_price_tier_at_exactly_50_pct
    """
    env, _ = _setup_two_sold_dynamic(api)
    event = validate_success(api.get_event(env["event"]["id"], BOX), 200)
    assert event["pct_sold"] == 50.0
    assert event["seats_sold"] == 2 and event["total_capacity"] == 4


# ─── Difficulty: platinum floor + tier + clamp interaction ────────────────
def test_platinum_seat_prices_to_floor_at_50_pct(api):
    """PRD §3.3: "If the seat's price level is platinum, the multiplier is then raised to
    whichever is larger, the tier multiplier or the platinum floor of 2.00 — so a platinum
    seat never prices below twice its base even in a cold sale."

    Design: Difficulty/combinatorial_formula/dynamic_seat_price_tiered_platinum_clamp
    """
    env = setup_onsale_event(num_seats=4, base_face_value_cents=10000,
                             dynamic_pricing_enabled=True, is_platinum=True)
    ev_id = env["event"]["id"]
    _buy_seat(api, ev_id, env["seats"][0]["id"])
    _buy_seat(api, ev_id, env["seats"][1]["id"])  # pct_sold -> 50
    event = validate_success(api.get_event(ev_id, BOX), 200)
    assert event["pct_sold"] == 50.0
    seat = validate_success(api.get_seat(env["seats"][2]["id"], BOX), 200)
    # max(1.25 tier, 2.00 floor) = 2.00 -> 20000, within clamp [10000, 30000].
    assert seat["current_face_value_cents"] == 20000, (
        f"platinum floor should price to 20000, got {seat['current_face_value_cents']}"
    )


def test_platinum_floor_applies_even_in_cold_sale(api):
    """PRD §3.3: "If the seat's price level is platinum, the multiplier is then raised to
    whichever is larger, the tier multiplier or the platinum floor of 2.00 — so a platinum
    seat never prices below twice its base even in a cold sale." At pct_sold 0 the floor
    still beats the 1.00 tier.

    Design: Difficulty/combinatorial_formula/dynamic_seat_price_tiered_platinum_clamp
    """
    event = create_event()
    pl = create_price_level(event["id"], base_face_value_cents=10000, is_platinum=True,
                            dynamic_pricing_enabled=True)
    seat = create_seat(event["id"], pl["id"])
    read = validate_success(api.get_seat(seat["id"], BOX), 200)
    assert read["current_face_value_cents"] == 20000


# ─── Corner: dynamic pricing edge readings ────────────────────────────────
def test_seat_current_face_defaults_to_base_when_low_demand(api):
    """PRD §3.3: "below 50 percent sold the multiplier is 1.00". With no sales (pct_sold 0)
    a dynamic base-10000 seat reads its base face value.

    Design: Corner/entities/seat_current_face_defaults_to_base_when_low_demand
    """
    event = create_event()
    pl = create_price_level(event["id"], base_face_value_cents=10000,
                            dynamic_pricing_enabled=True)
    seat = create_seat(event["id"], pl["id"])
    read = validate_success(api.get_seat(seat["id"], BOX), 200)
    assert read["current_face_value_cents"] == 10000
    assert read["status"] == "AVAILABLE"


def test_seat_price_dynamic_disabled_equals_base(api):
    """PRD §3.1: "when dynamic pricing is disabled the seats in that level always price at
    exactly their base face value regardless of how the show is selling."

    Design: Corner/calculations/seat_price_dynamic_disabled_equals_base
    """
    env = setup_onsale_event(num_seats=2, base_face_value_cents=9990,
                             dynamic_pricing_enabled=False)
    ev_id = env["event"]["id"]
    _buy_seat(api, ev_id, env["seats"][0]["id"])  # pct_sold -> 50
    event = validate_success(api.get_event(ev_id, BOX), 200)
    assert event["pct_sold"] == 50.0
    seat = validate_success(api.get_seat(env["seats"][1]["id"], BOX), 200)
    assert seat["current_face_value_cents"] == 9990


# ─── Difficulty: empty seat selection boundary ────────────────────────────
def test_empty_seat_ids_rejected_on_hold_create(api):
    """PRD §3.3: "An empty `seat_ids` array is rejected with `ERR_EMPTY_SEAT_SELECTION`."

    Design: Difficulty/boundary_precision_check/empty_seat_ids_rejected_on_hold_create
    """
    env = setup_admitted_buyer_on_onsale_event(num_seats=1)
    ev_id = env["event"]["id"]
    res = api.create_hold(
        ev_id,
        create_hold_payload([], env["buyer"]["id"], event_version(ev_id)),
        make_buyer_headers(env["buyer"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_EMPTY_SEAT_SELECTION.value, expected_status=422)


def test_single_seat_hold_succeeds_just_above_empty_boundary(api):
    """PRD §3.3: "Creating a hold names the seats through a non-empty `seat_ids` array and
    the acting `buyer_id`". One seat is the smallest legal (non-empty) selection and yields
    an ACTIVE hold.

    Design: Difficulty/boundary_precision_check/empty_seat_ids_rejected_on_hold_create
    """
    env = setup_admitted_buyer_on_onsale_event(num_seats=1)
    ev_id = env["event"]["id"]
    hold = validate_success(
        api.create_hold(
            ev_id,
            create_hold_payload([env["seats"][0]["id"]], env["buyer"]["id"], event_version(ev_id)),
            make_buyer_headers(env["buyer"]["id"]),
        ),
        201,
    )
    assert hold["status"] == "ACTIVE"
    assert hold["seat_ids"] == [env["seats"][0]["id"]]


# ─── Corner: capacity + presale gates ─────────────────────────────────────
def test_hold_over_seat_limit_returns_capacity_exceeded(api):
    """PRD §3.3: "A hold may cover at most two seats — the per-hold cap `MAX_SEATS_PER_HOLD`
    is 2 — and a request for more is rejected with `ERR_CAPACITY_EXCEEDED`."

    Design: Corner/validations/hold_over_seat_limit_returns_capacity_exceeded
    """
    env = setup_admitted_buyer_on_onsale_event(num_seats=3)
    ev_id = env["event"]["id"]
    seat_ids = [s["id"] for s in env["seats"]]
    res = api.create_hold(
        ev_id,
        create_hold_payload(seat_ids, env["buyer"]["id"], event_version(ev_id)),
        make_buyer_headers(env["buyer"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CAPACITY_EXCEEDED.value, expected_status=422)


def test_presale_hold_invalid_code_returns_invalid_presale_code(api):
    """PRD §3.2: "once that count reaches `presale_max_uses`, or if the supplied code is
    missing or wrong, the hold is rejected with `ERR_INVALID_PRESALE_CODE`."

    Design: Corner/validations/presale_hold_invalid_code_returns_invalid_presale_code
    """
    env = setup_presale_event(num_seats=1, presale_code="SECRET", presale_max_uses=5)
    buyer = register_buyer()
    ev_id = env["event"]["id"]
    payload = create_hold_payload([env["seats"][0]["id"]], buyer["id"], event_version(ev_id))
    payload["presale_code"] = "WRONG"
    res = api.create_hold(ev_id, payload, make_buyer_headers(buyer["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_PRESALE_CODE.value, expected_status=409)


# ─── Corner: hold not-found + OCC stale event version ─────────────────────
def test_hold_get_nonexistent_returns_hold_not_found(api):
    """PRD §2.9: "an unresolved `hold_id` yields `ERR_HOLD_NOT_FOUND`; an unresolved
    `order_id` yields `ERR_ORDER_NOT_FOUND`".

    Design: Corner/errors/hold_get_nonexistent_returns_hold_not_found
    """
    res = api.get_hold(NON_EXISTENT_UUID, BOX)
    validate_error(res, ApiErrorId.ERR_HOLD_NOT_FOUND.value, expected_status=404)


def test_hold_create_stale_event_version_returns_412(api):
    """PRD §2.7: "A request that creates an inventory hold against an event must carry
    `expected_event_version`, a non-optional field whose value is the `version` of the target
    `Event` as the client last observed it." PRD §2.7: "If that value does not match the
    event's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/hold_create_stale_event_version_returns_412
    """
    env = setup_admitted_buyer_on_onsale_event(num_seats=2)
    ev_id = env["event"]["id"]
    buyer_id = env["buyer"]["id"]
    stale_version = env["event"]["version"]  # version observed before any hold

    # First hold consumes `stale_version` and advances the event's version.
    validate_success(
        api.create_hold(
            ev_id,
            create_hold_payload([env["seats"][0]["id"]], buyer_id, stale_version),
            make_buyer_headers(buyer_id),
        ),
        201,
    )
    # Second hold still carries the now-stale version.
    res = api.create_hold(
        ev_id,
        create_hold_payload([env["seats"][1]["id"]], buyer_id, stale_version),
        make_buyer_headers(buyer_id),
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)


# ─── Difficulty: seat-hold half-open overlap ──────────────────────────────
def _onsale_two_admitted_b1_holds(api):
    set_clock("2026-06-01T10:00:00Z")
    b1, b2 = register_buyer(), register_buyer()
    env = setup_onsale_event(num_seats=1, hold_ttl_minutes=15)
    ev_id = env["event"]["id"]
    admit_buyer(ev_id, b1["id"])
    admit_buyer(ev_id, b2["id"])
    h1 = hold_seats(ev_id, [env["seats"][0]["id"]], b1["id"])  # created at 10:00, expires 10:15
    return env, b1, b2, h1


def test_overlapping_active_hold_rejects_second_buyer(api):
    """PRD §3.3: "no other `ACTIVE`, unexpired hold may already cover it; a seat that fails
    this is rejected with `ERR_SEAT_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/seat_hold_overlap_half_open_expiry
    """
    env, b1, b2, h1 = _onsale_two_admitted_b1_holds(api)
    ev_id = env["event"]["id"]
    res = api.create_hold(
        ev_id,
        create_hold_payload([env["seats"][0]["id"]], b2["id"], event_version(ev_id)),
        make_buyer_headers(b2["id"]),
    )
    validate_error(res, ApiErrorId.ERR_SEAT_UNAVAILABLE.value, expected_status=409)


def test_seat_free_again_after_sweep_past_expiry(api):
    """PRD §2.5: "a hold is considered expired once the clock has reached or passed its
    `expires_at`". PRD §3.3: "any `ACTIVE` hold whose `expires_at` is at or before the
    current clock moves to `EXPIRED` and returns its seats to `AVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/seat_hold_overlap_half_open_expiry
    """
    env, b1, b2, h1 = _onsale_two_admitted_b1_holds(api)
    ev_id = env["event"]["id"]
    set_clock("2026-06-01T10:20:00Z")  # strictly past expires_at (10:15)
    validate_success(api.sweep_holds(ev_id, BOX), 200)

    swept_h1 = validate_success(api.get_hold(h1["id"], BOX), 200)
    assert swept_h1["status"] == "EXPIRED"

    h2 = validate_success(
        api.create_hold(
            ev_id,
            create_hold_payload([env["seats"][0]["id"]], b2["id"], event_version(ev_id)),
            make_buyer_headers(b2["id"]),
        ),
        201,
    )
    assert h2["status"] == "ACTIVE"


# ─── Difficulty: seat-count conservation across hold/release ──────────────
def test_seat_counts_while_two_seats_held(api):
    """PRD §2.8: "for any event the counts always satisfy: available seats plus held seats
    plus sold seats equals total capacity."

    Design: Difficulty/compensating_invariant/seat_count_conservation_hold_then_release
    """
    env = setup_admitted_buyer_on_onsale_event(num_seats=2)
    ev_id = env["event"]["id"]
    seat_ids = [s["id"] for s in env["seats"]]
    hold_seats(ev_id, seat_ids, env["buyer"]["id"])

    event = validate_success(api.get_event(ev_id, BOX), 200)
    assert event["seats_available"] == 0
    assert event["seats_held"] == 2
    assert event["seats_sold"] == 0
    assert (event["seats_available"] + event["seats_held"] + event["seats_sold"]
            == event["total_capacity"] == 2)


def test_seat_counts_restored_after_release(api):
    """PRD §3.3: a released hold is "moving it from `ACTIVE` to `RELEASED` and returning its
    seats from `HELD` to `AVAILABLE`". PRD §2.8: "for any event the counts always satisfy:
    available seats plus held seats plus sold seats equals total capacity."

    Design: Difficulty/compensating_invariant/seat_count_conservation_hold_then_release
    """
    env = setup_admitted_buyer_on_onsale_event(num_seats=2)
    ev_id = env["event"]["id"]
    seat_ids = [s["id"] for s in env["seats"]]
    hold = hold_seats(ev_id, seat_ids, env["buyer"]["id"])

    validate_success(api.release_hold(hold["id"], make_buyer_headers(env["buyer"]["id"])), 200)
    event = validate_success(api.get_event(ev_id, BOX), 200)
    assert event["seats_available"] == 2
    assert event["seats_held"] == 0
    assert event["seats_sold"] == 0
    assert (event["seats_available"] + event["seats_held"] + event["seats_sold"]
            == event["total_capacity"] == 2)
