"""State machines that are not a straight line: the air block's unbounded
offer/counter cycle, and the traveler's three orthogonal dimensions."""

from __future__ import annotations

from test_helpers import (
    assign_room,
    confirm_traveler,
    counter_fare,
    create_air_block,
    enrol_traveler,
    offer_fare,
    open_departure,
    pay,
    program_with_departure,
    purchase_protection,
    quote_protection,
    read_air_block,
    api_client,
    get_success_data,
    TEST_USERS,
)

AIR_DESK = TEST_USERS["air_desk_agent"]


# ---------------------------------------------------------------------------
# Offer / counter / re-offer
# ---------------------------------------------------------------------------


def _negotiated_and_contracted_block():
    """Three carrier offers separated by two operator counters, then confirm."""
    _program, departure = program_with_departure()
    block = create_air_block(
        departure["id"],
        carrier_code="LY",
        seats_held=20,
        name_change_deadline_utc="2026-09-20T00:00:00Z",
        deposit_deadline_utc="2026-08-25T00:00:00Z",
    )
    offer_fare(block["id"], 850_000)
    counter_fare(block["id"], 790_000)
    offer_fare(block["id"], 820_000)
    counter_fare(block["id"], 800_000)
    offer_fare(block["id"], 810_000)
    confirmed = get_success_data(api_client.confirm_air_block(block["id"], AIR_DESK))
    return block, confirmed


def test_negotiation_round_counts_carrier_offers_and_ignores_operator_counters(api):
    """PRD §3.6: "The `OFFERED → COUNTERED → OFFERED` cycle may repeat without
    bound, so `negotiation_round` after three carrier offers separated by two
    counters is 3."

    Design: Difficulty/non_linear_state_machine/air_block_offer_counter_reoffer_cycle
    """
    _block, confirmed = _negotiated_and_contracted_block()

    assert confirmed["negotiation_round"] == 3
    assert confirmed["offered_fare_cents"] == 810_000
    assert confirmed["countered_fare_cents"] == 800_000


def test_confirming_a_block_freezes_the_standing_offer_as_the_contracted_fare(api):
    """PRD §3.6: "Confirmation freezes `contracted_fare_cents` at the standing
    `offered_fare_cents` and recomputes `seats_assigned`."

    Design: Difficulty/non_linear_state_machine/air_block_offer_counter_reoffer_cycle
    """
    block, confirmed = _negotiated_and_contracted_block()

    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["contracted_fare_cents"] == 810_000
    # No traveler has filed a ticketed name yet.
    assert confirmed["seats_assigned"] == 0

    reread = read_air_block(block["id"])
    assert reread["contracted_fare_cents"] == 810_000


# ---------------------------------------------------------------------------
# Three orthogonal traveler dimensions
# ---------------------------------------------------------------------------


def _traveler_advanced_on_all_three_dimensions():
    """Booking, money and insurance each move once, in that order."""
    stage = open_departure()
    traveler = enrol_traveler(
        stage["departure"]["id"], full_name="Marta Sen", date_of_birth="1980-05-05"
    )
    assign_room(traveler["id"])
    pay(traveler["id"], 50_000, method="CARD")
    protection = quote_protection(
        traveler["id"], plan_code="STANDARD", medical_limit_cents=3_000_000
    )
    purchased = purchase_protection(protection["id"])
    confirmed = confirm_traveler(traveler["id"])
    return confirmed, purchased


def test_booking_money_and_protection_dimensions_each_hold_their_own_state(api):
    """PRD §3.5: "A **Pilgrim** is one traveler on one departure, and the row
    deliberately carries **three orthogonal state dimensions** that advance
    independently and must never be collapsed into one."

    Design: Difficulty/non_linear_state_machine/pilgrim_three_parallel_dimensions_advance_independently
    """
    confirmed, _purchased = _traveler_advanced_on_all_three_dimensions()

    assert confirmed["booking_status"] == "CONFIRMED"
    # A single deposit leaves the money dimension at DEPOSIT_PAID.
    assert confirmed["payment_status"] == "DEPOSIT_PAID"
    assert confirmed["protection_status"] == "PURCHASED"
    assert confirmed["invoice_total_cents"] == 577_168
    assert confirmed["cash_applied_cents"] == 50_000


def test_purchasing_protection_copies_the_premium_onto_the_traveler(api):
    """PRD §3.8: "`base_premium_cents` is `insured_trip_cost_cents` multiplied
    by the band rate in basis points, divided by 10,000, rounded half up."

    Design: Difficulty/non_linear_state_machine/pilgrim_three_parallel_dimensions_advance_independently
    """
    confirmed, purchased = _traveler_advanced_on_all_three_dimensions()

    # Age 46 at departure falls in band B at 620bp: 577168 * 620 / 10000.
    assert purchased["age_band"] == "B"
    assert purchased["base_premium_cents"] == 35_784
    assert purchased["medical_uplift_cents"] == 0
    assert purchased["waiver_surcharge_cents"] == 0
    assert purchased["premium_cents"] == 35_784
    assert confirmed["protection_premium_cents"] == 35_784
