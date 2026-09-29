"""Derived arithmetic: the requirement variants, the waterfall, deadlines, verdicts and money."""

from test_helpers import (
    CART_CODE_CHILL,
    CART_CODE_CHILL_2,
    CLOCK_CART,
    CLOCK_LOCK,
    CLOCK_ORDERS,
    CLOCK_PLAN,
    CLOCK_PRODUCTION,
    CLOCK_QA,
    CLOCK_SETUP,
    COMPLIANCE,
    FEED,
    LM_ALICE,
    QA,
    SPEC_AN_C,
    SPEC_AN_F,
    SPEC_AN_Y,
    SUPERVISOR,
    add_flight,
    advance_to_built_cart,
    advance_to_departed,
    advance_to_issued,
    advance_to_locked,
    advance_to_planned,
    advance_to_reconciled,
    advance_to_released,
    advance_to_sealed,
    assert_decimal_equals,
    assert_instant_equals,
    assert_total_count,
    build_base,
    capture_order,
    factories as f,
    find_by,
    get_success_data,
    ingest_flight,
    load_item,
    lock_counts,
    produce_and_release,
    read_flight,
    register_airline,
    register_cart,
    register_spec,
    set_clock,
    start_batch,
    validate_paginated,
    validate_success,
)


class TestTheRequirementVariantsAndTheWaterfall:
    """From passenger counts to physical batches."""

    def test_the_load_factor_ceiling_is_taken_per_cabin_before_the_cabins_are_summed(
        self, base_env
    ):
        """Per-cabin ceilings reach 218 where one ceiling on the grand total reaches 217.

        PRD §3.2: "For each cabin the contribution is that cabin's booked passenger count multiplied by one plus the chosen specification's `load_factor_pct` divided by one hundred, with the product rounded **up** to the next whole unit."

        PRD §3.2: "`units_planned_provisional` is the sum of the three per-cabin contributions, and the rounding up happens per cabin, never once on the total."

        Design: Corner/calculations/the_load_factor_ceiling_is_applied_per_cabin_before_the_cabins_are_summed
        """
        env = base_env
        api = env.api
        flight = ingest_flight(
            api,
            env.airline_id,
            flight_number="AN423",
            tail_number="LN-FFF",
            pax_first=7,
            pax_business=23,
            pax_economy=181,
        )
        assert flight["total_pax"] == 211
        # 7 * 1.00 -> 7, 23 * 1.05 = 24.15 -> 25, 181 * 1.025 = 185.525 -> 186.
        assert flight["units_planned_provisional"] == 218
        assert flight["units_planned_provisional"] != 217

        patched = validate_success(
            api.update_pax_counts(
                flight["id"], f.pax_counts_payload(pax_economy=180), FEED
            ),
            200,
        )
        assert patched["pax_economy"] == 180
        assert patched["total_pax"] == 210
        # 181 * 1.025 = 184.5 -> 185, so the sum drops by exactly one unit.
        assert patched["units_planned_provisional"] == 217
        assert patched["status"] == "SCHEDULED"
        assert patched["version"] == 2

    def test_the_waterfall_spills_chill_into_dry_in_the_pinned_visit_order(
        self, base_env
    ):
        """Two chill specifications share one 250-unit store, and both spill into dry.

        PRD §3.4: "The requirement is expanded into demand rows of one specification and one quantity each, and those rows are visited in a single total order: first by the specification's `storage_class` in the sequence hot store, then chill store, then dry store; within a storage class by `cabin` in the sequence `FIRST`, then `BUSINESS`, then `ECONOMY`; and within that by `spec_code` ascending by ASCII comparison."

        PRD §3.4: "The waterfall is strictly first-come-first-served: an early demand row fills a store to its limit and a later row visiting the same store finds it exhausted."

        Design: Corner/calculations/zone_allocation_overflows_chill_into_dry_in_the_pinned_visit_order
        """
        env = base_env
        api = env.api
        add_flight(
            env,
            flight_number="AN421",
            tail_number="LN-DDD",
            pax_first=8,
            pax_business=24,
            pax_economy=300,
        )
        # 8 + ceil(24 * 1.05) + ceil(300 * 1.025) == 8 + 26 + 308.
        assert env.flight["units_planned_provisional"] == 342

        set_clock(api, CLOCK_ORDERS)
        vgml_id = env.specs["V"]["id"]
        for seat in ("21A", "21B", "21C"):
            capture_order(api, env.airline_id, env.flight_id, vgml_id, seat)

        set_clock(api, CLOCK_LOCK)
        lock_counts(api, env.flight_id)
        orders, meta = validate_paginated(
            api.list_special_meal_orders(FEED, {"flight_id": env.flight_id})
        )
        assert_total_count(meta, 3)
        assert [order["status"] for order in orders] == ["CONFIRMED"] * 3
        assert {order["cabin"] for order in orders} == {"ECONOMY"}

        set_clock(api, CLOCK_PLAN)
        response = api.cut_production_plan(env.flight_id, {}, SUPERVISOR)
        assert response.json()["response_type"] == "array"
        batches = get_success_data(response)
        assert len(batches) == 5
        # 8 FIRST + 24 BUSINESS + (300 - 3) standard ECONOMY + 3 special trays.
        assert read_flight(api, env.flight_id)["units_planned"] == 332

        spec_f, spec_c = env.specs["F"]["id"], env.specs["C"]["id"]
        spec_y = env.specs["Y"]["id"]
        assert [
            (b["meal_specification_id"], b["store_zone"], b["planned_qty"], b["is_overflow"])
            for b in batches
        ] == [
            (spec_f, "HOT", 8, False),
            (spec_c, "HOT", 24, False),
            (spec_y, "CHILL", 250, False),
            (spec_y, "DRY", 47, True),
            (vgml_id, "DRY", 3, True),
        ]

        _, overflow_meta = validate_paginated(
            api.list_production_batches(
                SUPERVISOR, {"flight_id": env.flight_id, "is_overflow": "true"}
            )
        )
        assert_total_count(overflow_meta, 2)

        for batch in batches[:2]:
            assert_instant_equals(
                batch["release_deadline_utc"], "2026-09-15T08:00:00Z"
            )
        for batch in batches[2:]:
            assert_instant_equals(
                batch["release_deadline_utc"], "2026-09-15T08:30:00Z"
            )

    def test_each_release_deadline_candidate_binds_on_a_different_batch(self, api):
        """One plan makes the shelf life, the slot preparation lead and the zone cutoff each bind.

        PRD §3.4: "Three candidate instants are evaluated in this order: the plan instant advanced by the specification's `shelf_life_hours`; the flight's `revised_std_utc` pulled back by an hour and a half of slot preparation lead; and the plan instant advanced by the zone cutoff for the batch's allocated `store_zone`, which is 4 hours for the hot store, 72 hours for the chill store, and 720 hours for the dry store."

        PRD §3.4: "The earliest of the three candidates wins; where candidates tie, the tied instant is the winner and the choice is unambiguous."

        Design: Corner/calculations/each_release_deadline_term_binds_on_a_different_batch_of_one_plan
        """
        set_clock(api, CLOCK_SETUP)
        airline = register_airline(api)
        spec_long = register_spec(
            api,
            airline["id"],
            SPEC_AN_F,
            spec_code="AN-F-LNG",
            portion_grams=430,
            gross_weight_grams=910,
            unit_cost_cents=4400,
            shelf_life_hours=8,
        )
        spec_short = register_spec(
            api,
            airline["id"],
            SPEC_AN_C,
            spec_code="AN-C-SHT",
            shelf_life_hours=2,
            load_factor_pct=0.00,
        )
        spec_chill = register_spec(api, airline["id"], SPEC_AN_Y)
        flight = ingest_flight(
            api,
            airline["id"],
            flight_number="AN422",
            tail_number="LN-EEE",
            pax_first=4,
            pax_business=6,
            pax_economy=10,
        )
        # 4 + 6 + ceil(10 * 1.025) == 21 before the load factor is dropped.
        assert flight["units_planned_provisional"] == 21

        set_clock(api, CLOCK_LOCK)
        lock_counts(api, flight["id"])
        set_clock(api, CLOCK_PLAN)
        batches = get_success_data(
            api.cut_production_plan(flight["id"], {}, SUPERVISOR)
        )
        assert len(batches) == 3
        assert read_flight(api, flight["id"])["units_planned"] == 20

        first = find_by(batches, meal_specification_id=spec_long["id"])
        business = find_by(batches, meal_specification_id=spec_short["id"])
        economy = find_by(batches, meal_specification_id=spec_chill["id"])
        # min(04:00 + 8h, 08:30, 04:00 + 4h) — the hot zone cutoff binds.
        assert_instant_equals(first["release_deadline_utc"], "2026-09-15T08:00:00Z")
        # min(04:00 + 2h, 08:30, 04:00 + 4h) — the two-hour shelf life binds.
        assert_instant_equals(business["release_deadline_utc"], "2026-09-15T06:00:00Z")
        # min(04:00 + 72h, 08:30, 04:00 + 72h) — the slot preparation lead binds.
        assert_instant_equals(economy["release_deadline_utc"], "2026-09-15T08:30:00Z")

        assert first["store_zone"] == "HOT"
        assert business["store_zone"] == "HOT"
        assert economy["store_zone"] == "CHILL"
        assert [b["is_overflow"] for b in batches] == [False, False, False]


class TestVerdictsAndRiskScores:
    """The kitchen's derived food-safety figures."""

    def test_a_cook_reading_passes_at_the_minimum_and_fails_one_tenth_below_it(
        self, base_env
    ):
        """75.0 exactly is a `PASS`; 74.9 holds the batch and scores it at 40.00.

        PRD §3.5: "Every comparison is inclusive at the constant, so a cook reading of exactly 75.0 is `PASS` while 74.9 is `FAIL`."

        PRD §3.5: "That score is the smaller of 100.00 and the quantity formed by weighting each failed check on the batch at 40.00 and each completed rework round at 15.00 and adding the two products together; the fail count includes every `FAIL` check on the batch regardless of `step_code` or `sequence_no`."

        Design: Corner/calculations/cook_temp_verdict_flips_one_tenth_of_a_degree_below_the_pinned_minimum
        """
        env = advance_to_planned(
            advance_to_locked(add_flight(base_env, pax_first=4, pax_economy=0))
        )
        api = env.api
        batch_id = env.batch["id"]
        assert env.batch["store_zone"] == "HOT"
        assert env.batch["planned_qty"] == 4

        set_clock(api, CLOCK_PRODUCTION)
        start_batch(api, batch_id)
        set_clock(api, CLOCK_QA)

        passing = validate_success(
            api.record_haccp_check(batch_id, f.haccp_payload("COOK_TEMP", 75.0), QA),
            201,
        )
        assert passing["verdict"] == "PASS"
        assert passing["sequence_no"] == 1
        held = validate_success(api.get_production_batch(batch_id, SUPERVISOR), 200)
        assert held["production_status"] == "IN_PRODUCTION"
        assert_decimal_equals(held["haccp_risk_score"], "0.00")

        failing = validate_success(
            api.record_haccp_check(batch_id, f.haccp_payload("COOK_TEMP", 74.9), QA),
            201,
        )
        assert failing["verdict"] == "FAIL"
        assert failing["sequence_no"] == 2

        batch = validate_success(api.get_production_batch(batch_id, SUPERVISOR), 200)
        assert batch["production_status"] == "HACCP_HOLD"
        assert batch["haccp_rework_rounds"] == 0
        # 40.00 * 1 fail + 15.00 * 0 rework rounds.
        assert_decimal_equals(batch["haccp_risk_score"], "40.00")


class TestMoneyAndDeviation:
    """Overhead, handling bands, deviation bands and penalties."""

    def test_an_uplift_with_nothing_returned_prices_in_the_lowest_handling_band(
        self, api
    ):
        """Net equals gross, and the whole net sits in the nine percent band.

        PRD §3.9: "Step one selects the handling rate from the band containing `net_cost_cents`: nine percent for a net cost from 0 up to and including 199,999 cents, seven percent from 200,000 up to and including 499,999 cents, and five percent for 500,000 cents and above."

        PRD §3.9: "Step four sets `billing_total_cents` to `net_cost_cents` plus `handling_fee_cents` plus `late_penalty_cents`."

        Design: Corner/calculations/a_small_uplift_is_priced_in_the_lowest_handling_band
        """
        env = build_base(api)
        add_flight(env, pax_economy=100)
        advance_to_released(advance_to_planned(advance_to_locked(env)))
        advance_to_departed(
            advance_to_issued(advance_to_sealed(advance_to_built_cart(env)))
        )
        advance_to_reconciled(env, consumed_units=100, returned_units=0)

        record = env.uplift
        assert record["uplifted_units"] == 100
        assert record["consumed_units"] == 100
        assert record["returned_units"] == 0
        assert record["unused_units"] == 0
        # round_half_up(100 * 1450 * 1.12).
        assert record["gross_cost_cents"] == 162400
        assert record["net_cost_cents"] == 162400
        # round_half_up(162400 * 0.09).
        assert record["handling_fee_cents"] == 14616
        assert record["late_penalty_cents"] == 0
        assert record["billing_total_cents"] == 177016
        assert record["cost_per_pax_cents"] == 1624
        assert read_flight(api, env.flight_id)["status"] == "RECONCILED"

    def test_a_forty_unit_shortfall_lands_in_the_critical_deviation_band(self, api):
        """22.22 percent clears the open-ended `CRITICAL` band and the net re-tiers the fee.

        PRD §3.9: "The severity band is inclusive at its lower bound: a deviation from 5.00 up to and including 9.99 is `MINOR`, from 10.00 up to and including 19.99 is `MAJOR`, and 20.00 or above is `CRITICAL`."

        PRD §3.9: "The specification's deviation is the absolute difference between delivered and required, divided by required, multiplied by one hundred, and rounded half up to two decimals."

        Design: Corner/calculations/a_forty_unit_shortfall_lands_in_the_critical_deviation_band
        """
        env = build_base(api)
        add_flight(env)
        advance_to_planned(advance_to_locked(env))
        produce_and_release(
            api,
            env.batch,
            list(SPEC_AN_Y["required_haccp_steps"]),
            produced_qty=140,
        )
        env.reload_batches()
        assert env.batch["produced_qty"] == 140
        assert env.batch["scrapped_qty"] == 40

        advance_to_built_cart(env, qty_units=140)
        advance_to_departed(advance_to_issued(advance_to_sealed(env)))
        advance_to_reconciled(env, consumed_units=140, returned_units=0)

        record = env.uplift
        # round_half_up(abs(140 - 180) / 180 * 100, 2).
        assert_decimal_equals(record["spec_deviation_pct"], "22.22")
        assert record["gross_cost_cents"] == 227360
        assert record["net_cost_cents"] == 227360
        # 227360 sits in the 200000..499999 band, so the rate is 0.07.
        assert record["handling_fee_cents"] == 15915
        assert record["billing_total_cents"] == 243275
        assert record["cost_per_pax_cents"] == 1263

        findings, meta = validate_paginated(
            api.list_audit_findings(COMPLIANCE, {"flight_id": env.flight_id})
        )
        assert_total_count(meta, 1)
        finding = findings[0]
        assert finding["finding_type"] == "SPEC_DEVIATION"
        assert finding["severity"] == "CRITICAL"
        assert finding["source"] == "SYSTEM"
        # 120000 * 5.0.
        assert finding["penalty_cents"] == 600000
        assert finding["status"] == "OPEN"

        airline = env.reload_airline()
        assert airline["open_finding_count"] == 1
        assert airline["penalty_accrued_cents"] == 0
        assert airline["status"] == "ACTIVE"

    def test_voided_cart_items_leave_the_cost_report_input_set_entirely(
        self, released_env
    ):
        """The report reads `ACTIVE` items only, so voiding twenty units moves both figures.

        PRD §3.9: "First, each `ACTIVE` cart item's overhead-loaded gross is computed exactly as for `gross_cost_cents`: `qty_units` times the specification's `unit_cost_cents` times one plus the twelve percent overhead, rounded half up."

        PRD §3.6: "`VOID` items are excluded from every unit and cost aggregate in the service."

        Design: Corner/calculations/voided_cart_items_leave_the_cost_report_input_set_entirely
        """
        env = released_env
        api = env.api
        set_clock(api, CLOCK_CART)
        cart_a = register_cart(api, env.flight_id, cart_code=CART_CODE_CHILL)
        cart_b = register_cart(
            api,
            env.flight_id,
            cart_code=CART_CODE_CHILL_2,
            cart_type="STD_HALF",
            capacity_units=100,
            galley_position="G2",
        )
        load_item(api, cart_a["id"], env.batch["id"], 160)
        item_small = load_item(api, cart_b["id"], env.batch["id"], 20)

        first = validate_success(api.get_cost_report(env.flight_id, COMPLIANCE), 200)
        assert first["total_pax"] == 180
        # 259840 for the 160-unit item plus 32480 for the 20-unit item.
        assert first["gross_cost_cents"] == 292320
        assert first["cost_per_pax_cents"] == 1624
        assert_decimal_equals(first["spec_deviation_pct"], "0.00")
        assert first["cost_cap_per_pax_cents"] == 6000
        assert first["cap_breached"] is False
        # The two empty cabins are still reported, each with `cabin_pax` 0, and are
        # excluded from the blend — which is why the blend equals the economy figure.
        assert sorted(entry["cabin_pax"] for entry in first["cabin_breakdown"]) == [
            0,
            0,
            180,
        ]

        validate_success(
            api.void_cart_item(cart_b["id"], item_small["id"], LM_ALICE), 200
        )

        second = validate_success(api.get_cost_report(env.flight_id, COMPLIANCE), 200)
        assert second["gross_cost_cents"] == 259840
        # round_half_up(259840 / 180).
        assert second["cost_per_pax_cents"] == 1444
        # round_half_up(abs(160 - 180) / 180 * 100, 2) — the MAJOR band, but a read raises nothing.
        assert_decimal_equals(second["spec_deviation_pct"], "11.11")
        assert second["cost_cap_per_pax_cents"] == 6000
        assert second["cap_breached"] is False

        _, meta = validate_paginated(
            api.list_audit_findings(COMPLIANCE, {"flight_id": env.flight_id})
        )
        assert_total_count(meta, 0)
        assert read_flight(api, env.flight_id)["units_planned"] == 180

    def test_finding_penalties_are_the_product_of_the_pinned_constants(self, flight_env):
        """Two constant tables, two frozen penalties, and an untouched accrual.

        PRD §3.10: "Each type carries a base amount — 120,000 cents for a specification deviation, 500,000 cents for a HACCP breach, 200,000 cents for a seal mismatch, and 80,000 cents for a late delivery — and each severity carries a multiplier: one for `MINOR`, two and a half for `MAJOR`, and five for `CRITICAL`."

        PRD §3.10: "`penalty_cents` is the base multiplied by the multiplier, rounded half up to whole cents."

        Design: Corner/calculations/finding_penalties_are_the_product_of_the_pinned_base_and_severity_constants
        """
        env = flight_env
        api = env.api
        breach = validate_success(
            api.create_audit_finding(
                f.finding_payload(
                    env.airline_id,
                    env.flight_id,
                    "HACCP_BREACH",
                    "CRITICAL",
                    evidence_ref="QA-LOG-77",
                ),
                COMPLIANCE,
            ),
            201,
        )
        # 500000 * 5.0.
        assert breach["penalty_cents"] == 2500000
        assert breach["status"] == "OPEN"
        assert breach["source"] == "SYSTEM"

        mismatch = validate_success(
            api.create_audit_finding(
                f.finding_payload(
                    env.airline_id, env.flight_id, "SEAL_MISMATCH", "MAJOR"
                ),
                COMPLIANCE,
            ),
            201,
        )
        # 200000 * 2.5.
        assert mismatch["penalty_cents"] == 500000
        assert mismatch["status"] == "OPEN"
        assert mismatch["source"] == "SYSTEM"

        airline = env.reload_airline()
        assert airline["open_finding_count"] == 2
        assert airline["penalty_accrued_cents"] == 0
        assert airline["status"] == "ACTIVE"
        assert read_flight(api, env.flight_id)["production_hold"] is False
