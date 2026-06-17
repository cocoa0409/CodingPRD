"""Pricing and gratuity calculations: seat subtotal, deposit, add-on line
totals, and the gratuity computed at settlement. Covers difficulty-design
combinatorial-formula and dual-variant gratuity instances, plus the corner
calculation/computed-field instances rooted in §3.4–§3.8 of the PRD.
"""
from test_helpers import (
    validate_success,
    make_customer_headers,
    make_captain_headers,
    create_booking_payload,
    create_add_on_line_payload,
    # fixtures
    pin_clock,
    create_marina,
    create_boat,
    create_customer,
    create_charter,
    create_booking,
    pay_deposit,
    add_on_line,
    current_charter_version,
    get_charter,
    api_client,
)
from test_helpers.fixtures import FLEET_MANAGER


# ===========================================================================
# Difficulty: combinatorial_formula / seat_subtotal_split_surcharge_group_floor_before_multiply
# ===========================================================================

def test_split_group_seat_subtotal_floor_before_multiply(api):
    """PRD §3.4: "If the charter is a split charter, a fixed solidarity surcharge
    of 1500 cents is added to the per-seat price, because shared boats cost more
    to coordinate. Then, if the `party_size` is at least 4 seats, a group volume
    discount of 10 percent is taken off the per-seat price: the discounted
    per-seat price is the effective per-seat price multiplied by 90, divided by
    100, with the fractional part floored away — and this floor is applied to the
    per-seat figure **before** any multiplication by party size."

    base 10000 + split 1500 = 11500; floor(11500*90/100) = 10350; *4 = 41400.

    Design: Difficulty/combinatorial_formula/seat_subtotal_split_surcharge_group_floor_before_multiply
    """
    marina = create_marina(name="Combo Marina")
    boat = create_boat(marina["id"], name="Splitter", passenger_capacity=10)
    customer = create_customer()
    charter = create_charter(marina["id"], boat["id"], base_seat_price_cents=10000,
                             seats_total=10, split_charter=True)
    version = current_charter_version(charter["id"])
    res = api.create_booking(
        create_booking_payload(charter["id"], customer["id"], version, party_size=4),
        make_customer_headers(customer["id"]),
    )
    booking = validate_success(res, expected_status=201)
    assert booking["seat_subtotal_cents"] == 41400, booking["seat_subtotal_cents"]


def test_split_group_deposit_from_floored_subtotal(api):
    """PRD §3.4: "The raw deposit is 25 percent of `seat_subtotal_cents` — the
    subtotal multiplied by 25, divided by 100 — rounded half up to a whole cent.
    That rounded figure is then clamped: the deposit due is the rounded
    percentage but never below a minimum of 2000 cents and never above the seat
    subtotal itself."

    seat_subtotal 41400 -> round_half_up(41400*25/100) = 10350 (> MIN 2000,
    < subtotal) -> deposit_due 10350.

    Design: Difficulty/combinatorial_formula/seat_subtotal_split_surcharge_group_floor_before_multiply
    """
    marina = create_marina(name="Combo Marina 2")
    boat = create_boat(marina["id"], name="Splitter2", passenger_capacity=10)
    customer = create_customer()
    charter = create_charter(marina["id"], boat["id"], base_seat_price_cents=10000,
                             seats_total=10, split_charter=True)
    version = current_charter_version(charter["id"])
    res = api.create_booking(
        create_booking_payload(charter["id"], customer["id"], version, party_size=4),
        make_customer_headers(customer["id"]),
    )
    booking = validate_success(res, expected_status=201)
    assert booking["seat_subtotal_cents"] == 41400
    assert booking["deposit_due_cents"] == 10350, booking["deposit_due_cents"]


# ===========================================================================
# Difficulty: combinatorial_formula / gratuity_tip_base_floor_per_addon_line_then_sum
# ===========================================================================

def test_addon_lines_floored_per_line_then_summed_into_tip_base(api):
    """PRD §3.5: "if the `quantity` is at least 10 units, 15 percent comes off the
    whole line — the discount is the gross multiplied by 15, divided by 100, with
    the fractional part floored away so the customer is never over-credited, and
    the `line_total_cents` is the gross minus that floored discount."

    ROD_RENTAL x10: gross 25000, discount floor(25000*15/100)=3750 -> 21250.
    BAIT x3 (< 10): gross 2400, no discount -> 2400.

    Design: Difficulty/combinatorial_formula/gratuity_tip_base_floor_per_addon_line_then_sum
    """
    pin_clock("2026-08-05T11:00:00Z")
    marina = create_marina(name="Addon Marina")
    from test_helpers.fixtures import (create_dock_slot, create_captain, reserve_slot,
                                        assign_captain)
    slot = create_dock_slot(marina["id"], slot_label="B1")
    boat = create_boat(marina["id"], name="Gearboat", passenger_capacity=6)
    captain = create_captain(marina["id"])
    customer = create_customer()
    charter = create_charter(marina["id"], boat["id"], base_seat_price_cents=10000,
                             seats_total=6, depart_at="2026-08-05T12:00:00Z",
                             return_at="2026-08-05T16:00:00Z")
    assign_captain(charter["id"], captain["id"])
    reserve_slot(slot["id"], charter["id"])
    booking = create_booking(charter["id"], customer["id"], party_size=2,
                             gratuity_input_mode="PERCENT", gratuity_input_value=18)
    pay_deposit(booking["id"], customer["id"], 5000)
    rod = add_on_line(booking["id"], customer["id"], "ROD_RENTAL", 10)
    bait = add_on_line(booking["id"], customer["id"], "BAIT", 3)
    assert rod["line_total_cents"] == 21250, rod["line_total_cents"]
    assert bait["line_total_cents"] == 2400, bait["line_total_cents"]


def test_gratuity_floor_then_sum_into_tip_base_at_settlement(api):
    """PRD §3.8: "The tip base is the booking's `seat_subtotal_cents` plus the sum
    of the `line_total_cents` of its non-voided add-on lines (those in `PENDING`
    or `FULFILLED`). When the booking's `gratuity_input_mode` is `PERCENT`, the
    customer tip is the tip base multiplied by the booking's `gratuity_input_value`,
    divided by 100, rounded half up to a whole cent."

    tip_base = 20000 (subtotal) + 21250 + 2400 = 43650; 18% -> 7857.

    Design: Difficulty/combinatorial_formula/gratuity_tip_base_floor_per_addon_line_then_sum
    """
    pin_clock("2026-08-05T12:00:00Z")
    marina = create_marina(name="Addon Marina 2")
    from test_helpers.fixtures import (create_dock_slot, create_captain, reserve_slot,
                                        assign_captain)
    slot = create_dock_slot(marina["id"], slot_label="B2")
    boat = create_boat(marina["id"], name="Gearboat2", passenger_capacity=6)
    captain = create_captain(marina["id"])
    customer = create_customer()
    charter = create_charter(marina["id"], boat["id"], base_seat_price_cents=10000,
                             seats_total=6, depart_at="2026-08-05T12:00:00Z",
                             return_at="2026-08-05T16:00:00Z")
    assign_captain(charter["id"], captain["id"])
    reserve_slot(slot["id"], charter["id"])
    booking = create_booking(charter["id"], customer["id"], party_size=2,
                             gratuity_input_mode="PERCENT", gratuity_input_value=18)
    pay_deposit(booking["id"], customer["id"], 5000)
    add_on_line(booking["id"], customer["id"], "ROD_RENTAL", 10)
    add_on_line(booking["id"], customer["id"], "BAIT", 3)
    from test_helpers.fixtures import FLEET_MANAGER as FM
    api_client.schedule_charter(charter["id"], FM)
    api_client.sail_charter(charter["id"], make_captain_headers(captain["id"]))
    res = api.settle_charter(charter["id"], FM)
    validate_success(res, expected_status=200)
    settled = validate_success(api.get_booking(booking["id"], FM), expected_status=200)
    assert settled["gratuity_cents"] == 7857, settled["gratuity_cents"]


# ===========================================================================
# Difficulty: dual_variant_calc / gratuity_percent_vs_flat_mode
# ===========================================================================

def _settle_two_tip_bookings():
    """Build one settled INSHORE charter carrying two CONFIRMED bookings — one
    PERCENT@18, one FLAT@5000, each seat_subtotal 20000 (base 10000, party 2)."""
    pin_clock("2026-07-10T12:00:00Z")
    marina = create_marina(name="Tip Marina")
    from test_helpers.fixtures import (create_dock_slot, create_captain, reserve_slot,
                                        assign_captain)
    slot = create_dock_slot(marina["id"], slot_label="T1")
    boat = create_boat(marina["id"], name="Tipper", passenger_capacity=8)
    captain = create_captain(marina["id"])
    cust_p = create_customer()
    cust_f = create_customer()
    charter = create_charter(marina["id"], boat["id"], base_seat_price_cents=10000,
                             seats_total=8, depart_at="2026-07-10T12:00:00Z",
                             return_at="2026-07-10T16:00:00Z")
    assign_captain(charter["id"], captain["id"])
    reserve_slot(slot["id"], charter["id"])
    bk_p = create_booking(charter["id"], cust_p["id"], party_size=2,
                          gratuity_input_mode="PERCENT", gratuity_input_value=18)
    pay_deposit(bk_p["id"], cust_p["id"], 5000)
    bk_f = create_booking(charter["id"], cust_f["id"], party_size=2,
                          gratuity_input_mode="FLAT", gratuity_input_value=5000)
    pay_deposit(bk_f["id"], cust_f["id"], 5000)
    from test_helpers.fixtures import FLEET_MANAGER as FM
    api_client.schedule_charter(charter["id"], FM)
    api_client.sail_charter(charter["id"], make_captain_headers(captain["id"]))
    api_client.settle_charter(charter["id"], FM)
    return bk_p["id"], bk_f["id"]


def test_gratuity_percent_mode_at_settlement(api):
    """PRD §3.8: "When the booking's `gratuity_input_mode` is `PERCENT`, the
    customer tip is the tip base multiplied by the booking's `gratuity_input_value`,
    divided by 100, rounded half up to a whole cent."

    seat_subtotal 20000, PERCENT 18 -> round_half_up(20000*18/100) = 3600.

    Design: Difficulty/dual_variant_calc/gratuity_percent_vs_flat_mode
    """
    from test_helpers.fixtures import FLEET_MANAGER as FM
    bk_p_id, _ = _settle_two_tip_bookings()
    bk = validate_success(api.get_booking(bk_p_id, FM), expected_status=200)
    assert bk["gratuity_cents"] == 3600, bk["gratuity_cents"]
    assert bk["status"] == "SETTLED"


def test_gratuity_flat_mode_at_settlement(api):
    """PRD §3.8: "when the mode is `FLAT`, the customer tip is simply the
    `gratuity_input_value` in cents."

    FLAT 5000 -> gratuity 5000 (party 2 < 6, no auto-grat floor).

    Design: Difficulty/dual_variant_calc/gratuity_percent_vs_flat_mode
    """
    from test_helpers.fixtures import FLEET_MANAGER as FM
    _, bk_f_id = _settle_two_tip_bookings()
    bk = validate_success(api.get_booking(bk_f_id, FM), expected_status=200)
    assert bk["gratuity_cents"] == 5000, bk["gratuity_cents"]
    assert bk["status"] == "SETTLED"


# ===========================================================================
# Corner: calculations / gratuity_auto_grat_floor_large_party
# ===========================================================================

def test_auto_gratuity_floor_for_large_party(api):
    """PRD §3.8: "if the booking's `party_size` is at least 6, the booking owes at
    least 20 percent of the tip base — that floor is the tip base multiplied by
    20, divided by 100, rounded half up — and the final `gratuity_cents` is the
    larger of the computed customer tip and that auto-gratuity floor."

    party 6 -> seat_subtotal 54000; PERCENT 10 -> 5400; floor 20% -> 10800;
    max(5400, 10800) = 10800.

    Design: Corner/calculations/gratuity_auto_grat_floor_large_party
    """
    pin_clock("2027-12-10T12:00:00Z")
    marina = create_marina(name="Auto Marina")
    from test_helpers.fixtures import (create_dock_slot, create_captain, reserve_slot,
                                        assign_captain)
    slot = create_dock_slot(marina["id"], slot_label="AT1")
    boat = create_boat(marina["id"], name="Autoboat", passenger_capacity=8)
    captain = create_captain(marina["id"])
    customer = create_customer()
    charter = create_charter(marina["id"], boat["id"], base_seat_price_cents=10000,
                             seats_total=8, depart_at="2027-12-10T12:00:00Z",
                             return_at="2027-12-10T16:00:00Z")
    assign_captain(charter["id"], captain["id"])
    reserve_slot(slot["id"], charter["id"])
    booking = create_booking(charter["id"], customer["id"], party_size=6,
                             gratuity_input_mode="PERCENT", gratuity_input_value=10)
    pay_deposit(booking["id"], customer["id"], 13500)
    from test_helpers.fixtures import FLEET_MANAGER as FM
    api_client.schedule_charter(charter["id"], FM)
    api_client.sail_charter(charter["id"], make_captain_headers(captain["id"]))
    api.settle_charter(charter["id"], FM)
    settled = validate_success(api.get_booking(booking["id"], FM), expected_status=200)
    assert settled["seat_subtotal_cents"] == 54000, settled["seat_subtotal_cents"]
    assert settled["gratuity_cents"] == 10800, settled["gratuity_cents"]


# ===========================================================================
# Corner: entities / addon_line_total_non_bulk_no_discount
# ===========================================================================

def test_addon_line_below_bulk_quantity_no_discount(api):
    """PRD §3.5: "The `unit_price_cents` is resolved from a fixed rate card by
    kind: `BAIT` is 800 cents per unit ... Below 10 units there is no discount,
    and the line total equals the gross."

    BAIT x2 -> unit 800, gross 1600, no discount -> line_total 1600.

    Design: Corner/entities/addon_line_total_non_bulk_no_discount
    """
    marina = create_marina(name="NB Marina")
    boat = create_boat(marina["id"], name="NBboat")
    customer = create_customer()
    charter = create_charter(marina["id"], boat["id"])
    booking = create_booking(charter["id"], customer["id"], party_size=1)
    res = api.create_add_on_line(
        create_add_on_line_payload(booking["id"], "BAIT", 2),
        make_customer_headers(customer["id"]),
    )
    line = validate_success(res, expected_status=201)
    assert line["unit_price_cents"] == 800, line["unit_price_cents"]
    assert line["line_total_cents"] == 1600, line["line_total_cents"]


# ===========================================================================
# Corner: entities / deposit_min_floor_applied
# ===========================================================================

def test_deposit_min_floor_clamps_up_to_2000(api):
    """PRD §3.4: "the deposit due is the rounded percentage but never below a
    minimum of 2000 cents and never above the seat subtotal itself."

    base 2000 party 1 -> seat_subtotal 2000; 25% = 500 but MIN 2000 floor and
    subtotal cap -> deposit_due 2000.

    Design: Corner/entities/deposit_min_floor_applied
    """
    marina = create_marina(name="Floor Marina")
    boat = create_boat(marina["id"], name="Floorboat")
    customer = create_customer()
    charter = create_charter(marina["id"], boat["id"], trip_type="HALF_DAY",
                             base_seat_price_cents=2000)
    booking = create_booking(charter["id"], customer["id"], party_size=1)
    assert booking["seat_subtotal_cents"] == 2000, booking["seat_subtotal_cents"]
    assert booking["deposit_due_cents"] == 2000, booking["deposit_due_cents"]


# ===========================================================================
# Corner: entities / deposit_round_half_up_above_floor
# ===========================================================================

def test_deposit_round_half_up_on_percentage_step(api):
    """PRD §3.4: "The raw deposit is 25 percent of `seat_subtotal_cents` — the
    subtotal multiplied by 25, divided by 100 — rounded half up to a whole cent."

    base 4001 party 2 (no split) -> seat_subtotal 8002; 25% = 2000.5 ->
    round_half_up 2001 (> MIN 2000).

    Design: Corner/entities/deposit_round_half_up_above_floor
    """
    marina = create_marina(name="Round Marina")
    boat = create_boat(marina["id"], name="Roundboat")
    customer = create_customer()
    charter = create_charter(marina["id"], boat["id"], base_seat_price_cents=4001)
    booking = create_booking(charter["id"], customer["id"], party_size=2)
    assert booking["seat_subtotal_cents"] == 8002, booking["seat_subtotal_cents"]
    assert booking["deposit_due_cents"] == 2001, booking["deposit_due_cents"]


# ===========================================================================
# Corner: entities / get_charter_recomputes_seats_and_catch
# ===========================================================================

def test_get_charter_reflects_seats_booked_and_catch_total(api):
    """PRD §3.6: "A charter's `catch_total` is the running tally of **kept** fish
    across all of its catch reports."
    PRD §3.4: "On success, the charter's `seats_booked` is increased by
    `party_size`."

    One party-3 RESERVED booking -> seats_booked 3, catch_total 0.

    Design: Corner/entities/get_charter_recomputes_seats_and_catch
    """
    marina = create_marina(name="Comp Marina")
    boat = create_boat(marina["id"], name="Compboat")
    customer = create_customer()
    charter = create_charter(marina["id"], boat["id"], seats_total=6)
    create_booking(charter["id"], customer["id"], party_size=3)
    fresh = get_charter(charter["id"])
    assert fresh["seats_booked"] == 3, fresh["seats_booked"]
    assert fresh["catch_total"] == 0, fresh["catch_total"]


# ===========================================================================
# Corner: calculations / open_slot_count_excludes_non_overlapping_window
# ===========================================================================

def test_open_slot_count_excludes_future_window_reservation(api):
    """PRD §3.6: "a slot is busy if any of its reservations is `HELD` or
    `OCCUPIED` and that reservation's half-open window — from `window_start` up to
    but not including `window_end` — brackets the current clock (`window_start` at
    or before now, and now strictly before `window_end`). The open count is the
    marina's `slot_count` minus the number of distinct busy slots."

    Clock 2028-02-01, reservation window 2028-02-10..16 (future) -> not busy ->
    open_slot_count == slot_count 2.

    Design: Corner/calculations/open_slot_count_excludes_non_overlapping_window
    """
    pin_clock("2028-02-01T00:00:00Z")
    marina = create_marina(name="Win Marina", slot_count=2)
    from test_helpers.fixtures import create_dock_slot, reserve_slot
    slot = create_dock_slot(marina["id"], slot_label="V1")
    boat = create_boat(marina["id"], name="Winboat")
    charter = create_charter(marina["id"], boat["id"],
                             depart_at="2028-02-10T12:00:00Z",
                             return_at="2028-02-10T16:00:00Z")
    reserve_slot(slot["id"], charter["id"])
    fresh = validate_success(api.get_marina(marina["id"], FLEET_MANAGER), expected_status=200)
    assert fresh["open_slot_count"] == 2, fresh["open_slot_count"]
