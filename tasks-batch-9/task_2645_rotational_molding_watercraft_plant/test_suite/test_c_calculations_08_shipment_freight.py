"""Trailer cube rollups and the two freight variants: per-line rounding, tier steps.

PRD.md section 3.8 rounds each line's freight to a whole cent *before* the lines
are summed, then applies the volume discount before the fuel surcharge, and picks
the discount tier from the two-decimal ``cube_utilization_pct`` rather than from
the raw quotient. The nested and gross cube bases give one trailer two different
totals from the same untouched lines.
"""

from test_helpers import (
    ADMIN_HEADERS,
    assert_at_most_scale,
    assert_instant_equals,
    assert_money_equals,
    create_plant_baseline,
    create_production_order,
    create_resin_lot,
    create_shipment,
    dec,
    depart_payload,
    deliver_payload,
    get_success_data,
    load_unit,
    reserve_charge,
    run_cycle_to_demold,
    schedule_cycle,
    set_clock,
    setup_loaded_shipment,
    advance_unit_to_sellable,
    store_unit,
)


def _p5_exact(actual, expected, places, label):
    """Assert a decimal value carries no more than ``places`` digits and equals ``expected``."""
    assert_at_most_scale(actual, places, label)
    assert dec(actual) == dec(expected), f"{label}: expected {expected}, got {actual!r}"


def _p5_line_shape(line, *, nest_position, gross, nested, label):
    """Assert one line's position and its two cube bases.

    PRD.md section 3.8: "a line's `nest_position` is one plus the number of earlier
    lines whose hull shares the same `product_model_id`... A line's
    `line_gross_cube_m3` is always the model's `gross_cube_m3` rounded to four
    decimals. Its `line_nested_cube_m3` is the full gross cube when its
    `nest_position` is 1, and `gross_cube_m3` multiplied by `nest_factor`, rounded to
    four decimals, for every position after the first."
    """
    assert line["nest_position"] == nest_position, (
        f"{label}: nest_position expected {nest_position}, got {line['nest_position']}"
    )
    _p5_exact(line["line_gross_cube_m3"], gross, 4, f"{label}: line_gross_cube_m3")
    _p5_exact(line["line_nested_cube_m3"], nested, 4, f"{label}: line_nested_cube_m3")
    assert line["status"] == "LOADED", f"{label}: status, got {line['status']}"


def _p5_rollups(shipment, *, loaded, nested, weight, utilization, density, label):
    """Assert the five shipment-level cube rollups PRD.md section 3.8 names."""
    _p5_exact(shipment["loaded_cube_m3"], loaded, 4, f"{label}: loaded_cube_m3")
    _p5_exact(shipment["nested_cube_m3"], nested, 4, f"{label}: nested_cube_m3")
    _p5_exact(shipment["loaded_weight_kg"], weight, 3, f"{label}: loaded_weight_kg")
    _p5_exact(shipment["cube_utilization_pct"], utilization, 2, f"{label}: cube_utilization_pct")
    _p5_exact(shipment["density_kg_per_m3"], density, 3, f"{label}: density_kg_per_m3")


def test_freight_rounds_per_line_before_summing_and_re_prices_on_gross_at_delivery(
    api, admin_headers, planner_headers
):
    """One untouched two-hull trailer quotes 14398 cents and bills 19198 cents.

    PRD.md section 3.8 rounds per line and forbids the reverse: "The line's
    `line_freight_cents` is the chargeable weight multiplied by the destination zone
    rate, rounded half-up to a whole cent, where the zone rates in cents per kilogram
    are 42 for `Z1`, 61 for `Z2` and 88 for `Z3`. The pre-discount total is the sum of
    the **already-rounded** per-line amounts: rounding happens per line and only then
    are the lines summed, never the reverse."  The chargeable mass itself comes from
    "a dimensional weight ... derived as the billable cube multiplied by the
    dimensional factor of 120.000 kilograms per cubic metre, rounded to three
    decimals. The chargeable weight is the greater of the hull's actual
    `unit_weight_kg` and that dimensional weight".  The order of the two adjustments
    is pinned: "The discount amount is the pre-discount total multiplied by the tier
    percentage divided by 100, rounded half-up. Finally a fuel surcharge of 9.50
    percent is applied, rounded half-up, to the **discounted** base. The order is
    pinned: discount first, then fuel on the reduced amount, never fuel on the gross
    followed by a discount."  Only the cube basis separates the two variants: "The
    `QUOTED` variant, produced at seal, bills every line on `line_nested_cube_m3` ...
    The `BILLED` variant, produced at delivery, bills every line on
    `line_gross_cube_m3`".  Departure moves the hulls but not the lines: it "moves
    every referenced hull `LOADED` to `IN_TRANSIT`, firing the four links of CASCADE-C
    once per hull so that footprints are released".

    Design: Corner/calculations/calc_precision_shipment_freight_per_line_rounding_before_sum
    """
    ctx = setup_loaded_shipment(
        model_overrides={"gross_cube_m3": 1.2345, "nest_factor": 0.5, "unit_weight_kg": 30.0},
        shipment_overrides={"trailer_cube_capacity_m3": 3.0, "trailer_max_payload_kg": 1000.0},
    )
    shipment_id = ctx["shipment_id"]

    loading = api.read_entity("get_shipment", shipment_id, planner_headers)
    assert loading["status"] == "LOADING", f"expected LOADING, got {loading['status']}"
    # 0.61725 rounds HALF_UP to 0.6173, not down to 0.6172, so the nested total is
    # 1.2345 + 0.6173 = 1.8518 against a gross total of 2.4690.
    # utilisation = 1.8518 / 3.0000 * 100 = 61.72666... -> 61.73
    # density = 60.000 / 1.8518 = 32.40091... -> 32.401, taken from the NESTED cube.
    _p5_rollups(
        loading,
        loaded="2.4690",
        nested="1.8518",
        weight="60.000",
        utilization="61.73",
        density="32.401",
        label="the loaded trailer",
    )
    assert loading["quoted_freight_cents"] is None, (
        f"a loading trailer has no quote yet, got {loading['quoted_freight_cents']!r}"
    )
    assert loading["billed_freight_cents"] is None, (
        f"a loading trailer has no bill yet, got {loading['billed_freight_cents']!r}"
    )

    first_line, second_line = ctx["shipment_lines"][0], ctx["shipment_lines"][1]
    _p5_line_shape(
        api.read_entity("get_shipment_line", first_line["id"], planner_headers),
        nest_position=1,
        gross="1.2345",
        nested="1.2345",
        label="the anchor line",
    )
    _p5_line_shape(
        api.read_entity("get_shipment_line", second_line["id"], planner_headers),
        nest_position=2,
        gross="1.2345",
        nested="0.6173",
        label="the nesting line",
    )

    before_read = api.read_version("get_shipment", shipment_id, planner_headers)
    api.read_freight_summary(shipment_id, planner_headers)
    api.read_freight_summary(shipment_id, admin_headers)
    assert api.read_version("get_shipment", shipment_id, planner_headers) == before_read, (
        "the freight breakdown read is read-only and never advances a version"
    )

    set_clock("2026-08-01T11:00:00Z")
    sealed = get_success_data(api.seal_shipment(shipment_id, planner_headers))
    assert sealed["status"] == "SEALED", f"expected SEALED, got {sealed['status']}"
    assert_instant_equals(sealed["sealed_at"], "2026-08-01T11:00:00Z", "sealed_at")
    # QUOTED basis, per line: line 1 dim weight = round(1.2345 * 120.000, 3) = 148.140,
    # chargeable = max(30.000, 148.140) = 148.140, freight = round_half_up(9036.54) = 9037;
    # line 2 dim weight = round(0.6173 * 120.000, 3) = 74.076, chargeable = 74.076,
    # freight = round_half_up(4518.636) = 4519. Pre-discount total = 9037 + 4519 = 13556.
    # Summing the chargeable masses first instead gives (148.140 + 74.076) * 61 =
    # 13555.176 -> 13555, which would quote 14397, so the one cent of per-line rounding
    # is visible in the total.
    # Tier: the first row whose minimum utilisation is at or below 61.73 is the 60.00
    # row at 3.00 percent. Discount = round_half_up(406.68) = 407, base = 13149,
    # fuel = round_half_up(1249.155) = 1249, total = 14398. Applying fuel to the gross
    # first would give 13556 + 1288 = 14844 less round_half_up(445.32) = 445, i.e. 14399.
    assert_money_equals(sealed["quoted_freight_cents"], 14398, "quoted_freight_cents")
    assert sealed["billed_freight_cents"] is None, (
        f"the bill waits for delivery, got {sealed['billed_freight_cents']!r}"
    )
    _p5_rollups(
        sealed,
        loaded="2.4690",
        nested="1.8518",
        weight="60.000",
        utilization="61.73",
        density="32.401",
        label="the sealed trailer",
    )

    set_clock("2026-08-01T11:30:00Z")
    departed = get_success_data(
        api.depart_shipment(
            shipment_id, depart_payload("2026-08-01T11:30:00Z"), planner_headers
        )
    )
    assert departed["status"] == "IN_TRANSIT", f"expected IN_TRANSIT, got {departed['status']}"
    assert_money_equals(
        departed["quoted_freight_cents"], 14398, "departure leaves the quote alone"
    )
    for label, line in (("the anchor line", first_line), ("the nesting line", second_line)):
        in_flight = api.read_entity("get_shipment_line", line["id"], planner_headers)
        assert in_flight["status"] == "LOADED", (
            f"{label} stays LOADED after departure, which is why delivery can still "
            f"price it, got {in_flight['status']}"
        )
    for unit_id in ctx["stored_unit_ids"]:
        hull = api.read_entity("get_finished_unit", unit_id, planner_headers)
        assert hull["logistics_status"] == "IN_TRANSIT", (
            f"expected IN_TRANSIT, got {hull['logistics_status']}"
        )
        _p5_exact(hull["stored_footprint_cube_m3"], "0.0000", 4, "stored_footprint_cube_m3")
    site = api.read_entity("get_warehouse", ctx["warehouse_id"], planner_headers)
    _p5_exact(site["committed_cube_m3"], "0.0000", 4, "the origin site's committed_cube_m3")

    set_clock("2026-08-01T12:00:00Z")
    delivered = get_success_data(
        api.deliver_shipment(
            shipment_id, deliver_payload("2026-08-01T12:00:00Z"), planner_headers
        )
    )
    assert delivered["status"] == "DELIVERED", f"expected DELIVERED, got {delivered['status']}"
    # BILLED basis: both lines are charged on line_gross_cube_m3 1.2345, so each is
    # round_half_up(148.140 * 61) = 9037 and the pre-discount total is 18074. The tier
    # is still the 3.00 percent row chosen from the NESTED utilisation 61.73 and is
    # never re-selected: discount = round_half_up(542.22) = 542, base = 17532,
    # fuel = round_half_up(1665.54) = 1666, total = 19198. Re-deriving the tier from
    # the gross share 2.4690 / 3.0000 = 82.30 would apply 7.50 percent and bill 18306.
    assert_money_equals(delivered["billed_freight_cents"], 19198, "billed_freight_cents")
    assert_money_equals(
        delivered["quoted_freight_cents"], 14398, "the quote survives on the same row"
    )
    assert (
        delivered["billed_freight_cents"] - delivered["quoted_freight_cents"] == 4800
    ), (
        "the gross-basis bill exceeds the nested quote on a trailer whose two lines "
        f"never changed, got {delivered['billed_freight_cents'] - delivered['quoted_freight_cents']}"
    )

    # PRD.md section 3.8 says the freight breakdown read reflects "the persisted
    # `billed_freight_cents` once delivered".
    summary = api.read_freight_summary(shipment_id, ADMIN_HEADERS)
    assert_money_equals(
        summary["billed_freight_cents"], 19198, "the projection's billed_freight_cents"
    )


def test_discount_tier_is_read_from_the_rounded_utilisation_not_the_raw_quotient(
    api, planner_headers
):
    """Trailers of 2.4691 and 2.4693 cube carry identical loads and quote 13730 and 14398.

    PRD.md section 3.8 makes the utilisation a two-decimal figure before anything reads
    it: "`cube_utilization_pct` is `nested_cube_m3` divided by `trailer_cube_capacity_m3`
    times 100, rounded to two decimals".  The tier ladder is then walked against that
    figure: "A volume discount is then chosen by walking a fixed ordered tier list and
    taking the **first** row whose minimum utilisation is at or below the shipment's
    `cube_utilization_pct`: 90.00 percent utilisation earns 12.00 percent, 75.00 earns
    7.50, 60.00 earns 3.00, and anything below 60.00 earns 0.00. That tier is selected
    once, from the utilisation at seal time, and is never re-selected later in the
    computation."  Sealing itself reads the same rounded figure: "its
    `cube_utilization_pct` must be at or above the minimum seal utilisation of 60.00
    percent (`ERR_TRAILER_UNDERUTILIZED`, HTTP 409, with exactly 60.00 passing)".  And
    the position numbering is per trailer: "a line's `nest_position` is one plus the
    number of earlier lines whose hull shares the same `product_model_id`".

    Design: Corner/calculations/calc_tiered_pricing_freight_utilization_discount_tier_straddle
    """
    ctx = create_plant_baseline(
        model_overrides={
            "gross_cube_m3": 1.2345,
            "nest_factor": 0.5,
            "unit_weight_kg": 30.0,
            "nominal_charge_kg": 10.0,
        },
        mold_overrides={"cavity_count": 4, "nominal_charge_kg": 40.0},
    )
    lot = create_resin_lot(received_kg=200.0)
    order = create_production_order(ctx, ordered_qty=4)
    cycle = schedule_cycle(ctx, order)
    ctx["molding_cycle"] = cycle
    ctx["molding_cycle_id"] = cycle["id"]
    reserve_charge(ctx, cycle, lot, charge_kg=40.0, regrind_kg=4.0)
    run_cycle_to_demold(ctx)
    hulls = ctx["finished_units"]
    assert len(hulls) == 4, f"a four-cavity mould mints four hulls, got {len(hulls)}"
    stored = [store_unit(ctx, advance_unit_to_sellable(ctx, hull)) for hull in hulls]

    # The zone anchor takes its full gross cube and the other three nest:
    # 1.2345 + 3 * 0.6173 = 3.0864 committed at the origin site.
    site = api.read_entity("get_warehouse", ctx["warehouse_id"], planner_headers)
    _p5_exact(site["committed_cube_m3"], "3.0864", 4, "the origin site's committed_cube_m3")
    assert site["posture"] == "NORMAL", f"expected NORMAL, got {site['posture']}"

    tight = create_shipment(
        ctx, trailer_cube_capacity_m3=2.4691, trailer_max_payload_kg=1000.0
    )
    slack = create_shipment(
        ctx, trailer_cube_capacity_m3=2.4693, trailer_max_payload_kg=1000.0
    )
    tight_lines = [load_unit(ctx, tight, stored[0]), load_unit(ctx, tight, stored[1])]
    slack_lines = [load_unit(ctx, slack, stored[2]), load_unit(ctx, slack, stored[3])]

    for label, lines in (("the tight trailer", tight_lines), ("the slack trailer", slack_lines)):
        _p5_line_shape(
            api.read_entity("get_shipment_line", lines[0]["id"], planner_headers),
            nest_position=1,
            gross="1.2345",
            nested="1.2345",
            label=f"{label}: the anchor line",
        )
        # Numbering restarts on each trailer, so four hulls of one model across two
        # trailers give two position-1 full-cube lines, not one.
        _p5_line_shape(
            api.read_entity("get_shipment_line", lines[1]["id"], planner_headers),
            nest_position=2,
            gross="1.2345",
            nested="0.6173",
            label=f"{label}: the nesting line",
        )

    # 1.8518 / 2.4691 * 100 = 74.998987... which rounds HALF_UP to exactly 75.00 and
    # therefore SATISFIES the 75.00 tier row, while
    # 1.8518 / 2.4693 * 100 = 74.992912... rounds to 74.99 and falls to the 60.00 row.
    # Testing the raw quotient against 75.00 instead would drop both trailers into the
    # 3.00 percent row and erase the divergence.
    loaded_tight = api.read_entity("get_shipment", tight["id"], planner_headers)
    _p5_rollups(
        loaded_tight,
        loaded="2.4690",
        nested="1.8518",
        weight="60.000",
        utilization="75.00",
        density="32.401",
        label="the tight trailer",
    )
    loaded_slack = api.read_entity("get_shipment", slack["id"], planner_headers)
    _p5_rollups(
        loaded_slack,
        loaded="2.4690",
        nested="1.8518",
        weight="60.000",
        utilization="74.99",
        density="32.401",
        label="the slack trailer",
    )

    set_clock("2026-08-01T11:00:00Z")
    # Both rounded utilisations clear the 60.00 seal minimum, so the underutilisation
    # gate never interferes with the tier observation.
    sealed_tight = get_success_data(api.seal_shipment(tight["id"], planner_headers))
    sealed_slack = get_success_data(api.seal_shipment(slack["id"], planner_headers))
    assert sealed_tight["status"] == "SEALED", f"got {sealed_tight['status']}"
    assert sealed_slack["status"] == "SEALED", f"got {sealed_slack['status']}"

    # Both quotes start from the same pre-discount 9037 + 4519 = 13556.
    # 7.50 percent: round_half_up(1016.70) = 1017, base 12539,
    #               fuel round_half_up(1191.205) = 1191, total 13730.
    # 3.00 percent: round_half_up(406.68) = 407, base 13149,
    #               fuel round_half_up(1249.155) = 1249, total 14398.
    assert_money_equals(
        sealed_tight["quoted_freight_cents"], 13730, "the tight trailer's quote"
    )
    assert_money_equals(
        sealed_slack["quoted_freight_cents"], 14398, "the slack trailer's quote"
    )
    assert (
        sealed_slack["quoted_freight_cents"] - sealed_tight["quoted_freight_cents"] == 668
    ), (
        "0.0002 m3 of declared capacity moves 668 cents, because the discount is a step "
        "function of the rounded utilisation, got "
        f"{sealed_slack['quoted_freight_cents'] - sealed_tight['quoted_freight_cents']}"
    )
    assert sealed_tight["quoted_freight_cents"] < sealed_slack["quoted_freight_cents"], (
        "the SMALLER trailer is the cheaper one: paying for less declared cube raises "
        "utilisation and so earns a larger discount"
    )
