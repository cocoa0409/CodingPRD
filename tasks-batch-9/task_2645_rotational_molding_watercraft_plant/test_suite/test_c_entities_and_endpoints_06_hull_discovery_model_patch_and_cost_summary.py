"""Three read paths: the hull list, the model amendment, and the order cost read.

The hull collection is the only way to reach a FinishedUnit at all, the model
PATCH is the only write path onto a ProductModel, and the cost summary is the
one place the five-step order arithmetic of PRD.md section 3.3 is visible
without recomputing it.
"""

from test_helpers import (
    PASSING_WALL_THICKNESS_POINTS,
    assert_decimal_equals,
    assert_hull_serial_format,
    assert_money_equals,
    assert_pagination_meta,
    assert_wall_statistics,
    create_demand_bucket,
    create_plant_baseline,
    create_production_order,
    create_resin_lot,
    dec,
    get_success_data,
    setup_sellable_units,
    setup_stored_units,
    validate_paginated,
    validate_success,
)

Q_CUBE = dec("0.0001")
Q_PCT = dec("0.01")
ORDER_CODE = "POR-CD-DISC"


def _p3_identity_overrides(ctx, cycle_overrides=None, charge_overrides=None):
    """Fill in the two identity fields the shared factories deliberately omit.

    ``molding_cycle_payload`` omits ``operator_technician_id`` and
    ``resin_charge_payload`` omits ``created_by_technician_id``, yet PRD.md
    section 2.8 lists both as required client-supplied fields that must equal
    the acting identifier. Sending the acting identifier satisfies that reading
    and the section 3.4 / 3.2 reading in which the server copies it, so this
    partition always sends it.
    """
    cyc = dict(cycle_overrides or {})
    cyc.setdefault("operator_technician_id", ctx["molding_operator_id"])
    chg = dict(charge_overrides or {})
    chg.setdefault("created_by_technician_id", ctx["resin_technician_id"])
    return cyc, chg


def _p3_stored_plant():
    """Two hulls of one cycle, inspected PASS and both stored in the one zone."""
    baseline = create_plant_baseline()
    bucket = create_demand_bucket(baseline)
    cyc, chg = _p3_identity_overrides(baseline)
    ctx = setup_stored_units(
        baseline=baseline,
        order_overrides={
            "order_code": ORDER_CODE,
            "ordered_qty": 2,
            "demand_bucket_id": bucket["id"],
        },
        cycle_overrides=cyc,
        charge_overrides=chg,
    )
    ctx["demand_bucket"] = bucket
    return ctx


class TestHullListIsTheOnlyDiscoveryChannel:
    """Every foreign key the cascade minted is reachable through a filter."""

    def test_the_producing_cycle_filter_returns_one_row_per_cavity(self, api):
        """Filtering by the producing cycle finds exactly the hulls it minted.

        PRD.md section 3.6: "Hulls are listed with optional `molding_cycle_id`,
        `product_model_id`, `warehouse_id`, `outfitted_by_technician_id`,
        `inspected_by_technician_id`, `demand_bucket_id`, `build_status`,
        `logistics_status`, `inspection_verdict`, `storage_zone_code` and
        `is_zone_anchor` filters."

        PRD.md section 3.5: "Because there is no creation endpoint for hulls,
        the filtered hull list is their only discovery channel."

        Design: Corner/endpoints/ep_finished_unit_filtered_list_is_the_only_discovery_channel_for_its_fks
        """
        ctx = _p3_stored_plant()

        rows, meta = validate_paginated(
            api.list_finished_units(
                {"molding_cycle_id": ctx["molding_cycle_id"]}, ctx["planner_headers"]
            )
        )

        assert_pagination_meta(meta, 2, 10, 0)
        assert meta["has_more"] is False
        ordered = sorted(rows, key=lambda unit: unit["cavity_index"])
        assert [unit["cavity_index"] for unit in ordered] == [1, 2]
        assert ordered[0]["hull_serial"] == f"{ORDER_CODE}-01-0001"
        assert ordered[1]["hull_serial"] == f"{ORDER_CODE}-02-0002"
        for unit in ordered:
            assert_hull_serial_format(
                unit["hull_serial"], ORDER_CODE, unit["cavity_index"]
            )

    def test_each_minted_foreign_key_has_its_own_filter(self, api):
        """Model, site, both technicians and the bucket each narrow to the pair.

        PRD.md section 3.6: "Hulls are listed with optional `molding_cycle_id`,
        `product_model_id`, `warehouse_id`, `outfitted_by_technician_id`,
        `inspected_by_technician_id`, `demand_bucket_id`, `build_status`,
        `logistics_status`, `inspection_verdict`, `storage_zone_code` and
        `is_zone_anchor` filters."

        PRD.md section 3.7: "Storing writes `logistics_status` `STORED`, copies
        `warehouse_id` and `demand_bucket_id` from the producing order, stamps
        `stored_at` from the logical clock, and writes `storage_zone_code`,
        `stored_footprint_cube_m3` and `is_zone_anchor`."

        Design: Corner/endpoints/ep_finished_unit_filtered_list_is_the_only_discovery_channel_for_its_fks
        """
        ctx = _p3_stored_plant()
        headers = ctx["planner_headers"]

        for label, params in (
            ("product_model_id", {"product_model_id": ctx["product_model_id"]}),
            ("warehouse_id", {"warehouse_id": ctx["warehouse_id"]}),
            (
                "outfitted_by_technician_id",
                {"outfitted_by_technician_id": ctx["assembly_technician_id"]},
            ),
            (
                "inspected_by_technician_id",
                {"inspected_by_technician_id": ctx["quality_inspector_id"]},
            ),
            ("demand_bucket_id", {"demand_bucket_id": ctx["demand_bucket"]["id"]}),
        ):
            rows, meta = validate_paginated(
                api.list_finished_units(params, headers)
            )
            assert meta["total_count"] == 2, (
                f"the {label} filter should reach both hulls of the cycle"
            )
            assert len(rows) == 2

    def test_the_two_state_axes_and_the_zone_compose_as_filters(self, api):
        """Both axes narrow together, and so do verdict and zone.

        PRD.md section 2.3: "Filter parameters on list endpoints are exact-match
        and are combined with logical AND."

        PRD.md section 3.6: "A hull carries two independent state axes on one
        row: `build_status`, which the shop floor drives, and
        `logistics_status`, which the warehouse and trailer workflows drive."

        Design: Corner/endpoints/ep_finished_unit_filtered_list_is_the_only_discovery_channel_for_its_fks
        """
        ctx = _p3_stored_plant()
        headers = ctx["planner_headers"]

        _rows, both_axes = validate_paginated(
            api.list_finished_units(
                {"build_status": "SELLABLE", "logistics_status": "STORED"}, headers
            )
        )
        assert both_axes["total_count"] == 2

        _rows, verdict_and_zone = validate_paginated(
            api.list_finished_units(
                {"inspection_verdict": "PASS", "storage_zone_code": "Z-A"}, headers
            )
        )
        assert verdict_and_zone["total_count"] == 2

        _rows, unallocated = validate_paginated(
            api.list_finished_units(
                {"build_status": "SELLABLE", "logistics_status": "UNALLOCATED"},
                headers,
            )
        )
        assert unallocated["total_count"] == 0

    def test_the_anchor_flag_separates_the_anchor_from_its_nested_sibling(
        self, api
    ):
        """One of the two stored hulls anchors the nest group and one nests.

        PRD.md section 3.7: "Opening a **new nest group** — no eligible zone
        anchors this model — charges the full `gross_cube_m3` and sets
        `is_zone_anchor` true."

        PRD.md section 3.7: "**Joining an existing nest group** charges
        `gross_cube_m3` multiplied by `nest_factor` and leaves `is_zone_anchor`
        false, and the affinity term forces that zone even when a wholly empty
        zone would give a looser fit."

        Design: Corner/endpoints/ep_finished_unit_filtered_list_is_the_only_discovery_channel_for_its_fks
        """
        ctx = _p3_stored_plant()
        headers = ctx["planner_headers"]

        anchors, anchor_meta = validate_paginated(
            api.list_finished_units({"is_zone_anchor": "true"}, headers)
        )
        assert anchor_meta["total_count"] == 1
        anchor = validate_success(
            api.get_finished_unit(anchors[0]["id"], headers)
        )
        assert anchor["is_zone_anchor"] is True
        assert_decimal_equals(
            anchor["stored_footprint_cube_m3"],
            "2.0000",
            Q_CUBE,
            "anchor stored_footprint_cube_m3",
        )

        followers, follower_meta = validate_paginated(
            api.list_finished_units({"is_zone_anchor": "false"}, headers)
        )
        assert follower_meta["total_count"] == 1
        follower = validate_success(
            api.get_finished_unit(followers[0]["id"], headers)
        )
        assert follower["is_zone_anchor"] is False
        assert_decimal_equals(
            follower["stored_footprint_cube_m3"],
            "1.0000",
            Q_CUBE,
            "nested stored_footprint_cube_m3",
        )
        assert anchor["id"] != follower["id"]

    def test_the_single_hull_read_exposes_the_inspection_statistics(self, api):
        """The one-row read carries the wall statistics the inspection derived.

        PRD.md section 3.6: "With `n` the number of supplied points:
        `mean_wall_thickness_mm` is the sum of the points divided by `n`,
        rounded to three decimals and stored."

        PRD.md section 3.6: "`wall_sd_mm` is then the population standard
        deviation taken **about that already-rounded mean** — the sum over the
        points of the squared difference from `mean_wall_thickness_mm`, divided
        by `n` (the population divisor, never `n` minus 1), square-rooted, and
        rounded to three decimals."

        PRD.md section 3.6: "`wall_cv_pct` is then `wall_sd_mm` divided by
        `mean_wall_thickness_mm` times 100, rounded to two decimals, computed
        from the two already-rounded values, and is 0.00 when the mean is
        0.000."

        PRD.md section 3.6: "`min_wall_thickness_mm` is the smallest supplied
        point rounded to three decimals."

        Design: Corner/endpoints/ep_finished_unit_filtered_list_is_the_only_discovery_channel_for_its_fks
        """
        ctx = _p3_stored_plant()

        unit = validate_success(
            api.get_finished_unit(
                ctx["stored_unit_ids"][0], ctx["planner_headers"]
            )
        )

        assert unit["inspection_verdict"] == "PASS"
        assert_wall_statistics(unit, PASSING_WALL_THICKNESS_POINTS)
        assert_decimal_equals(
            unit["min_wall_thickness_mm"],
            min(PASSING_WALL_THICKNESS_POINTS),
            dec("0.001"),
            "min_wall_thickness_mm",
        )


class TestModelAmendmentDoesNotRejudgeStoredMeasurements:
    """Tightening a limit binds later inspections only."""

    def test_the_patch_writes_only_the_named_limits(self, api):
        """Three named limits move; every omitted field keeps its value.

        PRD.md section 3.1: "The amendable fields are the process and quality
        limits: `max_color_delta_e`, `max_regrind_pct`,
        `min_melt_index_g10min`, `max_melt_index_g10min`, `nominal_charge_kg`,
        `charge_tolerance_pct`, `min_cooling_minutes`,
        `target_wall_thickness_mm`, `wall_thickness_min_mm`,
        `wall_cv_max_pct`, `impact_test_min_joules`, `gross_cube_m3`,
        `nest_factor`, `unit_weight_kg` and `msrp_cents`."

        PRD.md section 3.1: "Amending them does not re-judge any measurement
        already stored on a hull; the new limits bind subsequent inspections
        only, and the model's `version` advances by 1."

        Design: Corner/endpoints/ep_product_model_patch_narrows_limits_without_rejudging_a_passed_hull
        """
        ctx = _p3_stored_plant()
        before = validate_success(
            api.get_product_model(ctx["product_model_id"], ctx["admin_headers"])
        )

        patched = validate_success(
            api.update_product_model(
                ctx["product_model_id"],
                {
                    "wall_cv_max_pct": 0.5,
                    "impact_test_min_joules": 200.0,
                    "min_cooling_minutes": 31,
                },
                ctx["admin_headers"],
            )
        )

        assert_decimal_equals(
            patched["wall_cv_max_pct"], "0.50", Q_PCT, "wall_cv_max_pct"
        )
        assert_decimal_equals(
            patched["impact_test_min_joules"],
            "200.00",
            Q_PCT,
            "impact_test_min_joules",
        )
        assert patched["min_cooling_minutes"] == 31
        assert_decimal_equals(
            patched["gross_cube_m3"], before["gross_cube_m3"], Q_CUBE, "gross_cube_m3"
        )
        assert_decimal_equals(
            patched["nest_factor"], before["nest_factor"], Q_CUBE, "nest_factor"
        )
        assert_money_equals(patched["msrp_cents"], before["msrp_cents"], "msrp_cents")
        assert patched["version"] == before["version"] + 1

    def test_a_hull_that_already_passed_keeps_its_verdict_and_statistics(
        self, api
    ):
        """A ceiling tightened below a stored reading does not demote the hull.

        PRD.md section 3.1: "Amending them does not re-judge any measurement
        already stored on a hull; the new limits bind subsequent inspections
        only, and the model's `version` advances by 1."

        PRD.md section 3.6: "Only the array supplied on this call participates,
        in the order given; a re-inspection replaces the previous array wholesale
        rather than merging it."

        Design: Corner/endpoints/ep_product_model_patch_narrows_limits_without_rejudging_a_passed_hull
        """
        ctx = _p3_stored_plant()
        unit_id = ctx["stored_unit_ids"][0]
        before = validate_success(
            api.get_finished_unit(unit_id, ctx["planner_headers"])
        )
        assert before["inspection_verdict"] == "PASS"

        get_success_data(
            api.update_product_model(
                ctx["product_model_id"],
                {
                    "wall_cv_max_pct": 0.5,
                    "impact_test_min_joules": 200.0,
                    "min_cooling_minutes": 31,
                },
                ctx["admin_headers"],
            )
        )

        after = validate_success(
            api.get_finished_unit(unit_id, ctx["planner_headers"])
        )
        assert after["inspection_verdict"] == "PASS"
        assert after["build_status"] == "SELLABLE"
        assert after["rework_count"] == 0
        assert after["version"] == before["version"]
        assert_wall_statistics(after, PASSING_WALL_THICKNESS_POINTS)
        assert_decimal_equals(
            after["impact_test_joules"], "120.00", Q_PCT, "impact_test_joules"
        )


class TestOrderCostSummaryZeroThenComplete:
    """The same computed read, before any cycle and after both hulls pass."""

    def test_an_order_with_no_cycle_reads_every_money_field_at_zero(self, api):
        """The zero state still names the first overhead tier.

        PRD.md section 3.3: "A computed cost read, available to `PlantAdmin` and
        `LogisticsPlanner`, exposes that arithmetic directly:
        `production_order_id`, `consumed_charge_count`, `material_cost_cents`,
        `demolded_cycle_count`, `oven_energy_cost_cents`,
        `pre_overhead_subtotal_cents`, `overhead_rate_pct`, `overhead_cents`,
        `total_cost_cents`, `completed_qty` and `unit_cost_cents`."

        PRD.md section 3.3: "the overhead rate is the rate of the *first* tier
        whose ceiling is at or above that subtotal — 18.00 percent up to 500000
        cents, 14.50 percent up to 2000000 cents, and 11.00 percent above that."

        PRD.md section 3.3: "`unit_cost_cents` is the **floor** of
        `total_cost_cents` divided by `completed_qty` when `completed_qty` is at
        least 1, and null otherwise".

        Design: Corner/endpoints/ep_production_order_cost_summary_zero_state_then_completed_state
        """
        ctx = create_plant_baseline()
        create_resin_lot()
        order = create_production_order(
            ctx, order_code="POR-CD-COST-0", ordered_qty=2
        )

        summary = validate_success(
            api.get_production_order_cost_summary(order["id"], ctx["admin_headers"])
        )

        assert summary["production_order_id"] == order["id"]
        assert summary["consumed_charge_count"] == 0
        assert_money_equals(summary["material_cost_cents"], 0, "material_cost_cents")
        assert summary["demolded_cycle_count"] == 0
        assert_money_equals(
            summary["oven_energy_cost_cents"], 0, "oven_energy_cost_cents"
        )
        assert_money_equals(
            summary["pre_overhead_subtotal_cents"], 0, "pre_overhead_subtotal_cents"
        )
        assert_decimal_equals(
            summary["overhead_rate_pct"], "18.00", Q_PCT, "overhead_rate_pct"
        )
        assert_money_equals(summary["overhead_cents"], 0, "overhead_cents")
        assert_money_equals(summary["total_cost_cents"], 0, "total_cost_cents")
        assert summary["completed_qty"] == 0
        assert summary["unit_cost_cents"] is None

    def test_a_completed_order_reads_the_five_step_arithmetic(self, api):
        """Material, energy, subtotal, overhead, total and a floored unit cost.

        PRD.md section 3.3: "First, material: over the order's charges in
        `status` `CONSUMED` — reached through the order's cycles — each charge
        contributes `charge_kg` multiplied by its lot's `cost_cents_per_kg`,
        **rounded half-up to whole cents per charge and only then summed** into
        `material_cost_cents`".

        PRD.md section 3.3: "Second, oven energy: over the order's cycles in
        `status` `DEMOLDED` only, each contributes `actual_oven_minutes`
        multiplied by its station's `energy_cents_per_min`, again rounded to
        whole cents per cycle before summation into `oven_energy_cost_cents`".

        PRD.md section 3.3: "Third, the pre-overhead subtotal is
        `material_cost_cents` plus `oven_energy_cost_cents`, and the overhead
        rate is the rate of the *first* tier whose ceiling is at or above that
        subtotal — 18.00 percent up to 500000 cents, 14.50 percent up to 2000000
        cents, and 11.00 percent above that."

        PRD.md section 3.3: "Fourth, `overhead_cents` is the subtotal multiplied
        by the chosen rate divided by 100, rounded half-up, and
        `total_cost_cents` is the subtotal plus overhead."

        PRD.md section 3.3: "Fifth, `unit_cost_cents` is the **floor** of
        `total_cost_cents` divided by `completed_qty` when `completed_qty` is at
        least 1, and null otherwise; because it is floored, the summed unit costs
        may fall below `total_cost_cents` and the remainder is deliberately not
        redistributed."

        PRD.md section 3.3: "Completion uses an at-or-above comparison, so
        over-production keeps the order `COMPLETE`."

        Design: Corner/endpoints/ep_production_order_cost_summary_zero_state_then_completed_state
        """
        baseline = create_plant_baseline()
        cyc, chg = _p3_identity_overrides(baseline)
        ctx = setup_sellable_units(
            baseline=baseline,
            order_overrides={"order_code": "POR-CD-COST", "ordered_qty": 2},
            cycle_overrides=cyc,
            charge_overrides=chg,
        )

        summary = validate_success(
            api.get_production_order_cost_summary(
                ctx["production_order_id"], ctx["admin_headers"]
            )
        )

        assert summary["consumed_charge_count"] == 1
        assert_money_equals(
            summary["material_cost_cents"], 5040, "material_cost_cents"
        )
        assert summary["demolded_cycle_count"] == 1
        assert_money_equals(
            summary["oven_energy_cost_cents"], 6000, "oven_energy_cost_cents"
        )
        assert_money_equals(
            summary["pre_overhead_subtotal_cents"],
            11040,
            "pre_overhead_subtotal_cents",
        )
        assert_decimal_equals(
            summary["overhead_rate_pct"], "18.00", Q_PCT, "overhead_rate_pct"
        )
        assert_money_equals(summary["overhead_cents"], 1987, "overhead_cents")
        assert_money_equals(summary["total_cost_cents"], 13027, "total_cost_cents")
        assert summary["completed_qty"] == 2
        assert_money_equals(summary["unit_cost_cents"], 6513, "unit_cost_cents")

        order = validate_success(
            api.get_production_order(
                ctx["production_order_id"], ctx["admin_headers"]
            )
        )
        assert order["status"] == "COMPLETE"
        assert_money_equals(order["unit_cost_cents"], 6513, "order unit_cost_cents")
        assert_money_equals(
            order["total_cost_cents"], 13027, "order total_cost_cents"
        )
