"""Booking price quote, gratuity, and group-size tier boundaries.

Queue A: combinatorial_formula (round-then-multiply, gratuity-excludes-charter).
Queue B: calculations section (tier boundary party3 vs party4).
"""
from test_helpers import (
    validate_success,
    make_operator_headers, make_guest_headers,
    get_success_data,
    create_add_on_payload, create_booking_payload, create_guest_payload,
    setup_scheduled_departure,
    assert_booking_quote,
)
from test_helpers import api_client

OP = make_operator_headers()


# ---------------------------------------------------------------------------
# Queue A: combinatorial_formula
# ---------------------------------------------------------------------------
def test_quote_round_per_person_then_multiply_mode_b(api):
    """PRD §3.7: "The discounted per-person fare is computed by multiplying
    `base_price_per_person_cents` by one minus the selected tier rate and
    rounding that per-person figure half up to whole cents first; the seats
    total is then that rounded per-person fare multiplied by `party_size`. This
    round-then-multiply order is part of the contract and must not be reversed."
    PRD §3.7: "The add-on total is the add-on's `price_per_person_cents`
    multiplied by `party_size` when an add-on is attached, and 0 otherwise."

    Design: Difficulty/combinatorial_formula/quote_round_per_person_then_multiply_mode_b
    """
    # base 9000, party 6 -> tier 5%: disc_pp = round(9000*0.95)=8550; seats=8550*6=51300
    # add-on 1500*6=9000; subtotal = 60300 (non-charter).
    s = setup_scheduled_departure(seat_capacity=12,
                                  product_overrides={"theme": "FOOD",
                                                     "base_price_per_person_cents": 9000,
                                                     "gratuity_pct": 0.18})
    addon = get_success_data(api.create_add_on(
        create_add_on_payload(s["product"]["id"], name="Cheese",
                              price_per_person_cents=1500), OP))
    guest = get_success_data(api.create_guest(create_guest_payload(), OP))
    booking = validate_success(api.create_booking(
        create_booking_payload(s["departure"]["id"], guest["id"], s["pickup"]["id"], 6,
                               add_on_id=addon["id"]),
        make_guest_headers(guest["id"])), expected_status=201)
    assert booking["subtotal_cents"] == 60300, \
        f"expected subtotal_cents 60300, got {booking['subtotal_cents']}"


def test_gratuity_circular_dep_excludes_charter_mode_c(api):
    """PRD §3.7: "the gratuity base is the seats total plus the add-on total —
    the charter component is not part of it. The booking's `gratuity_cents` is
    that gratuity base multiplied by the tour product's `gratuity_pct`, rounded
    half up to whole cents. The booking's `total_cents` is then `subtotal_cents`
    plus `gratuity_cents`"
    PRD §3.7: "The charter component is the tour product's `charter_fee_cents`
    when the departure is a private charter, and 0 otherwise. The booking's
    `subtotal_cents` is the sum of the seats total, the add-on total, and the
    charter component."

    Design: Difficulty/combinatorial_formula/gratuity_circular_dep_excludes_charter_mode_c
    """
    # base 9000, party 12 -> tier 15%: disc_pp=round(9000*0.85)=7650; seats=7650*12=91800
    # charter 5000 -> subtotal=96800; gratuity_base=91800; gratuity=round(91800*0.18)=16524
    # total=96800+16524=113324.
    s = setup_scheduled_departure(seat_capacity=12, is_private_charter=True,
                                  product_overrides={"theme": "MIXED",
                                                     "base_price_per_person_cents": 9000,
                                                     "gratuity_pct": 0.18,
                                                     "charter_fee_cents": 5000})
    guest = get_success_data(api.create_guest(create_guest_payload(), OP))
    booking = validate_success(api.create_booking(
        create_booking_payload(s["departure"]["id"], guest["id"], s["pickup"]["id"], 12),
        make_guest_headers(guest["id"])), expected_status=201)
    assert booking["subtotal_cents"] == 96800, \
        f"expected subtotal_cents 96800, got {booking['subtotal_cents']}"
    assert booking["gratuity_cents"] == 16524, \
        f"expected gratuity_cents 16524, got {booking['gratuity_cents']}"
    assert booking["total_cents"] == 113324, \
        f"expected total_cents 113324, got {booking['total_cents']}"
    assert_booking_quote(booking)


# ---------------------------------------------------------------------------
# Queue B: calculations (tier boundary)
# ---------------------------------------------------------------------------
def test_pricing_tier_boundary_party3_vs_party4(api):
    """PRD §3.7: "a party of at least 4 but fewer than 8 takes 5 percent off,
    and a party of fewer than 4 takes no discount."

    Design: Corner/calculations/pricing_tier_boundary_party3_vs_party4
    """
    # base 8000. party 3 -> 0% : 8000*3 = 24000. party 4 -> 5% : round(8000*0.95)=7600; *4=30400.
    s = setup_scheduled_departure(seat_capacity=20,
                                  product_overrides={"base_price_per_person_cents": 8000,
                                                     "gratuity_pct": 0.18})
    g1 = get_success_data(api.create_guest(create_guest_payload(full_name="G1"), OP))
    g2 = get_success_data(api.create_guest(create_guest_payload(full_name="G2"), OP))
    b1 = validate_success(api.create_booking(
        create_booking_payload(s["departure"]["id"], g1["id"], s["pickup"]["id"], 3),
        make_guest_headers(g1["id"])), expected_status=201)
    b2 = validate_success(api.create_booking(
        create_booking_payload(s["departure"]["id"], g2["id"], s["pickup"]["id"], 4),
        make_guest_headers(g2["id"])), expected_status=201)
    assert b1["subtotal_cents"] == 24000, \
        f"party 3 expected subtotal 24000, got {b1['subtotal_cents']}"
    assert b2["subtotal_cents"] == 30400, \
        f"party 4 expected subtotal 30400, got {b2['subtotal_cents']}"
