"""Buying a garment out of the box: two ageing variants, the pinned rounding order,
the quote TTL and the concurrency guard that sits above the settlement gate."""

from test_helpers import (
    ADMIN,
    BILLING,
    ApiErrorId,
    assert_buy_out_order,
    assert_same_instant,
    confirm_grade,
    find_rental_assessment,
    get_box_item,
    get_buy_out_order,
    get_cycle,
    list_buy_out_orders,
    make_member_headers,
    mint_buy_out_quote,
    set_clock,
    setup_basic_delivered_scenario,
    setup_returned_items,
    submit_grade,
    validate_error,
    validate_paginated,
    validate_success,
)


def _delivered_item(sku, retail_price_cents=5000, acquired_at="2026-04-01T00:00:00Z",
                    current_grade="A", cycles_completed=0, late_fee_mode=None,
                    slots_per_box=1, monthly_fee_cents=5000):
    plan = {"slots_per_box": slots_per_box, "swaps_per_cycle": 1,
            "monthly_fee_cents": monthly_fee_cents}
    if late_fee_mode:
        plan["late_fee_mode"] = late_fee_mode
    return setup_basic_delivered_scenario(
        plan=plan,
        member={"child_size_code": "5"},
        style={"sku": sku, "name": "Buyout Style", "size_code": "5",
               "retail_price_cents": retail_price_cents},
        unit={"acquired_at": acquired_at, "current_grade": current_grade,
              "cycles_completed": cycles_completed},
        unit_count=slots_per_box,
    )


class TestBuyOutPriceVariants:
    def _two_identical_units(self, sku):
        return setup_basic_delivered_scenario(
            plan={"tier": "CORE", "slots_per_box": 2, "swaps_per_cycle": 2,
                  "monthly_fee_cents": 8900, "discount_pct": 0},
            member={"child_size_code": "5", "protection_enrolled": False,
                    "auto_apply_credit": False},
            style={"sku": sku, "name": "Play Set", "size_code": "5",
                   "retail_price_cents": 6000, "brand_tier": "STANDARD",
                   "season": "ALL_SEASON", "category": "TOP"},
            unit={"acquired_at": "2025-11-01T00:00:00Z", "current_grade": "B",
                  "cycles_completed": 5},
            unit_count=2,
        )

    def test_the_cycles_worn_variant_decays_on_wear(self, api):
        """PRD §3.7: "The base price is the unit's style `retail_price_cents`
        multiplied by the base rate for the unit's `current_grade`:
        `BUYOUT_BASE_RATE_BY_GRADE` gives 0.62 for `A`, 0.50 for `B`, 0.38 for
        `C` and 0.22 for `D`."
        PRD §3.7: "Under the `CYCLES_WORN` variant the decay factor is one minus
        the unit's `cycles_completed` multiplied by
        `BUYOUT_CYCLE_DECAY_PER_CYCLE`, 0.04 — so a garment worn through six
        cycles has lost 24 percent regardless of how long the service has owned
        it."
        PRD §3.7: "The raw price is the graded base multiplied by the floored
        decay factor, and `quoted_price_cents` is that raw price rounded **half
        up to the nearest 25 cents**, the step fixed by
        `BUYOUT_ROUNDING_STEP_CENTS`."
        PRD §3.7: "If the item is already late — its `days_late` is greater than
        zero — a `late_surcharge_cents` of 10 percent of `quoted_price_cents`,
        rounded half up, is added; otherwise `late_surcharge_cents` is 0."

        Design: Difficulty/dual_variant_calc/buyout_price_cycles_worn_vs_months_held
        """
        scenario = self._two_identical_units("SKU-BO-1")
        member, first_item = scenario["member"], scenario["items"][0]

        order = mint_buy_out_quote(member["id"], first_item["id"], "CYCLES_WORN")
        assert_buy_out_order(order)
        assert order["quoted_price_cents"] == 2400
        assert order["late_surcharge_cents"] == 0
        assert order["final_price_cents"] == 2400
        assert order["status"] == "QUOTED"

    def test_the_months_held_variant_decays_on_tenure(self, api):
        """PRD §3.7: "Under the `MONTHS_HELD` variant the decay factor is one
        minus the number of whole months between the unit's `acquired_at` and
        the logical clock, multiplied by `BUYOUT_MONTH_DECAY_PER_MONTH`, 0.015 —
        so a garment acquired six months ago has lost 9 percent regardless of
        how often it has been worn."
        PRD §3.7: "The two variants price the *same* unit differently on
        purpose."
        PRD §3.7: "The `final_price_cents` is `quoted_price_cents` plus
        `late_surcharge_cents`, raised to `BUYOUT_MIN_PRICE_CENTS`, 900 cents,
        if it would otherwise fall below it."

        Design: Difficulty/dual_variant_calc/buyout_price_cycles_worn_vs_months_held
        """
        scenario = self._two_identical_units("SKU-BO-2")
        member, second_item = scenario["member"], scenario["items"][1]

        order = mint_buy_out_quote(member["id"], second_item["id"], "MONTHS_HELD")
        assert order["quoted_price_cents"] == 2725
        assert order["late_surcharge_cents"] == 0
        assert order["final_price_cents"] == 2725
        assert order["status"] == "QUOTED"

    def test_the_decay_floor_clamps_a_thirty_month_tenure(self, api):
        """PRD §3.7: "In both variants the decay factor is floored at
        `BUYOUT_DECAY_FLOOR_FACTOR`, 0.60, so no garment ever decays below sixty
        percent of its graded base."
        PRD §3.7: "The raw price is the graded base multiplied by the floored
        decay factor, and `quoted_price_cents` is that raw price rounded **half
        up to the nearest 25 cents**, the step fixed by
        `BUYOUT_ROUNDING_STEP_CENTS`."

        Design: Corner/calculations/corner_calc_buyout_decay_floor_binds_on_months_held
        """
        scenario = _delivered_item("SKU-K9-5", retail_price_cents=6000,
                                   acquired_at="2023-11-01T00:00:00Z")
        order = mint_buy_out_quote(scenario["member"]["id"],
                                   scenario["items"][0]["id"], "MONTHS_HELD")
        assert order["quoted_price_cents"] == 2225
        assert order["late_surcharge_cents"] == 0
        assert order["final_price_cents"] == 2225
        assert order["quote_variant"] == "MONTHS_HELD"

    def test_the_late_surcharge_stacks_on_the_already_rounded_quote(self, api):
        """PRD §3.7: "**The order here is pinned**: the 25-cent step rounding is
        applied to `quoted_price_cents` *before* the surcharge, and the 900-cent
        floor is applied *after* the surcharge. Applying the floor first, or
        rounding after the surcharge, gives a different answer."
        PRD §3.7: "Buying out a late garment does **not** erase the `LATE_FEE`
        already accrued — the surcharge is additional — though the obligation to
        return that garment is extinguished the moment the buy-out completes, so
        no further late days accrue on that slot."

        Design: Corner/calculations/corner_calc_buyout_late_surcharge_stacks_on_the_rounded_quote
        """
        scenario = _delivered_item("SKU-K10-5", retail_price_cents=5000,
                                   late_fee_mode="PER_DAY")
        cycle = scenario["cycle"]
        set_clock("2026-05-22T00:00:00Z")
        validate_success(api.close_swap_window(cycle["id"], ADMIN))
        set_clock("2026-06-08T00:00:00Z")
        validate_success(api.assess_late(cycle["id"], BILLING))

        item = get_box_item(scenario["items"][0]["id"])
        assert item["days_late"] == 3
        assert item["late_fee_cents"] == 450
        assert get_cycle(cycle["id"])["status"] == "GRACE"

        order = mint_buy_out_quote(scenario["member"]["id"], item["id"], "CYCLES_WORN")
        assert order["quoted_price_cents"] == 3100
        assert order["late_surcharge_cents"] == 310
        assert order["final_price_cents"] == 3410


class TestBuyOutRefusals:
    def test_a_style_priced_under_the_floor_may_not_be_quoted(self, api):
        """PRD §2.6 rung 61: "A buy-out may not be quoted for a unit whose
        style's `retail_price_cents` is below 900, because the price floor would
        then exceed the garment's own retail value. Otherwise
        `ERR_BUYOUT_BELOW_FLOOR` (422). Applies to
        `POST /kidswear/box-items/{box_item_id}/buy-out`."
        PRD §3.7: "A quote may not be minted at all for a unit whose style
        `retail_price_cents` is below 900 cents, because the floor would then
        exceed the garment's own retail value; that is refused with
        `ERR_BUYOUT_BELOW_FLOOR` (HTTP 422)."

        Design: Corner/errors/corner_err_buyout_of_a_garment_priced_below_the_floor_is_rejected
        """
        scenario = _delivered_item("SKU-XFL-5", retail_price_cents=800)
        item = scenario["items"][0]
        version = get_box_item(item["id"])["version"]

        resp = api.create_buy_out_quote(
            item["id"],
            {"quote_variant": "CYCLES_WORN", "expected_box_item_version": version},
            make_member_headers(scenario["member"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BUYOUT_BELOW_FLOOR.value, 422)
        assert get_box_item(item["id"])["settlement_status"] == "OPEN"
        _, meta = validate_paginated(api.list_buy_out_orders(BILLING,
                                                             {"limit": 10, "offset": 0}))
        assert meta["total_count"] == 0

    def test_a_second_live_quote_on_one_slot_is_refused(self, api):
        """PRD §3.7: "A second quote against a box item that already carries an
        order in `QUOTED`, `ACCEPTED`, `PAID` or `COMPLETED` is refused with
        `ERR_BUYOUT_ALREADY_EXISTS`."
        PRD §2.8: "A successful quote increments the box item's `version` by 1."

        Design: Corner/errors/corner_err_second_buyout_quote_on_one_item_is_rejected
        """
        scenario = _delivered_item("SKU-XBO-5", retail_price_cents=5000)
        member, item = scenario["member"], scenario["items"][0]
        first = mint_buy_out_quote(member["id"], item["id"], "CYCLES_WORN")
        fresh_version = get_box_item(item["id"])["version"]

        resp = api.create_buy_out_quote(
            item["id"],
            {"quote_variant": "MONTHS_HELD", "expected_box_item_version": fresh_version},
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BUYOUT_ALREADY_EXISTS.value, 409)
        assert get_buy_out_order(first["id"])["status"] == "QUOTED"
        _, meta = validate_paginated(api.list_buy_out_orders(
            BILLING, {"box_item_id": item["id"], "limit": 10, "offset": 0}))
        assert meta["total_count"] == 1

    def test_the_concurrency_gate_pre_empts_the_state_gate(self, api):
        """PRD §2.5: "**G6_OCC precedes G7_STATE.** A buy-out quote request
        carrying a stale `expected_box_item_version` against a `BoxItem` whose
        `settlement_status` is already `BOUGHT_OUT` is answered
        `ERR_STALE_BOX_ITEM_VERSION` (HTTP 412), *not*
        `ERR_BOX_ITEM_ALREADY_SETTLED` (HTTP 409)."
        PRD §2.8: "Because this check sits at gate G6 and the settlement-state
        check sits at gate G7, a stale request against an already `BOUGHT_OUT`
        item is answered with the 412, not the 409."

        Design: Corner/cross_cutting_complexity_layers/corner_ccl_occ_before_state_gate_returns_412_not_409
        """
        scenario = _delivered_item("SKU-O2-5", retail_price_cents=5000)
        member, item = scenario["member"], scenario["items"][0]
        stale_version = get_box_item(item["id"])["version"]
        first = mint_buy_out_quote(member["id"], item["id"], "CYCLES_WORN", stale_version)

        resp = api.create_buy_out_quote(
            item["id"],
            {"quote_variant": "MONTHS_HELD", "expected_box_item_version": stale_version},
            make_member_headers(member["id"]),
        )
        error = validate_error(resp, ApiErrorId.ERR_STALE_BOX_ITEM_VERSION.value, 412)
        assert error["error_id"] != ApiErrorId.ERR_BUYOUT_ALREADY_EXISTS.value
        assert get_buy_out_order(first["id"])["status"] == "QUOTED"
        assert get_box_item(item["id"])["settlement_status"] == "OPEN"

    def test_a_settled_item_refuses_a_quote_even_on_a_fresh_version(self, api):
        """PRD §2.6 rung 26: "`BoxItem.settlement_status` is `OPEN` for buy-out
        quoting and for damage settlement. Otherwise
        `ERR_BOX_ITEM_ALREADY_SETTLED` (409). Applies to
        `POST /kidswear/box-items/{box_item_id}/buy-out` and
        `POST /kidswear/condition-assessments/{assessment_id}/confirm`."
        PRD §3.6: "Confirming an assessment on an item whose
        `settlement_status` is no longer `OPEN` is refused with
        `ERR_BOX_ITEM_ALREADY_SETTLED`"

        Design: Corner/errors/corner_err_buyout_on_an_already_settled_item_is_rejected
        """
        scenario = _delivered_item("SKU-Y7-5", retail_price_cents=5000)
        member, item, unit = scenario["member"], scenario["items"][0], scenario["units"][0]
        setup_returned_items(member, [item["id"]])
        assessment = find_rental_assessment(unit["id"])
        submit_grade(assessment["id"], "A", grader_id="grader-y7")
        confirm_grade(assessment["id"], planner_id="planner-y7")

        fresh_version = get_box_item(item["id"])["version"]
        resp = api.create_buy_out_quote(
            item["id"],
            {"quote_variant": "CYCLES_WORN", "expected_box_item_version": fresh_version},
            make_member_headers(member["id"]),
        )
        error = validate_error(resp, ApiErrorId.ERR_BOX_ITEM_ALREADY_SETTLED.value, 409)
        assert error["error_id"] != ApiErrorId.ERR_STALE_BOX_ITEM_VERSION.value

        after = get_box_item(item["id"])
        assert after["settlement_status"] == "SETTLED"
        assert after["fulfillment_status"] == "RECEIVED"


class TestQuoteLifetime:
    def test_acceptance_after_the_seventy_two_hour_ttl_is_refused(self, api):
        """PRD §3.7: "A minted order is `QUOTED`, records `quoted_at` at the
        logical clock, denormalises `member_id`, and sets `quote_expires_at` to
        `quoted_at` plus `BUYOUT_QUOTE_TTL_HOURS`, seventy-two hours."
        PRD §3.7: "Acceptance is a member action and is allowed only while the
        logical clock is **strictly before** `quote_expires_at`; at or after
        that instant acceptance is refused with `ERR_BUYOUT_QUOTE_EXPIRED`."

        Design: Corner/errors/corner_err_buyout_accepted_after_the_quote_ttl_is_rejected
        """
        scenario = _delivered_item("SKU-Y6-5", retail_price_cents=5000)
        member, item = scenario["member"], scenario["items"][0]
        order = mint_buy_out_quote(member["id"], item["id"], "CYCLES_WORN")
        set_clock("2026-05-05T00:00:00Z")

        resp = api.accept_buy_out_order(order["id"], make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_BUYOUT_QUOTE_EXPIRED.value, 409)

        after = get_buy_out_order(order["id"])
        assert after["status"] == "QUOTED"
        assert_same_instant(after["quote_expires_at"], "2026-05-04T00:00:00.000Z",
                            "BuyOutOrder.quote_expires_at")
        assert get_box_item(item["id"])["settlement_status"] == "OPEN"

    def test_a_quote_may_not_be_expired_before_its_instant_arrives(self, api):
        """PRD §3.7: "A `BillingAgent` may instead expire a stale quote, moving
        it `QUOTED → EXPIRED` once the clock has reached `quote_expires_at`; and
        the household may cancel, moving `QUOTED → CANCELLED`, or moving
        `ACCEPTED → CANCELLED` provided no `BUYOUT_PRICE` charge has yet been
        raised for the order."
        PRD §3.7: "A minted order is `QUOTED`, records `quoted_at` at the
        logical clock, denormalises `member_id`, and sets `quote_expires_at` to
        `quoted_at` plus `BUYOUT_QUOTE_TTL_HOURS`, seventy-two hours."

        Design: Corner/state_machines/corner_sm_buyout_expire_before_ttl_is_rejected
        """
        scenario = _delivered_item("SKU-SM15-5", retail_price_cents=5000)
        member, item = scenario["member"], scenario["items"][0]
        order = mint_buy_out_quote(member["id"], item["id"], "CYCLES_WORN")
        set_clock("2026-05-02T00:00:00Z")

        api.expire_buy_out_order(order["id"], BILLING)

        after = get_buy_out_order(order["id"])
        assert after["status"] == "QUOTED", (
            "A quote may only be expired once the clock has reached quote_expires_at"
        )
        assert_same_instant(after["quoted_at"], "2026-05-01T00:00:00.000Z",
                            "BuyOutOrder.quoted_at")
        assert_same_instant(after["quote_expires_at"], "2026-05-04T00:00:00.000Z",
                            "BuyOutOrder.quote_expires_at")
        assert after["quoted_price_cents"] == 3100
