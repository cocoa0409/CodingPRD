"""Pricing calculations: equipment line pricing, crew labor, order totals,
provisional-vs-final divergence, and the constants those passes apply."""
from test_helpers import (
    api_client, validate_success,
    set_clock, new_customer, new_venue, new_equipment, new_crew_member, new_order,
    add_reservation, add_crew_assignment, quote, submit_coi, approve_coi,
    confirm_fresh, add_sub_rental, read_order,
)


# ─── dual_variant_calc / revenue_provisional_vs_final_diverges ─────────
def test_provisional_quote_total_excludes_subrental_and_uses_reserved_qty(api, account_manager_headers):
    """PRD §3.6: "in the provisional pass the confirmed sub-rental cost is excluded
    from this subtotal."
    PRD §3.6: "The provisional grand total is the discounted amount plus the frozen
    rush surcharge, and it is written to `quote_total_cents`."

    Design: Difficulty/dual_variant_calc/revenue_provisional_vs_final_diverges
    """
    set_clock("2026-06-05T00:00:00Z")
    cust = new_customer(credit_limit_cents=100_000_000)
    ven = new_venue(required_coverage_cents=0)
    led = new_equipment(category="LED", total_units=20, daily_rate_cents=12000,
                        replacement_value_cents=500000)
    order = new_order(cust["id"], ven["id"], event_start_date="2026-06-10",
                     event_end_date="2026-06-12")
    add_reservation(order["id"], led["id"], qty=2,
                    reserve_start_date="2026-06-10", reserve_end_date="2026-06-12")

    quoted = validate_success(api.quote_order(order["id"], account_manager_headers), 200)
    # 12000 * 2 units * 3 billable days = 72000 raw; 10% multi-day tier -> 64800 equipment
    # subtotal; rush (event 5 days out) = round(64800 * 0.08) = 5184; quote_total = 69984.
    assert quoted["quote_total_cents"] == 69984, quoted["quote_total_cents"]
    assert quoted["pricing_variant"] == "PROVISIONAL"


def test_final_total_adds_subrental_and_diverges_from_quote(api, account_manager_headers,
                                                            warehouse_manager_headers):
    """PRD §3.9: "The final order-totals pass now includes the order's
    `sub_rental_cost_cents` in the subtotal, reuses the rush surcharge that was frozen
    at quote time rather than recomputing it, and writes the resulting grand total to
    `final_total_cents` while setting `pricing_variant` to `FINAL`."

    Design: Difficulty/dual_variant_calc/revenue_provisional_vs_final_diverges
    """
    set_clock("2026-06-05T00:00:00Z")
    cust = new_customer(credit_limit_cents=100_000_000)
    ven = new_venue(required_coverage_cents=0)
    led = new_equipment(category="LED", total_units=20, daily_rate_cents=12000,
                        replacement_value_cents=500000)
    order = new_order(cust["id"], ven["id"], event_start_date="2026-06-10",
                     event_end_date="2026-06-12")
    res = add_reservation(order["id"], led["id"], qty=2,
                          reserve_start_date="2026-06-10", reserve_end_date="2026-06-12")
    quoted = quote(order["id"])
    assert quoted["quote_total_cents"] == 69984
    coi = submit_coi(order["id"], cust["id"], coverage_amount_cents=100000)
    approve_coi(coi["id"])
    confirm_fresh(order["id"])

    sr = add_sub_rental(order["id"], led["id"], reservation_id=res["id"],
                        direction="SUB_IN", qty=1, cost_cents=20000)
    validate_success(api.confirm_sub_rental(sr["id"], warehouse_manager_headers), 200)
    validate_success(api.load_out_order(order["id"], warehouse_manager_headers), 200)
    validate_success(api.check_out_reservation(res["id"], warehouse_manager_headers), 200)
    validate_success(api.start_event_order(order["id"], account_manager_headers), 200)
    validate_success(api.check_in_reservation(res["id"], {"damaged": False},
                                              warehouse_manager_headers), 200)
    validate_success(api.load_in_order(order["id"], warehouse_manager_headers), 200)

    settled = validate_success(api.settle_order(order["id"], account_manager_headers), 200)
    # FINAL: 64800 equipment (checked_out_qty 2) + 20000 sub-rental + 5184 frozen rush = 89984.
    assert settled["final_total_cents"] == 89984, settled["final_total_cents"]
    assert settled["final_total_cents"] != settled["quote_total_cents"]
    assert settled["pricing_variant"] == "FINAL"


# ─── combinatorial_formula / crew_labor_overtime_operator_premium_mode_a ──
def test_operator_overtime_labor_charge(api, account_manager_headers, crew_chief_headers):
    """PRD §3.6: "Regular hours are paid at the member's `hourly_rate_cents`; overtime
    hours are paid at that rate multiplied by an overtime multiplier of 1.5. Both pay
    components are further scaled by a role multiplier: an `OPERATOR` shift multiplies
    its pay by the operator premium of 1.20, while a `TECH` shift uses a multiplier of
    1.00."

    Design: Difficulty/combinatorial_formula/crew_labor_overtime_operator_premium_mode_a
    """
    cust = new_customer(credit_limit_cents=100_000_000)
    ven = new_venue(required_coverage_cents=0)
    led = new_equipment()
    crew = new_crew_member(name="Op One", crew_role="OPERATOR", hourly_rate_cents=6000)
    order = new_order(cust["id"], ven["id"])
    add_reservation(order["id"], led["id"], qty=1)
    ca = add_crew_assignment(order["id"], crew["id"], assignment_role="OPERATOR",
                             shift_start="2026-06-10T08:00:00Z",
                             shift_end="2026-06-10T20:00:00Z", scheduled_hours=12)

    validate_success(api.quote_order(order["id"], account_manager_headers), 200)
    assignment = validate_success(
        api.get_crew_assignment(ca["id"], crew_chief_headers), 200)
    # 12h: reg 10h @ 6000 * 1.20 = 72000; OT 2h @ 6000 * 1.5 * 1.20 = 21600; total 93600.
    assert assignment["assignment_cost_cents"] == 93600, assignment["assignment_cost_cents"]


def test_operator_overtime_reflected_in_crew_subtotal(api, account_manager_headers, crew_chief_headers):
    """PRD §3.6: "The assignment's `assignment_cost_cents` is the sum of the regular pay
    and the overtime pay, rounded half up to a whole cent, and the order's
    `crew_subtotal_cents` is the sum of those per-assignment charges."

    Design: Difficulty/combinatorial_formula/crew_labor_overtime_operator_premium_mode_a
    """
    cust = new_customer(credit_limit_cents=100_000_000)
    ven = new_venue(required_coverage_cents=0)
    led = new_equipment()
    crew = new_crew_member(name="Op One", crew_role="OPERATOR", hourly_rate_cents=6000)
    order = new_order(cust["id"], ven["id"])
    add_reservation(order["id"], led["id"], qty=1)
    add_crew_assignment(order["id"], crew["id"], assignment_role="OPERATOR",
                        shift_start="2026-06-10T08:00:00Z",
                        shift_end="2026-06-10T20:00:00Z", scheduled_hours=12)

    quoted = validate_success(api.quote_order(order["id"], account_manager_headers), 200)
    assert quoted["crew_subtotal_cents"] == 93600, quoted["crew_subtotal_cents"]


# ─── combinatorial_formula / equipment_line_rounding_per_line_then_sum_mode_b ──
def test_each_equipment_line_rounded_independently(api, account_manager_headers, warehouse_manager_headers):
    """PRD §3.6: "The line's `line_charge_cents` is the discounted raw charge rounded
    half up to a whole cent. Each line is rounded independently, and the order's
    `equipment_subtotal_cents` is the sum of those already-rounded line charges."

    Design: Difficulty/combinatorial_formula/equipment_line_rounding_per_line_then_sum_mode_b
    """
    cust = new_customer(credit_limit_cents=100_000_000)
    ven = new_venue(required_coverage_cents=0)
    dmx = new_equipment(name="DMX Controller", category="LIGHTING", total_units=10,
                        daily_rate_cents=10001, replacement_value_cents=100000)
    order = new_order(cust["id"], ven["id"])
    r1 = add_reservation(order["id"], dmx["id"], qty=1)
    r2 = add_reservation(order["id"], dmx["id"], qty=1)

    validate_success(api.quote_order(order["id"], account_manager_headers), 200)
    res1 = validate_success(api.get_reservation(r1["id"], warehouse_manager_headers), 200)
    res2 = validate_success(api.get_reservation(r2["id"], warehouse_manager_headers), 200)
    # 10001 * 1 * 3 days = 30003 raw; 10% tier -> 27002.7 -> round_half_up -> 27003 per line.
    assert res1["line_charge_cents"] == 27003, res1["line_charge_cents"]
    assert res2["line_charge_cents"] == 27003, res2["line_charge_cents"]


def test_equipment_subtotal_sums_rounded_lines_not_rounded_sum(api, account_manager_headers):
    """PRD §2.5: "into the equipment subtotal (never summed first and rounded once)"
    PRD §3.6: "Each line is rounded independently, and the order's
    `equipment_subtotal_cents` is the sum of those already-rounded line charges."

    Design: Difficulty/combinatorial_formula/equipment_line_rounding_per_line_then_sum_mode_b
    """
    cust = new_customer(credit_limit_cents=100_000_000)
    ven = new_venue(required_coverage_cents=0)
    dmx = new_equipment(name="DMX Controller", category="LIGHTING", total_units=10,
                        daily_rate_cents=10001, replacement_value_cents=100000)
    order = new_order(cust["id"], ven["id"])
    add_reservation(order["id"], dmx["id"], qty=1)
    add_reservation(order["id"], dmx["id"], qty=1)

    quoted = validate_success(api.quote_order(order["id"], account_manager_headers), 200)
    # 27003 + 27003 = 54006 (round-per-line-then-sum). Sum-then-round would give 54005.
    assert quoted["equipment_subtotal_cents"] == 54006, quoted["equipment_subtotal_cents"]


# ─── calculations / standby_line_billed_half_rate ─────────────────────
def test_standby_line_billed_at_half_rate(api, account_manager_headers):
    """PRD §3.6: "If the reservation is a standby line, that raw charge is then
    multiplied by the standby factor of 0.50, halving it."

    Design: Corner/calculations/standby_line_billed_half_rate
    """
    cust = new_customer(credit_limit_cents=100_000_000)
    ven = new_venue(required_coverage_cents=0)
    arr = new_equipment(name="K2 Array", category="SOUND", total_units=8,
                        daily_rate_cents=15000, replacement_value_cents=800000)
    order = new_order(cust["id"], ven["id"], event_start_date="2026-06-10",
                     event_end_date="2026-06-11")
    res = add_reservation(order["id"], arr["id"], qty=2,
                          reserve_start_date="2026-06-10", reserve_end_date="2026-06-11",
                          is_standby=True)

    quoted = validate_success(api.quote_order(order["id"], account_manager_headers), 200)
    # 15000 * 2 * 2 days = 60000 raw; standby * 0.5 = 30000; 2-day tier is 0%.
    reservation = validate_success(
        api.get_reservation(res["id"], account_manager_headers), 200)
    assert reservation["line_charge_cents"] == 30000, reservation["line_charge_cents"]
    assert quoted["equipment_subtotal_cents"] == 30000, quoted["equipment_subtotal_cents"]


# ─── calculations / volume_discount_tier_t1_applied ───────────────────
def test_volume_discount_tier_t1_applied(api, account_manager_headers):
    """PRD §3.6: "A volume discount is selected by that subtotal: a subtotal below
    100000 cents earns no discount, a subtotal from 100000 cents up to but not including
    500000 cents earns 5%, and a subtotal of 500000 cents or more earns 10%."

    Design: Corner/calculations/volume_discount_tier_t1_applied
    """
    set_clock("2026-05-01T00:00:00Z")
    cust = new_customer(credit_limit_cents=100_000_000)
    ven = new_venue(required_coverage_cents=0)
    led = new_equipment(category="LED", total_units=20, daily_rate_cents=12000,
                        replacement_value_cents=500000)
    order = new_order(cust["id"], ven["id"], event_start_date="2026-06-10",
                     event_end_date="2026-06-12")
    add_reservation(order["id"], led["id"], qty=10)

    quoted = validate_success(api.quote_order(order["id"], account_manager_headers), 200)
    # 12000*10*3 = 360000 raw; 10% tier -> 324000 subtotal; tier t1 5% -> 16200; 307800 total.
    assert quoted["equipment_subtotal_cents"] == 324000
    assert quoted["volume_discount_cents"] == 16200, quoted["volume_discount_cents"]
    assert quoted["quote_total_cents"] == 307800, quoted["quote_total_cents"]


# ─── calculations / rush_surcharge_window_boundary_seven_days ──────────
def test_rush_surcharge_at_seven_day_boundary(api, account_manager_headers):
    """PRD §3.6: "if the number of days from the current logical clock date to the
    order's `event_start_date` is 7 or fewer, the `rush_surcharge_cents` is the
    discounted amount multiplied by 8%, rounded half up; otherwise the rush surcharge is
    zero."

    Design: Corner/calculations/rush_surcharge_window_boundary_seven_days
    """
    set_clock("2026-06-03T00:00:00Z")
    cust = new_customer(credit_limit_cents=100_000_000)
    ven = new_venue(required_coverage_cents=0)
    led = new_equipment(category="LED", total_units=20, daily_rate_cents=12000,
                        replacement_value_cents=500000)
    order = new_order(cust["id"], ven["id"], event_start_date="2026-06-10",
                     event_end_date="2026-06-12")
    add_reservation(order["id"], led["id"], qty=1)

    quoted = validate_success(api.quote_order(order["id"], account_manager_headers), 200)
    # discounted 32400; event exactly 7 days out -> rush = round(32400*0.08) = 2592; total 34992.
    assert quoted["rush_surcharge_cents"] == 2592, quoted["rush_surcharge_cents"]
    assert quoted["quote_total_cents"] == 34992, quoted["quote_total_cents"]
