"""The costing ladder as a quote prices it: parts markup, rounding and labour bands."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_close,
    assert_money,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]


def _rounding_world():
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Millbrook Homestead",
        email="ap@millbrook.example",
        membership_tier="NONE",
        account_jurisdiction="JUR_CHARLIE",
        property_jurisdiction="JUR_CHARLIE",
        well_jurisdiction="JUR_CHARLIE",
        address_line="9 Millbrook Way",
        household_size=2,
        depth_feet=150.0,
        drawdown=8.0,
        technician_tier="APPRENTICE",
        technician_name="Sam Okafor",
    )
    part = fixtures.new_part("CON-5001", "CONSUMABLE", 5001, on_hand_qty=40)
    inspection = fixtures.completed_inspection(
        world["well_id"],
        world["technician_id"],
        "2026-06-01T10:00:00Z",
        measured_yield_gpm=12.0,
        static_level_feet=35.0,
        observed_drawdown_gallons=8.0,
    )
    quote = fixtures.new_quote(
        world["property_id"],
        world["well_id"],
        inspection["id"],
        "REPAIR",
        60,
        "2026-06-03T12:00:00Z",
        "APPRENTICE",
    )
    added = fixtures.add_quote_line(quote["id"], part["id"], 3)
    return {"quote_id": quote["id"], "line_id": added["line_id"]}


def test_a_part_is_marked_up_and_rounded_once_per_unit(api):
    """PRD 2.9: "**Parts are rounded per unit, then extended, then summed.** The marked-up
    price of one unit is rounded to whole cents before it is multiplied by the quantity;
    the already-rounded line extensions are what get added together."
    PRD 2.9: "For example, a part costing 5001 cents at quantity 3 gives a unit price of
    7001 cents and an extension of 21003 cents; sum-then-round would give 21004."
    PRD 3.5: "A unit cost of at most 5000 cents carries a markup of 0.60; above 5000 and
    at most 25000 carries 0.40; above 25000 and at most 100000 carries 0.28; above 100000
    carries 0.18."

    Design: Difficulty/combinatorial_formula/parts_rounding_mode_b_round_per_unit_then_extend_not_sum_then_round
    """
    world = _rounding_world()
    validate_success(api.price_quote(world["quote_id"], ESTIMATOR))

    line = fixtures.get_quote_line(world["line_id"])
    assert_money(line["unit_cost_cents_pinned"], 5001, "QuoteLine.unit_cost_cents_pinned")
    assert_close(line["markup_pct_applied"], 0.40, "QuoteLine.markup_pct_applied")
    assert_money(line["unit_price_cents"], 7001, "QuoteLine.unit_price_cents")
    assert_money(line["extended_price_cents"], 21003, "QuoteLine.extended_price_cents")


def test_the_quote_total_assembles_the_rounded_extensions(api):
    """PRD 3.6: "`parts_subtotal_cents` is the sum of the extended prices of the `ACTIVE`
    lines."
    PRD 3.6: "`tax_cents` is `TAX_RATE_PCT` (7.25 percent) applied to the **parts
    subtotal only** and rounded half up once — **labour is not taxable and neither is the
    permit fee**. `total_cents` is the sum of the four."
    PRD 3.5: "The base rates are 6500 cents an hour for `APPRENTICE`, 9500 for
    `JOURNEYMAN` and 13500 for `MASTER`."

    Design: Difficulty/combinatorial_formula/parts_rounding_mode_b_round_per_unit_then_extend_not_sum_then_round
    """
    world = _rounding_world()
    priced = validate_success(api.price_quote(world["quote_id"], ESTIMATOR))
    assert_money(priced["parts_subtotal_cents"], 21003, "Quote.parts_subtotal_cents")
    assert_money(priced["labor_subtotal_cents"], 6500, "Quote.labor_subtotal_cents")
    assert_money(priced["permit_fee_cents"], 0, "Quote.permit_fee_cents")
    assert_money(priced["tax_cents"], 1523, "Quote.tax_cents")
    assert_money(priced["total_cents"], 29026, "Quote.total_cents")
    assert priced["status"] == "PRICED"


def _band_edge_world():
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Boundary Creek LLC",
        email="ap@boundarycreek.example",
        membership_tier="NONE",
        account_jurisdiction="JUR_CHARLIE",
        property_jurisdiction="JUR_CHARLIE",
        well_jurisdiction="JUR_CHARLIE",
        address_line="8 Boundary Creek",
        distance_miles=15.0,
        household_size=2,
        depth_feet=160.0,
        drawdown=8.0,
        technician_tier="APPRENTICE",
        technician_name="Yuki Tan",
    )
    part_lo = fixtures.new_part("CON-5000", "CONSUMABLE", 5000, on_hand_qty=30)
    part_hi = fixtures.new_part("CON-5001-B", "CONSUMABLE", 5001, on_hand_qty=30)
    inspection = fixtures.completed_inspection(
        world["well_id"],
        world["technician_id"],
        "2026-06-01T10:00:00Z",
        measured_yield_gpm=11.0,
        static_level_feet=30.0,
        observed_drawdown_gallons=8.0,
    )
    quote = fixtures.new_quote(
        world["property_id"],
        world["well_id"],
        inspection["id"],
        "REPAIR",
        60,
        "2026-06-03T12:00:00Z",
        "APPRENTICE",
    )
    line_lo = fixtures.add_quote_line(quote["id"], part_lo["id"], 1)["line_id"]
    line_hi = fixtures.add_quote_line(quote["id"], part_hi["id"], 1)["line_id"]
    return {"quote_id": quote["id"], "line_lo": line_lo, "line_hi": line_hi}


def test_one_extra_cent_of_cost_drops_the_marked_up_price(api):
    """PRD 3.5: "A unit cost of at most 5000 cents carries a markup of 0.60; above 5000
    and at most 25000 carries 0.40; above 25000 and at most 100000 carries 0.28; above
    100000 carries 0.18. All three band ceilings are inclusive."
    PRD 3.5: "Because the bands are flat rather than marginal, the marked-up price is
    **not monotone** in cost: a unit cost of 5000 prices at 8000 while 5001 prices at
    7001; 25000 prices at 35000 while 25001 prices at 32001; 100000 prices at 128000
    while 100001 prices at 118001."

    Design: Difficulty/boundary_precision_check/parts_markup_band_boundary_5000_inclusive_versus_5001
    """
    world = _band_edge_world()
    validate_success(api.price_quote(world["quote_id"], ESTIMATOR))

    low = fixtures.get_quote_line(world["line_lo"])
    high = fixtures.get_quote_line(world["line_hi"])
    assert_close(low["markup_pct_applied"], 0.60, "QuoteLine.markup_pct_applied")
    assert_money(low["unit_price_cents"], 8000, "QuoteLine.unit_price_cents")
    assert_close(high["markup_pct_applied"], 0.40, "QuoteLine.markup_pct_applied")
    assert_money(high["unit_price_cents"], 7001, "QuoteLine.unit_price_cents")
    assert high["unit_price_cents"] < low["unit_price_cents"]


def test_the_band_edge_pair_sums_into_the_quote_and_its_tax(api):
    """PRD 3.6: "`parts_subtotal_cents` is the sum of the extended prices of the `ACTIVE`
    lines."
    PRD 3.6: "`tax_cents` is `TAX_RATE_PCT` (7.25 percent) applied to the **parts
    subtotal only** and rounded half up once — **labour is not taxable and neither is the
    permit fee**. `total_cents` is the sum of the four."

    Design: Difficulty/boundary_precision_check/parts_markup_band_boundary_5000_inclusive_versus_5001
    """
    world = _band_edge_world()
    priced = validate_success(api.price_quote(world["quote_id"], ESTIMATOR))
    assert_money(priced["parts_subtotal_cents"], 15001, "Quote.parts_subtotal_cents")
    assert_money(priced["tax_cents"], 1088, "Quote.tax_cents")


def test_the_two_upper_markup_band_edges_invert_the_same_way(api):
    """PRD 3.5: "Because the bands are flat rather than marginal, the marked-up price is
    **not monotone** in cost: a unit cost of 5000 prices at 8000 while 5001 prices at
    7001; 25000 prices at 35000 while 25001 prices at 32001; 100000 prices at 128000
    while 100001 prices at 118001. A more expensive part can genuinely cost the customer
    less."
    PRD 3.5: "The **unit price** is the unit cost multiplied by one plus the markup
    fraction, rounded half up to whole cents *per unit*. The **extended price** is that
    rounded unit price multiplied by the quantity."

    Design: Corner/calculations/corner_calc_parts_markup_upper_band_edges_are_non_monotone
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Markup Edge Co",
        email="me@corner.example",
        address_line="25 Markup",
        drawdown=6.0,
        technician_name="Markup Tech",
    )
    costs = [25000, 25001, 100000, 100001]
    parts = [
        fixtures.new_part(f"CTL-{cost}", "CONTROL", cost, on_hand_qty=10)
        for cost in costs
    ]
    inspection = fixtures.completed_inspection(
        world["well_id"], world["technician_id"], "2026-06-01T10:00:00Z", 20.0, 50.0, 6.0
    )
    quote = fixtures.new_quote(
        world["property_id"],
        world["well_id"],
        inspection["id"],
        "REPAIR",
        60,
        "2026-06-03T09:00:00Z",
        "JOURNEYMAN",
    )
    lines = [fixtures.add_quote_line(quote["id"], part["id"], 1)["line_id"] for part in parts]

    priced = validate_success(api.price_quote(quote["id"], ESTIMATOR))

    expected = [
        (0.40, 35000, 35000),
        (0.28, 32001, 32001),
        (0.28, 128000, 128000),
        (0.18, 118001, 118001),
    ]
    rendered = [fixtures.get_quote_line(line_id) for line_id in lines]
    for line, (markup, unit, extended) in zip(rendered, expected):
        assert_close(line["markup_pct_applied"], markup, "QuoteLine.markup_pct_applied")
        assert_money(line["unit_price_cents"], unit, "QuoteLine.unit_price_cents")
        assert_money(line["extended_price_cents"], extended, "QuoteLine.extended_price_cents")

    assert rendered[1]["unit_price_cents"] < rendered[0]["unit_price_cents"]
    assert rendered[3]["unit_price_cents"] < rendered[2]["unit_price_cents"]

    assert_money(priced["parts_subtotal_cents"], 313002, "Quote.parts_subtotal_cents")
    assert_money(priced["labor_subtotal_cents"], 9500, "Quote.labor_subtotal_cents")
    assert_money(priced["tax_cents"], 22693, "Quote.tax_cents")
    assert_money(priced["total_cents"], 345195, "Quote.total_cents")


def test_the_labour_time_band_is_read_from_the_estimated_start_instant(api):
    """PRD 3.5: "If its ISO weekday is Saturday or Sunday — weekday 6 or 7 — the band is
    `WEEKEND`, and weekend beats every hour band regardless of the hour. Otherwise, an
    hour of at least 8 and below 17 is `STANDARD`; an hour of at least 17 and below 22 is
    `EVENING`; every other hour, meaning 22 and 23 or anything from 0 up to but not
    including 8, is `NIGHT`."
    PRD 3.5: "The multipliers are 1.00 for `STANDARD`, 1.35 for `EVENING`, 1.75 for
    `NIGHT` and 1.50 for `WEEKEND`."
    PRD 3.5: "The **labour charge** is the already-rounded hourly rate multiplied by
    billable minutes divided by sixty, rounded half up to whole cents a second time."

    Design: Corner/calculations/corner_calc_labor_time_band_boundaries_across_four_quotes
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Band Sweep Co",
        email="bs@corner.example",
        address_line="8 Band",
        drawdown=6.0,
        technician_name="Band Tech",
    )
    part = fixtures.new_part("CTL-5000-B", "CONTROL", 5000, on_hand_qty=10)
    inspection = fixtures.completed_inspection(
        world["well_id"], world["technician_id"], "2026-06-01T10:00:00Z", 20.0, 50.0, 6.0
    )

    cases = [
        ("2026-06-03T08:00:00Z", 16625, 25205),
        ("2026-06-03T17:00:00Z", 22444, 31024),
        ("2026-06-03T22:00:00Z", 29094, 37674),
        ("2026-06-06T20:00:00Z", 24938, 33518),
    ]
    for index, (start_at, labour, total) in enumerate(cases):
        quote = fixtures.new_quote(
            world["property_id"],
            world["well_id"],
            inspection["id"],
            "REPAIR",
            100,
            start_at,
            "JOURNEYMAN",
        )
        fixtures.add_quote_line(quote["id"], part["id"], 1)
        priced = validate_success(api.price_quote(quote["id"], ESTIMATOR))
        assert_money(priced["parts_subtotal_cents"], 8000, "Quote.parts_subtotal_cents")
        assert_money(priced["tax_cents"], 580, "Quote.tax_cents")
        assert_money(priced["labor_subtotal_cents"], labour, "Quote.labor_subtotal_cents")
        assert_money(priced["total_cents"], total, "Quote.total_cents")
        if index == 0:
            assert priced["status"] == "PRICED"


def test_quote_line_quantity_ceiling_is_a_business_rule_not_a_payload_rule(api):
    """PRD 3.6: "The `quantity` must not exceed `PART_MAX_LINE_QUANTITY` (50); note that
    the payload gate only checks that the quantity is a non-negative integer, so a
    quantity of 51 passes G8 and is refused at the business gate with
    `ERR_QUANTITY_EXCEEDS_LIMIT`, not with a validation error."
    PRD 2.7: "`ERR_NEGATIVE_QUANTITY` (HTTP 400) is raised when a quantity, amount or
    pounds body field is **strictly** negative. Zero passes this gate."

    Design: Corner/validations/corner_validation_quote_line_quantity_boundary_fifty_versus_fiftyone
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Quantity Cap Co",
        email="qc@corner.example",
        address_line="50 Quantity",
        technician_name="Quantity Tech",
    )
    part = fixtures.new_part("CTL-QTY-1", "CONTROL", 5000, on_hand_qty=0)
    inspection = fixtures.completed_inspection(
        world["well_id"], world["technician_id"], "2026-06-01T10:00:00Z", 20.0, 50.0, 6.0
    )
    quote = fixtures.new_quote(
        world["property_id"],
        world["well_id"],
        inspection["id"],
        "REPAIR",
        60,
        "2026-06-03T09:00:00Z",
        "JOURNEYMAN",
    )

    accepted = validate_success(
        api.add_quote_line(
            quote["id"],
            {
                "part_catalog_item_id": part["id"],
                "quantity": 50,
                "expected_quote_version": fixtures.quote_version(quote["id"]),
            },
            ESTIMATOR,
        ),
        201,
    )
    assert accepted["quantity"] == 50
    assert accepted["status"] == "ACTIVE"

    current = fixtures.quote_version(quote["id"])
    validate_error(
        api.add_quote_line(
            quote["id"],
            {
                "part_catalog_item_id": part["id"],
                "quantity": 51,
                "expected_quote_version": current,
            },
            ESTIMATOR,
        ),
        ApiErrorId.ERR_QUANTITY_EXCEEDS_LIMIT.value,
        422,
    )
    validate_error(
        api.add_quote_line(
            quote["id"],
            {
                "part_catalog_item_id": part["id"],
                "quantity": -1,
                "expected_quote_version": current,
            },
            ESTIMATOR,
        ),
        ApiErrorId.ERR_NEGATIVE_QUANTITY.value,
        400,
    )

    rows, _ = validate_paginated(api.list_quote_lines_of(quote["id"], ESTIMATOR))
    assert len(rows) == 1
    assert fixtures.quote_version(quote["id"]) == current


def test_pump_lines_are_gated_on_the_wells_measured_yield(api):
    """PRD 3.6: "If the well has no `measured_yield_gpm` at all — no inspection has ever
    completed on it — the line is refused with `ERR_INSPECTION_REQUIRED`."
    PRD 3.6: "Otherwise the pump is acceptable exactly when its `rated_gpm` is at most
    the well's `measured_yield_gpm` multiplied by `YIELD_SAFETY_FACTOR` (0.80), the
    comparison being **inclusive**; a pump above that ceiling would run the well dry and
    is refused, again with `ERR_YIELD_INSUFFICIENT_FOR_PUMP`. With a measured yield of
    12.5 gallons a minute the ceiling is exactly 10.0, so a 10.0 pump passes and a 10.1
    pump fails."
    PRD 3.6: "A removal attempted on a line that is not `ACTIVE`, or whose quote is in
    any other state, is refused with `ERR_QUOTE_LINE_INVALID_STATE`."

    Design: Corner/errors/corner_pump_line_gates_rejected
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    account = fixtures.new_account("Pump Gate Co", "JUR_ALPHA", "pu@corner.example")
    prop = fixtures.new_property(account["id"], "7 Pump", "JUR_ALPHA", 10.0, 3)
    well_1 = fixtures.new_well(prop["id"], "JUR_ALPHA", "DRILLED", 200.0)
    well_2 = fixtures.new_well(prop["id"], "JUR_ALPHA", "DRILLED", 260.0)
    technician = fixtures.new_technician("Pump Tech", "MASTER", "JUR_ALPHA")
    pump_ok = fixtures.new_part(
        "PMP-10-0", "PUMP", 40000, on_hand_qty=4, rated_gpm=10.0
    )
    pump_big = fixtures.new_part(
        "PMP-10-1", "PUMP", 41000, on_hand_qty=4, rated_gpm=10.1
    )
    inspection_2 = fixtures.completed_inspection(
        well_2["id"], technician["id"], "2026-06-01T10:00:00Z", 12.5, 60.0, 8.0
    )
    inspection_1 = fixtures.schedule_inspection(
        well_1["id"], technician["id"], "2026-06-01T11:00:00Z"
    )
    quote_1 = fixtures.new_quote(
        prop["id"], well_1["id"], inspection_1["id"], "PUMP_REPLACEMENT", 120,
        "2026-06-03T12:00:00Z", "MASTER",
    )
    quote_2 = fixtures.new_quote(
        prop["id"], well_2["id"], inspection_2["id"], "PUMP_REPLACEMENT", 120,
        "2026-06-03T12:00:00Z", "MASTER",
    )

    validate_error(
        api.add_quote_line(
            quote_1["id"],
            {
                "part_catalog_item_id": pump_ok["id"],
                "quantity": 1,
                "expected_quote_version": fixtures.quote_version(quote_1["id"]),
            },
            ESTIMATOR,
        ),
        ApiErrorId.ERR_INSPECTION_REQUIRED.value,
        422,
    )
    validate_error(
        api.add_quote_line(
            quote_2["id"],
            {
                "part_catalog_item_id": pump_big["id"],
                "quantity": 1,
                "expected_quote_version": fixtures.quote_version(quote_2["id"]),
            },
            ESTIMATOR,
        ),
        ApiErrorId.ERR_YIELD_INSUFFICIENT_FOR_PUMP.value,
        422,
    )
    accepted = validate_success(
        api.add_quote_line(
            quote_2["id"],
            {
                "part_catalog_item_id": pump_ok["id"],
                "quantity": 1,
                "expected_quote_version": fixtures.quote_version(quote_2["id"]),
            },
            ESTIMATOR,
        ),
        201,
    )
    removed = validate_success(api.delete_quote_line(accepted["id"], ESTIMATOR))
    assert removed["status"] == "REMOVED"
    validate_error(
        api.delete_quote_line(accepted["id"], ESTIMATOR),
        ApiErrorId.ERR_QUOTE_LINE_INVALID_STATE.value,
        409,
    )
    assert_close(
        fixtures.get_well(well_2["id"])["measured_yield_gpm"],
        12.5,
        "WellProfile.measured_yield_gpm",
    )


def _empty_quote_world():
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Emptyset Holdings",
        email="ap@emptyset.example",
        membership_tier="NONE",
        account_jurisdiction="JUR_CHARLIE",
        property_jurisdiction="JUR_CHARLIE",
        well_jurisdiction="JUR_CHARLIE",
        address_line="0 Emptyset",
        distance_miles=5.0,
        household_size=1,
        depth_feet=40.0,
        drawdown=8.0,
        technician_tier="APPRENTICE",
        technician_name="Rune Dahl",
    )
    part = fixtures.new_part("CON-1200", "CONSUMABLE", 1200, on_hand_qty=10)
    inspection = fixtures.completed_inspection(
        world["well_id"], world["technician_id"], "2026-06-01T10:00:00Z", 9.0, 20.0, 8.0
    )
    quote = fixtures.new_quote(
        world["property_id"],
        world["well_id"],
        inspection["id"],
        "REPAIR",
        30,
        "2026-06-03T12:00:00Z",
        "APPRENTICE",
    )
    line_id = fixtures.add_quote_line(quote["id"], part["id"], 1)["line_id"]
    fixtures._ok(fixtures.api_client.delete_quote_line(line_id, ESTIMATOR))
    return {"quote_id": quote["id"], "line_id": line_id}


def test_pricing_a_quote_with_no_active_lines_is_refused(api):
    """PRD 3.6: "At least one `ACTIVE` line must exist, or the call is refused with
    `ERR_QUOTE_HAS_NO_ACTIVE_LINES`."
    PRD 3.6: "An `Estimator` may remove an `ACTIVE` line while the owning quote is
    `DRAFT` or `REVISION_REQUIRED`; the line moves to `REMOVED` and both the line's and
    the quote's `version` rise by 1."

    Design: Difficulty/boundary_precision_check/price_quote_with_zero_active_lines_rejected
    """
    world = _empty_quote_world()
    validate_error(
        api.price_quote(world["quote_id"], ESTIMATOR),
        ApiErrorId.ERR_QUOTE_HAS_NO_ACTIVE_LINES.value,
        422,
    )
    assert fixtures.get_quote_line(world["line_id"])["status"] == "REMOVED"


def test_a_refused_pricing_leaves_the_quote_untouched(api):
    """PRD 3.6: "The quote opens in `DRAFT` with `parts_subtotal_cents`,
    `labor_subtotal_cents`, `permit_fee_cents`, `tax_cents` and `total_cents` all 0, and
    `sent_at`, `approved_at` and `approved_total_cents` all null."
    PRD 3.6: "At least one `ACTIVE` line must exist, or the call is refused with
    `ERR_QUOTE_HAS_NO_ACTIVE_LINES`."

    Design: Difficulty/boundary_precision_check/price_quote_with_zero_active_lines_rejected
    """
    world = _empty_quote_world()
    api.price_quote(world["quote_id"], ESTIMATOR)
    quote = fixtures.get_quote(world["quote_id"])
    assert quote["status"] == "DRAFT"
    assert_money(quote["total_cents"], 0, "Quote.total_cents")
