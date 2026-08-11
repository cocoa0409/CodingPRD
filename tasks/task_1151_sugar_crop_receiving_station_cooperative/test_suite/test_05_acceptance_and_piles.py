"""Ticket acceptance: preconditions (lab sample, trash limit, pile fill, pile
station), final vs provisional payment bases, trash deduction tiers, and the
accept side-effect chain (allocation, pile, station)."""
import pytest

from test_helpers import (
    ApiErrorId,
    SLOT_AM_END,
    SLOT_AM_START,
    SLOT_PM_END,
    SLOT_PM_START,
    WEIGH_CLOCK_AM,
    WEIGH_CLOCK_PM,
    accept_ticket,
    add_verified_lab_sample,
    assert_pile_allocation,
    create_confirmed_booking,
    create_pile,
    create_station,
    create_weighed_ticket,
    make_sampled_ticket,
    seal_pile,
    setup_world,
    validate_error,
    validate_success,
)


def test_accept_without_verified_lab_sample_returns_error(api, station_operator_headers):
    """PRD §3.6: "The ticket must have at least one `VERIFIED` sample whose
    `sample_type` is `LAB_VERIFY`, otherwise `ERR_LAB_SAMPLE_REQUIRED`."

    Design: Corner/validations/accept_without_verified_lab_sample_returns_error
    """
    world = setup_world()
    booking = create_confirmed_booking(
        world["campaign"]["id"], world["station"]["id"], world["member"]["id"],
        SLOT_AM_START, SLOT_AM_END, 20)
    ticket, _s = make_sampled_ticket(booking["id"], 60000, 32000, WEIGH_CLOCK_AM,
                                     sugar_pct=16.50, trash_pct=4.50,
                                     sample_type="STATION_QUICK")
    res = api.accept_ticket(ticket["id"], {"pile_id": world["pile"]["id"]},
                            station_operator_headers)
    validate_error(res, ApiErrorId.ERR_LAB_SAMPLE_REQUIRED.value)
    after = validate_success(api.get_ticket(ticket["id"], station_operator_headers), 200)
    assert after["status"] == "SAMPLED"


def test_trash_exactly_20_00_accepted(api, station_operator_headers):
    """PRD §3.6: "The resulting `final_trash_pct` — taken from the latest
    `VERIFIED` `LAB_VERIFY` sample by `created_at` — must be at most 20.00
    percent exactly: 20.00 is accepted, 20.01 is rejected with
    `ERR_TRASH_LIMIT_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/trash_accept_boundary_exactly_20_00
    """
    world = setup_world()
    booking = create_confirmed_booking(
        world["campaign"]["id"], world["station"]["id"], world["member"]["id"],
        SLOT_AM_START, SLOT_AM_END, 25)
    ticket = create_weighed_ticket(booking["id"], 72000, 32000, WEIGH_CLOCK_AM)
    add_verified_lab_sample(ticket["id"], 16.00, 20.00)
    accepted = validate_success(api.accept_ticket(
        ticket["id"], {"pile_id": world["pile"]["id"]}, station_operator_headers), 200)
    assert accepted["status"] == "ACCEPTED"
    # trash 20.00 -> deducted min((20.00-3.00) x 1.5, 20.00) = 20.00%; 20.0 t x 0.80
    assert accepted["adjusted_net_tons_final"] == pytest.approx(16.0, abs=1e-9)
    assert accepted["final_trash_pct"] == pytest.approx(20.00, abs=1e-9)


def test_trash_20_01_rejected(api, station_operator_headers):
    """PRD §3.6: "must be at most 20.00 percent exactly: 20.00 is accepted,
    20.01 is rejected with `ERR_TRASH_LIMIT_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/trash_accept_boundary_exactly_20_00
    """
    world = setup_world()
    booking = create_confirmed_booking(
        world["campaign"]["id"], world["station"]["id"], world["member"]["id"],
        SLOT_AM_START, SLOT_AM_END, 25)
    ticket = create_weighed_ticket(booking["id"], 72000, 32000, WEIGH_CLOCK_AM)
    add_verified_lab_sample(ticket["id"], 16.00, 20.01)
    res = api.accept_ticket(ticket["id"], {"pile_id": world["pile"]["id"]},
                            station_operator_headers)
    validate_error(res, ApiErrorId.ERR_TRASH_LIMIT_EXCEEDED.value)
    after = validate_success(api.get_ticket(ticket["id"], station_operator_headers), 200)
    assert after["status"] == "SAMPLED"


def test_accept_pile_at_other_station_returns_mismatch(api, station_operator_headers):
    """PRD §3.6: "The pile's `station_id` must equal the ticket's `station_id`
    (`ERR_PILE_STATION_MISMATCH`)."

    Design: Corner/validations/accept_pile_at_other_station_returns_mismatch
    """
    world = setup_world()
    other_station = create_station(name="STB", booking_capacity_tons=1000)
    other_pile = create_pile(other_station["id"], capacity_tons=200)
    booking = create_confirmed_booking(
        world["campaign"]["id"], world["station"]["id"], world["member"]["id"],
        SLOT_AM_START, SLOT_AM_END, 20)
    ticket = create_weighed_ticket(booking["id"], 72000, 32000, WEIGH_CLOCK_AM)
    add_verified_lab_sample(ticket["id"], 16.00, 2.00)
    res = api.accept_ticket(ticket["id"], {"pile_id": other_pile["id"]},
                            station_operator_headers)
    validate_error(res, ApiErrorId.ERR_PILE_STATION_MISMATCH.value)
    after = validate_success(api.get_ticket(ticket["id"], station_operator_headers), 200)
    assert after["status"] == "SAMPLED"


def test_pile_seal_rejects_further_accepts(api, station_operator_headers):
    """PRD §3.6: "The target pile's `fill_status` must be `FILLING`
    (`ERR_PILE_NOT_FILLING`)."

    Design: Corner/state_machines/pile_seal_rejects_further_accepts
    """
    world = setup_world(pile_capacity_tons=500)
    b1 = create_confirmed_booking(
        world["campaign"]["id"], world["station"]["id"], world["member"]["id"],
        SLOT_AM_START, SLOT_AM_END, 20)
    t1 = create_weighed_ticket(b1["id"], 72000, 32000, WEIGH_CLOCK_AM)
    add_verified_lab_sample(t1["id"], 16.00, 2.00)
    accept_ticket(t1["id"], world["pile"]["id"])
    seal_pile(world["pile"]["id"])

    b2 = create_confirmed_booking(
        world["campaign"]["id"], world["station"]["id"], world["member"]["id"],
        SLOT_PM_START, SLOT_PM_END, 20)
    t2 = create_weighed_ticket(b2["id"], 72000, 32000, WEIGH_CLOCK_PM)
    add_verified_lab_sample(t2["id"], 16.00, 2.00)
    res = api.accept_ticket(t2["id"], {"pile_id": world["pile"]["id"]},
                            station_operator_headers)
    validate_error(res, ApiErrorId.ERR_PILE_NOT_FILLING.value)
    after = validate_success(api.get_ticket(t2["id"], station_operator_headers), 200)
    assert after["status"] == "SAMPLED"


def test_accept_side_effects_immediately_visible(api, station_operator_headers):
    """PRD §3.6: "A **pile allocation** is created for the receiving pile and is
    addressable thereafter by its `allocation_id`" and "The pile's `stored_lbs`
    increases by the allocated pounds, which triggers recomputation of the
    station's `received_tons` and `stored_tons`."
    PRD §2.8: "the server recomputes them immediately whenever an underlying
    record changes."

    Design: Corner/consistency_model/accept_side_effects_immediately_visible
    """
    world = setup_world()
    booking = create_confirmed_booking(
        world["campaign"]["id"], world["station"]["id"], world["member"]["id"],
        SLOT_AM_START, SLOT_AM_END, 25)
    ticket = create_weighed_ticket(booking["id"], 72000, 32000, WEIGH_CLOCK_AM)
    add_verified_lab_sample(ticket["id"], 16.00, 2.00)
    accepted = validate_success(api.accept_ticket(
        ticket["id"], {"pile_id": world["pile"]["id"]}, station_operator_headers), 200)
    assert accepted["status"] == "ACCEPTED"
    assert accepted["adjusted_net_tons_final"] == pytest.approx(20.0, abs=1e-9)
    assert accepted["final_factor"] == pytest.approx(1.0, abs=1e-9)

    pile = validate_success(api.get_pile(world["pile"]["id"], station_operator_headers), 200)
    assert pile["stored_lbs"] == pytest.approx(40000.0, abs=1e-9)
    station = validate_success(
        api.get_station(world["station"]["id"], station_operator_headers), 200)
    assert station["received_tons"] == pytest.approx(20.0, abs=1e-9)
    assert station["stored_tons"] == pytest.approx(20.0, abs=1e-9)


def test_pile_allocations_filtered_list_reverse_reachability(api, pool_accountant_headers):
    """PRD §3.6: "its `ticket_id` and `pile_id` identify the load and the pile,
    its `member_id` is copied from the ticket, its `allocated_lbs` equals the
    ticket's `adjusted_net_lbs_final` at this moment, its `remaining_lbs` starts
    equal to `allocated_lbs`, and its `status` begins `ACTIVE`."

    Design: Corner/endpoints/pile_allocations_filtered_list_reverse_reachability
    """
    world = setup_world()
    booking = create_confirmed_booking(
        world["campaign"]["id"], world["station"]["id"], world["member"]["id"],
        SLOT_AM_START, SLOT_AM_END, 25)
    ticket = create_weighed_ticket(booking["id"], 72000, 32000, WEIGH_CLOCK_AM)
    add_verified_lab_sample(ticket["id"], 16.00, 2.00)
    accept_ticket(ticket["id"], world["pile"]["id"])

    data = validate_success(api.list_pile_allocations(
        pool_accountant_headers, params={"ticket_id": ticket["id"]}), 200)
    assert len(data) == 1
    alloc = data[0]
    assert_pile_allocation(alloc)
    assert alloc["allocated_lbs"] == pytest.approx(40000.0, abs=1e-9)
    assert alloc["remaining_lbs"] == pytest.approx(40000.0, abs=1e-9)
    assert alloc["pile_id"] == world["pile"]["id"]
    assert alloc["member_id"] == world["member"]["id"]
    assert alloc["status"] == "ACTIVE"


def test_provisional_factor_uses_first_recorded_sample(api, pool_accountant_headers):
    """PRD §3.5: "The **provisional** factor, computed when the ticket enters
    `SAMPLED` from its first recorded sample of any type, clamps the base factor
    into the band from 0.70 to 1.30 inclusive and rounds half-up to 4 decimal
    places; no low-sugar penalty applies."
    PRD §3.5: "its `provisional_value_cents` is the product of
    `provisional_adjusted_net_tons`, the campaign's `base_price_cents_per_ton`,
    and `provisional_factor`, rounded half-up to integer cents."

    Design: Difficulty/dual_variant_calc/ticket_payment_factor_provisional_vs_final
    """
    world = setup_world()
    booking = create_confirmed_booking(
        world["campaign"]["id"], world["station"]["id"], world["member"]["id"],
        SLOT_AM_START, SLOT_AM_END, 30)
    ticket, _s = make_sampled_ticket(booking["id"], 80000, 32000, WEIGH_CLOCK_AM,
                                     sugar_pct=16.50, trash_pct=4.50,
                                     sample_type="STATION_QUICK")
    assert ticket["status"] == "SAMPLED"
    # provisional: factor 1.00 + (16.50-16.00) x 0.04 = 1.0200;
    # trash 4.50 -> deducted 1.50%; 24.0 t x 0.985 = 23.6400 t
    assert ticket["provisional_factor"] == pytest.approx(1.02, abs=1e-9)
    assert ticket["provisional_adjusted_net_tons"] == pytest.approx(23.64, abs=1e-9)
    # 23.6400 x 5500 x 1.0200 = 132620.4 -> 132620
    assert ticket["provisional_value_cents"] == 132620


def test_final_factor_diverges_from_provisional_on_same_load(api, station_operator_headers):
    """PRD §3.5: "The **final** factor, computed at acceptance from the latest
    `VERIFIED` `LAB_VERIFY` sample by `created_at`, is not clamped; instead, when
    the final sugar content falls below 13.00 percent, a penalty of 0.05 is
    subtracted from the base factor, and the result is rounded half-up to 4
    decimal places. Because the two variants typically read different samples,
    the provisional and final factors for the same load commonly diverge."

    Design: Difficulty/dual_variant_calc/ticket_payment_factor_provisional_vs_final
    """
    world = setup_world()
    booking = create_confirmed_booking(
        world["campaign"]["id"], world["station"]["id"], world["member"]["id"],
        SLOT_AM_START, SLOT_AM_END, 30)
    ticket, _s = make_sampled_ticket(booking["id"], 80000, 32000, WEIGH_CLOCK_AM,
                                     sugar_pct=16.50, trash_pct=4.50,
                                     sample_type="STATION_QUICK")
    add_verified_lab_sample(ticket["id"], 16.10, 4.40)
    accepted = validate_success(api.accept_ticket(
        ticket["id"], {"pile_id": world["pile"]["id"]}, station_operator_headers), 200)
    assert accepted["status"] == "ACCEPTED"
    # final basis: sugar 16.10 -> factor 1.00 + 0.10 x 0.04 = 1.0040 (unclamped,
    # no penalty); trash 4.40 -> deducted 1.40%; 24.0 t x 0.986 = 23.6640 t
    assert accepted["final_sugar_pct"] == pytest.approx(16.10, abs=1e-9)
    assert accepted["final_factor"] == pytest.approx(1.004, abs=1e-9)
    assert accepted["adjusted_net_tons_final"] == pytest.approx(23.664, abs=1e-9)
    assert accepted["final_factor"] != pytest.approx(1.02, abs=1e-12)


def test_trash_9_99_stays_below_heavy_tier(api, pool_accountant_headers):
    """PRD §3.5: "The first 3.00 percent of trash is free: the deductible
    percentage is the amount by which `t` exceeds 3.00, or zero if `t` is at or
    below 3.00. Loads at or above 10.00 percent trash are penalized with a heavy
    multiplier of 1.5 applied to the deductible percentage; below 10.00 percent
    the multiplier is 1.0."

    Design: Difficulty/combinatorial_formula/trash_deduction_heavy_tier_nested_min_max
    """
    world = setup_world()
    booking = create_confirmed_booking(
        world["campaign"]["id"], world["station"]["id"], world["member"]["id"],
        SLOT_AM_START, SLOT_AM_END, 25)
    ticket, _s = make_sampled_ticket(booking["id"], 72000, 32000, WEIGH_CLOCK_AM,
                                     sugar_pct=16.00, trash_pct=9.99,
                                     sample_type="STATION_QUICK")
    # deducted = (9.99 - 3.00) x 1.0 = 6.99%; 20.0 t x (1 - 0.0699) = 18.6020 t
    assert ticket["provisional_adjusted_net_tons"] == pytest.approx(18.602, abs=1e-9)
    assert ticket["provisional_factor"] == pytest.approx(1.0, abs=1e-9)


def test_trash_10_00_engages_heavy_multiplier_with_min_cap(api, pool_accountant_headers):
    """PRD §3.5: "Loads at or above 10.00 percent trash are penalized with a
    heavy multiplier of 1.5 applied to the deductible percentage; below 10.00
    percent the multiplier is 1.0. The deducted percentage is the deductible
    percentage times the multiplier, but it is capped at `t` itself — the
    deduction can never consume more trash than the sample measured."

    Design: Difficulty/combinatorial_formula/trash_deduction_heavy_tier_nested_min_max
    """
    world = setup_world()
    booking = create_confirmed_booking(
        world["campaign"]["id"], world["station"]["id"], world["member"]["id"],
        SLOT_AM_START, SLOT_AM_END, 25)
    ticket, _s = make_sampled_ticket(booking["id"], 72000, 32000, WEIGH_CLOCK_AM,
                                     sugar_pct=16.00, trash_pct=10.00,
                                     sample_type="STATION_QUICK")
    # deducted = min((10.00 - 3.00) x 1.5, 10.00) = 10.00%; 20.0 t x 0.90 = 18.0000 t
    assert ticket["provisional_adjusted_net_tons"] == pytest.approx(18.0, abs=1e-9)
    assert ticket["provisional_factor"] == pytest.approx(1.0, abs=1e-9)


def test_trash_free_allowance_boundary_at_3_00(api, pool_accountant_headers):
    """PRD §3.5: "The first 3.00 percent of trash is free: the deductible
    percentage is the amount by which `t` exceeds 3.00, or zero if `t` is at or
    below 3.00."

    Design: Corner/calculations/trash_free_allowance_boundary_at_3_00
    """
    world = setup_world()
    ba = create_confirmed_booking(
        world["campaign"]["id"], world["station"]["id"], world["member"]["id"],
        SLOT_AM_START, SLOT_AM_END, 20)
    ta, _ = make_sampled_ticket(ba["id"], 60000, 32000, WEIGH_CLOCK_AM,
                                sugar_pct=16.00, trash_pct=3.00,
                                sample_type="STATION_QUICK")
    bb = create_confirmed_booking(
        world["campaign"]["id"], world["station"]["id"], world["member"]["id"],
        SLOT_PM_START, SLOT_PM_END, 20)
    tb, _ = make_sampled_ticket(bb["id"], 60000, 32000, WEIGH_CLOCK_PM,
                                sugar_pct=16.00, trash_pct=3.01,
                                sample_type="STATION_QUICK")
    # 14.0 t net each; 3.00 -> 0% deducted; 3.01 -> 0.01% deducted
    assert ta["provisional_adjusted_net_tons"] == pytest.approx(14.0, abs=1e-9)
    assert tb["provisional_adjusted_net_tons"] == pytest.approx(13.9986, abs=1e-9)


def test_provisional_factor_clamped_at_minimum(api, pool_accountant_headers):
    """PRD §3.5: "The **provisional** factor, computed when the ticket enters
    `SAMPLED` from its first recorded sample of any type, clamps the base factor
    into the band from 0.70 to 1.30 inclusive and rounds half-up to 4 decimal
    places; no low-sugar penalty applies."

    Design: Corner/calculations/provisional_factor_clamped_at_minimum
    """
    world = setup_world()
    booking = create_confirmed_booking(
        world["campaign"]["id"], world["station"]["id"], world["member"]["id"],
        SLOT_AM_START, SLOT_AM_END, 20)
    ticket, _s = make_sampled_ticket(booking["id"], 60000, 32000, WEIGH_CLOCK_AM,
                                     sugar_pct=8.00, trash_pct=2.00,
                                     sample_type="STATION_QUICK")
    # raw base = 1.00 + (8.00 - 16.00) x 0.04 = 0.68 -> clamped to 0.7000
    assert ticket["provisional_factor"] == pytest.approx(0.70, abs=1e-9)
    # trash 2.00 <= 3.00 -> no deduction; 14.0 t x 5500 x 0.7000 = 53900
    assert ticket["provisional_adjusted_net_tons"] == pytest.approx(14.0, abs=1e-9)
    assert ticket["provisional_value_cents"] == 53900


def test_final_factor_low_sugar_penalty_boundary(api, station_operator_headers):
    """PRD §3.5: "The **final** factor, computed at acceptance from the latest
    `VERIFIED` `LAB_VERIFY` sample by `created_at`, is not clamped; instead, when
    the final sugar content falls below 13.00 percent, a penalty of 0.05 is
    subtracted from the base factor, and the result is rounded half-up to 4
    decimal places."

    Design: Corner/calculations/final_factor_low_sugar_penalty_boundary
    """
    world = setup_world()
    ba = create_confirmed_booking(
        world["campaign"]["id"], world["station"]["id"], world["member"]["id"],
        SLOT_AM_START, SLOT_AM_END, 20)
    ta = create_weighed_ticket(ba["id"], 72000, 32000, WEIGH_CLOCK_AM)
    add_verified_lab_sample(ta["id"], 13.00, 2.00)
    accepted_a = validate_success(api.accept_ticket(
        ta["id"], {"pile_id": world["pile"]["id"]}, station_operator_headers), 200)
    # 13.00 is NOT below 13.00 -> no penalty: 1.00 + (13.00-16.00) x 0.04 = 0.8800
    assert accepted_a["final_factor"] == pytest.approx(0.88, abs=1e-9)

    bb = create_confirmed_booking(
        world["campaign"]["id"], world["station"]["id"], world["member"]["id"],
        SLOT_PM_START, SLOT_PM_END, 20)
    tb = create_weighed_ticket(bb["id"], 72000, 32000, WEIGH_CLOCK_PM)
    add_verified_lab_sample(tb["id"], 12.99, 2.00)
    accepted_b = validate_success(api.accept_ticket(
        tb["id"], {"pile_id": world["pile"]["id"]}, station_operator_headers), 200)
    # 12.99 < 13.00 -> base 0.8796 minus 0.05 = 0.8296
    assert accepted_b["final_factor"] == pytest.approx(0.8296, abs=1e-9)
