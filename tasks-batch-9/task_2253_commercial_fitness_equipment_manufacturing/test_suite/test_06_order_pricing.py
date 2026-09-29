"""The eight-step order total, its two variants and the rounding rules."""
from test_helpers import (
    add_order_line,
    add_partner_ctx,
    arrive_ctx,
    complete_install_ctx,
    complete_production_ctx,
    confirm_ctx,
    new_order,
    new_order_line,
    quote_ctx,
    quote_payload,
    read_order,
    read_order_line,
    read_price_breakdown,
    schedule_install_ctx,
    setup_configured_order,
    setup_released_revision,
    setup_scheduled_install,
    validate_success,
)

Z2_FACILITY = {"account_name": "Northgate Athletic Club", "freight_zone": "Z2",
               "credit_limit_cents": 100_000_000}


def _on_site_two_unit_order():
    """Two T900 units quoted, confirmed, staged and with the crew on site."""
    ctx = setup_scheduled_install(preset="T900", quantity=2)
    arrive_ctx(ctx)
    return ctx


def _l200_order(quantity):
    """One L200 line of the requested size at a Z2 facility, still unquoted."""
    return setup_configured_order(preset="L200", quantity=quantity,
                                  facility_overrides=dict(Z2_FACILITY))


def test_final_variant_writes_beside_the_retained_provisional_total(api):
    """Actual crew hours produce a second total without erasing the quoted one.

    The PRD states that for the final variant "The total is stored in
    `final_total_cents` while `quoted_total_cents` is retained unchanged so that
    the provisional-to-final delta stays auditable, and `price_variant_applied`
    becomes `FINAL`."

    Design: Difficulty/dual_variant_calc/order_price_provisional_vs_final_variant_divergence
    """
    ctx = _on_site_two_unit_order()
    assert read_order(ctx["order"]["id"])["quoted_total_cents"] == 1_120_619

    job = complete_install_ctx(ctx, actual_labor_hours=4.5, punch_list_open_count=0)

    assert job["status"] == "COMPLETED"
    order = read_order(ctx["order"]["id"])
    assert order["fulfillment_status"] == "INSTALLED"
    assert order["billing_status"] == "INVOICED"
    assert order["line_subtotal_cents"] == 1_017_494
    assert order["quoted_total_cents"] == 1_120_619
    assert order["final_total_cents"] == 1_133_932
    assert order["final_total_cents"] - order["quoted_total_cents"] == 13_313
    assert order["install_amount_cents"] == 39_938
    assert order["freight_cents"] == 76_500
    assert order["volume_discount_cents"] == 0
    assert order["punch_list_credit_cents"] == 0
    assert order["price_variant_applied"] == "FINAL"
    assert order["amount_due_cents"] == 1_133_932


def test_only_the_install_hours_step_differs_between_the_two_variants(api):
    """Steps 1, 4 and 6 are identical across variants; only step 2 moves.

    The PRD states that "The two variants differ only in steps 2 and 7, and in
    where the total lands", the provisional install hours being an estimate and
    the final variant's figure being "the completed install job's
    `actual_labor_hours` — real crew time, not the estimate."

    Design: Difficulty/dual_variant_calc/order_price_provisional_vs_final_variant_divergence
    """
    ctx = _on_site_two_unit_order()
    provisional = read_price_breakdown(ctx["order"]["id"])
    assert provisional["install_amount_cents"] == 26_625
    assert provisional["discount_base_cents"] == 1_044_119
    assert provisional["price_variant_applied"] == "PROVISIONAL"

    complete_install_ctx(ctx, actual_labor_hours=4.5, punch_list_open_count=0)

    final = read_price_breakdown(ctx["order"]["id"])
    assert final["line_subtotal_cents"] == provisional["line_subtotal_cents"] == 1_017_494
    assert final["install_amount_cents"] == 39_938
    assert final["discount_base_cents"] == 1_057_432
    assert final["volume_discount_cents"] == 0
    assert final["discounted_base_cents"] == 1_057_432
    assert final["freight_cents"] == 76_500
    assert final["punch_list_credit_cents"] == 0
    assert final["quoted_total_cents"] == 1_120_619
    assert final["final_total_cents"] == 1_133_932
    assert final["price_variant_applied"] == "FINAL"


def _three_half_cent_lines():
    """Twelve treadmills and seventeen presses, every line landing on a half cent."""
    ctx = setup_configured_order(
        revision_ctx=setup_released_revision("T900"), quantity=12,
        finish_codes=["ARCTIC_WHITE"], layout_zone_label="CARDIO-DECK",
        facility_overrides=dict(Z2_FACILITY),
    )
    press = setup_released_revision(
        "S500", rig_overrides={"name": "RIG-B", "parallel_station_count": 2,
                               "supported_duty_classes": ["INSTITUTIONAL"]},
    )
    ctx["press"] = press
    ctx["second_line"] = add_order_line(
        ctx, revision=press["revision"], model=press["model"], quantity=7,
        finish_codes=["PREMIUM_UPHOLSTERY"], layout_zone_label="STRENGTH-BAY",
    )
    ctx["third_line"] = add_order_line(
        ctx, revision=press["revision"], model=press["model"], quantity=10,
        finish_codes=["CLUB_RED"], layout_zone_label="STRENGTH-BAY",
    )
    return ctx


def test_three_half_cent_lines_are_each_rounded_before_the_subtotal(
    api, order_planner_headers
):
    """Rounding per line then summing gives one cent more than rounding once.

    The PRD states that "Rounding **per line and only then summing** is normative:
    it can differ by whole cents from rounding a single aggregate product, and the
    per-line result is the figure that is stored and billed."

    Design: Difficulty/combinatorial_formula/order_line_extended_price_rounds_per_line_before_subtotal
    """
    ctx = _three_half_cent_lines()

    first = read_order_line(ctx["line"]["id"], order_planner_headers)
    second = read_order_line(ctx["second_line"]["id"], order_planner_headers)
    third = read_order_line(ctx["third_line"]["id"], order_planner_headers)

    assert first["unit_price_cents"] == 484_450
    assert first["extended_price_cents"] == 6_162_204
    assert second["unit_price_cents"] == 350_575
    assert second["extended_price_cents"] == 2_723_968
    assert third["unit_price_cents"] == 332_075
    assert third["extended_price_cents"] == 3_686_033
    order = read_order(ctx["order"]["id"])
    assert order["line_subtotal_cents"] == 12_572_205
    assert order["line_subtotal_cents"] != 12_572_204, (
        "summing the raw products and rounding once would lose a cent"
    )


def test_the_three_line_quote_walks_the_pinned_eight_step_sequence(
    api, order_planner_headers
):
    """Each step consumes the previous one, from subtotal through freight.

    The PRD states that "Order totals are assembled in eight steps that run in
    exactly this pinned sequence, because every step consumes the previous step's
    output and no step may be reordered" and that "Rounding half up occurs at
    steps 2, 4 and 6 and nowhere else".

    Design: Difficulty/combinatorial_formula/order_line_extended_price_rounds_per_line_before_subtotal
    """
    ctx = _three_half_cent_lines()

    quoted = validate_success(
        api.quote_order(ctx["order"]["id"],
                        quote_payload(read_order(ctx["order"]["id"])["version"]),
                        order_planner_headers)
    )

    assert quoted["billing_status"] == "QUOTED"
    assert quoted["install_amount_cents"] == 536_938
    assert quoted["volume_discount_cents"] == 524_366
    assert float(quoted["chargeable_weight_kg"]) == 8347.0
    assert quoted["freight_cents"] == 2_170_220
    assert quoted["quoted_total_cents"] == 14_754_997
    assert quoted["price_variant_applied"] == "PROVISIONAL"
    breakdown = read_price_breakdown(ctx["order"]["id"])
    assert breakdown["discount_base_cents"] == 13_109_143
    assert breakdown["discounted_base_cents"] == 12_584_777


def test_freight_waiver_is_evaluated_against_the_discounted_base(
    api, order_planner_headers
):
    """A base above the waiver threshold still pays freight once the discount lands.

    The PRD states that "`freight_cents` is zero when the discounted base has
    reached 20,000,000 cents (200,000 dollars) or more — freight is waived on
    orders that large."

    Design: Difficulty/combinatorial_formula/order_total_step_order_freight_waiver_reads_post_discount_base
    """
    ctx = _l200_order(55)

    quoted = validate_success(
        api.quote_order(ctx["order"]["id"],
                        quote_payload(read_order(ctx["order"]["id"])["version"]),
                        order_planner_headers)
    )

    breakdown = read_price_breakdown(ctx["order"]["id"])
    assert breakdown["discount_base_cents"] == 20_625_000
    assert breakdown["discount_base_cents"] >= 20_000_000
    assert breakdown["discounted_base_cents"] == 19_078_125
    assert breakdown["discounted_base_cents"] < 20_000_000
    assert quoted["freight_cents"] == 1_258_400
    assert quoted["freight_cents"] != 0, "the waiver reads step 5, not step 3"
    assert quoted["quoted_total_cents"] == 20_336_525
    assert quoted["quoted_total_cents"] != 19_078_125


def test_the_fifty_five_unit_order_reports_every_intermediate_step(
    api, order_planner_headers
):
    """The discount rate and the freight rate are both read on their own inputs.

    The PRD states that the tiers "are read on the discount base, each with an
    inclusive lower bound and an exclusive upper bound" and that freight otherwise
    "is the order's `chargeable_weight_kg` multiplied by the per-kilogram rate for
    the facility's `freight_zone`, rounded half up to a whole number of cents".

    Design: Difficulty/combinatorial_formula/order_total_step_order_freight_waiver_reads_post_discount_base
    """
    ctx = _l200_order(55)

    quoted = validate_success(
        api.quote_order(ctx["order"]["id"],
                        quote_payload(read_order(ctx["order"]["id"])["version"]),
                        order_planner_headers)
    )

    assert quoted["line_subtotal_cents"] == 19_160_625
    assert quoted["install_amount_cents"] == 1_464_375
    assert quoted["volume_discount_cents"] == 1_546_875
    assert float(quoted["chargeable_weight_kg"]) == 4840.0
    assert quoted["freight_cents"] == 4840 * 260
    assert quoted["quoted_total_cents"] == (
        19_160_625 + 1_464_375 - 1_546_875 + 1_258_400
    )


def test_discount_tier_applies_at_its_exact_inclusive_lower_bound(
    api, order_planner_headers
):
    """A base landing exactly on 15,000,000 takes the higher rate.

    The PRD states that the tiers run "from 0 up to 5,000,000 cents the rate is
    zero; from 5,000,000 up to 15,000,000 cents it is four percent; from
    15,000,000 up to 40,000,000 cents it is seven and a half percent; and at
    40,000,000 cents (400,000 dollars) or above it is eleven percent."

    Design: Difficulty/boundary_precision_check/volume_discount_tier_exact_lower_bound_and_price_inversion
    """
    ctx = _l200_order(40)

    quoted = validate_success(
        api.quote_order(ctx["order"]["id"],
                        quote_payload(read_order(ctx["order"]["id"])["version"]),
                        order_planner_headers)
    )

    breakdown = read_price_breakdown(ctx["order"]["id"])
    assert breakdown["discount_base_cents"] == 15_000_000
    assert quoted["volume_discount_cents"] == 1_125_000
    assert quoted["volume_discount_cents"] != 600_000, (
        "an exclusive lower bound would have kept the four percent rate"
    )
    assert breakdown["discounted_base_cents"] == 13_875_000
    assert quoted["freight_cents"] == 915_200
    assert quoted["quoted_total_cents"] == 14_790_200


def test_the_forty_unit_order_costs_less_than_the_thirty_nine_unit_order(
    api, order_planner_headers
):
    """Crossing the tier boundary inverts the price against the smaller order.

    The PRD states that "Because the tier is selected on a base that *includes*
    installation labour, installation labour can push an order across a tier
    boundary — that is intended, not an accident of ordering."

    Design: Difficulty/boundary_precision_check/volume_discount_tier_exact_lower_bound_and_price_inversion
    """
    ctx = _l200_order(39)
    smaller = quote_ctx(ctx)
    bigger_order = new_order(ctx["facility"]["id"])
    new_order_line(bigger_order["id"], ctx["revision"]["id"], quantity=40,
                   finish_codes=["GRAPHITE"], layout_zone_label="ZONE-B")

    bigger = validate_success(
        api.quote_order(bigger_order["id"],
                        quote_payload(read_order(bigger_order["id"])["version"]),
                        order_planner_headers)
    )

    assert smaller["line_subtotal_cents"] == 13_586_625
    assert smaller["install_amount_cents"] == 1_038_375
    assert smaller["volume_discount_cents"] == 585_000
    assert smaller["freight_cents"] == 892_320
    assert smaller["quoted_total_cents"] == 14_932_320
    assert bigger["quoted_total_cents"] == 14_790_200
    assert smaller["quoted_total_cents"] - bigger["quoted_total_cents"] == 142_120


def test_freight_rate_and_duty_uplift_constants_are_read_per_zone_and_duty_class(
    api, order_planner_headers
):
    """Two identical orders diverge only on the freight rate of their zones.

    The PRD states that the freight rates "are 180 cents per kilogram for `Z1`,
    260 for `Z2`, 340 for `Z3` and 520 for `Z4`", and that the line uplift is
    "zero for `LIGHT_COMMERCIAL`, six percent for `FULL_COMMERCIAL` and eleven
    percent for `INSTITUTIONAL`".

    Design: Corner/calculations/freight_rate_and_duty_uplift_constants_are_read_per_zone_and_duty_class
    """
    near = setup_configured_order(
        preset="T900", quantity=1,
        facility_overrides={"account_name": "Grandstand Fitness", "freight_zone": "Z1"},
    )
    far_facility_order = setup_configured_order(
        revision_ctx=near, quantity=1,
        facility_overrides={"account_name": "Longhaul Leisure Centre",
                            "freight_zone": "Z3"},
    )

    close_quote = validate_success(
        api.quote_order(near["order"]["id"],
                        quote_payload(read_order(near["order"]["id"])["version"]),
                        order_planner_headers)
    )
    distant_quote = validate_success(
        api.quote_order(far_facility_order["order"]["id"],
                        quote_payload(
                            read_order(far_facility_order["order"]["id"])["version"]),
                        order_planner_headers)
    )

    close_breakdown = read_price_breakdown(near["order"]["id"])
    distant_breakdown = read_price_breakdown(far_facility_order["order"]["id"])
    assert close_breakdown["line_subtotal_cents"] == 508_747
    assert close_breakdown["install_amount_cents"] == 13_313
    assert close_breakdown["discount_base_cents"] == 522_060
    assert close_breakdown["volume_discount_cents"] == 0
    assert close_breakdown["discounted_base_cents"] == 522_060
    assert float(close_breakdown["chargeable_weight_kg"]) == 212.5
    assert close_breakdown["freight_cents"] == 38_250
    assert close_quote["quoted_total_cents"] == 560_310
    assert distant_breakdown["line_subtotal_cents"] == 508_747
    assert distant_breakdown["install_amount_cents"] == 13_313
    assert distant_breakdown["discounted_base_cents"] == 522_060
    assert distant_breakdown["freight_cents"] == 72_250
    assert distant_quote["quoted_total_cents"] == 594_310
    assert distant_quote["quoted_total_cents"] - close_quote["quoted_total_cents"] == 34_000
    for breakdown in (close_breakdown, distant_breakdown):
        assert breakdown["price_variant_applied"] == "PROVISIONAL"
        assert breakdown["punch_list_credit_cents"] == 0
        assert breakdown["final_total_cents"] is None


def test_install_amount_rounds_half_up_at_the_half_cent(api):
    """Both variants land on a half cent and both round upward.

    The PRD states that "`install_amount_cents` is that hours figure multiplied by
    the installation labour rate of 8,875 cents per crew hour (88.75 dollars an
    hour), rounded half up to a whole number of cents."

    Design: Corner/calculations/install_amount_rounds_half_up_at_the_half_cent
    """
    ctx = setup_scheduled_install(preset="T900", quantity=1,
                                  estimated_labor_hours=1.5)
    arrive_ctx(ctx)
    provisional = read_price_breakdown(ctx["order"]["id"])
    assert provisional["install_amount_cents"] == 13_313
    assert provisional["quoted_total_cents"] == 560_310

    complete_install_ctx(ctx, actual_labor_hours=4.5, punch_list_open_count=0)

    final = read_price_breakdown(ctx["order"]["id"])
    assert final["install_amount_cents"] == 39_938
    assert final["discount_base_cents"] == 548_685
    assert final["volume_discount_cents"] == 0
    assert final["freight_cents"] == 38_250
    assert final["punch_list_credit_cents"] == 0
    assert final["final_total_cents"] == 586_935
    assert final["price_variant_applied"] == "FINAL"
    assert final["quoted_total_cents"] == 560_310
    assert final["final_total_cents"] - final["quoted_total_cents"] == 26_625
    assert read_order(ctx["order"]["id"])["amount_due_cents"] == 586_935


def test_free_freight_waiver_reads_the_post_discount_base_at_sixty_units(
    api, order_planner_headers
):
    """Sixty units keep the discounted base above the threshold, so freight is nil.

    The PRD states that the waiver applies "when the discounted base has reached
    20,000,000 cents (200,000 dollars) or more — freight is waived on orders that
    large."

    Design: Corner/calculations/free_freight_waiver_reads_the_post_discount_base_at_sixty_units
    """
    ctx = _l200_order(60)

    quoted = validate_success(
        api.quote_order(ctx["order"]["id"],
                        quote_payload(read_order(ctx["order"]["id"])["version"]),
                        order_planner_headers)
    )

    line = read_order_line(ctx["line"]["id"], order_planner_headers)
    assert line["unit_price_cents"] == 348_375
    assert line["extended_price_cents"] == 20_902_500
    breakdown = read_price_breakdown(ctx["order"]["id"])
    assert breakdown["install_amount_cents"] == 1_597_500
    assert breakdown["discount_base_cents"] == 22_500_000
    assert breakdown["volume_discount_cents"] == 1_687_500
    assert breakdown["discounted_base_cents"] == 20_812_500
    assert breakdown["discounted_base_cents"] >= 20_000_000
    assert float(breakdown["chargeable_weight_kg"]) == 5280.0
    assert breakdown["freight_cents"] == 0
    assert quoted["quoted_total_cents"] == 20_812_500
    assert quoted["price_variant_applied"] == "PROVISIONAL"


def test_price_variant_selection_moves_none_then_provisional_then_final(api):
    """The variant marker tracks whichever assembly last wrote the money fields.

    The PRD states that on a quote "`price_variant_applied` is set to
    `PROVISIONAL`", while the final variant is "written automatically when the
    install job completes" and "`price_variant_applied` becomes `FINAL`".

    Design: Corner/calculations/price_variant_selection_moves_none_then_provisional_then_final
    """
    ctx = setup_configured_order(preset="T900", quantity=1)

    unquoted = read_order(ctx["order"]["id"])
    assert unquoted["price_variant_applied"] == "NONE"
    assert unquoted["quoted_total_cents"] == 0
    assert unquoted["final_total_cents"] is None
    assert unquoted["install_amount_cents"] == 0
    assert unquoted["line_subtotal_cents"] == 508_747

    quoted = quote_ctx(ctx)
    assert quoted["price_variant_applied"] == "PROVISIONAL"
    assert quoted["install_amount_cents"] == 13_313
    assert quoted["quoted_total_cents"] == 560_310
    assert quoted["final_total_cents"] is None

    confirm_ctx(ctx)
    complete_production_ctx(ctx)
    add_partner_ctx(ctx)
    schedule_install_ctx(ctx, estimated_labor_hours=1.5)
    arrive_ctx(ctx)
    complete_install_ctx(ctx, actual_labor_hours=3.0, punch_list_open_count=0)

    final = read_order(ctx["order"]["id"])
    assert final["price_variant_applied"] == "FINAL"
    assert final["install_amount_cents"] == 26_625
    assert final["final_total_cents"] == 573_622
    assert final["quoted_total_cents"] == 560_310
    assert final["amount_due_cents"] == 573_622
    assert final["billing_status"] == "INVOICED"


def test_price_breakdown_exposes_intermediate_steps_absent_from_the_order_row(
    api, order_planner_headers
):
    """Two assembly intermediates are published only by the breakdown read.

    The PRD states that the breakdown "restates the assembly step by step,
    returning `line_subtotal_cents`, `install_amount_cents`,
    `discount_base_cents`, `volume_discount_cents`, `discounted_base_cents`,
    `chargeable_weight_kg`, `freight_cents`, `punch_list_credit_cents`,
    `quoted_total_cents`, `final_total_cents`, `tradein_credit_applied_cents`,
    `amount_due_cents` and `price_variant_applied`."

    Design: Corner/endpoints/price_breakdown_exposes_intermediate_steps_absent_from_the_order_row
    """
    ctx = setup_configured_order(preset="T900", quantity=1)
    quoted = quote_ctx(ctx)
    assert quoted["billing_status"] == "QUOTED"
    version_before = read_order(ctx["order"]["id"])["version"]

    response = api.get_price_breakdown(ctx["order"]["id"], order_planner_headers)

    breakdown = validate_success(response)
    assert breakdown["line_subtotal_cents"] == 508_747
    assert breakdown["install_amount_cents"] == 13_313
    assert breakdown["discount_base_cents"] == 522_060
    assert breakdown["volume_discount_cents"] == 0
    assert breakdown["discounted_base_cents"] == 522_060
    assert float(breakdown["chargeable_weight_kg"]) == 212.5
    assert breakdown["freight_cents"] == 38_250
    assert breakdown["punch_list_credit_cents"] == 0
    assert breakdown["quoted_total_cents"] == 560_310
    assert breakdown["final_total_cents"] is None
    assert breakdown["amount_due_cents"] is None
    assert breakdown["tradein_credit_applied_cents"] == 0
    assert breakdown["price_variant_applied"] == "PROVISIONAL"
    assert breakdown["discount_base_cents"] == (
        breakdown["line_subtotal_cents"] + breakdown["install_amount_cents"]
    )
    assert breakdown["discounted_base_cents"] == (
        breakdown["discount_base_cents"] - breakdown["volume_discount_cents"]
    )
    order = read_order(ctx["order"]["id"])
    assert order["version"] == version_before, "the breakdown read is read-only"
    assert order["quoted_total_cents"] == breakdown["quoted_total_cents"]
    assert order["line_subtotal_cents"] == breakdown["line_subtotal_cents"]
    assert order["install_amount_cents"] == breakdown["install_amount_cents"]
    assert order["freight_cents"] == breakdown["freight_cents"]
