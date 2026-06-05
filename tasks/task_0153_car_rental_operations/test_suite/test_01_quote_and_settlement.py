"""Quote estimation and agreement settlement — the pricing engine.

Covers reservation_quote (forward-looking estimate frozen at confirm) and
agreement_settlement (chronological final settlement at close), including the
provisional-vs-final divergence, combinatorial quote inputs, rate-plan overrides,
and boundary precision on the weekly breakpoint and mileage zero-floor.
"""
from test_helpers import (
    validate_success,
    api_client,
    make_fleet_manager_headers,
    make_rental_agent_headers,
    create_location, create_econ_class, create_vehicle, create_member,
    create_reservation, confirm_reservation, hold_vehicle,
    setup_fleet, setup_open_agreement,
    get_agreement, get_ledger_entries, get_member_accruals,
    set_member_loyalty,
    create_vehicle_class_payload,
)
from test_helpers import factories as f
from test_helpers.assertions import find_ledger_entries, ledger_sum

FM = make_fleet_manager_headers()
RA = make_rental_agent_headers()


# ===========================================================================
# Queue A — dual_variant_calc
# ===========================================================================
def test_settlement_provisional_quote_vs_final_total_diverge(api):
    """PRD §1 (Introduction): "The estimate and the settlement share the same
    date-driven base but diverge precisely by the usage-driven charges that
    could not be known in advance."
    PRD §3.7: "The agreement's `final_total_cents` is the sum of `amount_cents`
    across all of that agreement's ledger entries, where charges are positive
    and credits or reversals are negative."

    Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_diverges_on_agreement
    """
    ctx = setup_open_agreement(api=api, odometer_out=1000, fuel_out_eighths=8)
    res = ctx["reservation"]
    assert res["quoted_total_cents"] == 15000, (
        f"3-day ECON daily 5000 no add-ons should quote 15000, got {res['quoted_total_cents']}"
    )

    closed = validate_success(api.close_rental_agreement(
        ctx["agreement"]["id"], {"odometer_in": 1700, "fuel_in_eighths": 6}, RA,
    ))
    # 700 driven - 600 included = 100 overage * 25 = 2500; fuel 2 eighths * 1500 = 3000.
    assert closed["final_total_cents"] == 20500, (
        f"final = 15000 base + 2500 mileage + 3000 fuel, got {closed['final_total_cents']}"
    )
    assert closed["final_total_cents"] - res["quoted_total_cents"] == 5500


def test_incident_liability_diverges_ldw_vs_no_ldw_same_assessed(api):
    """PRD §3.8: "When the agreement's reservation had `ldw_selected` true, the
    waiver caps the member at the lesser of the assessed damage and that
    per-severity deductible. When `ldw_selected` was false, no waiver applies
    and the member owes the lesser of the assessed damage and the high no-LDW
    ceiling of 5000000 cents."

    Design: Difficulty/dual_variant_calc/incident_liability_ldw_vs_no_ldw_diverges_on_member
    """
    fleet = setup_fleet(api=api, num_vehicles=2)
    loc, cls = fleet["location"], fleet["vehicle_class"]
    vehA, vehB = fleet["vehicles"]
    member = create_member(api=api)

    # Agreement A: ldw_selected true.
    resA = create_reservation(member["id"], loc["id"], loc["id"], cls["id"],
                              "2026-07-01T10:00:00Z", "2026-07-04T10:00:00Z",
                              api=api, ldw_selected=True)
    confirm_reservation(resA["id"], api=api)
    hold_vehicle(vehA["id"], resA["id"], vehA["version"], api=api)
    agrA = validate_success(api.create_rental_agreement(
        f.create_rental_agreement_payload(resA["id"], vehA["id"], odometer_out=1000, fuel_out_eighths=8), RA,
    ), 201)

    # Agreement B: ldw_selected false.
    resB = create_reservation(member["id"], loc["id"], loc["id"], cls["id"],
                              "2026-08-01T10:00:00Z", "2026-08-04T10:00:00Z",
                              api=api, ldw_selected=False)
    confirm_reservation(resB["id"], api=api)
    hold_vehicle(vehB["id"], resB["id"], vehB["version"], api=api)
    agrB = validate_success(api.create_rental_agreement(
        f.create_rental_agreement_payload(resB["id"], vehB["id"], odometer_out=1000, fuel_out_eighths=8), RA,
    ), 201)

    incA = validate_success(api.create_incident_report(
        f.create_incident_report_payload(agrA["id"], "MAJOR", 300000), RA,
    ), 201)
    incB = validate_success(api.create_incident_report(
        f.create_incident_report_payload(agrB["id"], "MAJOR", 300000), RA,
    ), 201)

    # MAJOR deductible 100000; LDW caps at min(300000, 100000) = 100000.
    assert incA["member_liability_cents"] == 100000
    # No LDW: min(300000, 5000000) = 300000.
    assert incB["member_liability_cents"] == 300000


# ===========================================================================
# Queue A — combinatorial_formula
# ===========================================================================
def test_quote_combines_weekly_addons_young_oneway_gold_discount(api):
    """PRD §3.3: "The frozen `quoted_total_cents` is the base plus the add-ons
    plus the young-driver amount plus the one-way drop amount minus the discount."
    PRD §3.3: "when `rental_days` is at least the weekly breakpoint of 7 days,
    the days are split into whole weeks and a leftover remainder ... the base
    equals whole weeks times the weekly rate plus leftover days times the daily rate"

    Design: Difficulty/combinatorial_formula/quote_nested_tier_and_conditional_inputs_mode_a
    """
    loc_lax = create_location(api=api, code="LAX", name="Los Angeles",
                              one_way_drop_fee_cents=4500, young_driver_surcharge_per_day_cents=1000)
    loc_sfo = create_location(api=api, code="SFO", name="San Francisco",
                              one_way_drop_fee_cents=6000, young_driver_surcharge_per_day_cents=1500)
    cls_lux = validate_success(api.create_vehicle_class(create_vehicle_class_payload(
        code="LUX", tier_rank=4, daily_rate_cents=5000, weekly_rate_cents=28000,
        included_miles_per_day=200, overage_per_mile_cents=25,
        ldw_per_day_cents=1500, pai_per_day_cents=800,
    ), FM), 201)
    create_vehicle(loc_lax["id"], cls_lux["id"], api=api, plate="LAX-LUX1", odometer_miles=500)
    member = create_member(api=api, email="young@x.com", full_name="Young Gold", driver_age=23)
    set_member_loyalty(member["id"], api=api, tier="GOLD", lifetime_points=2500, points_balance=2500)

    res = create_reservation(member["id"], loc_lax["id"], loc_sfo["id"], cls_lux["id"],
                             "2026-07-01T10:00:00Z", "2026-07-11T10:00:00Z",
                             api=api, ldw_selected=True, pai_selected=False)
    confirmed = validate_success(api.confirm_reservation(res["id"], RA))
    # 10 days: 1 week (28000) + 3 daily (15000) = 43000 base; addons 10*1500=15000;
    # young 10*1000=10000; one-way 6000; GOLD discount round(43000*0.10)=4300.
    assert confirmed["quoted_total_cents"] == 69700, (
        f"expected 69700, got {confirmed['quoted_total_cents']}"
    )
    assert confirmed["status"] == "CONFIRMED"


def test_loyalty_accrual_floor_before_multiply_order_pinned(api):
    """PRD §3.9: "The earned points are the floor of the agreement's
    `final_total_cents` (floored at zero if somehow negative) divided by the
    points divisor of 100 cents, and that integer quotient is then multiplied
    by the tier multiplier. The division is floored before the multiplication;
    the order is fixed."

    Design: Difficulty/combinatorial_formula/loyalty_accrual_floor_order_pinned_mode_b
    """
    fleet = setup_fleet(api=api, num_vehicles=1)
    loc, cls = fleet["location"], fleet["vehicle_class"]
    veh = fleet["vehicles"][0]
    member = create_member(api=api, email="silver@x.com", full_name="Sil Ver", driver_age=40)
    set_member_loyalty(member["id"], api=api, tier="SILVER", lifetime_points=800, points_balance=800)

    res = create_reservation(member["id"], loc["id"], loc["id"], cls["id"],
                             "2026-07-01T10:00:00Z", "2026-07-04T10:00:00Z", api=api)
    confirm_reservation(res["id"], api=api)
    hold_vehicle(veh["id"], res["id"], veh["version"], api=api)
    agr = validate_success(api.create_rental_agreement(
        f.create_rental_agreement_payload(res["id"], veh["id"], odometer_out=1000, fuel_out_eighths=8), RA,
    ), 201)
    closed = validate_success(api.close_rental_agreement(
        agr["id"], {"odometer_in": 1700, "fuel_in_eighths": 6}, RA,
    ))
    # base 3*5000=15000; overage (700-600)=100mi*25=2500; fuel (8-6)=2*1500=3000;
    # SILVER loyalty discount on base = round_half_up(15000*0.05)=750 (a credit).
    # final = 15000 + 2500 + 3000 - 750 = 19750 (PRD §3.7 sum-of-ledger-lines).
    assert closed["final_total_cents"] == 19750

    accruals = get_member_accruals(member["id"], api=api)
    accrual_events = [a for a in accruals if a["kind"] == "ACCRUAL"]
    assert len(accrual_events) == 1, f"expected one ACCRUAL, got {accrual_events}"
    # floor(19750/100)=197, *2 (SILVER) = 394.
    assert accrual_events[0]["delta_points"] == 394


# ===========================================================================
# Queue A — boundary_precision_check
# ===========================================================================
def test_weekly_breakpoint_six_days_daily_seven_days_weekly(api):
    """PRD §3.3: "when `rental_days` is below 7, the base is simply `rental_days`
    times the daily rate."
    PRD §3.3: "the number of whole weeks is the integer quotient of `rental_days`
    divided by 7, the leftover is the remainder of that division, and the base
    equals whole weeks times the weekly rate plus leftover days times the daily rate"

    Design: Difficulty/boundary_precision_check/weekly_breakpoint_at_six_vs_seven_days
    """
    fleet = setup_fleet(api=api, num_vehicles=2)
    loc, cls = fleet["location"], fleet["vehicle_class"]
    member = create_member(api=api)

    res6 = create_reservation(member["id"], loc["id"], loc["id"], cls["id"],
                              "2026-07-01T10:00:00Z", "2026-07-07T10:00:00Z", api=api)
    res7 = create_reservation(member["id"], loc["id"], loc["id"], cls["id"],
                              "2026-09-01T10:00:00Z", "2026-09-08T10:00:00Z", api=api)
    q6 = validate_success(api.confirm_reservation(res6["id"], RA))
    q7 = validate_success(api.confirm_reservation(res7["id"], RA))
    # 6 days * 5000 = 30000 (daily); 7 days -> 1 week = 28000 (weekly block).
    assert q6["quoted_total_cents"] == 30000
    assert q7["quoted_total_cents"] == 28000


def test_mileage_overage_zero_at_allowance_boundary(api):
    """PRD §3.7: "the overage miles are the miles driven minus that allowance,
    floored at zero so a customer who stays under the allowance owes nothing;
    and the `MILEAGE_OVERAGE` line is the overage miles multiplied by the
    class's `overage_per_mile_cents`."

    Design: Difficulty/boundary_precision_check/mileage_overage_zero_floor_at_allowance
    """
    ctx = setup_open_agreement(api=api, odometer_out=1000, fuel_out_eighths=8)
    agr = ctx["agreement"]
    # included = 200/day * 3 days = 600; drive exactly 600 -> overage 0.
    closed = validate_success(api.close_rental_agreement(
        agr["id"], {"odometer_in": 1600, "fuel_in_eighths": 8}, RA,
    ))
    assert closed["miles_driven"] == 600
    assert closed["final_total_cents"] == 15000, "base only, no overage, no fuel"
    entries = get_ledger_entries(agr["id"], api=api)
    # PRD §3.7 fixes the overage AMOUNT to zero at the allowance boundary
    # ("a customer who stays under the allowance owes nothing"); it does not
    # uniquely determine whether a zero-amount MILEAGE_OVERAGE line is present
    # or suppressed, so assert only the PRD-derivable amount.
    for e in find_ledger_entries(entries, "MILEAGE_OVERAGE"):
        assert e["amount_cents"] == 0, (
            "MILEAGE_OVERAGE must be zero when exactly at the allowance"
        )


# ===========================================================================
# Queue B — calculations section
# ===========================================================================
def test_fuel_charge_applied_when_returned_low(api):
    """PRD §3.7: "the missing eighths are the pickup fuel minus the return fuel,
    floored at zero, and the `FUEL` line is the missing eighths multiplied by
    the per-eighth fuel charge of 1500 cents."

    Design: Corner/calculations/fuel_charge_applied_when_returned_low
    """
    ctx = setup_open_agreement(api=api, odometer_out=1000, fuel_out_eighths=8)
    agr = ctx["agreement"]
    # 600 miles (no overage), fuel 8 -> 5 = 3 missing eighths * 1500 = 4500.
    closed = validate_success(api.close_rental_agreement(
        agr["id"], {"odometer_in": 1600, "fuel_in_eighths": 5}, RA,
    ))
    assert closed["final_total_cents"] == 19500, "15000 base + 4500 fuel"


def test_rate_plan_override_applied_at_quote(api):
    """PRD §3.1: "When the estimate runs, it gathers every rate plan that is
    active, whose `location_id` equals the reservation's pickup location, whose
    `class_id` equals the reservation's class, and whose `effective_from` is at
    or before the reservation's pickup instant; among those candidates it picks
    the one with the latest `effective_from`, breaking ties by the earliest
    `created_at`."

    Design: Corner/calculations/rate_plan_override_applied_at_quote
    """
    loc = create_location(api=api, code="LAX", name="Los Angeles")
    cls = create_econ_class(api=api)
    validate_success(api.create_rate_plan(
        f.create_rate_plan_payload(loc["id"], cls["id"], daily_rate_cents=6000,
                                   weekly_rate_cents=34000,
                                   effective_from="2026-01-01T00:00:00Z", active=True),
        FM,
    ), 201)
    create_vehicle(loc["id"], cls["id"], api=api)
    member = create_member(api=api)
    res = create_reservation(member["id"], loc["id"], loc["id"], cls["id"],
                             "2026-07-01T10:00:00Z", "2026-07-04T10:00:00Z", api=api)
    confirmed = validate_success(api.confirm_reservation(res["id"], RA))
    # 3 days * 6000 (override) = 18000, not 15000.
    assert confirmed["quoted_total_cents"] == 18000


# ===========================================================================
# Queue A — second variants (each difficulty instance carries >=2 tests)
# ===========================================================================
def test_provisional_pickup_ledger_equals_quote_then_usage_rows_added(api):
    """PRD §3.5: "ledger lines are written for the date-driven charges only — a
    `BASE_RENTAL` line, an `ADDONS` line, a `YOUNG_DRIVER` line, a
    `ONE_WAY_DROP` line, and a `LOYALTY_DISCOUNT` line — whose amounts equal the
    corresponding components of the quoted estimate. The usage-driven lines are
    deliberately absent at this stage because the return odometer and fuel are
    not yet known."

    Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_diverges_on_agreement
    """
    ctx = setup_open_agreement(api=api, odometer_out=1000, fuel_out_eighths=8)
    agr = ctx["agreement"]
    # Provisional pass: BASE_RENTAL present, no usage rows yet.
    prov = get_ledger_entries(agr["id"], api=api)
    assert len(find_ledger_entries(prov, "BASE_RENTAL")) == 1
    assert find_ledger_entries(prov, "MILEAGE_OVERAGE") == []
    assert find_ledger_entries(prov, "FUEL") == []

    validate_success(api.close_rental_agreement(agr["id"], {"odometer_in": 1700, "fuel_in_eighths": 6}, RA))
    final = get_ledger_entries(agr["id"], api=api)
    # Final pass keeps BASE_RENTAL and adds the usage rows.
    assert len(find_ledger_entries(final, "BASE_RENTAL")) == 1
    assert len(find_ledger_entries(final, "MILEAGE_OVERAGE")) == 1
    assert len(find_ledger_entries(final, "FUEL")) == 1


def test_incident_liability_total_severity_no_ldw_capped_at_ceiling(api):
    """PRD §3.8: "When `ldw_selected` was false, no waiver applies and the member
    owes the lesser of the assessed damage and the high no-LDW ceiling of
    5000000 cents."

    Design: Difficulty/dual_variant_calc/incident_liability_ldw_vs_no_ldw_diverges_on_member
    """
    ctx = setup_open_agreement(api=api, reservation_overrides={"ldw_selected": False},
                               odometer_out=1000, fuel_out_eighths=8)
    # Assessed above the ceiling: min(6000000, 5000000) = 5000000 with no LDW.
    inc = validate_success(api.create_incident_report(
        f.create_incident_report_payload(ctx["agreement"]["id"], "TOTAL", 6000000), RA,
    ), 201)
    assert inc["member_liability_cents"] == 5000000


def test_quote_standard_member_short_rental_no_conditionals(api):
    """PRD §3.3: "when `rental_days` is below 7, the base is simply `rental_days`
    times the daily rate."
    PRD §3.3: "The young-driver amount is `rental_days` multiplied by the pickup
    location's `young_driver_surcharge_per_day_cents` when the member's
    `driver_age` is below the young-driver threshold of 25, and zero otherwise."

    Design: Difficulty/combinatorial_formula/quote_nested_tier_and_conditional_inputs_mode_a
    """
    fleet = setup_fleet(api=api, num_vehicles=1)
    loc, cls = fleet["location"], fleet["vehicle_class"]
    member = create_member(api=api, driver_age=40)  # STANDARD, above young threshold.
    res = create_reservation(member["id"], loc["id"], loc["id"], cls["id"],
                             "2026-07-01T10:00:00Z", "2026-07-04T10:00:00Z", api=api)
    confirmed = validate_success(api.confirm_reservation(res["id"], RA))
    # 3 days * 5000 = 15000; no add-ons, no young surcharge, same-location, STANDARD (no discount).
    assert confirmed["quoted_total_cents"] == 15000


def test_loyalty_accrual_gold_multiplier_floor_then_multiply(api):
    """PRD §3.9: "The tier multiplier is taken from the member's tier at
    settlement time — three for `GOLD`, two for `SILVER`, and one for `STANDARD`."
    PRD §3.9: "The division is floored before the multiplication; the order is
    fixed."

    Design: Difficulty/combinatorial_formula/loyalty_accrual_floor_order_pinned_mode_b
    """
    fleet = setup_fleet(api=api, num_vehicles=1)
    loc, cls = fleet["location"], fleet["vehicle_class"]
    veh = fleet["vehicles"][0]
    member = create_member(api=api, driver_age=40)
    set_member_loyalty(member["id"], api=api, tier="GOLD", lifetime_points=2500, points_balance=2500)
    res = create_reservation(member["id"], loc["id"], loc["id"], cls["id"],
                             "2026-07-01T10:00:00Z", "2026-07-04T10:00:00Z", api=api)
    confirm_reservation(res["id"], api=api)
    hold_vehicle(veh["id"], res["id"], veh["version"], api=api)
    agr = validate_success(api.create_rental_agreement(
        f.create_rental_agreement_payload(res["id"], veh["id"], odometer_out=1000, fuel_out_eighths=8), RA,
    ), 201)
    # GOLD discount on base: quote = 15000 - round(15000*0.10)=1500 -> 13500;
    # close at 100 miles full fuel -> final 13500. floor(13500/100)=135 *3 = 405.
    closed = validate_success(api.close_rental_agreement(
        agr["id"], {"odometer_in": 1100, "fuel_in_eighths": 8}, RA,
    ))
    assert closed["final_total_cents"] == 13500
    accruals = get_member_accruals(member["id"], api=api)
    earned = [a for a in accruals if a["kind"] == "ACCRUAL"]
    assert len(earned) == 1
    assert earned[0]["delta_points"] == 405


def test_weekly_breakpoint_eight_days_one_week_one_day(api):
    """PRD §3.3: "the number of whole weeks is the integer quotient of
    `rental_days` divided by 7, the leftover is the remainder of that division,
    and the base equals whole weeks times the weekly rate plus leftover days
    times the daily rate"

    Design: Difficulty/boundary_precision_check/weekly_breakpoint_at_six_vs_seven_days
    """
    fleet = setup_fleet(api=api, num_vehicles=1)
    loc, cls = fleet["location"], fleet["vehicle_class"]
    member = create_member(api=api)
    res8 = create_reservation(member["id"], loc["id"], loc["id"], cls["id"],
                              "2026-07-01T10:00:00Z", "2026-07-09T10:00:00Z", api=api)
    q8 = validate_success(api.confirm_reservation(res8["id"], RA))
    # 8 days -> 1 week (28000) + 1 daily (5000) = 33000.
    assert q8["quoted_total_cents"] == 33000


def test_mileage_overage_one_mile_past_allowance_charged(api):
    """PRD §3.7: "the overage miles are the miles driven minus that allowance,
    floored at zero so a customer who stays under the allowance owes nothing;
    and the `MILEAGE_OVERAGE` line is the overage miles multiplied by the
    class's `overage_per_mile_cents`."

    Design: Difficulty/boundary_precision_check/mileage_overage_zero_floor_at_allowance
    """
    ctx = setup_open_agreement(api=api, odometer_out=1000, fuel_out_eighths=8)
    agr = ctx["agreement"]
    # 601 miles, included 600 -> 1 overage mile * 25 = 25.
    closed = validate_success(api.close_rental_agreement(
        agr["id"], {"odometer_in": 1601, "fuel_in_eighths": 8}, RA,
    ))
    assert closed["miles_driven"] == 601
    assert closed["final_total_cents"] == 15025
    entries = get_ledger_entries(agr["id"], api=api)
    overage = find_ledger_entries(entries, "MILEAGE_OVERAGE")
    assert len(overage) == 1
    assert overage[0]["amount_cents"] == 25
