"""Where one input feeds two different formula variants, and where a composed formula's step order is observable."""

from test_helpers import (
    CART_CODE_CHILL,
    CART_CODE_HOT,
    CLOCK_CART,
    CLOCK_ORDERS,
    CLOCK_UPLIFT,
    COMPLIANCE,
    EVENT_ARRIVE,
    EVENT_DELIVER,
    EVENT_DISPATCH,
    SPEC_AN_C,
    SPEC_AN_F,
    SPEC_AN_V,
    SPEC_AN_Y,
    add_flight,
    advance_to_departed,
    advance_to_issued,
    advance_to_locked,
    advance_to_planned,
    advance_to_released,
    assert_decimal_equals,
    assert_instant_equals,
    assert_total_count,
    blended_cost_per_pax_cents,
    blended_unit_rate_cents,
    build_base,
    cabin_cost_per_pax_cents,
    capture_order,
    factories as f,
    handling_fee_cents,
    item_gross_cents,
    lateness_penalty_cents,
    load_item,
    produce_and_release,
    read_cart,
    read_flight,
    reconcile,
    record_dispositions,
    register_cart,
    reserve_run,
    run_event,
    seal_cart,
    set_clock,
    sign_off_build,
    validate_paginated,
    validate_success,
)

CLOCK_ARRIVE_LATE = "2026-09-15T08:40:00Z"
SEAT_ROW = ("31A", "31B", "31C")


def _cabin_figures(entry):
    """The money figures of one `cabin_breakdown` entry, whatever it names them."""
    return {
        value
        for key, value in entry.items()
        if key not in ("cabin", "cabin_pax") and isinstance(value, int)
    }


def _mixed_cabin_flight(api):
    """AN412 with 7 FIRST, 23 BUSINESS, 181 ECONOMY and three timely VGML orders."""
    env = build_base(api)
    add_flight(
        env,
        flight_number="AN412",
        tail_number="LN-BBB",
        pax_first=7,
        pax_business=23,
        pax_economy=181,
    )
    set_clock(api, CLOCK_ORDERS)
    env.orders = [
        capture_order(api, env.airline_id, env.flight_id, env.specs["V"]["id"], seat)
        for seat in SEAT_ROW
    ]
    return env


def _mixed_cabin_flight_loaded(api):
    """The same flight with all four batches released and loaded into two carts."""
    env = _mixed_cabin_flight(api)
    advance_to_locked(env)
    advance_to_planned(env)
    for batch, spec in zip(
        env.batches, (SPEC_AN_F, SPEC_AN_C, SPEC_AN_Y, SPEC_AN_V)
    ):
        produce_and_release(env.api, batch, list(spec["required_haccp_steps"]))
    env.reload_batches()

    api = env.api
    set_clock(api, CLOCK_CART)
    hot = register_cart(
        api,
        env.flight_id,
        cart_code=CART_CODE_HOT,
        cart_type="OVEN_RACK",
        storage_class="HOT",
        capacity_units=40,
        galley_position="G1",
    )
    chill = register_cart(
        api,
        env.flight_id,
        cart_code=CART_CODE_CHILL,
        cart_type="STD_FULL",
        storage_class="CHILL",
        capacity_units=200,
        galley_position="G2",
    )
    env.carts.extend([hot, chill])
    load_item(api, hot["id"], env.batches[0]["id"], 7)
    load_item(api, hot["id"], env.batches[1]["id"], 23)
    load_item(api, chill["id"], env.batches[2]["id"], 178)
    load_item(api, chill["id"], env.batches[3]["id"], 3)
    env.reload_flight()
    return env


def _business_flight_at_aircraft(api):
    """AN414 with 112 BUSINESS trays uplifted and its single run standing at the stand."""
    env = build_base(api)
    add_flight(
        env,
        flight_number="AN414",
        tail_number="LN-CCC",
        pax_business=112,
        pax_economy=0,
    )
    advance_to_locked(env)
    advance_to_planned(env)
    assert len(env.batches) == 1
    produce_and_release(env.api, env.batch, list(SPEC_AN_C["required_haccp_steps"]))
    env.reload_batches()

    api_ = env.api
    set_clock(api_, CLOCK_CART)
    cart = register_cart(
        api_,
        env.flight_id,
        cart_code=CART_CODE_HOT,
        cart_type="OVEN_RACK",
        storage_class="HOT",
        capacity_units=120,
        galley_position="G1",
    )
    env.carts.append(cart)
    env.items.append(load_item(api_, cart["id"], env.batch["id"], 112))
    env.carts[0] = sign_off_build(api_, cart["id"])
    env.carts[0] = seal_cart(api_, cart["id"], "SEAL-AN414-01")
    advance_to_issued(env)
    run = reserve_run(api_, env.manifest["id"], env.truck["id"], env.stand["id"])
    env.runs.append(run)
    set_clock(api_, "2026-09-15T07:25:00Z")
    run_event(api_, run["id"], EVENT_DISPATCH)
    set_clock(api_, CLOCK_ARRIVE_LATE)
    run_event(api_, run["id"], EVENT_ARRIVE)
    return env


class TestTheTwoUpliftCostVariants:
    """`GROSS_UPLIFTED` at reconciliation, `NET_CONSUMED` at disposition."""

    def test_a_bonded_reconciliation_prices_the_whole_uplift_at_the_gross_variant(
        self, reconciled_env
    ):
        """The DRAFT record carries no credit at all, so net equals gross exactly.

        PRD §3.9: "Reconciliation also derives `cost_per_pax_cents` — a snapshot of the flight's own figure — `spec_deviation_pct`, `late_penalty_cents`, `handling_fee_cents` and `billing_total_cents`, and it sets `net_cost_cents` equal to `gross_cost_cents`, because no unit has yet been dispositioned."

        PRD §3.9: "For each `ACTIVE` cart item of the flight, taken in `created_at` ascending order, the item's overhead-loaded gross is its `qty_units` multiplied by its specification's `unit_cost_cents`, multiplied by one plus a twelve percent overhead rate, with that product rounded half up to whole cents."

        Design: Difficulty/dual_variant_calc/bonded_uplift_net_cost_cannot_diverge_from_gross_uplifted
        """
        record = reconciled_env.uplift
        assert record["status"] == "DRAFT"
        assert record["uplifted_units"] == 180
        assert record["consumed_units"] == 170
        assert record["returned_units"] == 10
        assert record["unused_units"] == 10

        assert record["gross_cost_cents"] == 292320 == item_gross_cents(180, 1450)
        assert record["net_cost_cents"] == 292320
        assert record["handling_fee_cents"] == 20462 == handling_fee_cents(292320)
        assert record["billing_total_cents"] == 312782
        assert record["late_penalty_cents"] == 0
        assert record["seal_mismatch_count"] == 0
        assert_decimal_equals(record["spec_deviation_pct"], "0.00")
        assert record["cost_per_pax_cents"] == 1624

    def test_a_bonded_disposition_cannot_move_the_net_cost_off_the_gross(
        self, dispositioned_env
    ):
        """Destruction earns nothing, so the credit basis of a bonded record is always zero.

        PRD §3.9: "Because a `BONDED` airline's dispositions must be entirely destruction, its credit basis is always zero and its `net_cost_cents` can never diverge from `gross_cost_cents` — while an otherwise identical `DOMESTIC` airline's does."

        Design: Difficulty/dual_variant_calc/bonded_uplift_net_cost_cannot_diverge_from_gross_uplifted
        """
        env = dispositioned_env
        record = env.reload_uplift()
        assert record["status"] == "DISPOSITIONED"
        assert record["net_cost_cents"] == record["gross_cost_cents"] == 292320
        assert record["gross_cost_cents"] - record["net_cost_cents"] == 0
        # The band containing 292,320 cents is unmoved by the disposition.
        assert record["handling_fee_cents"] == 20462
        assert record["billing_total_cents"] == 312782

        line = record["lines"][0]
        assert line["reuse_units"] == 0
        assert line["donate_units"] == 0
        assert line["destroy_units"] == 10
        assert env.reload_batches()[0]["production_status"] == "DISPOSED"

    def test_a_domestic_disposition_credits_reuse_and_donate_at_the_once_rounded_blend(
        self, api
    ):
        """Identical uplift inputs, and the credit drops the net by exactly 4,872 cents.

        PRD §3.9: "First the blended unit rate is derived once: `gross_cost_cents` divided by `uplifted_units`, rounded half up to whole cents — and rounded exactly once, not per line."

        PRD §3.9: "The credit is that credit basis multiplied by the blended rate, multiplied by the airline's `unused_recovery_rate_pct` divided by one hundred, rounded half up to whole cents."

        Design: Difficulty/dual_variant_calc/domestic_uplift_net_cost_credits_reuse_and_donate_at_the_weighted_rate
        """
        env = _domestic_flight_reconciled(api)
        draft = env.uplift
        # Byte-identical uplift input to the BONDED instance.
        assert draft["gross_cost_cents"] == 292320
        assert draft["net_cost_cents"] == 292320
        assert draft["handling_fee_cents"] == 20462

        record = record_dispositions(
            api,
            draft["id"],
            [f.disposition_line(env.specs["Y"]["id"], 7, 3, 0)],
        )
        assert blended_unit_rate_cents(292320, 180) == 1624
        assert record["net_cost_cents"] == 287448
        # 10 credited units at 1,624 cents and a 30.00 percent recovery rate.
        assert draft["gross_cost_cents"] - record["net_cost_cents"] == 4872
        # Re-derived from the NET figure, not from 292,320.
        assert record["handling_fee_cents"] == 20121 == handling_fee_cents(287448)
        assert record["billing_total_cents"] == 307569
        assert record["status"] == "DISPOSITIONED"
        assert env.reload_batches()[0]["production_status"] == "RELEASED"

    def test_destroyed_units_earn_no_credit_even_under_a_domestic_regime(self, api):
        """Same airline, same rate, and a wholly destructive disposition credits nothing.

        PRD §3.9: "Then the credit basis is the sum across lines of `reuse_units` plus `donate_units`; destroyed units earn nothing."

        Design: Difficulty/dual_variant_calc/domestic_uplift_net_cost_credits_reuse_and_donate_at_the_weighted_rate
        """
        env = _domestic_flight_reconciled(api)
        assert env.airline["waste_regime"] == "DOMESTIC"
        record = record_dispositions(
            api,
            env.uplift["id"],
            [f.disposition_line(env.specs["Y"]["id"], 0, 0, 10)],
        )
        assert record["net_cost_cents"] == 292320
        assert record["net_cost_cents"] == record["gross_cost_cents"]
        assert record["handling_fee_cents"] == 20462
        assert record["billing_total_cents"] == 312782
        assert record["status"] == "DISPOSITIONED"
        # Destroyed units do move the batch, even though they earn no credit.
        assert env.reload_batches()[0]["production_status"] == "DISPOSED"


class TestTheTwoMealRequirementVariants:
    """The provisional estimate and the final requirement on one passenger mix."""

    def test_the_provisional_variant_uplifts_by_load_factor_and_ignores_special_orders(
        self, api
    ):
        """218 units, and capturing three special orders does not move the figure.

        PRD §3.2: "For each cabin the contribution is that cabin's booked passenger count multiplied by one plus the chosen specification's `load_factor_pct` divided by one hundred, with the product rounded **up** to the next whole unit."

        PRD §3.3: "Capture deliberately leaves `units_planned_provisional` alone, because the provisional variant ignores special orders by design."

        Design: Difficulty/dual_variant_calc/provisional_and_final_meal_requirement_diverge_on_load_factor_and_special_meals
        """
        env = _mixed_cabin_flight(api)
        flight = read_flight(api, env.flight_id)
        assert flight["total_pax"] == 211
        # 7 at 0.00 percent, 25 at 5.00 percent and 186 at 2.50 percent.
        assert flight["units_planned_provisional"] == 218
        assert_instant_equals(
            flight["special_meal_cutoff_utc"], "2026-09-14T22:00:00Z"
        )
        assert flight["units_planned"] == 0
        assert [order["status"] for order in env.orders] == ["REQUESTED"] * 3

    def test_the_final_variant_drops_the_load_factor_and_swaps_one_tray_per_order(
        self, api
    ):
        """211 units, seven fewer than the estimate, split across four batches.

        PRD §3.4: "`units_planned` is therefore the sum across cabins of the standard-tray demand plus the total count of `CONFIRMED` orders on the flight."

        PRD §3.4: "The **final requirement** differs from the provisional one on two independent axes at once: it applies no load factor whatsoever, and it substitutes one special tray for one standard tray in the ordering passenger's cabin."

        Design: Difficulty/dual_variant_calc/provisional_and_final_meal_requirement_diverge_on_load_factor_and_special_meals
        """
        env = _mixed_cabin_flight(api)
        advance_to_locked(env)
        confirmed = [
            validate_success(
                api.get_special_meal_order(order["id"], env.rep_headers), 200
            )
            for order in env.orders
        ]
        assert [order["status"] for order in confirmed] == ["CONFIRMED"] * 3

        advance_to_planned(env)
        flight = env.flight
        assert flight["status"] == "PLANNED"
        # 7 + 23 + (181 - 3) standard trays plus the three special trays.
        assert flight["units_planned"] == 211
        assert flight["units_planned_provisional"] - flight["units_planned"] == 7

        batches = env.batches
        assert len(batches) == 4
        assert [batch["planned_qty"] for batch in batches] == [7, 23, 178, 3]
        assert [batch["store_zone"] for batch in batches] == [
            "HOT",
            "HOT",
            "CHILL",
            "CHILL",
        ]
        assert [batch["meal_specification_id"] for batch in batches] == [
            env.specs["F"]["id"],
            env.specs["C"]["id"],
            env.specs["Y"]["id"],
            env.specs["V"]["id"],
        ]
        assert all(batch["is_overflow"] is False for batch in batches)
        assert all(batch["production_status"] == "PLANNED" for batch in batches)
        assert_instant_equals(
            batches[2]["release_deadline_utc"], "2026-09-15T08:30:00Z"
        )
        assert_instant_equals(
            batches[0]["release_deadline_utc"], "2026-09-15T08:00:00Z"
        )


class TestTheBlendedCostPerPassenger:
    """Four non-commuting steps, and the two rounding stages that cannot be collapsed."""

    def test_the_report_rounds_each_cabin_before_blending_them(self, api):
        """2,029 cents, one above the 2,028 a single division of the total would give.

        PRD §3.9: "Third — the first rounding — each included cabin's per-passenger cost is that cabin's cost divided by that cabin's booked passenger count, rounded half up to whole cents. Fourth — the second and final rounding — `cost_per_pax_cents` is the sum, across included cabins, of each cabin's rounded per-passenger cost multiplied by that cabin's passenger count, divided by `total_pax`, rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/cost_per_passenger_rounds_per_cabin_before_blending_not_after
        """
        env = _mixed_cabin_flight_loaded(api)
        report = validate_success(api.get_cost_report(env.flight_id, COMPLIANCE), 200)
        assert report["flight_id"] == env.flight_id
        assert report["total_pax"] == 211
        assert report["cost_cap_per_pax_cents"] == 6000
        assert report["gross_cost_cents"] == 428008
        assert (
            item_gross_cents(7, 4200)
            + item_gross_cents(23, 3900)
            + item_gross_cents(178, 1450)
            + item_gross_cents(3, 1650)
            == 428008
        )

        breakdown = report["cabin_breakdown"]
        assert [entry["cabin"] for entry in breakdown] == [
            "FIRST",
            "BUSINESS",
            "ECONOMY",
        ]
        assert [entry["cabin_pax"] for entry in breakdown] == [7, 23, 181]
        assert _cabin_figures(breakdown[0]) == {32928, 4704}
        assert _cabin_figures(breakdown[1]) == {100464, 4368}
        assert _cabin_figures(breakdown[2]) == {294616, 1628}
        assert cabin_cost_per_pax_cents(294616, 181) == 1628

        assert report["cost_per_pax_cents"] == 2029 == blended_cost_per_pax_cents(
            [(4704, 7), (4368, 23), (1628, 181)], 211
        )
        # 2,028 is round_half_up(428008 / 211) — collapsing both roundings into one.
        assert report["cost_per_pax_cents"] != 2028
        assert report["cap_breached"] is False
        assert_decimal_equals(report["spec_deviation_pct"], "0.00")
        assert read_flight(api, env.flight_id)["cost_per_pax_cents"] == 2029

    def test_a_cabin_with_no_passengers_is_reported_but_kept_out_of_the_blend(
        self, released_env
    ):
        """One populated cabin, so the blend collapses onto that cabin's own figure.

        PRD §3.9: "Each `cabin_breakdown` entry reports its cabin's `cabin_pax` count alongside that cabin's cost and rounded per-passenger cost; a cabin whose passenger count is 0 is reported with `cabin_pax` 0 and is excluded from the blend."

        Design: Difficulty/combinatorial_formula/cost_per_passenger_rounds_per_cabin_before_blending_not_after
        """
        env = released_env
        api = env.api
        set_clock(api, CLOCK_CART)
        cart = register_cart(api, env.flight_id, cart_code=CART_CODE_CHILL)
        load_item(api, cart["id"], env.batch["id"], 180)

        report = validate_success(api.get_cost_report(env.flight_id, COMPLIANCE), 200)
        assert report["total_pax"] == 180
        assert report["gross_cost_cents"] == 292320
        breakdown = report["cabin_breakdown"]
        assert [entry["cabin"] for entry in breakdown] == [
            "FIRST",
            "BUSINESS",
            "ECONOMY",
        ]
        assert [entry["cabin_pax"] for entry in breakdown] == [0, 0, 180]
        assert _cabin_figures(breakdown[2]) == {292320, 1624}

        # The two empty cabins contribute to neither numerator nor denominator.
        assert report["cost_per_pax_cents"] == 1624 == cabin_cost_per_pax_cents(
            292320, 180
        )
        assert report["cap_breached"] is False


class TestTheBillingComposition:
    """The handling band, the marginal lateness schedule, and the order they run in."""

    def test_the_handling_band_is_keyed_on_the_net_cost_alone(self, api):
        """489,216 cents selects seven percent even though the billed total crosses 500,000.

        PRD §3.9: "Step one selects the handling rate from the band containing `net_cost_cents`: nine percent for a net cost from 0 up to and including 199,999 cents, seven percent from 200,000 up to and including 499,999 cents, and five percent for 500,000 cents and above."

        PRD §3.9: "The band is selected before the late penalty is added and is never re-selected afterwards: with a net cost of 489,216 cents and a late penalty of 11,500 cents, the seven percent band applies, giving a handling fee of 34,245 cents and a billing total of 534,961 cents — whereas keying the band on the 500,716-cent combined figure would wrongly select five percent and give 24,461 and 525,177."

        Design: Difficulty/combinatorial_formula/handling_tier_is_keyed_on_net_cost_before_the_late_penalty_is_added
        """
        env = _business_flight_at_aircraft(api)
        api_ = env.api
        set_clock(api_, "2026-09-15T08:50:00Z")
        delivered = run_event(api_, env.run["id"], EVENT_DELIVER)
        assert delivered["lateness_minutes"] == 50
        assert delivered["penalty_cents"] == 11500 == lateness_penalty_cents(40)

        set_clock(api_, CLOCK_UPLIFT)
        record = reconcile(
            api_,
            env.flight_id,
            [f.uplift_line(env.specs["C"]["id"], 112, 0)],
        )
        assert record["gross_cost_cents"] == 489216 == item_gross_cents(112, 3900)
        assert record["net_cost_cents"] == 489216
        assert record["handling_fee_cents"] == 34245 == handling_fee_cents(489216)
        # 24,461 is five percent of the net — the band the combined figure would pick.
        assert record["handling_fee_cents"] != 24461
        assert record["late_penalty_cents"] == 11500
        assert record["billing_total_cents"] == 534961
        assert record["billing_total_cents"] != 525177
        assert record["cost_per_pax_cents"] == 4368
        assert_decimal_equals(record["spec_deviation_pct"], "0.00")
        assert read_flight(api_, env.flight_id)["status"] == "RECONCILED"

    def test_the_same_net_cost_buys_the_same_handling_fee_with_no_penalty_at_all(
        self, api
    ):
        """Removing the lateness leaves the fee untouched and only the total moves.

        PRD §3.9: "Step four sets `billing_total_cents` to `net_cost_cents` plus `handling_fee_cents` plus `late_penalty_cents`."

        Design: Difficulty/combinatorial_formula/handling_tier_is_keyed_on_net_cost_before_the_late_penalty_is_added
        """
        env = _business_flight_at_aircraft(api)
        api_ = env.api
        set_clock(api_, "2026-09-15T07:55:00Z")
        delivered = run_event(api_, env.run["id"], EVENT_DELIVER)
        assert delivered["lateness_minutes"] == 0
        assert delivered["penalty_cents"] == 0

        set_clock(api_, CLOCK_UPLIFT)
        record = reconcile(
            api_,
            env.flight_id,
            [f.uplift_line(env.specs["C"]["id"], 112, 0)],
        )
        assert record["net_cost_cents"] == 489216
        # The identical fee, from the identical net figure.
        assert record["handling_fee_cents"] == 34245
        assert record["late_penalty_cents"] == 0
        assert record["billing_total_cents"] == 523461 == 489216 + 34245
        _, meta = validate_paginated(
            api_.list_audit_findings(COMPLIANCE, {"flight_id": env.flight_id})
        )
        assert_total_count(meta, 0)

    def test_lateness_prices_each_band_marginally_not_at_a_single_rate(self, api):
        """37 billable minutes cost 10,300 cents, not the 14,800 of flat banding.

        PRD §3.7: "`penalty_cents` then prices those billable minutes **marginally** across three bands: the first thirty billable minutes at 250 cents each, the next thirty — those from the thirty-first up to and including the sixtieth — at 400 cents each, and every billable minute beyond the sixtieth at 600 cents each."

        PRD §3.7: "**Delivery** moves the run `AT_AIRCRAFT → DELIVERED`, sets `delivered_at_utc` to the logical clock, and evaluates the lateness penalty into `lateness_minutes` and `penalty_cents`."

        Design: Difficulty/combinatorial_formula/delivery_lateness_prices_each_band_marginally_not_at_a_single_rate
        """
        env = _business_flight_at_aircraft(api)
        api_ = env.api
        set_clock(api_, "2026-09-15T08:47:00Z")
        delivered = run_event(api_, env.run["id"], EVENT_DELIVER)
        assert delivered["status"] == "DELIVERED"
        assert_instant_equals(delivered["delivered_at_utc"], "2026-09-15T08:47:00Z")
        assert delivered["lateness_minutes"] == 47
        # 47 less the ten-minute grace: thirty at 250 plus seven at 400.
        assert delivered["penalty_cents"] == 10300 == lateness_penalty_cents(37)
        assert delivered["penalty_cents"] != 14800

        findings, meta = validate_paginated(
            api_.list_audit_findings(COMPLIANCE, {"flight_id": env.flight_id})
        )
        assert_total_count(meta, 1)
        assert findings[0]["finding_type"] == "LATE_DELIVERY"
        assert findings[0]["severity"] == "MINOR"
        assert findings[0]["source"] == "SYSTEM"
        assert findings[0]["penalty_cents"] == 80000
        assert findings[0]["status"] == "OPEN"

        airline = env.reload_airline()
        assert airline["open_finding_count"] == 1
        assert airline["penalty_accrued_cents"] == 0
        assert airline["status"] == "ACTIVE"
        assert read_flight(api_, env.flight_id)["status"] == "DEPARTED"
        assert read_cart(api_, env.cart["id"])["build_status"] == "LOADED"

    def test_the_third_band_prices_only_the_minutes_beyond_the_sixtieth(self, api):
        """70 billable minutes cross all three bands and cost 25,500 cents.

        PRD §3.7: "Each band prices only the minutes that fall inside it; the total is not priced at the single rate of the band it happens to land in."

        Design: Difficulty/combinatorial_formula/delivery_lateness_prices_each_band_marginally_not_at_a_single_rate
        """
        env = _business_flight_at_aircraft(api)
        api_ = env.api
        set_clock(api_, "2026-09-15T09:20:00Z")
        delivered = run_event(api_, env.run["id"], EVENT_DELIVER)
        assert delivered["lateness_minutes"] == 80
        # 70 billable minutes: 30 at 250, 30 at 400, then 10 at 600.
        assert delivered["penalty_cents"] == 25500 == lateness_penalty_cents(70)
        assert delivered["penalty_cents"] != 70 * 600
        assert delivered["status"] == "DELIVERED"


def _domestic_flight_reconciled(api):
    """SB222 under a DOMESTIC regime, reconciled with 170 consumed and 10 returned."""
    env = build_base(
        api,
        name="Sunbridge Airways",
        iata_code="SB",
        waste_regime="DOMESTIC",
        cost_cap_per_pax_cents=6000,
    )
    add_flight(env, flight_number="SB222", tail_number="SE-BBB")
    advance_to_locked(env)
    advance_to_planned(env)
    advance_to_released(env)
    api_ = env.api
    set_clock(api_, CLOCK_CART)
    cart = register_cart(api_, env.flight_id, cart_code=CART_CODE_CHILL)
    env.carts.append(cart)
    env.items.append(load_item(api_, cart["id"], env.batch["id"], 180))
    env.carts[0] = sign_off_build(api_, cart["id"])
    env.carts[0] = seal_cart(api_, cart["id"], "SEAL-SB222-01")
    advance_to_issued(env)
    advance_to_departed(env)
    set_clock(api_, CLOCK_UPLIFT)
    env.uplift = reconcile(
        api_, env.flight_id, [f.uplift_line(env.specs["Y"]["id"], 170, 10)]
    )
    env.reload_flight()
    return env
