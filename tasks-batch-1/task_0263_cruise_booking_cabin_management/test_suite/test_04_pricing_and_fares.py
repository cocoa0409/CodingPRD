"""Pricing: occupancy-tiered fares, per-guest tax rounding, deposits, group fares.

Covers the non-linear occupancy fare branch, the round-per-guest-then-sum tax
order, the deposit floor-vs-percentage choice, guest-delete re-indexing, and the
provisional-vs-final group-fare divergence at confirm.
"""
from test_helpers import (
    validate_success, get_success_data,
    TEST_USERS,
    create_guest_payload, make_guest_user_headers,
    create_quote_booking, get_booking,
    setup_held_group_block, create_booking, add_guests, make_and_capture_payment,
)

RM = TEST_USERS["revenue_manager_headers"]


def _occupancy_index_one_guest(api, booking_id):
    guests = get_success_data(api.list_guests(RM, params={"booking_id": booking_id}))
    if isinstance(guests, dict):
        guests = guests.get("data", guests)
    return min(guests, key=lambda g: g["occupancy_index"])


# ===========================================================================
# Difficulty: combinatorial occupancy fare + tax rounding order
# ===========================================================================
def test_occupancy_tiered_fare_third_guest_reduced(api):
    """PRD 3.4: "a guest at position 3 or 4 has a `base_fare_cents` equal to the full
    base fare multiplied by the third-and-fourth-occupant rate of 0.55, rounded
    half-up to whole cents."

    Design: Difficulty/combinatorial_formula/occupancy_tiered_fare_nonlinear_three_inputs
    """
    sailing, category, booking = create_quote_booking(
        "guest-3", num_guests=2, num_cabins=2,
        guests=[("C One", 40), ("C Two", 38)],
    )
    resp = api.create_guest(create_guest_payload(booking["id"], "C Three", 11),
                            make_guest_user_headers("guest-3"))
    g3 = validate_success(resp, expected_status=201)
    assert g3["occupancy_index"] == 3
    assert g3["base_fare_cents"] == 65945


def test_occupancy_tiered_fare_total_is_nonlinear(api):
    """PRD 3.4: "A guest at `occupancy_index` 1 or 2 has a `base_fare_cents` equal to
    the full base fare". PRD 3.4: "The `fare_total_cents` is the sum over all guests
    of their `final_fare_cents`."

    Design: Difficulty/combinatorial_formula/occupancy_tiered_fare_nonlinear_three_inputs
    """
    sailing, category, booking = create_quote_booking(
        "guest-3b", num_guests=2, num_cabins=2,
        guests=[("C One", 40), ("C Two", 38)],
    )
    get_success_data(api.create_guest(create_guest_payload(booking["id"], "C Three", 11),
                                      make_guest_user_headers("guest-3b")))
    after = get_booking(booking["id"])
    assert after["fare_total_cents"] == 305745  # 119900 + 119900 + 65945


def test_tax_port_round_per_guest_then_sum(api):
    """PRD 2.8: "per-guest fares and per-guest taxes are each rounded as they are
    computed, and the booking totals are formed by summing the already-rounded
    per-guest amounts without any further rounding."

    Design: Difficulty/combinatorial_formula/tax_port_round_per_guest_then_sum_pinned_order
    """
    sailing, category, booking = create_quote_booking(
        "guest-4", num_guests=2, num_cabins=2,
        guests=[("D One", 40), ("D Two", 38)],
    )
    resp = api.create_guest(create_guest_payload(booking["id"], "D Three", 12),
                            make_guest_user_headers("guest-4"))
    g3 = validate_success(resp, expected_status=201)
    assert g3["tax_port_cents"] == 16484  # half_up(65945*0.115)+8900


def test_tax_port_total_pinned_order_diverges_from_sum_then_round(api):
    """PRD 2.8: "taxes are rounded per guest and then summed; summing first and
    rounding once is not permitted."

    Design: Difficulty/combinatorial_formula/tax_port_round_per_guest_then_sum_pinned_order
    """
    sailing, category, booking = create_quote_booking(
        "guest-4b", num_guests=2, num_cabins=2,
        guests=[("D One", 40), ("D Two", 38)],
    )
    get_success_data(api.create_guest(create_guest_payload(booking["id"], "D Three", 12),
                                      make_guest_user_headers("guest-4b")))
    after = get_booking(booking["id"])
    # Round-per-guest-then-sum yields 61862, not the sum-then-round 61861.
    assert after["tax_port_total_cents"] == 61862
    assert after["booking_total_cents"] == 367607


# ===========================================================================
# Difficulty: provisional-vs-final group fare divergence
# ===========================================================================
def test_group_fare_provisional_while_deposit_held(api):
    """PRD 3.4: "While a booking is in `QUOTE` or `DEPOSIT_HELD`, `final_fare_cents`
    equals `base_fare_cents`; the rack fare stands with no group discount yet
    applied, even if the booking draws from a block."

    Design: Difficulty/dual_variant_calc/guest_fare_provisional_vs_final_group_diverges
    """
    sailing, category, _cabins, block = setup_held_group_block(num_cabins=4, block_size=2)
    booking = create_booking(sailing["id"], category["id"], "guest-2",
                             sailing["version"], group_block_id=block["id"])
    add_guests(booking["id"], "guest-2",
               [("G One", 41), ("G Two", 39), ("G Three", 9)])
    g1 = _occupancy_index_one_guest(api, booking["id"])
    assert g1["final_fare_cents"] == 119900  # provisional rack fare, no discount


def test_group_fare_final_after_confirm_applies_discount(api):
    """PRD 3.4: "Once a booking is `CONFIRMED` and carries a `group_block_id`,
    `final_fare_cents` is recomputed as `base_fare_cents` multiplied by one minus
    the block's `group_discount_pct`, rounded half-up to whole cents; for the same
    guest roster this final figure diverges from the provisional one."

    Design: Difficulty/dual_variant_calc/guest_fare_provisional_vs_final_group_diverges
    """
    sailing, category, _cabins, block = setup_held_group_block(num_cabins=4, block_size=2)
    booking = create_booking(sailing["id"], category["id"], "guest-2b",
                             sailing["version"], group_block_id=block["id"])
    add_guests(booking["id"], "guest-2b",
               [("G One", 41), ("G Two", 39), ("G Three", 9)])
    # Deposit 75000 (floor 25000*3), then final 241469 -> total 316469.
    make_and_capture_payment(booking["id"], "guest-2b", "DEPOSIT", 75000)
    get_success_data(api.hold_deposit(booking["id"], make_guest_user_headers("guest-2b")))
    make_and_capture_payment(booking["id"], "guest-2b", "FINAL", 241469)
    confirmed = get_success_data(
        api.confirm_booking(booking["id"], make_guest_user_headers("guest-2b"))
    )
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["fare_total_cents"] == 259883
    assert confirmed["booking_total_cents"] == 316469
    g1 = _occupancy_index_one_guest(api, booking["id"])
    assert g1["final_fare_cents"] == 101915  # half_up(119900*0.85)


# ===========================================================================
# Corner: deposit floor, guest-delete reindex
# ===========================================================================
def test_deposit_floor_per_guest_beats_percentage(api):
    """PRD 3.4: "The `deposit_due_cents` is the larger of those two components, so a
    small booking is protected by the per-guest floor. The `final_due_cents` is
    `booking_total_cents` minus `deposit_due_cents`".

    Design: Corner/calculations/deposit_floor_per_guest_beats_percentage
    """
    sailing, category, booking = create_quote_booking(
        "guest-c8", num_guests=2, num_cabins=1,
        guests=[("C One", 40), ("C Two", 38)],
    )
    get_success_data(api.create_guest(create_guest_payload(booking["id"], "C Three", 10),
                                      make_guest_user_headers("guest-c8")))
    after = get_booking(booking["id"])
    assert after["deposit_due_cents"] == 75000   # max(73521, 25000*3)
    assert after["final_due_cents"] == 292607


def test_guest_delete_reindexes_and_recomputes_total(api):
    """PRD 3.3: "Removing a guest (permitted only while the booking is `QUOTE`, else
    `ERR_INVALID_STATE`) re-indexes the remaining guests to keep the positions
    contiguous. Every guest add or delete recomputes the per-guest fares, the
    booking totals, and the deposit schedule described in Section 3.4."

    Design: Corner/calculations/guest_delete_reindexes_occupancy_and_recomputes_total
    """
    sailing, category, booking = create_quote_booking(
        "guest-c9", num_guests=2, num_cabins=1,
        guests=[("C One", 40), ("C Two", 38)],
    )
    g1 = get_success_data(api.create_guest(create_guest_payload(booking["id"], "C Three", 10),
                                           make_guest_user_headers("guest-c9")))
    # Delete the occupancy-index-1 guest (the first added).
    first = _occupancy_index_one_guest(api, booking["id"])
    get_success_data(api.delete_guest(first["id"], make_guest_user_headers("guest-c9")))
    after = get_booking(booking["id"])
    assert after["guest_count"] == 2
    assert after["fare_total_cents"] == 239800  # both remaining at full fare
