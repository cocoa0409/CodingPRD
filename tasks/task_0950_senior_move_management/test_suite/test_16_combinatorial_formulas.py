"""Multi-input money formulas: nested overtime, the coordination fee tier,
net proceeds and the cross-aggregate stairs surcharge."""

from test_helpers import (
    BILLING_ADMIN,
    MOVE_MANAGER,
    MOVE_START,
    PACKER_CHECK_IN,
    api_client,
    assert_exactly_one_line,
    assert_hours,
    assert_money,
    assert_two_dp,
    assign_crew,
    check_in,
    check_out,
    commission_cents,
    confirm_assignment,
    consignment_fees_cents,
    coordination_fee_cents,
    designate,
    drive_sort_plan_to_approved,
    freeze_and_start,
    get_success_data,
    invoice_lines,
    invoice_of,
    labor_cents,
    long_carry_surcharge_cents,
    net_proceeds_cents,
    new_crew_member,
    new_item,
    new_move_day_plan,
    no_show,
    read_crew_assignment,
    read_engagement,
    read_invoice,
    read_lot,
    read_move_day_plan,
    set_clock,
    setup_completed_move_day,
    setup_engagement,
    setup_move_day_plan_confirmed,
    setup_sold_lot,
    stairs_surcharge_cents,
    travel_surcharge_cents,
    validate_success,
)

ADDENDUM_ROOM = {"approved_addendum_linear_inches": 36}
CHECK_OUT_2330 = "2026-06-15T23:30:00.000Z"


def _lead_works_nine_and_a_half_hours():
    world = setup_move_day_plan_confirmed(room_kwargs=ADDENDUM_ROOM)
    freeze_and_start(world)
    check_in(world["lead_assignment"]["id"], MOVE_START)
    check_in(world["packer_assignment"]["id"], PACKER_CHECK_IN)
    set_clock(CHECK_OUT_2330)
    check_out(world["lead_assignment"]["id"], CHECK_OUT_2330)
    return world


def test_lead_labor_cents_rounds_the_regular_and_overtime_components_separately():
    """PRD §3.7: "Finally `labor_cents` is the regular hours multiplied by the crew
    member's `hourly_rate_cents` and rounded half-up to whole cents, plus the
    overtime hours multiplied by that same rate and by an overtime multiplier of
    1.5 and rounded half-up to whole cents. The two components are rounded
    separately and then added; they are never summed as fractional amounts and
    rounded once."

    Design: Difficulty/combinatorial_formula/crew_labor_cents_nested_overtime_and_role_rate
    """
    world = _lead_works_nine_and_a_half_hours()
    assignment = read_crew_assignment(world["lead_assignment"]["id"])

    assert_hours(assignment["billing_hours"], 9.50, "billing_hours")
    assert_hours(assignment["applied_hours"], 9.50, "applied_hours")
    assert_hours(assignment["overtime_hours"], 1.50, "overtime_hours")
    # 8.00 regular hours at 9500 plus 1.50 overtime hours at 9500 * 1.5.
    assert_money(assignment["labor_cents"], labor_cents(9.50, 9500), "labor_cents")


def test_engagement_rollup_takes_only_the_completed_assignment():
    """PRD §3.7: "The engagement's rollups take only `COMPLETED` assignments:
    `accrued_labor_cents` sums their `labor_cents`, and `billing_hours_total` sums
    their `applied_hours` rounded half-up to two decimal places. Assignments in
    `ASSIGNED`, `CONFIRMED`, `CHECKED_IN`, `NO_SHOW` or `REPLACED` contribute nothing."

    Design: Difficulty/combinatorial_formula/crew_labor_cents_nested_overtime_and_role_rate
    """
    world = _lead_works_nine_and_a_half_hours()
    engagement = read_engagement(world["engagement_id"])

    assert_money(
        engagement["accrued_labor_cents"], labor_cents(9.50, 9500), "accrued_labor_cents"
    )
    assert_hours(engagement["billing_hours_total"], 9.50, "billing_hours_total")
    assert read_crew_assignment(world["packer_assignment"]["id"])["status"] == "CHECKED_IN"


def _issued_invoice_for_the_standard_move_day():
    world = setup_completed_move_day(
        room_kwargs=ADDENDUM_ROOM,
        lead_in=MOVE_START,
        packer_in=PACKER_CHECK_IN,
        lead_out=CHECK_OUT_2330,
        packer_out=None,
        complete_at=CHECK_OUT_2330,
        actual_loaded_volume_cft=2200,
    )
    world["invoice"] = get_success_data(
        api_client.issue_invoice(world["invoice"]["id"], BILLING_ADMIN)
    )
    return world


def test_coordination_fee_tier_is_keyed_on_the_pre_fee_subtotal():
    """PRD §3.11: "First `subtotal_cents` is computed from the lines, excluding any
    coordination-fee line already present. Second the tier is keyed on that pre-fee
    `subtotal_cents`, never on `total_cents`: a subtotal of at most 300000 cents
    takes a cap of 18000, a subtotal above that but at most 800000 takes a cap of
    42000, and anything above 800000 takes a cap of 75000. Third the fee is six
    percent of the subtotal, rounded half-up to whole cents, capped at the tier's cap.
    Fourth `total_cents` is the subtotal plus the fee plus `credits_cents`, so
    credits are applied **after** the fee and never influence the tier."

    Design: Difficulty/combinatorial_formula/invoice_coordination_fee_tier_keyed_on_presubtotal
    """
    world = _issued_invoice_for_the_standard_move_day()
    invoice = read_invoice(world["invoice"]["id"])

    labour = labor_cents(9.50, 9500) + labor_cents(6.00, 6800)
    expected_subtotal = (
        labour
        + travel_surcharge_cents(22)
        + stairs_surcharge_cents(2, 2)
        + long_carry_surcharge_cents(100)
    )
    expected_fee = coordination_fee_cents(expected_subtotal)

    assert invoice["status"] == "ISSUED"
    assert_money(invoice["subtotal_cents"], expected_subtotal, "subtotal_cents")
    assert_money(invoice["coordination_fee_cents"], expected_fee, "coordination_fee_cents")
    assert_money(invoice["credits_cents"], 0, "credits_cents")
    assert_money(invoice["total_cents"], expected_subtotal + expected_fee, "total_cents")
    assert_money(
        invoice["balance_due_cents"], expected_subtotal + expected_fee, "balance_due_cents"
    )


def test_issue_appends_the_three_site_surcharges_before_the_coordination_fee():
    """PRD §3.11: "It appends the three site surcharges and then the coordination
    fee, and recomputes `subtotal_cents`, `coordination_fee_cents`, `credits_cents`,
    `total_cents` and `balance_due_cents` in that pinned order, stamping
    `issued_at_utc`."
    PRD §3.11: "The miles from there up to forty are charged at 317 cents each —
    that is, the lesser of the mileage and forty, less fifteen, floored at zero."

    Design: Difficulty/combinatorial_formula/invoice_coordination_fee_tier_keyed_on_presubtotal
    """
    world = _issued_invoice_for_the_standard_move_day()
    lines = invoice_lines(world["invoice"]["id"])

    assert_exactly_one_line(lines, "TRAVEL_SURCHARGE", travel_surcharge_cents(22))
    assert_exactly_one_line(lines, "STAIRS_SURCHARGE", stairs_surcharge_cents(2, 2))
    assert_exactly_one_line(lines, "LONG_CARRY_SURCHARGE", long_carry_surcharge_cents(100))
    assert read_invoice(world["invoice"]["id"])["issued_at_utc"] is not None


def test_net_proceeds_subtract_separately_rounded_commission_and_fees():
    """PRD §3.8: "`net_proceeds_cents` is then the gross less `commission_cents`
    less `fees_cents`, floored at zero; the commission and the fees are each rounded
    to whole cents **before** the subtraction, never rounded once at the end."
    PRD §3.8: "a gross of at most 50000 cents pays fifty percent, a gross above that
    but at most 250000 cents pays forty percent, and anything above 250000 pays
    thirty percent"

    Design: Difficulty/combinatorial_formula/consignment_net_proceeds_round_each_component_then_subtract
    """
    world = setup_sold_lot(gross_sale_price_cents=250000)
    lot = read_lot(world["lot"]["id"])

    assert_money(lot["commission_cents"], commission_cents(250000), "commission_cents")
    assert_money(lot["fees_cents"], consignment_fees_cents(3), "fees_cents")
    assert_money(
        lot["net_proceeds_cents"], net_proceeds_cents(250000, 3), "net_proceeds_cents"
    )


def test_recording_a_sale_stamps_the_lot_without_touching_the_asking_price():
    """PRD §3.8: "The `fees_cents` figure is a flat pickup charge of 7500 cents plus
    a photography charge of 1200 cents per member item, that photography component
    capped at 12000 cents; the item count used is the number of items pointing at
    the lot at the moment of sale."
    PRD §3.8: "Creating it sets `consignment_lot_id` on each member item, computes
    `item_count` from those members, and computes `current_price_cents`."

    Design: Difficulty/combinatorial_formula/consignment_net_proceeds_round_each_component_then_subtract
    """
    world = setup_sold_lot(gross_sale_price_cents=250000)
    lot = read_lot(world["lot"]["id"])

    assert lot["status"] == "SOLD"
    assert lot["item_count"] == 3
    assert_money(lot["current_price_cents"], 240000, "current_price_cents")
    assert lot["markdown_round"] == 0


def _stairs_scenario_with_a_no_show_driver():
    """Three confirmed crew on a three-flight STUDIO site, then the driver no-shows."""
    world = setup_engagement(origin_stairs_flights=3, with_residence=True)
    item = new_item(
        world["engagement_id"],
        label="Walnut sideboard",
        footprint_linear_inches=96,
        volume_cft=40,
    )
    designate(item["id"], "KEEP", world["room"]["id"])
    world["sort_plan"] = drive_sort_plan_to_approved(
        world["engagement_id"], world["client_party"]["id"]
    )
    plan = new_move_day_plan(world["engagement_id"])
    lead = new_crew_member("Tom Reyes", "LEAD", 9500)
    packer = new_crew_member("Nina Ortiz", "PACKER", 6800)
    driver = new_crew_member("Gus Iyer", "DRIVER", 7400)
    lead_a = assign_crew(plan["id"], lead["id"])
    packer_a = assign_crew(plan["id"], packer["id"])
    driver_a = assign_crew(plan["id"], driver["id"])
    for assignment in (lead_a, packer_a, driver_a):
        confirm_assignment(assignment["id"])
    get_success_data(api_client.confirm_move_day_plan(plan["id"], MOVE_MANAGER))
    no_show(driver_a["id"], "Driver called in sick the night before")

    world.update(
        {
            "plan": plan,
            "lead_assignment": lead_a,
            "packer_assignment": packer_a,
            "driver_assignment": driver_a,
        }
    )
    freeze_and_start(world)
    check_in(lead_a["id"], MOVE_START)
    check_in(packer_a["id"], MOVE_START)
    set_clock("2026-06-15T22:00:00.000Z")
    check_out(lead_a["id"], "2026-06-15T22:00:00.000Z")
    check_out(packer_a["id"], "2026-06-15T22:00:00.000Z")
    world["invoice"] = invoice_of(world["engagement_id"])
    get_success_data(
        api_client.complete_move_day_plan(
            plan["id"], {"actual_loaded_volume_cft": 900}, MOVE_MANAGER
        )
    )
    world["invoice"] = get_success_data(
        api_client.issue_invoice(world["invoice"]["id"], BILLING_ADMIN)
    )
    return world


def test_stairs_surcharge_multiplies_the_confirmed_crew_count_at_issue():
    """PRD §3.11: "The stairs surcharge charges only the flights past the first: the
    engagement's `origin_stairs_flights` less one, floored at zero. Each billable
    flight costs 2500 cents *per crew member*, multiplied by the move-day plan's
    `crew_confirmed_count` at issue time, or by zero when the engagement has no plan."

    Design: Difficulty/combinatorial_formula/stairs_surcharge_scales_with_the_confirmed_crew_count_at_issue
    """
    world = _stairs_scenario_with_a_no_show_driver()

    assert read_crew_assignment(world["driver_assignment"]["id"])["status"] == "NO_SHOW"
    plan = read_move_day_plan(world["plan"]["id"])
    assert plan["crew_confirmed_count"] == 2, (
        "the no-show driver leaves two confirmed crew, not three"
    )

    lines = invoice_lines(world["invoice"]["id"])
    assert_exactly_one_line(lines, "STAIRS_SURCHARGE", stairs_surcharge_cents(3, 2))
    assert_exactly_one_line(lines, "TRAVEL_SURCHARGE", travel_surcharge_cents(22))
    assert_exactly_one_line(lines, "LONG_CARRY_SURCHARGE", long_carry_surcharge_cents(100))


def test_a_smaller_stairs_line_moves_the_coordination_fee_and_the_total():
    """PRD §3.11: "Third the fee is six percent of the subtotal, rounded half-up to
    whole cents, capped at the tier's cap. Fourth `total_cents` is the subtotal plus
    the fee plus `credits_cents`, so credits are applied **after** the fee and never
    influence the tier."
    PRD §3.7: "Then `overtime_hours` is whatever part of `applied_hours` exceeds
    eight hours, and zero when it does not; the boundary is strict, so
    `applied_hours` of exactly 8.00 yields `overtime_hours` of 0.00."

    Design: Difficulty/combinatorial_formula/stairs_surcharge_scales_with_the_confirmed_crew_count_at_issue
    """
    world = _stairs_scenario_with_a_no_show_driver()

    lead = read_crew_assignment(world["lead_assignment"]["id"])
    packer = read_crew_assignment(world["packer_assignment"]["id"])
    assert_hours(lead["applied_hours"], 8.00, "lead applied_hours")
    assert_hours(lead["overtime_hours"], 0.00, "lead overtime_hours")
    assert_money(lead["labor_cents"], labor_cents(8.00, 9500), "lead labor_cents")
    assert_money(packer["labor_cents"], labor_cents(8.00, 6800), "packer labor_cents")

    labour = labor_cents(8.00, 9500) + labor_cents(8.00, 6800)
    assert_money(
        read_engagement(world["engagement_id"])["accrued_labor_cents"],
        labour,
        "accrued_labor_cents",
    )

    expected_subtotal = (
        labour
        + travel_surcharge_cents(22)
        + stairs_surcharge_cents(3, 2)
        + long_carry_surcharge_cents(100)
    )
    invoice = read_invoice(world["invoice"]["id"])
    assert_money(invoice["subtotal_cents"], expected_subtotal, "subtotal_cents")
    assert_money(
        invoice["coordination_fee_cents"],
        coordination_fee_cents(expected_subtotal),
        "coordination_fee_cents",
    )
    assert_money(
        invoice["total_cents"],
        expected_subtotal + coordination_fee_cents(expected_subtotal),
        "total_cents",
    )
