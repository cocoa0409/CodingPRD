"""Surcharge bands, consignment arithmetic, donation receipts, space fit,
progress weighting and quarter-hour rounding."""

from test_helpers import (
    ApiErrorId,
    BILLING_ADMIN,
    MOVE_MANAGER,
    MOVE_START,
    PACKAGE_BASE_CENTS,
    api_client,
    assert_exactly_one_line,
    assert_hours,
    assert_money,
    assert_no_line_of_type,
    assert_two_dp,
    check_in,
    commission_cents,
    consignment_fees_cents,
    coordination_fee_cents,
    designate,
    disposal_fee_cents,
    donation_receipt_cents,
    drive_sort_plan_to_approved,
    freeze_and_start,
    get_success_data,
    heuristic_volume_cft,
    invoice_lines,
    labor_cents,
    long_carry_surcharge_cents,
    markdown_price_cents,
    net_proceeds_cents,
    new_consignment_lot,
    new_item,
    new_time_entry,
    new_vendor,
    package_overage_cents,
    read_crew_assignment,
    read_engagement,
    read_invoice,
    read_item,
    read_lot,
    read_room,
    read_summary,
    set_clock,
    setup_completed_move_day,
    setup_consignment_lot,
    setup_engagement,
    setup_move_day_plan_confirmed,
    stairs_surcharge_cents,
    travel_surcharge_cents,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_the_summary_projects_two_band_travel_and_a_single_long_carry_block():
    """PRD §3.11: "The travel surcharge is marginal, not average. The first fifteen
    miles of the engagement's `mileage_miles` are free. The miles from there up to
    forty are charged at 317 cents each — that is, the lesser of the mileage and
    forty, less fifteen, floored at zero. Every mile beyond forty is charged at 486
    cents — the mileage less forty, floored at zero. Each band is rounded half-up to
    whole cents separately and the two results are then added."
    PRD §3.1: "`projected_total_cents` is pinned as the value the invoice's
    `total_cents` *would* take if the invoice were issued at this instant: the
    current subtotal plus the travel, stairs and long-carry surcharges, plus the
    coordination fee computed from that pre-fee subtotal, plus credits."

    Design: Corner/calculations/summary_projects_two_band_travel_and_long_carry_and_heuristic_volume
    """
    world = setup_engagement(
        with_client_party=False,
        mileage_miles=55,
        origin_stairs_flights=0,
        origin_long_carry_feet=76,
    )
    summary = read_summary(world["engagement_id"])

    expected_subtotal = (
        travel_surcharge_cents(55) + stairs_surcharge_cents(0, 0) + long_carry_surcharge_cents(76)
    )
    assert_money(
        summary["projected_total_cents"],
        expected_subtotal + coordination_fee_cents(expected_subtotal),
        "projected_total_cents",
    )
    assert_two_dp(
        summary["volume_estimate_cft"], heuristic_volume_cft("STUDIO"), "volume_estimate_cft"
    )
    assert summary["progress_pct"] == 0
    assert summary["open_hold_count"] == 0
    assert summary["next_unpack_session_id"] is None
    assert_hours(summary["billing_hours_total"], 0, "billing_hours_total")
    assert_money(summary["accrued_labor_cents"], 0, "accrued_labor_cents")


def test_sitting_exactly_on_all_three_free_allowances_produces_no_surcharge():
    """PRD §3.11: "The long-carry surcharge charges in blocks. The first seventy-five
    feet of `origin_long_carry_feet` are free; the excess beyond that, floored at
    zero, is divided by twenty-five and rounded **up** to a whole number of blocks,
    each block costing 1800 cents. Exactly seventy-five feet therefore yields
    nothing, while seventy-six feet yields one full block."
    PRD §3.11: "The stairs surcharge charges only the flights past the first: the
    engagement's `origin_stairs_flights` less one, floored at zero."

    Design: Corner/calculations/long_carry_and_travel_free_allowances_produce_zero_surcharge
    """
    world = setup_engagement(
        with_client_party=False,
        mileage_miles=15,
        origin_stairs_flights=1,
        origin_long_carry_feet=75,
    )
    summary = read_summary(world["engagement_id"])
    assert travel_surcharge_cents(15) == 0
    assert long_carry_surcharge_cents(75) == 0
    assert_money(summary["projected_total_cents"], 0, "projected_total_cents")
    assert_two_dp(
        summary["volume_estimate_cft"], heuristic_volume_cft("STUDIO"), "volume_estimate_cft"
    )


def test_the_package_pipeline_bills_base_plus_overage_and_its_coordination_fee():
    """PRD §3.11: "Under `PACKAGE` the fixed tier price was already billed at
    engagement creation, and only the hours beyond the tier's allowance are billed,
    at a different rate and with no minimum call-out floor: the allowance is 18 hours
    for `STUDIO`, 26 for `ONE_BED`, 40 for `TWO_BED` and 64 for `HOUSE`, the overage
    is the engagement's `billing_hours_total` less that allowance, floored at zero,
    and the charge is that overage multiplied by 8900 cents per hour and rounded
    half-up to whole cents."

    Design: Corner/calculations/package_pipeline_overage_deposit_and_coordination_fee_end_to_end
    """
    world = setup_completed_move_day(
        billing_mode="PACKAGE",
        package_tier="STUDIO",
        lead_in=MOVE_START,
        packer_in="2026-06-15T17:30:00.000Z",
        lead_out=None,
        packer_out=None,
        complete_at="2026-06-16T03:00:00.000Z",
        actual_loaded_volume_cft=500,
    )
    lead = read_crew_assignment(world["lead_assignment"]["id"])
    packer = read_crew_assignment(world["packer_assignment"]["id"])
    assert_hours(lead["billing_hours"], 13.00, "lead billing_hours")
    assert_hours(lead["applied_hours"], 13.00, "lead applied_hours")
    assert_hours(packer["billing_hours"], 9.50, "packer billing_hours")
    assert_hours(packer["applied_hours"], 9.50, "packer applied_hours")
    assert_hours(
        read_engagement(world["engagement_id"])["billing_hours_total"], 22.50, "billing_hours_total"
    )

    lines = invoice_lines(world["invoice"]["id"])
    assert_no_line_of_type(lines, "HOURLY_LABOR")
    assert_exactly_one_line(lines, "OVERAGE_LABOR", package_overage_cents(22.50, "STUDIO"))
    assert_exactly_one_line(lines, "PACKAGE_BASE", PACKAGE_BASE_CENTS["STUDIO"])

    invoice = validate_success(api_client.issue_invoice(world["invoice"]["id"], BILLING_ADMIN))
    expected_subtotal = (
        PACKAGE_BASE_CENTS["STUDIO"]
        + package_overage_cents(22.50, "STUDIO")
        + travel_surcharge_cents(22)
        + stairs_surcharge_cents(2, 2)
        + long_carry_surcharge_cents(100)
    )
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


def test_the_commission_band_boundary_is_inclusive_on_the_lower_band():
    """PRD §3.8: "The commission is a banded **average** rate applied to the whole
    gross, not a marginal one: a gross of at most 50000 cents pays fifty percent, a
    gross above that but at most 250000 cents pays forty percent, and anything above
    250000 pays thirty percent — so a lot selling for exactly 50000 pays half, while
    one selling for 50001 pays forty percent of the whole."

    Design: Corner/calculations/consignment_commission_band_boundary_is_inclusive_on_the_lower_band
    """
    world = setup_consignment_lot(list_price_cents=60000)
    eng_id = world["engagement_id"]
    second_specs = [
        {
            "label": f"Print {suffix}",
            "category": "ARTWORK",
            "footprint_linear_inches": 20,
            "volume_cft": 4,
            "appraised_value_cents": 40000,
            "appraisal_source": "APPRAISED",
        }
        for suffix in ("D", "E", "F")
    ]
    second_items = []
    for spec in second_specs:
        item = new_item(eng_id, **spec)
        designate(item["id"], "SELL")
        second_items.append(item["id"])
    lot_b = new_consignment_lot(
        eng_id, world["vendor"]["id"], 60000, "2026-05-05", second_items
    )

    validate_success(
        api_client.record_lot_sale(
            world["lot"]["id"], {"gross_sale_price_cents": 50000, "sold_on": "2026-05-20"}, MOVE_MANAGER
        )
    )
    validate_success(
        api_client.record_lot_sale(
            lot_b["id"], {"gross_sale_price_cents": 50001, "sold_on": "2026-05-20"}, MOVE_MANAGER
        )
    )
    on_edge = read_lot(world["lot"]["id"])
    above_edge = read_lot(lot_b["id"])
    assert_money(on_edge["commission_cents"], commission_cents(50000), "band-1 commission")
    assert_money(on_edge["fees_cents"], consignment_fees_cents(3), "band-1 fees")
    assert_money(on_edge["net_proceeds_cents"], net_proceeds_cents(50000, 3), "band-1 net")
    assert_money(above_edge["commission_cents"], commission_cents(50001), "band-2 commission")
    assert_money(above_edge["fees_cents"], consignment_fees_cents(3), "band-2 fees")
    assert_money(above_edge["net_proceeds_cents"], net_proceeds_cents(50001, 3), "band-2 net")


def test_the_photography_fee_is_capped_and_markdowns_never_compound():
    """PRD §3.8: "The `fees_cents` figure is a flat pickup charge of 7500 cents plus
    a photography charge of 1200 cents per member item, that photography component
    capped at 12000 cents; the item count used is the number of items pointing at the
    lot at the moment of sale."
    PRD §3.8: "Markdowns run twice at most and are always taken off the **original**
    list price rather than compounded off the previous price."

    Design: Corner/calculations/consignment_photo_fee_is_capped_and_markdown_is_not_compounded
    """
    specs = [
        {
            "label": f"Lot piece {index}",
            "category": "MISC",
            "footprint_linear_inches": 8,
            "volume_cft": 2,
            "appraised_value_cents": 20000,
            "appraisal_source": "APPRAISED",
        }
        for index in range(1, 12)
    ]
    world = setup_consignment_lot(item_specs=specs, list_price_cents=240000)

    validate_success(api_client.mark_down_lot(world["lot"]["id"], MOVE_MANAGER))
    assert_money(
        read_lot(world["lot"]["id"])["current_price_cents"],
        markdown_price_cents(240000, 1),
        "current_price_cents after one markdown",
    )
    validate_success(api_client.mark_down_lot(world["lot"]["id"], MOVE_MANAGER))
    assert_money(
        read_lot(world["lot"]["id"])["current_price_cents"],
        markdown_price_cents(240000, 2),
        "current_price_cents after two markdowns",
    )

    validate_success(
        api_client.record_lot_sale(
            world["lot"]["id"],
            {"gross_sale_price_cents": 156000, "sold_on": "2026-05-25"},
            MOVE_MANAGER,
        )
    )
    lot = read_lot(world["lot"]["id"])
    assert lot["item_count"] == 11
    assert_money(lot["fees_cents"], consignment_fees_cents(11), "fees_cents")
    assert_money(lot["commission_cents"], commission_cents(156000), "commission_cents")
    assert_money(lot["net_proceeds_cents"], net_proceeds_cents(156000, 11), "net_proceeds_cents")


def test_a_third_markdown_is_refused_and_leaves_the_price_alone():
    """PRD §2.7: "The lot's `markdown_round` is strictly less than 2. Otherwise
    `ERR_MARKDOWN_ROUNDS_EXHAUSTED`, HTTP 409. Applies to
    `POST /consignment-lots/{id}/mark-down`."
    PRD §3.8: "At `markdown_round` 0 no discount applies at all. A third attempt is
    refused with `ERR_MARKDOWN_ROUNDS_EXHAUSTED`. Both the move manager and the
    vendor may mark down."

    Design: Corner/calculations/markdown_beyond_the_cap_is_refused
    """
    world = setup_consignment_lot(
        item_specs=[
            {
                "label": "Mantel clock",
                "category": "MISC",
                "footprint_linear_inches": 12,
                "volume_cft": 3,
                "appraised_value_cents": 45000,
                "appraisal_source": "APPRAISED",
            }
        ],
        list_price_cents=240000,
    )
    get_success_data(api_client.mark_down_lot(world["lot"]["id"], MOVE_MANAGER))
    get_success_data(api_client.mark_down_lot(world["lot"]["id"], MOVE_MANAGER))

    validate_error(
        api_client.mark_down_lot(world["lot"]["id"], MOVE_MANAGER),
        ApiErrorId.ERR_MARKDOWN_ROUNDS_EXHAUSTED.value,
    )
    lot = read_lot(world["lot"]["id"])
    assert lot["markdown_round"] == 2
    assert_money(lot["current_price_cents"], markdown_price_cents(240000, 2), "current_price_cents")
    assert lot["status"] == "MARKED_DOWN"


def test_the_disposal_floor_governs_a_lot_priced_below_the_break_even_volume():
    """PRD §3.8: "The lot's `disposal_fee_cents` reads 0 until the lot is hauled; at
    haul time it becomes the total `volume_cft` of the lot's member items multiplied
    by 145 cents per cubic foot, rounded half-up to whole cents, and then floored at
    a minimum of 9500 cents — the rounding happens before the floor is applied."
    PRD §3.8: "Each member item's disposition changes to `HAUL_AWAY` and its
    handling state to `REMOVED` **even when `disposition_locked` is true**, because a
    system cascade is not a re-designation request."

    Design: Corner/calculations/disposal_fee_floor_applies_below_the_break_even_volume
    """
    specs = [
        {
            "label": label,
            "category": "FURNITURE",
            "footprint_linear_inches": 40,
            "volume_cft": 30,
            "appraised_value_cents": 30000,
            "appraisal_source": "APPRAISED",
        }
        for label in ("Bureau", "Sideboard")
    ]
    world = setup_consignment_lot(item_specs=specs, list_price_cents=80000)
    set_clock("2026-06-05T00:00:00.000Z")
    get_success_data(api_client.declare_lot_unsold(world["lot"]["id"], MOVE_MANAGER))

    validate_success(api_client.haul_away_lot(world["lot"]["id"], MOVE_MANAGER))
    lot = read_lot(world["lot"]["id"])
    assert lot["status"] == "HAULED"
    expected = disposal_fee_cents(60)
    assert_money(lot["disposal_fee_cents"], expected, "disposal_fee_cents")

    assert_exactly_one_line(invoice_lines(world["invoice"]["id"]), "DISPOSAL_FEE", expected)
    assert_money(
        read_invoice(world["invoice"]["id"])["subtotal_cents"], expected, "subtotal_cents"
    )
    member = read_item(world["items"][0]["id"])
    assert member["disposition"] == "HAUL_AWAY"
    assert member["handling_state"] == "REMOVED"


def test_the_donation_receipt_variant_is_keyed_on_provenance_and_capped():
    """PRD §3.4: "That receipt has two variants keyed on provenance: a self-reported
    value is discounted to 0.30 of the stated amount, while a professionally
    appraised value is taken at 0.85 — so the same object can be worth nearly three
    times as much on the receipt depending only on who valued it. The product is
    rounded half-up to whole cents and then capped at 500000 cents; the rounding
    happens before the cap, never after."

    Design: Corner/calculations/donation_receipt_variants_and_cap
    """
    world = setup_engagement(with_client_party=False)
    eng_id = world["engagement_id"]
    self_reported = new_item(
        eng_id,
        label="Dining set",
        footprint_linear_inches=120,
        volume_cft=60,
        appraised_value_cents=200000,
        appraisal_source="SELF_REPORTED",
    )
    appraised = new_item(
        eng_id,
        label="Persian rug",
        category="MISC",
        footprint_linear_inches=10,
        volume_cft=8,
        appraised_value_cents=800000,
        appraisal_source="APPRAISED",
    )
    designate(self_reported["id"], "DONATE")
    assert_money(
        read_item(self_reported["id"])["donation_receipt_cents"],
        donation_receipt_cents(200000, "SELF_REPORTED"),
        "self-reported receipt",
    )
    designate(appraised["id"], "DONATE")
    assert_money(
        read_item(appraised["id"])["donation_receipt_cents"],
        donation_receipt_cents(800000, "APPRAISED"),
        "capped appraised receipt",
    )

    validate_success(
        api_client.appraise_item(
            self_reported["id"],
            {"appraised_value_cents": 200000, "appraisal_source": "APPRAISED"},
            MOVE_MANAGER,
        )
    )
    re_appraised = read_item(self_reported["id"])
    assert_money(
        re_appraised["donation_receipt_cents"],
        donation_receipt_cents(200000, "APPRAISED"),
        "re-appraised receipt",
    )
    assert re_appraised["appraisal_source"] == "APPRAISED"


def test_a_prospective_load_exactly_equal_to_capacity_fits_and_one_inch_more_does_not():
    """PRD §3.4: "The linear test comes first: the room's current
    `keep_load_linear_inches`, excluding this item if it is already in the room, plus
    the item's `footprint_linear_inches`, must be less than or equal to the room's
    `effective_capacity_linear_inches`. A prospective load exactly equal to capacity
    fits."
    PRD §3.4: "The linear failure reports `ERR_ROOM_CAPACITY_EXCEEDED` and wins over
    the volume failure, which reports `ERR_ROOM_VOLUME_EXCEEDED`."

    Design: Corner/calculations/space_fit_inclusive_boundary_and_volume_check_runs_second
    """
    world = setup_engagement(
        with_client_party=False,
        with_residence=True,
        room_kwargs={"nominal_linear_inches": 240, "nominal_volume_cft": 100},
    )
    eng_id, room_id = world["engagement_id"], world["room"]["id"]
    exact = new_item(eng_id, label="Exact-fit wall unit", footprint_linear_inches=192, volume_cft=50)
    one_inch = new_item(eng_id, label="One inch too wide", footprint_linear_inches=1, volume_cft=1)

    validate_success(
        api_client.designate_item(
            exact["id"], {"disposition": "KEEP", "assigned_room_id": room_id}, MOVE_MANAGER
        )
    )
    assert read_item(exact["id"])["disposition"] == "KEEP"
    room = read_room(room_id)
    assert_two_dp(room["keep_load_linear_inches"], 192.00, "keep_load_linear_inches")
    assert_two_dp(room["headroom_linear_inches"], 0.00, "headroom_linear_inches")

    validate_error(
        api_client.designate_item(
            one_inch["id"], {"disposition": "KEEP", "assigned_room_id": room_id}, MOVE_MANAGER
        ),
        ApiErrorId.ERR_ROOM_CAPACITY_EXCEEDED.value,
    )
    assert read_item(one_inch["id"])["disposition"] == "UNDECIDED"


def test_progress_pct_counts_only_milestones_that_are_exactly_complete():
    """PRD §3.1: "`progress_pct` is a weighted score over milestones whose status is
    exactly `COMPLETE` — 10 for assessment, 25 for the sort plan, 15 for packing, 30
    for move day, 15 for settle-in and 5 for close-out, six weights summing to
    exactly 100 — with `REOPENED` and `IN_PROGRESS` milestones contributing nothing."
    PRD §3.1: "from the first catalogued item onward the inventory rollup applies,
    summing `volume_cft` across every item of the engagement regardless of
    disposition or handling state, which is exactly what `total_inventory_volume_cft`
    stores"

    Design: Corner/calculations/engagement_progress_pct_weights_sum_to_one_hundred
    """
    world = setup_engagement()
    eng_id = world["engagement_id"]
    item = new_item(eng_id, label="Old linens", category="LINENS", footprint_linear_inches=10, volume_cft=5)
    designate(item["id"], "DONATE")
    drive_sort_plan_to_approved(eng_id, world["client_party"]["id"])

    summary = read_summary(eng_id)
    assert summary["progress_pct"] == 35
    assert summary["phase"] == "PACK"
    assert_two_dp(summary["volume_estimate_cft"], 5.00, "volume_estimate_cft")


def test_a_seven_and_a_half_minute_entry_rounds_half_up_to_a_quarter_hour():
    """PRD §3.7: "Each entry carries a `raw_hours`, the exact interval length in
    hours held to four decimal places by truncation, and a `rounded_hours`, that raw
    figure divided by a quarter-hour increment, rounded half-up to a whole number of
    increments and multiplied back, giving a value at two decimal places."
    PRD §3.7: "Both draw on the same eligible set: the assignment's entries whose
    `voided` is false and whose `entry_kind` is `LABOR` or `TRAVEL`; break entries
    are computed the same way as any other but are excluded from both representations."

    Design: Corner/calculations/time_entry_quarter_hour_rounding_half_up_boundary
    """
    world = setup_move_day_plan_confirmed()
    freeze_and_start(world)
    lead = world["lead_assignment"]["id"]
    check_in(lead, MOVE_START)

    travel = new_time_entry(
        lead, "TRAVEL", "2026-06-15T09:00:00.000Z", "2026-06-15T09:07:30.000Z"
    )
    rest = new_time_entry(lead, "BREAK", "2026-06-15T12:00:00.000Z", "2026-06-15T13:00:00.000Z")

    assert round(travel["raw_hours"], 4) == 0.1250, (
        f"raw_hours is truncated to four decimals, got {travel['raw_hours']}"
    )
    assert_two_dp(travel["rounded_hours"], 0.25, "travel rounded_hours")
    assert round(rest["raw_hours"], 4) == 1.0000, (
        f"raw_hours is truncated to four decimals, got {rest['raw_hours']}"
    )
    assert_two_dp(rest["rounded_hours"], 1.00, "break rounded_hours")

    assignment = read_crew_assignment(lead)
    assert_hours(assignment["portal_hours"], 0.25, "portal_hours excludes the break")
    assert_hours(assignment["billing_hours"], 0.25, "billing_hours excludes the break")


def test_an_entry_whose_end_equals_its_start_is_refused():
    """PRD §2.7: "`ended_at_utc` is strictly after `started_at_utc` on a time entry,
    and the check-out `at_utc` is strictly after `checked_in_at_utc`. Otherwise
    `ERR_INVALID_TIME_RANGE`, HTTP 422. Applies to `POST /time-entries` and
    `POST /crew-assignments/{id}/check-out`."

    Design: Corner/calculations/invalid_time_range_on_time_entry_is_rejected
    """
    world = setup_move_day_plan_confirmed()
    freeze_and_start(world)
    lead = world["lead_assignment"]["id"]
    check_in(lead, MOVE_START)

    validate_error(
        api_client.create_time_entry(
            {
                "crew_assignment_id": lead,
                "entry_kind": "LABOR",
                "started_at_utc": "2026-06-15T15:00:00.000Z",
                "ended_at_utc": "2026-06-15T15:00:00.000Z",
            },
            MOVE_MANAGER,
        ),
        ApiErrorId.ERR_INVALID_TIME_RANGE.value,
    )
    _, meta = validate_paginated(
        api_client.list_time_entries(MOVE_MANAGER, params={"crew_assignment_id": lead})
    )
    assert meta["total_count"] == 0
    assert_hours(read_crew_assignment(lead)["billing_hours"], 0, "billing_hours")


def test_the_consignment_minimum_filters_the_sell_route_and_not_the_donate_route():
    """PRD §3.4: "Moving to `DONATE` recomputes the item's `donation_receipt_cents`
    under the variant selected by its `appraisal_source`."
    PRD §3.4: "Moving to `SELL` additionally requires `appraised_value_cents` of at
    least 15000 cents — exactly 15000 is consignable, one cent less is not, and the
    request is then refused with `ERR_ITEM_BELOW_CONSIGN_MINIMUM` — and it clears
    `assigned_room_id` to null."

    Design: Corner/calculations/consign_route_decision_matches_the_designate_gate
    """
    world = setup_engagement(with_client_party=False)
    item = new_item(
        world["engagement_id"],
        label="Brass candlesticks",
        category="MISC",
        footprint_linear_inches=6,
        volume_cft=1,
        appraised_value_cents=14999,
        appraisal_source="APPRAISED",
    )
    validate_success(
        api_client.designate_item(item["id"], {"disposition": "DONATE"}, MOVE_MANAGER)
    )
    donated = read_item(item["id"])
    assert donated["disposition"] == "DONATE"
    assert_money(
        donated["donation_receipt_cents"],
        donation_receipt_cents(14999, "APPRAISED"),
        "donation_receipt_cents",
    )
    engagement = read_engagement(world["engagement_id"])
    assert_two_dp(engagement["keep_volume_cft"], 0.00, "keep_volume_cft")
    assert_two_dp(engagement["haul_volume_cft"], 0.00, "haul_volume_cft")
    assert_two_dp(engagement["total_inventory_volume_cft"], 1.00, "total_inventory_volume_cft")
