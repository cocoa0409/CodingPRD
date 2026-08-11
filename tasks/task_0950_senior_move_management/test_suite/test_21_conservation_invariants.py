"""Forward action followed by its compensating action: money, time and volume
must all return to exactly their pre-action values."""

from test_helpers import (
    BILLING_ADMIN,
    MOVE_MANAGER,
    MOVE_START,
    api_client,
    assert_credits_match_lines,
    assert_exactly_one_line,
    assert_hours,
    assert_inventory_volume_conservation,
    assert_money,
    assert_two_dp,
    check_in,
    check_out,
    designate,
    disposal_fee_cents,
    get_success_data,
    invoice_lines,
    labor_cents,
    net_proceeds_cents,
    new_item,
    new_time_entry,
    read_crew_assignment,
    read_engagement,
    read_invoice,
    read_item,
    read_lot,
    read_room,
    read_time_entry,
    set_clock,
    setup_engagement,
    setup_move_day_plan_confirmed,
    setup_sold_lot,
    freeze_and_start,
    validate_success,
)

EXPECTED_NET = net_proceeds_cents(250000, 3)
CHECK_OUT_2330 = "2026-06-15T23:30:00.000Z"


def test_settling_a_sold_lot_posts_a_negative_consignment_credit():
    """PRD §3.8: "It appends a `CONSIGNMENT_CREDIT` ledger line whose `amount_cents`
    is the negation of `net_proceeds_cents` with `source_consignment_lot_id` set to
    the lot, then recomputes the invoice's `credits_cents`, `total_cents` and
    `balance_due_cents` and raises the invoice's `version` by one, then refreshes the
    engagement's `consignment_credit_cents`, and finally sets `credited` to true."

    Design: Difficulty/compensating_invariant/consignment_credit_reversal_conserves_invoice_credits
    """
    world = setup_sold_lot(gross_sale_price_cents=250000)
    validate_success(api_client.settle_lot(world["lot"]["id"], BILLING_ADMIN))

    invoice = read_invoice(world["invoice"]["id"])
    assert_money(invoice["credits_cents"], -EXPECTED_NET, "credits_cents")
    assert_money(invoice["total_cents"], -EXPECTED_NET, "total_cents")

    lot = read_lot(world["lot"]["id"])
    assert lot["status"] == "SETTLED"
    assert lot["credited"] is True


def test_returning_the_settled_lot_restores_credits_to_exactly_zero():
    """PRD §2.11: "An invoice's `credits_cents` always equals the sum of
    `amount_cents` over its lines whose `line_type` is `CONSIGNMENT_CREDIT` or
    `CONSIGNMENT_REVERSAL`. For every lot that has been both credited and reversed,
    the negative credit and the positive reversal sum to exactly zero. Settling a lot
    and then returning it to the client must therefore leave `credits_cents` at
    exactly its pre-settle value and `total_cents` at exactly its pre-settle value,
    with two ledger lines remaining on the invoice."

    Design: Difficulty/compensating_invariant/consignment_credit_reversal_conserves_invoice_credits
    """
    world = setup_sold_lot(gross_sale_price_cents=250000)
    get_success_data(api_client.settle_lot(world["lot"]["id"], BILLING_ADMIN))
    validate_success(
        api_client.return_lot_to_client(
            world["lot"]["id"],
            {"reason": "Buyer rescinded, gallery returned the lot"},
            MOVE_MANAGER,
        )
    )
    invoice = read_invoice(world["invoice"]["id"])
    lines = invoice_lines(world["invoice"]["id"])

    assert_money(invoice["credits_cents"], 0, "credits_cents after the round trip")
    assert_money(invoice["total_cents"], 0, "total_cents after the round trip")
    assert_money(invoice["subtotal_cents"], 0, "subtotal_cents")
    assert_exactly_one_line(lines, "CONSIGNMENT_CREDIT", -EXPECTED_NET)
    assert_exactly_one_line(lines, "CONSIGNMENT_REVERSAL", EXPECTED_NET)
    assert_credits_match_lines(invoice, lines)

    lot = read_lot(world["lot"]["id"])
    assert lot["status"] == "RETURNED"
    assert lot["reversed"] is True
    assert_money(
        read_engagement(world["engagement_id"])["consignment_credit_cents"],
        0,
        "consignment_credit_cents",
    )


def _lead_completed_at_nine_and_a_half_hours():
    world = setup_move_day_plan_confirmed()
    freeze_and_start(world)
    check_in(world["lead_assignment"]["id"], MOVE_START)
    set_clock(CHECK_OUT_2330)
    check_out(world["lead_assignment"]["id"], CHECK_OUT_2330)
    return world


def test_adding_a_travel_entry_re_rounds_the_summed_billing_hours():
    """PRD §3.7: "Entries may be added only while the parent assignment is
    `CHECKED_IN` or `COMPLETED`; on a `COMPLETED` assignment every hour and money
    rollup is recomputed in place."
    PRD §3.7: "Each entry carries a `raw_hours`, the exact interval length in hours
    held to four decimal places by truncation, and a `rounded_hours`, that raw figure
    divided by a quarter-hour increment, rounded half-up to a whole number of
    increments and multiplied back, giving a value at two decimal places."

    Design: Difficulty/compensating_invariant/time_entry_void_conserves_billing_hours
    """
    world = _lead_completed_at_nine_and_a_half_hours()
    lead = world["lead_assignment"]["id"]
    entry = new_time_entry(
        lead, "TRAVEL", "2026-06-15T12:00:00.000Z", "2026-06-15T13:06:00.000Z"
    )

    stored = read_time_entry(entry["id"])
    assert round(stored["raw_hours"], 4) == 1.1000, (
        f"raw_hours is truncated to four decimals, got {stored['raw_hours']}"
    )
    assert_two_dp(stored["rounded_hours"], 1.00, "rounded_hours")

    assignment = read_crew_assignment(lead)
    assert_hours(assignment["billing_hours"], 10.50, "billing_hours with the travel entry")
    assert_money(assignment["labor_cents"], labor_cents(10.50, 9500), "labor_cents")
    assert_hours(
        read_engagement(world["engagement_id"])["billing_hours_total"],
        10.50,
        "billing_hours_total",
    )


def test_voiding_the_travel_entry_returns_every_rollup_to_its_pre_add_value():
    """PRD §2.11: "Adding a time entry and then voiding it must return the
    assignment's `billing_hours`, the assignment's `labor_cents` and the engagement's
    `billing_hours_total` to their exact pre-add values. Because the billing view
    rounds the sum rather than the parts, an implementation that subtracts a rounded
    part will drift here."
    PRD §3.7: "Voiding an entry takes a `reason`, stored as `void_reason`, sets
    `voided` to true, and recomputes the assignment's hours and money from the
    remaining non-voided entries; a voided entry is excluded from every rollup
    thereafter."

    Design: Difficulty/compensating_invariant/time_entry_void_conserves_billing_hours
    """
    world = _lead_completed_at_nine_and_a_half_hours()
    lead = world["lead_assignment"]["id"]
    entry = new_time_entry(
        lead, "TRAVEL", "2026-06-15T12:00:00.000Z", "2026-06-15T13:06:00.000Z"
    )
    validate_success(
        api_client.void_time_entry(
            entry["id"],
            {"reason": "Travel already covered by the mileage surcharge"},
            BILLING_ADMIN,
        )
    )
    assert read_time_entry(entry["id"])["voided"] is True

    assignment = read_crew_assignment(lead)
    assert_hours(assignment["billing_hours"], 9.50, "billing_hours")
    assert_hours(assignment["portal_hours"], 9.50, "portal_hours")
    assert_hours(assignment["overtime_hours"], 1.50, "overtime_hours")
    assert_money(assignment["labor_cents"], labor_cents(9.50, 9500), "labor_cents")

    engagement = read_engagement(world["engagement_id"])
    assert_hours(engagement["billing_hours_total"], 9.50, "billing_hours_total")
    assert_money(
        engagement["accrued_labor_cents"], labor_cents(9.50, 9500), "accrued_labor_cents"
    )


def _two_keep_items_in_one_room():
    world = setup_engagement(with_client_party=False, with_residence=True)
    first = new_item(
        world["engagement_id"], label="Walnut sideboard", footprint_linear_inches=96, volume_cft=40
    )
    second = new_item(
        world["engagement_id"], label="Reading chair", footprint_linear_inches=90, volume_cft=35
    )
    designate(first["id"], "KEEP", world["room"]["id"])
    designate(second["id"], "KEEP", world["room"]["id"])
    world["first"] = first
    world["second"] = second
    return world


def test_moving_a_keep_item_to_donate_vacates_the_room_without_losing_volume():
    """PRD §3.4: "Going from `KEEP` to `DONATE` clears `assigned_room_id` to null,
    recomputes the vacated room's `keep_load_linear_inches` and
    `headroom_linear_inches`, raises the item's `redesignation_count` by one, and
    recomputes the engagement's `keep_volume_cft`."
    PRD §2.11: "An engagement's `total_inventory_volume_cft` always equals the sum of
    `volume_cft` over every one of its items regardless of disposition, and no
    designation ever changes it."

    Design: Difficulty/compensating_invariant/designate_round_trip_conserves_inventory_volume
    """
    world = _two_keep_items_in_one_room()
    validate_success(
        api_client.designate_item(world["first"]["id"], {"disposition": "DONATE"}, MOVE_MANAGER)
    )
    engagement = read_engagement(world["engagement_id"])
    assert_two_dp(engagement["keep_volume_cft"], 35.00, "keep_volume_cft")
    assert_inventory_volume_conservation(engagement, 75.00)

    room = read_room(world["room"]["id"])
    assert_two_dp(room["keep_load_linear_inches"], 90.00, "keep_load_linear_inches")
    assert_two_dp(room["headroom_linear_inches"], 102.00, "headroom_linear_inches")
    assert read_item(world["first"]["id"])["assigned_room_id"] is None


def test_the_designation_round_trip_returns_both_buckets_to_their_start():
    """PRD §2.11: "Re-designating an item moves volume between the keep and haul
    buckets; a designation round trip must return both buckets to their exact
    pre-trip values."
    PRD §3.4: "Going from `DONATE` back to `KEEP` requires a supplied
    `assigned_room_id` that passes the space-fit test, sets it, recomputes the room's
    load and headroom, sets `donation_receipt_cents` back to 0, and raises
    `redesignation_count` by one."

    Design: Difficulty/compensating_invariant/designate_round_trip_conserves_inventory_volume
    """
    world = _two_keep_items_in_one_room()
    get_success_data(
        api_client.designate_item(world["first"]["id"], {"disposition": "DONATE"}, MOVE_MANAGER)
    )
    validate_success(
        api_client.designate_item(
            world["first"]["id"],
            {"disposition": "KEEP", "assigned_room_id": world["room"]["id"]},
            MOVE_MANAGER,
        )
    )
    engagement = read_engagement(world["engagement_id"])
    assert_inventory_volume_conservation(engagement, 75.00)
    assert_two_dp(engagement["keep_volume_cft"], 75.00, "keep_volume_cft")
    assert_two_dp(engagement["haul_volume_cft"], 0.00, "haul_volume_cft")

    room = read_room(world["room"]["id"])
    assert_two_dp(room["keep_load_linear_inches"], 186.00, "keep_load_linear_inches")
    assert_two_dp(room["headroom_linear_inches"], 6.00, "headroom_linear_inches")

    item = read_item(world["first"]["id"])
    assert item["disposition"] == "KEEP"
    assert item["redesignation_count"] == 2
    assert_money(item["donation_receipt_cents"], 0, "donation_receipt_cents")


def test_the_settle_and_return_round_trip_leaves_the_charge_bucket_empty():
    """PRD §2.11: "Drift here means the reversal recomputed the net proceeds instead
    of mirroring the amount actually credited."
    PRD §3.8: "The final variant, the one actually posted, is `net_proceeds_cents` —
    gross less commission less fees — and it is the amount any later reversal must
    mirror exactly."

    Design: Difficulty/compensating_invariant/settled_lot_returned_then_hauled_conserves_credits_while_adding_a_disposal_fee
    """
    world = setup_sold_lot(gross_sale_price_cents=250000)
    get_success_data(api_client.settle_lot(world["lot"]["id"], BILLING_ADMIN))
    mid = read_invoice(world["invoice"]["id"])
    assert_money(mid["credits_cents"], -EXPECTED_NET, "credits_cents after settle")
    assert_money(mid["subtotal_cents"], 0, "subtotal_cents after settle")
    assert_money(mid["total_cents"], -EXPECTED_NET, "total_cents after settle")

    validate_success(
        api_client.return_lot_to_client(
            world["lot"]["id"],
            {"reason": "Buyer rescinded, the gallery returned the lot"},
            MOVE_MANAGER,
        )
    )
    after = read_invoice(world["invoice"]["id"])
    assert_money(after["credits_cents"], 0, "credits_cents after the return")
    assert_money(after["total_cents"], 0, "total_cents after the return")

    lot = read_lot(world["lot"]["id"])
    assert lot["status"] == "RETURNED"
    assert lot["credited"] is True
    assert lot["reversed"] is True


def test_hauling_the_returned_lot_adds_a_disposal_fee_the_round_trip_never_refunds():
    """PRD §3.8: "The lot's `disposal_fee_cents` reads 0 until the lot is hauled; at
    haul time it becomes the total `volume_cft` of the lot's member items multiplied
    by 145 cents per cubic foot, rounded half-up to whole cents, and then floored at
    a minimum of 9500 cents — the rounding happens before the floor is applied."
    PRD §3.8: "`HAULED` is the lot's only terminal state; `RETURNED` is not terminal
    precisely because a returned lot can still be hauled."

    Design: Difficulty/compensating_invariant/settled_lot_returned_then_hauled_conserves_credits_while_adding_a_disposal_fee
    """
    world = setup_sold_lot(gross_sale_price_cents=250000)
    get_success_data(api_client.settle_lot(world["lot"]["id"], BILLING_ADMIN))
    get_success_data(
        api_client.return_lot_to_client(
            world["lot"]["id"],
            {"reason": "Buyer rescinded, the gallery returned the lot"},
            MOVE_MANAGER,
        )
    )
    validate_success(api_client.haul_away_lot(world["lot"]["id"], MOVE_MANAGER))

    lot = read_lot(world["lot"]["id"])
    assert lot["status"] == "HAULED"
    expected_fee = disposal_fee_cents(6 + 8 + 3)
    assert_money(lot["disposal_fee_cents"], expected_fee, "disposal_fee_cents")

    lines = invoice_lines(world["invoice"]["id"])
    assert_exactly_one_line(lines, "DISPOSAL_FEE", expected_fee)
    assert_exactly_one_line(lines, "CONSIGNMENT_CREDIT", -EXPECTED_NET)
    assert_exactly_one_line(lines, "CONSIGNMENT_REVERSAL", EXPECTED_NET)

    invoice = read_invoice(world["invoice"]["id"])
    assert_money(invoice["credits_cents"], 0, "credits_cents")
    assert_money(invoice["subtotal_cents"], expected_fee, "subtotal_cents")
    assert_money(invoice["total_cents"], expected_fee, "total_cents")
    engagement = read_engagement(world["engagement_id"])
    assert_money(engagement["consignment_credit_cents"], 0, "consignment_credit_cents")
    assert_inventory_volume_conservation(engagement, 17.00)
