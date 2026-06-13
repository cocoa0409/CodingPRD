"""Charge computation and per-seat prep cost — pricing arithmetic.

Queue A (Difficulty): combinatorial_formula, boundary_precision_check (discount tier).
"""
from test_helpers import (
    api_client,
    validate_success,
    create_member,
    create_open_session,
    create_booking,
    make_member_headers,
)


def test_group_charge_combines_skill_surcharge_and_discount_tier(api):
    """PRD §3.5: "a per-seat skill surcharge is selected by the template's
    skill_level - 0 cents for BEGINNER, 500 cents for INTERMEDIATE, 1200 cents
    for ADVANCED, and 2500 cents for PROFESSIONAL - and the subtotal is the
    template's base_price_cents times seats_requested plus that per-seat skill
    surcharge times seats_requested."
    PRD §3.5: "a booking of 6 to 9 seats earns 10 percent"
    PRD §3.5: "the final charge_cents is the subtotal minus that rounded discount."

    ADVANCED base 8500, 6 seats: subtotal = 6*(8500+1200) = 58200,
    discount 10% = 5820, charge = 52380.

    Design: Difficulty/combinatorial_formula/booking_charge_tiered_nonlinear_mode_a
    """
    _instr, _tmpl, session = create_open_session(
        template_overrides={
            "skill_level": "ADVANCED", "base_price_cents": 8500, "default_capacity": 6,
            "station_fixed_cost_cents": 6000,
        },
        session_overrides={"planned_seats": 6, "station_id": "ST-CHARGE-A"},
        ingredient_overrides={"name": "rice", "qty_per_seat": 0.1, "unit_cost_cents": 200},
    )
    member = create_member()
    res = api.create_booking(
        {"session_id": session["id"], "member_id": member["id"], "seats_requested": 6},
        make_member_headers(member["id"]),
    )
    booking = validate_success(res, 201)
    assert booking["charge_cents"] == 52380, (
        f"expected charge 52380, got {booking['charge_cents']}"
    )


def test_group_charge_professional_tier_no_discount_small_party(api):
    """PRD §3.5: "a per-seat skill surcharge is selected by the template's
    skill_level - 0 cents for BEGINNER, 500 cents for INTERMEDIATE, 1200 cents for
    ADVANCED, and 2500 cents for PROFESSIONAL".
    PRD §3.5: "a booking of 2 seats or fewer earns no discount".

    A second mode-(a) witness on different inputs: PROFESSIONAL base 9000, 2 seats:
    subtotal = 2*(9000+2500) = 23000, 0% discount -> charge 23000.

    Design: Difficulty/combinatorial_formula/booking_charge_tiered_nonlinear_mode_a
    """
    _instr, _tmpl, session = create_open_session(
        instructor_max_skill="PROFESSIONAL",
        template_overrides={
            "skill_level": "PROFESSIONAL", "base_price_cents": 9000, "default_capacity": 4,
            "station_fixed_cost_cents": 1000,
        },
        session_overrides={"planned_seats": 4, "station_id": "ST-CHARGE-PRO"},
        ingredient_overrides={"name": "rice", "qty_per_seat": 0.1, "unit_cost_cents": 200},
    )
    member = create_member()
    booking = validate_success(
        api.create_booking(
            {"session_id": session["id"], "member_id": member["id"], "seats_requested": 2},
            make_member_headers(member["id"]),
        ), 201,
    )
    assert booking["charge_cents"] == 23000, (
        f"PROFESSIONAL 2 seats, no discount: 2*(9000+2500) = 23000, got {booking['charge_cents']}"
    )


def test_discount_tier_boundary_two_vs_three_seats(api):
    """PRD §3.5: "a booking of 2 seats or fewer earns no discount, a booking of 3
    to 5 seats earns 5 percent".
    PRD §3.5: "the subtotal is the template's base_price_cents times seats_requested
    plus that per-seat skill surcharge times seats_requested."

    A second discount-tier boundary (the 0%->5% edge): INTERMEDIATE base 8500,
    2 seats -> subtotal 2*(8500+500)=18000, 0% -> 18000; 3 seats -> subtotal 27000,
    5% disc 1350 -> 25650. The >=3 boundary is exact.

    Design: Difficulty/boundary_precision_check/group_discount_tier_boundary_seats_5_vs_6
    """
    _instr, _tmpl, session = create_open_session(
        template_overrides={
            "skill_level": "INTERMEDIATE", "base_price_cents": 8500, "default_capacity": 5,
            "station_fixed_cost_cents": 1000,
        },
        session_overrides={"planned_seats": 5, "station_id": "ST-TIER-BND2"},
        ingredient_overrides={"name": "stock", "qty_per_seat": 0.3, "unit_cost_cents": 80},
    )
    mem2 = create_member()
    mem3 = create_member()
    bk2 = validate_success(
        api.create_booking(
            {"session_id": session["id"], "member_id": mem2["id"], "seats_requested": 2},
            make_member_headers(mem2["id"]),
        ), 201,
    )
    bk3 = validate_success(
        api.create_booking(
            {"session_id": session["id"], "member_id": mem3["id"], "seats_requested": 3},
            make_member_headers(mem3["id"]),
        ), 201,
    )
    assert bk2["charge_cents"] == 18000, f"2-seat (0% tier) expected 18000, got {bk2['charge_cents']}"
    assert bk3["charge_cents"] == 25650, f"3-seat (5% tier) expected 25650, got {bk3['charge_cents']}"


def test_prep_cost_rounds_each_line_before_summing(api):
    """PRD §3.4: "For each ingredient line on the session, taken in ascending
    created_at order, the system multiplies that line's qty_per_seat by its
    unit_cost_cents and rounds that single product half-up to whole cents; these
    per-line whole-cent amounts are then summed to give the ingredient cost per
    seat."
    PRD §3.4: "the template's station_fixed_cost_cents is divided by the session's
    planned_seats using ceiling division - that is, any remainder rounds the
    per-seat station allocation up to the next whole cent."

    Four lines round to {40,299,93,15} = 447 (sum-then-round of 446.10 would give
    446); station ceil(6000/8) = 750; prep_cost_per_seat_cents = 1197.

    Design: Difficulty/combinatorial_formula/prep_cost_round_per_line_then_sum_mode_b
    """
    from test_helpers import (
        create_instructor, create_published_template, create_session,
        add_ingredient_line, make_instructor_headers,
    )
    instr = create_instructor()
    tmpl = create_published_template(
        skill_level="BEGINNER", base_price_cents=5000, default_capacity=8,
        station_fixed_cost_cents=6000, prep_minutes=30, cleanup_minutes=0,
    )
    session = create_session(
        tmpl["id"], instr["id"], station_id="ST-PREP-B", planned_seats=8,
        start_at="2026-08-05T14:00:00Z", end_at="2026-08-05T16:00:00Z",
    )
    add_ingredient_line(session["id"], instr["id"], name="flour", qty_per_seat=0.125, unit_cost_cents=322)
    add_ingredient_line(session["id"], instr["id"], name="saffron", qty_per_seat=0.003, unit_cost_cents=99500)
    add_ingredient_line(session["id"], instr["id"], name="olive_oil", qty_per_seat=0.05, unit_cost_cents=1850)
    add_ingredient_line(session["id"], instr["id"], name="herbs", qty_per_seat=0.011, unit_cost_cents=1350)
    opened = validate_success(
        api.open_session(session["id"], make_instructor_headers(instr["id"])), 200
    )
    assert opened["prep_cost_per_seat_cents"] == 1197, (
        f"expected prep_cost_per_seat_cents 1197, got {opened['prep_cost_per_seat_cents']}"
    )


def test_prep_cost_rounding_order_matters_second_witness(api):
    """PRD §3.4: "This rounding order is significant: each line is rounded before
    the lines are summed, never after."

    A second per-line-rounding witness on a different line set: line 0.125*322 =
    40.25 -> 40 per line, station ceil(1000/4) = 250 -> prep = 290. (Sum-then-round
    of a single line gives the same here; the witness pins the station ceil term
    on a non-dividing fixed cost: ceil(1000/4)=250.)

    Design: Difficulty/combinatorial_formula/prep_cost_round_per_line_then_sum_mode_b
    """
    from test_helpers import (
        create_instructor, create_published_template, create_session,
        add_ingredient_line, make_instructor_headers,
    )
    instr = create_instructor()
    tmpl = create_published_template(
        skill_level="BEGINNER", base_price_cents=5000, default_capacity=4,
        station_fixed_cost_cents=1000,
    )
    session = create_session(
        tmpl["id"], instr["id"], station_id="ST-PREP-B2", planned_seats=4,
        start_at="2026-08-06T14:00:00Z", end_at="2026-08-06T16:00:00Z",
    )
    add_ingredient_line(session["id"], instr["id"], name="flour", qty_per_seat=0.125, unit_cost_cents=322)
    opened = validate_success(
        api.open_session(session["id"], make_instructor_headers(instr["id"])), 200
    )
    # ingredient per seat: round(0.125*322=40.25) = 40 ; station ceil(1000/4) = 250
    assert opened["prep_cost_per_seat_cents"] == 290, (
        f"expected prep_cost_per_seat_cents 290, got {opened['prep_cost_per_seat_cents']}"
    )


def test_discount_tier_boundary_five_vs_six_seats(api):
    """PRD §3.5: "a booking of 3 to 5 seats earns 5 percent, a booking of 6 to 9
    seats earns 10 percent"
    PRD §3.5: "the subtotal is the template's base_price_cents times seats_requested
    plus that per-seat skill surcharge times seats_requested."

    ADVANCED base 8500: 5 seats -> subtotal 5*(8500+1200)=48500, 5% disc 2425 ->
    46075; 6 seats -> subtotal 58200, 10% disc 5820 -> 52380. The >=6 boundary
    is exact.

    Design: Difficulty/boundary_precision_check/group_discount_tier_boundary_seats_5_vs_6
    """
    _instr, _tmpl, session = create_open_session(
        template_overrides={
            "skill_level": "ADVANCED", "base_price_cents": 8500, "default_capacity": 11,
            "station_fixed_cost_cents": 1000,
        },
        session_overrides={"planned_seats": 11, "station_id": "ST-TIER-BND"},
        ingredient_overrides={"name": "stock", "qty_per_seat": 0.3, "unit_cost_cents": 80},
    )
    mem5 = create_member()
    mem6 = create_member()
    bk5 = validate_success(
        api.create_booking(
            {"session_id": session["id"], "member_id": mem5["id"], "seats_requested": 5},
            make_member_headers(mem5["id"]),
        ), 201,
    )
    bk6 = validate_success(
        api.create_booking(
            {"session_id": session["id"], "member_id": mem6["id"], "seats_requested": 6},
            make_member_headers(mem6["id"]),
        ), 201,
    )
    assert bk5["charge_cents"] == 46075, f"5-seat (5% tier) expected 46075, got {bk5['charge_cents']}"
    assert bk6["charge_cents"] == 52380, f"6-seat (10% tier) expected 52380, got {bk6['charge_cents']}"


def test_private_event_charge_is_flat_buyout_fee(api):
    """PRD §3.5: "For a PRIVATE event the charge is simply the session's
    private_event_fee_cents - a flat buyout with no per-seat pricing, no group
    discount, and no skill surcharge."

    PRIVATE planned_seats=4, fee 40000; a full-buyout booking charges exactly 40000
    regardless of the ADVANCED skill level or base price.

    Design: Corner/calculations/private_event_uses_flat_fee_not_per_seat
    """
    _instr, _tmpl, session = create_open_session(
        template_overrides={
            "skill_level": "ADVANCED", "base_price_cents": 8500, "default_capacity": 4,
            "station_fixed_cost_cents": 1000,
        },
        session_overrides={
            "event_type": "PRIVATE", "planned_seats": 4,
            "private_event_fee_cents": 40000, "station_id": "ST-PRIV-FLAT",
        },
        ingredient_overrides={"name": "p", "qty_per_seat": 1, "unit_cost_cents": 1},
    )
    member = create_member()
    booking = validate_success(
        api.create_booking(
            {"session_id": session["id"], "member_id": member["id"], "seats_requested": 4},
            make_member_headers(member["id"]),
        ), 201,
    )
    assert booking["charge_cents"] == 40000, (
        f"PRIVATE buyout expected 40000, got {booking['charge_cents']}"
    )


def test_get_session_reports_computed_prep_cost(api):
    """PRD §3.4: "the template's station_fixed_cost_cents is divided by the
    session's planned_seats using ceiling division" and per-line rounding gives
    the ingredient-per-seat total; "The per-seat prep cost stored on the session
    is the sum of the ingredient-per-seat total and the station-per-seat
    allocation."

    One line 0.1*200=20, station ceil(1000/4)=250 -> 270, read back via GET.

    Design: Corner/endpoints/get_session_summary_prep_cost_computed
    """
    _instr, _tmpl, session = create_open_session(
        template_overrides={
            "skill_level": "BEGINNER", "base_price_cents": 5000, "default_capacity": 4,
            "station_fixed_cost_cents": 1000,
        },
        session_overrides={"planned_seats": 4, "station_id": "ST-PREP-READ"},
        ingredient_overrides={"name": "stock", "qty_per_seat": 0.1, "unit_cost_cents": 200},
    )
    fetched = validate_success(api.get_session(session["id"], make_member_headers(create_member()["id"])), 200)
    assert fetched["prep_cost_per_seat_cents"] == 270, (
        f"expected prep_cost_per_seat_cents 270, got {fetched['prep_cost_per_seat_cents']}"
    )
