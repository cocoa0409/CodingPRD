"""Dual-variant calculations that diverge on one and the same row.

Three rules of PRD.md run the identical formula twice under different
substitutions and keep both answers: the freight quote billed on nested cube
against the delivered invoice billed on gross cube, the provisional warpage
index scored against scheduled cooling minutes against the final index scored
against actual cooling minutes, and the mould selector over the whole candidate
pool against the same pool minus an exclusion list.

Every figure asserted here is the one PRD.md's own arithmetic produces for the
default plant: a MID kayak of 2.0000 gross cube, 0.5000 nest factor and 24.000
kilograms, two hulls per cycle, a Z2 trailer of 5.0000 cube and 200.000
kilograms, and a forced-air cooling bay.
"""

from test_helpers import (
    ADMIN_HEADERS,
    PASSING_WALL_THICKNESS_POINTS,
    PLANNER_HEADERS,
    ApiErrorId,
    Q_CUBE,
    Q_MASS,
    Q_PERCENT,
    Q_WARPAGE,
    advance_unit_to_sellable,
    api_client,
    assert_decimal_equals,
    assert_instant_equals,
    assert_money_equals,
    create_plant_baseline,
    create_production_order,
    create_resin_lot,
    expected_wall_statistics,
    mold_payload,
    molding_cycle_payload,
    production_order_version,
    run_cycle_to_demold,
    setup_delivered_units,
    setup_loaded_shipment,
    setup_scheduled_cycle,
    unique_suffix,
    validate_error,
    validate_success,
)


class TestFreightQuotedNestedVersusBilledGross:
    """One trailer, two freight variants, two different totals on one row."""

    def test_quoted_variant_prices_every_line_on_nested_cube_at_seal(self):
        """Sealing prices the QUOTED variant on nested cube and stores it.

        PRD.md section 3.8: "The shipment's `loaded_cube_m3` is the sum of the
        per-line gross cubes and `nested_cube_m3` the sum of the per-line nested
        cubes, each rounded to four decimals; `loaded_weight_kg` is the sum of
        the hulls' `unit_weight_kg` rounded to three decimals;
        `cube_utilization_pct` is `nested_cube_m3` divided by
        `trailer_cube_capacity_m3` times 100, rounded to two decimals; and
        `density_kg_per_m3` is `loaded_weight_kg` divided by `nested_cube_m3`
        rounded to three decimals, or exactly 0.000 when `nested_cube_m3` is
        0.0000 — division by zero is never attempted."

        PRD.md section 3.8: "Sealing sets `quoted_freight_cents` and stamps
        `sealed_at` from the logical clock."

        PRD.md section 3.8: "The `QUOTED` variant, produced at seal, bills every
        line on `line_nested_cube_m3`, so nesting savings flow through to the
        quote."

        Two nested hulls give 3.0000 chargeable cube, so each line is billed on
        the dimensional weight of 120.000 kilograms per cubic metre at the Z2
        rate of 61 cents: 14640 plus 7320 is 21960 before the discount, the
        3.00 percent tier at exactly 60.00 percent utilisation takes 659, and
        9.50 percent fuel on the reduced 21301 adds 2024.

        Design: Difficulty/dual_variant_calc/freight_quote_nested_vs_bill_gross_divergence
        """
        ctx = setup_loaded_shipment()
        loaded = ctx["shipment"]
        assert_decimal_equals(loaded["loaded_cube_m3"], "4.0000", Q_CUBE, "loaded_cube_m3")
        assert_decimal_equals(loaded["nested_cube_m3"], "3.0000", Q_CUBE, "nested_cube_m3")
        assert_decimal_equals(
            loaded["loaded_weight_kg"], "48.000", Q_MASS, "loaded_weight_kg"
        )
        assert_decimal_equals(
            loaded["cube_utilization_pct"], "60.00", Q_PERCENT, "cube_utilization_pct"
        )
        assert_decimal_equals(
            loaded["density_kg_per_m3"], "16.000", Q_MASS, "density_kg_per_m3"
        )

        sealed = validate_success(
            api_client.seal_shipment(ctx["shipment_id"], PLANNER_HEADERS), 200
        )
        assert sealed["status"] == "SEALED", (
            f"sealing a loaded trailer must move it to SEALED, got {sealed['status']}"
        )
        assert_money_equals(sealed["quoted_freight_cents"], 23325, "quoted_freight_cents")
        assert sealed["billed_freight_cents"] is None, (
            "the BILLED variant is only produced at delivery, so "
            "billed_freight_cents must still be null at seal"
        )
        assert sealed["sealed_at"] is not None, "sealing stamps sealed_at"

    def test_billed_variant_prices_every_line_on_gross_cube_at_delivery(self):
        """Delivery prices the BILLED variant on gross cube beside the quote.

        PRD.md section 3.8: "The `BILLED` variant, produced at delivery, bills
        every line on `line_gross_cube_m3`, so the delivered invoice is computed
        on gross cube and normally exceeds the nested quote for any trailer
        holding more than one hull per model."

        PRD.md section 3.8: "**Delivering** requires `IN_TRANSIT`; it sets
        `billed_freight_cents` from the `BILLED` variant, stamps the shipment's
        `delivered_at`, and moves every hull `IN_TRANSIT` to `DELIVERED` with its
        own `delivered_at` copied from the same clock reading — that per-hull
        timestamp is the origin of the warranty clock and is what a claim
        measures against."

        On gross cube both lines are billed at 2.0000 cube, so the pre-discount
        total is 29280, the same 3.00 percent tier takes 878, and 9.50 percent
        fuel on 28402 adds 2698 — 31100 against the 23325 quote for the very
        same two hulls.

        Design: Difficulty/dual_variant_calc/freight_quote_nested_vs_bill_gross_divergence
        """
        ctx = setup_delivered_units()
        shipment = api_client.read_entity(
            "get_shipment", ctx["shipment_id"], PLANNER_HEADERS
        )
        assert shipment["status"] == "DELIVERED", (
            f"expected a DELIVERED trailer, got {shipment['status']}"
        )
        assert_money_equals(
            shipment["quoted_freight_cents"], 23325, "quoted_freight_cents"
        )
        assert_money_equals(
            shipment["billed_freight_cents"], 31100, "billed_freight_cents"
        )
        divergence = shipment["billed_freight_cents"] - shipment["quoted_freight_cents"]
        assert divergence == 7775, (
            "the gross-cube bill must exceed the nested-cube quote by 7775 cents, "
            f"got {divergence}"
        )
        assert_decimal_equals(
            shipment["nested_cube_m3"], "3.0000", Q_CUBE, "nested_cube_m3"
        )
        assert_decimal_equals(
            shipment["loaded_cube_m3"], "4.0000", Q_CUBE, "loaded_cube_m3"
        )

    def test_line_cube_basis_diverges_by_nest_position(self):
        """A line's two cube fields diverge only from position 2 onward.

        PRD.md section 3.8: "A line's `line_gross_cube_m3` is always the model's
        `gross_cube_m3` rounded to four decimals."

        PRD.md section 3.8: "Its `line_nested_cube_m3` is the full gross cube
        when its `nest_position` is 1, and `gross_cube_m3` multiplied by
        `nest_factor`, rounded to four decimals, for every position after the
        first."

        PRD.md section 3.8: "Walking that order, a line's `nest_position` is one
        plus the number of earlier lines whose hull shares the same
        `product_model_id`, so numbering is **per product model**, not per
        trailer: the first kayak and the first canoe are both position 1."

        The two cube bases are what the two freight variants read, so this is
        the row-level origin of the quote-to-bill divergence.

        Design: Difficulty/dual_variant_calc/freight_quote_nested_vs_bill_gross_divergence
        """
        ctx = setup_loaded_shipment()
        lines = [
            api_client.read_entity("get_shipment_line", line_id, PLANNER_HEADERS)
            for line_id in ctx["shipment_line_ids"]
        ]
        assert len(lines) == 2, f"expected two trailer lines, got {len(lines)}"
        by_position = sorted(lines, key=lambda line: line["nest_position"])

        anchor, follower = by_position
        assert anchor["nest_position"] == 1, (
            f"the first hull of the model group is position 1, got {anchor['nest_position']}"
        )
        assert_decimal_equals(
            anchor["line_gross_cube_m3"], "2.0000", Q_CUBE, "line_gross_cube_m3"
        )
        assert_decimal_equals(
            anchor["line_nested_cube_m3"], "2.0000", Q_CUBE, "line_nested_cube_m3"
        )

        assert follower["nest_position"] == 2, (
            f"the second hull of the model group is position 2, got {follower['nest_position']}"
        )
        assert_decimal_equals(
            follower["line_gross_cube_m3"], "2.0000", Q_CUBE, "line_gross_cube_m3"
        )
        assert_decimal_equals(
            follower["line_nested_cube_m3"], "1.0000", Q_CUBE, "line_nested_cube_m3"
        )


# The cycle that separates the two warpage variants: 300.0 C against the
# reference 288 gives a thermal term of 0.300, a rotation ratio of 4.200 gives
# 0.050, and ten scheduled cooling minutes against the model's thirty give a
# provisional cooling term of 0.667 that the actual thirty-five minutes erase.
_P1_WARPAGE_CYCLE_OVERRIDES = {
    "oven_temp_c": 300.0,
    "arm_rpm_major": 8.4,
    "arm_rpm_minor": 2.0,
    "scheduled_cooling_minutes": 10,
}


def _p1_demolded_warpage_cycle():
    """A demoulded cycle whose two warpage variants must disagree."""
    return run_cycle_to_demold(
        setup_scheduled_cycle(cycle_overrides=dict(_P1_WARPAGE_CYCLE_OVERRIDES))
    )


class TestWarpageProvisionalVersusFinalVariant:
    """The warpage formula scored twice: at demould, then at inspection."""

    def test_provisional_variant_scores_the_scheduled_cooling_deficit(self):
        """Demoulding scores the provisional index off scheduled cooling minutes.

        PRD.md section 3.6: "The **provisional** variant runs at demould, writes
        `provisional_warpage_index` on the cycle, uses `scheduled_cooling_minutes`
        for term 2, and forces the distribution term to 0.000 because no hull has
        been measured yet."

        PRD.md section 3.6: "The base is then the weighted sum over the
        **already-rounded** terms — 0.40 times the thermal term plus 0.35 times
        the cooling term plus 0.25 times the rotation term plus 0.50 times the
        distribution term — rounded to three decimals."

        PRD.md section 3.5: "The cycle moves `COOLING` to `DEMOLDED`,
        `actual_cooling_end_at` is recorded and `actual_cooling_minutes`
        recomputed by flooring, and `provisional_warpage_index` is computed."

        Thermal 0.300, cooling (30 - 10) / 30 = 0.667, rotation 0.050 and a
        forced distribution 0.000 weight to 0.366, which the MID size factor
        1.000 and the FORCED_AIR mode factor 0.900 take to 0.329.

        Design: Difficulty/dual_variant_calc/warpage_provisional_schedule_vs_final_actual_divergence
        """
        ctx = _p1_demolded_warpage_cycle()
        cycle = ctx["molding_cycle"]
        assert cycle["status"] == "DEMOLDED", (
            f"expected a DEMOLDED cycle, got {cycle['status']}"
        )
        assert cycle["actual_oven_minutes"] == 60, (
            "the oven ran from 09:00 to 10:00, so actual_oven_minutes is 60, got "
            f"{cycle['actual_oven_minutes']}"
        )
        assert cycle["actual_cooling_minutes"] == 35, (
            "the shot cooled from 10:00 to 10:35, so actual_cooling_minutes is 35, "
            f"got {cycle['actual_cooling_minutes']}"
        )
        assert_decimal_equals(
            cycle["provisional_warpage_index"],
            "0.329",
            Q_WARPAGE,
            "provisional_warpage_index",
        )

    def test_final_variant_scores_actual_cooling_and_measured_distribution(self):
        """Inspection rescores the same shot off the actual cooling minutes.

        PRD.md section 3.6: "The **final** variant runs at inspection, writes
        `final_warpage_index` on the hull, uses the cycle's
        `actual_cooling_minutes` for term 2, and takes a live distribution term
        from the inspected `wall_cv_pct`."

        PRD.md section 3.6: "Term 2, cooling deficit: the model's
        `min_cooling_minutes` minus the applicable cooling minutes, floored at
        zero, divided by `min_cooling_minutes`, rounded to three decimals."

        PRD.md section 3.6: "`wall_cv_pct` is then `wall_sd_mm` divided by
        `mean_wall_thickness_mm` times 100, rounded to two decimals, computed
        from the two already-rounded values, and is 0.00 when the mean is 0.000."

        Thirty-five actual minutes clear the model's thirty, so the cooling term
        floors to 0.000, and a measured 1.08 percent coefficient of variation is
        far inside the 12.00 percent ceiling, so the distribution term is 0.000
        too: the base falls to 0.133 and the forced-air factor takes it to 0.120.

        Design: Difficulty/dual_variant_calc/warpage_provisional_schedule_vs_final_actual_divergence
        """
        ctx = _p1_demolded_warpage_cycle()
        unit = advance_unit_to_sellable(ctx, ctx["finished_units"][0])

        expected = expected_wall_statistics(PASSING_WALL_THICKNESS_POINTS)
        assert_decimal_equals(
            unit["wall_cv_pct"], expected["wall_cv_pct"], Q_PERCENT, "wall_cv_pct"
        )
        assert_decimal_equals(unit["wall_cv_pct"], "1.08", Q_PERCENT, "wall_cv_pct")
        assert_decimal_equals(
            unit["final_warpage_index"], "0.120", Q_WARPAGE, "final_warpage_index"
        )
        assert unit["inspection_verdict"] == "PASS", (
            f"readings inside every gate must give PASS, got {unit['inspection_verdict']}"
        )
        assert unit["build_status"] == "SELLABLE", (
            f"a PASS moves the hull to SELLABLE, got {unit['build_status']}"
        )

    def test_both_indices_are_retained_side_by_side_on_different_rows(self):
        """Inspecting a hull never disturbs the cycle's provisional score.

        PRD.md section 3.6: "That single formula has two variants which are both
        retained side by side on different rows."

        PRD.md section 3.6: "Both substitutions are made in the same pass, so the
        two figures legitimately diverge on the identical cycle row — a cycle
        that cooled for less than its scheduled minutes, or a hull whose
        `wall_cv_pct` exceeds the model ceiling, scores higher on the final
        index."

        The cycle keeps 0.329 while the hull it minted carries 0.120, so the two
        variants of one formula are observable at once.

        Design: Difficulty/dual_variant_calc/warpage_provisional_schedule_vs_final_actual_divergence
        """
        ctx = _p1_demolded_warpage_cycle()
        unit = advance_unit_to_sellable(ctx, ctx["finished_units"][0])
        cycle = api_client.read_entity(
            "get_molding_cycle", ctx["molding_cycle_id"], ADMIN_HEADERS
        )

        assert_decimal_equals(
            cycle["provisional_warpage_index"],
            "0.329",
            Q_WARPAGE,
            "provisional_warpage_index after inspection",
        )
        assert_decimal_equals(
            unit["final_warpage_index"], "0.120", Q_WARPAGE, "final_warpage_index"
        )
        assert unit["final_warpage_index"] != cycle["provisional_warpage_index"], (
            "the two variants must diverge on this cycle: provisional "
            f"{cycle['provisional_warpage_index']} against final "
            f"{unit['final_warpage_index']}"
        )


def _p1_two_mold_plant():
    """A plant with two interchangeable single-cavity tools, A ranked before B.

    Both tools serve the same hull model, both are AVAILABLE with
    ``cycles_since_service`` 0 and a ``service_interval_cycles`` of 10, so the
    eligibility filter admits both and only the ``mold_code`` tie-break decides.
    The order is for three hulls, which keeps three single-cavity cycles inside
    the overbuild ceiling.
    """
    suffix = unique_suffix()
    ctx = create_plant_baseline(
        mold_overrides={
            "mold_code": f"MSA{suffix}",
            "cavity_count": 1,
            "nominal_charge_kg": 12.0,
        }
    )
    mold_b = validate_success(
        api_client.create_mold(
            mold_payload(
                ctx["product_model_id"],
                mold_code=f"MSB{suffix}",
                cavity_count=1,
                nominal_charge_kg=12.0,
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    create_resin_lot()
    order = create_production_order(ctx, ordered_qty=3)
    ctx["mold_a"] = ctx["mold"]
    ctx["mold_b"] = mold_b
    ctx["production_order"] = order
    ctx["production_order_id"] = order["id"]
    return ctx


def _p1_book_cycle(ctx, **overrides):
    """Post one cycle booking against the two-tool plant and return the response."""
    payload = molding_cycle_payload(
        ctx["production_order_id"],
        ctx["oven_station_id"],
        ctx["cooling_bay_id"],
        production_order_version(ctx["production_order_id"]),
        **overrides,
    )
    return api_client.create_molding_cycle(payload, ctx["operator_headers"])


class TestMoldSelectionFirstAttemptVersusRetryWithExclusions:
    """The same ranked pool, once whole and once minus an exclusion list."""

    def test_first_attempt_takes_the_lowest_mold_code_of_the_full_pool(self):
        """With both tools idle the mold_code tie-break decides the choice.

        PRD.md section 3.4: "Ranking is total and deterministic: ascending
        `cycles_since_service`, then ascending `mold_code`."

        PRD.md section 3.4: "The first ranked candidate is written to `mold_id`
        and returned in the response so the choice is observable."

        PRD.md section 3.4: "When every check passes, the three projected instants
        are written: `oven_end_at` is `oven_start_at` advanced by
        `scheduled_oven_minutes`; `cooling_window_start_at` equals `oven_end_at`
        exactly, butt-jointed with no gap; and `cooling_window_end_at` is
        `cooling_window_start_at` advanced by `scheduled_cooling_minutes`."

        Design: Difficulty/dual_variant_calc/mold_selection_first_attempt_vs_retry_with_exclusions
        """
        ctx = _p1_two_mold_plant()
        cycle = validate_success(_p1_book_cycle(ctx), 201)

        assert cycle["mold_id"] == ctx["mold_a"]["id"], (
            "with equal service counters the lower mold_code must win, expected "
            f"{ctx['mold_a']['mold_code']}, got mold_id {cycle['mold_id']}"
        )
        assert_instant_equals(
            cycle["oven_end_at"], "2026-08-01T10:00:00Z", "oven_end_at"
        )
        assert_instant_equals(
            cycle["cooling_window_start_at"],
            "2026-08-01T10:00:00Z",
            "cooling_window_start_at",
        )
        assert_instant_equals(
            cycle["cooling_window_end_at"],
            "2026-08-01T10:30:00Z",
            "cooling_window_end_at",
        )

    def test_retry_with_an_exclusion_takes_the_second_ranked_tool(self):
        """Excluding the winner returns the runner-up, not a window conflict.

        PRD.md section 3.4: "When the request carries `exclude_mold_ids`, those
        tools are removed **after** the eligibility filter and **before** ranking,
        so the second-ranked tool is returned instead of the first; exclusion
        never alters the ranking expression itself."

        PRD.md section 3.4: "Occupancy is evaluated only against cycles in
        `SCHEDULED`, `OVEN_RUNNING` or `COOLING`; `DEMOLDED` and `ABORTED` cycles
        never block a tool."

        The retry books an 11:00 window, and the first cycle's tool span runs
        09:00 up to 10:30, so tool A is still fully eligible and unoccupied over
        the retry's span: only the exclusion list moves the choice to tool B.

        Design: Difficulty/dual_variant_calc/mold_selection_first_attempt_vs_retry_with_exclusions
        """
        ctx = _p1_two_mold_plant()
        first = validate_success(_p1_book_cycle(ctx), 201)
        assert first["mold_id"] == ctx["mold_a"]["id"], (
            "the first attempt must take tool A before the retry is meaningful"
        )

        retry = validate_success(
            _p1_book_cycle(
                ctx,
                oven_start_at="2026-08-01T11:00:00Z",
                exclude_mold_ids=[ctx["mold_a"]["id"]],
            ),
            201,
        )
        assert retry["mold_id"] == ctx["mold_b"]["id"], (
            "the excluded tool A must be dropped before ranking, leaving tool B, "
            f"got mold_id {retry['mold_id']}"
        )
        assert retry["status"] == "SCHEDULED", (
            f"an accepted booking is SCHEDULED, got {retry['status']}"
        )
        for label in ("mold_a", "mold_b"):
            tool = api_client.read_entity("get_mold", ctx[label]["id"], ADMIN_HEADERS)
            assert tool["status"] == "AVAILABLE", (
                f"{label} must still be AVAILABLE after scheduling, got {tool['status']}"
            )
            assert tool["cycles_since_service"] == 0, (
                "scheduling never wears a tool, so cycles_since_service stays 0, got "
                f"{tool['cycles_since_service']} on {label}"
            )

    def test_exclusion_that_empties_the_pool_is_never_a_window_conflict(self):
        """An emptied pool reports the no-eligible-tool failure, not occupancy.

        PRD.md section 3.4: "An exclusion list that empties the pool always
        yields `ERR_NO_ELIGIBLE_MOLD`, never the window conflict."

        PRD.md section 3.4: "When the pool is empty the two failure modes are
        kept distinct: if at least one tool for this hull model is in `status`
        `AVAILABLE` but every such tool was removed by the occupancy clause, the
        request fails with `ERR_MOLD_WINDOW_CONFLICT` (HTTP 409); otherwise — no
        available tool at all, or an `exclude_mold_ids` list that emptied the
        pool — it fails with `ERR_NO_ELIGIBLE_MOLD` (HTTP 409)."

        The third booking asks for a 14:00 window on the station's second arm,
        where both tools are unoccupied and both are AVAILABLE, so occupancy
        cannot be the cause: the exclusion list is.

        Design: Difficulty/dual_variant_calc/mold_selection_first_attempt_vs_retry_with_exclusions
        """
        ctx = _p1_two_mold_plant()
        validate_success(_p1_book_cycle(ctx), 201)
        validate_success(
            _p1_book_cycle(
                ctx,
                oven_start_at="2026-08-01T11:00:00Z",
                exclude_mold_ids=[ctx["mold_a"]["id"]],
            ),
            201,
        )

        refused = _p1_book_cycle(
            ctx,
            arm_index=2,
            oven_start_at="2026-08-01T14:00:00Z",
            exclude_mold_ids=[ctx["mold_a"]["id"], ctx["mold_b"]["id"]],
        )
        validate_error(refused, ApiErrorId.NO_ELIGIBLE_MOLD, expected_status=409)
