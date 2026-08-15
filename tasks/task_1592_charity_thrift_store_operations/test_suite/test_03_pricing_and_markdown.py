"""Item valuation vs pricing, guideline math, markdown cadence, and shrink gates."""
import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_EST_RATE_CENTS,
    INTAKE,
    MGR,
    PRICER,
    add_item,
    assert_cycle,
    assert_item,
    begin_sort,
    close_cycle,
    close_cycle_and_get_next,
    create_batch_with_items,
    create_donor,
    create_cycle,
    create_floored_item,
    create_guideline,
    create_priced_item,
    create_salable_item,
    create_worker,
    find_accumulating_bale,
    get_open_cycle,
    get_success_data,
    make_store_manager_headers,
    open_till_session,
    price_item,
    ring_sale,
    run_markdown,
    set_clock,
    settle_bale,
    ship_bale,
    shrink_payload,
    count_session,
    close_till_session,
    seal_bale,
    sort_batch_all,
    to_floor_item,
    triage_item,
    validate_error,
    validate_success,
)


def _get_item(api, item_id):
    return validate_success(api.get_item(item_id, MGR))


def _get_cycle(api, cycle_id):
    return validate_success(api.get_cycle(cycle_id, MGR))


class TestDualVariantItemValue:
    def test_provisional_and_price_coexist_and_differ(self, api):
        """PRD 3.3: "This priced figure is intentionally a different number from the
        intake provisional value — a GOOD clothing item under a guideline with
        `base_cents` 2000 prices at 1600 cents, while its provisional value was
        computed as 560."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_item_value
        """
        create_guideline("CLOTHING", 2000, 1.0)
        donor, batch, items = create_batch_with_items(
            [{"category": "CLOTHING", "condition": "GOOD"}]
        )
        begin_sort(batch["id"])
        salable = triage_item(items[0]["id"], "SALABLE")
        assert salable["provisional_value_cents"] == 560, "800 x 0.7 = 560 at intake"

        priced = price_item(items[0]["id"])
        assert_item(priced)
        assert priced["provisional_value_cents"] == 560, (
            "pricing must not disturb the intake provisional valuation"
        )
        assert priced["base_price_cents"] == 1600, "2000 x 0.8 x 1.0 = 1600"
        assert priced["current_price_cents"] == 1600
        assert priced["provisional_value_cents"] != priced["base_price_cents"]
        assert priced["status"] == "PRICED"

    def test_provisional_and_price_differ_on_second_cell(self, api):
        """PRD 3.1: "This provisional figure deliberately ignores the store's pricing
        guidelines; it is the valuation basis for tax receipts, not the sell price."
        PRD 3.3: "Start from the condition's price multiplier — 1.0 for
        NEW_WITH_TAGS, 0.8 for GOOD, 0.6 for FAIR, 0.35 for POOR"

        Design: Difficulty/dual_variant_calc/provisional_vs_final_item_value
        """
        create_guideline("TOYS", 1000, 1.0)
        donor, batch, items = create_batch_with_items(
            [{"category": "TOYS", "condition": "POOR"}]
        )
        begin_sort(batch["id"])
        salable = triage_item(items[0]["id"], "SALABLE")
        # Provisional: 600 x 0.15 = 90 (value factor); price: 1000 x 0.35 = 350.
        assert salable["provisional_value_cents"] == 90

        priced = price_item(items[0]["id"])
        assert priced["provisional_value_cents"] == 90
        assert priced["base_price_cents"] == 350
        assert priced["current_price_cents"] == 350
        assert priced["base_price_cents"] != priced["provisional_value_cents"]


class TestSuggestedPriceBranchesAndClamps:
    def test_collectibles_floor_and_min_price_clamp(self, api):
        """PRD 3.3: "except that COLLECTIBLES items never price below a multiplier of
        1.2, so a collectibles multiplier that falls under 1.2 is raised to 1.2"
        PRD 3.3: "Clamp the product so it is never below 100 cents and never above
        500000 cents, then round half up to whole cents."

        Design: Difficulty/combinatorial_formula/suggested_price_branch_and_clamp
        """
        create_guideline("COLLECTIBLES", 2000, 1.5)
        create_guideline("HOUSEWARES", 200)
        donor, batch, items = create_batch_with_items(
            [
                {"category": "COLLECTIBLES", "condition": "POOR"},
                {"category": "HOUSEWARES", "condition": "POOR"},
            ]
        )
        begin_sort(batch["id"])
        for item in items:
            triage_item(item["id"], "SALABLE")

        collect = price_item(items[0]["id"])
        # max(0.35, 1.2) = 1.2 -> 2000 x 1.2 x 1.5 = 3600.
        assert collect["base_price_cents"] == 3600
        assert collect["current_price_cents"] == 3600

        house = price_item(items[1]["id"])
        # 200 x 0.35 x 1.0 = 70 -> clamped up to the 100-cent floor.
        assert house["base_price_cents"] == 100
        assert house["current_price_cents"] == 100

    def test_max_price_clamp_and_unclamped_path(self, api):
        """PRD 3.3: "Clamp the product so it is never below 100 cents and never above
        500000 cents, then round half up to whole cents."
        PRD 3.3: "Multiply the guideline's `base_cents` by that multiplier and by the
        guideline's `demand_multiplier`."

        Design: Difficulty/combinatorial_formula/suggested_price_branch_and_clamp
        """
        create_guideline("ELECTRONICS", 600000, 1.0)
        donor, batch, items = create_batch_with_items(
            [
                {"category": "ELECTRONICS", "condition": "NEW_WITH_TAGS"},
                {"category": "ELECTRONICS", "condition": "GOOD"},
            ]
        )
        begin_sort(batch["id"])
        for item in items:
            triage_item(item["id"], "SALABLE")

        capped = price_item(items[0]["id"])
        # 600000 x 1.0 x 1.0 = 600000 -> clamped down to the 500000 ceiling.
        assert capped["base_price_cents"] == 500000
        assert capped["current_price_cents"] == 500000

        plain = price_item(items[1]["id"])
        # 600000 x 0.8 = 480000 sits inside the clamps and passes through.
        assert plain["base_price_cents"] == 480000


class TestMarkdownProgression:
    def test_markdown_progression_prices(self, api):
        """PRD 3.4: "Every item still `ON_FLOOR` that was floored in an earlier cycle
        — its floor cycle's `sequence_number` strictly less than the running
        cycle's — and whose `markdown_round` is below 3 advances one round, and its
        `current_price_cents` is recomputed as its `base_price_cents` reduced by the
        entering round's discount: 25 percent off the base price at round 1, 50
        percent off at round 2, and 75 percent off at round 3, rounded half up to
        whole cents."
        PRD 2.7: "a sequence number whose remainder when divided by four is 1 rotates
        `RED`"

        Design: Corner/calculations/markdown_progression_prices
        """
        ctx = create_floored_item("CLOTHING", "GOOD", 2000,
                                  item_kwargs={"weight_lbs": 25.0})
        item_id = ctx["item"]["id"]
        cycle1 = ctx["cycle"]

        expected = [(1, 1200), (2, 800), (3, 400)]
        cycle = cycle1
        for round_no, price in expected:
            _closed, nxt = close_cycle_and_get_next(cycle["id"])
            run_markdown(nxt["id"])
            item = _get_item(api, item_id)
            assert item["markdown_round"] == round_no
            assert item["current_price_cents"] == price
            assert item["status"] == "ON_FLOOR", (
                "pull happens only once the item enters a run already at round 3"
            )
            cycle = nxt

        item = _get_item(api, item_id)
        assert item["tag_color"] == "RED", "floored in the sequence-1 cycle"

    def test_markdown_never_touches_current_cycle_items(self, api):
        """PRD 3.4: "Items floored in the running cycle itself are never touched by
        the run, whatever their round."

        Design: Difficulty/transitive_cascade/markdown_pull_cascade
        """
        ctx = create_floored_item("CLOTHING", "GOOD", 2000)
        item_id = ctx["item"]["id"]
        cycle1 = ctx["cycle"]

        run = run_markdown(cycle1["id"])
        assert_cycle(run)
        assert run["markdown_runs_count"] == 1
        item = _get_item(api, item_id)
        assert item["markdown_round"] == 0
        assert item["current_price_cents"] == 1600
        assert item["status"] == "ON_FLOOR"

        # After the week turns over, the same item is eligible and advances.
        _closed, cycle2 = close_cycle_and_get_next(cycle1["id"])
        run_markdown(cycle2["id"])
        item = _get_item(api, item_id)
        assert item["markdown_round"] == 1
        assert item["current_price_cents"] == 1200

    def test_markdown_pull_cascade_into_bale(self, api):
        """PRD 3.4: "Every item `ON_FLOOR` from an earlier cycle whose
        `markdown_round` has already reached 3 is not re-priced; it leaves the floor
        for good, moving to `PULLED_TO_SALVAGE`. The pull derives the item's
        `salvage_category` from its `category` through the category-to-salvage
        mapping, defaults its `weight_lbs` from the category average-weight table
        when the item carries none, and feeds the item into that salvage category's
        `ACCUMULATING` bale exactly as a RECYCLE triage would — auto-creating the
        bale when none exists, growing its `item_count` and `weight_lbs`, setting the
        item's `bale_id`, and recomputing the bale's estimate."

        Design: Difficulty/transitive_cascade/markdown_pull_cascade
        """
        ctx = create_floored_item("CLOTHING", "GOOD", 2000,
                                  item_kwargs={"weight_lbs": 25.0})
        item_id = ctx["item"]["id"]
        cycle = ctx["cycle"]

        # Rounds 1, 2, 3 over three week turnovers; the fourth run pulls.
        for expected_round, expected_price in [(1, 1200), (2, 800), (3, 400)]:
            _closed, cycle = close_cycle_and_get_next(cycle["id"])
            run_markdown(cycle["id"])
            item = _get_item(api, item_id)
            assert item["markdown_round"] == expected_round
            assert item["current_price_cents"] == expected_price

        _closed, cycle = close_cycle_and_get_next(cycle["id"])
        run_markdown(cycle["id"])

        item = _get_item(api, item_id)
        assert item["status"] == "PULLED_TO_SALVAGE"
        assert item["markdown_round"] == 3, "a pulled item never advances past 3"
        assert item["current_price_cents"] == 400, "the round-3 price is preserved"
        assert item.get("bale_id"), "pull assigns the item to a bale"
        assert item.get("salvage_category"), "pull derives a salvage category"

        bale = validate_success(api.get_bale(item["bale_id"], MGR))
        assert bale["status"] == "ACCUMULATING"
        assert bale["category"] == item["salvage_category"]
        assert bale["item_count"] == 1
        assert bale["weight_lbs"] == pytest.approx(25.0)
        # Pre-seal estimate: weight x the default commodity rate of its category.
        expected_estimate = round(25.0 * DEFAULT_EST_RATE_CENTS[bale["category"]])
        assert bale["estimated_revenue_cents"] == expected_estimate


class TestHoldCycleMarkdownExemption:
    def test_held_item_survives_markdown_run_unchanged(self, api):
        """PRD 3.4: "**Hold auto-release.** Every item `ON_HOLD` whose
        `hold_expires_at` has been reached by the clock returns `ON_HOLD` →
        `ON_FLOOR` with the expiry cleared. Auto-released items are exempt from
        markdown in this same run — their round does not advance."
        PRD 3.3: "releasing the hold returns the item `ON_HOLD` → `ON_FLOOR` with
        `hold_expires_at` cleared."

        Design: Difficulty/non_linear_state_machine/item_hold_cycle_exempts_markdown
        """
        create_guideline("CLOTHING", 2000, 1.0)
        donor, batch, items = create_batch_with_items(
            [
                {"category": "CLOTHING", "condition": "GOOD"},
                {"category": "CLOTHING", "condition": "GOOD"},
            ]
        )
        begin_sort(batch["id"])
        for item in items:
            triage_item(item["id"], "SALABLE")
        for item in items:
            price_item(item["id"])
        cycle1 = create_cycle()
        for item in items:
            to_floor_item(item["id"])

        # Item A is held at the default clock (expires 72h later, i.e. 2026-08-04),
        # so the next run — still at the default clock — must skip it entirely.
        held = get_success_data(api.hold_item(items[0]["id"], PRICER))
        assert held["status"] == "ON_HOLD"
        assert held.get("hold_expires_at")

        _closed, cycle2 = close_cycle_and_get_next(cycle1["id"])
        run = run_markdown(cycle2["id"])
        assert run["markdown_runs_count"] == 1

        held_after = _get_item(api, items[0]["id"])
        assert held_after["status"] == "ON_HOLD", "unexpired hold is not auto-released"
        assert held_after["markdown_round"] == 0
        assert held_after["current_price_cents"] == 1600

        sibling = _get_item(api, items[1]["id"])
        assert sibling["status"] == "ON_FLOOR"
        assert sibling["markdown_round"] == 1
        assert sibling["current_price_cents"] == 1200

        released = get_success_data(api.release_hold_item(items[0]["id"], PRICER))
        assert released["status"] == "ON_FLOOR", "the hold cycle re-enters ON_FLOOR"
        assert released.get("hold_expires_at") is None
        assert released["markdown_round"] == 0
        assert released["current_price_cents"] == 1600

    def test_expired_hold_auto_released_and_exempt(self, api):
        """PRD 3.4: "Every item `ON_HOLD` whose `hold_expires_at` has been reached by
        the clock returns `ON_HOLD` → `ON_FLOOR` with the expiry cleared.
        Auto-released items are exempt from markdown in this same run — their round
        does not advance."

        Design: Difficulty/non_linear_state_machine/item_hold_cycle_exempts_markdown
        """
        create_guideline("CLOTHING", 2000, 1.0)
        donor, batch, items = create_batch_with_items(
            [
                {"category": "CLOTHING", "condition": "GOOD"},
                {"category": "CLOTHING", "condition": "GOOD"},
            ]
        )
        begin_sort(batch["id"])
        for item in items:
            triage_item(item["id"], "SALABLE")
        for item in items:
            price_item(item["id"])
        cycle1 = create_cycle()
        for item in items:
            to_floor_item(item["id"])
        get_success_data(api.hold_item(items[0]["id"], PRICER))

        # Move the clock past the 72-hour expiry before the week turns.
        set_clock("2026-08-05T00:00:00Z")
        _closed, cycle2 = close_cycle_and_get_next(cycle1["id"])
        run_markdown(cycle2["id"])

        released = _get_item(api, items[0]["id"])
        assert released["status"] == "ON_FLOOR", "expired hold auto-releases"
        assert released.get("hold_expires_at") is None
        assert released["markdown_round"] == 0, "auto-released item is exempt this run"
        assert released["current_price_cents"] == 1600

        sibling = _get_item(api, items[1]["id"])
        assert sibling["markdown_round"] == 1
        assert sibling["current_price_cents"] == 1200


class TestPricingGuards:
    def test_price_without_guideline_rejected(self, api):
        """PRD 3.3: "The computation reads the `ACTIVE` guideline for the item's
        category; if none exists, pricing fails with `ERR_GUIDELINE_MISSING`."

        Design: Corner/validations/price_without_guideline_rejected
        """
        donor, batch, items = create_batch_with_items(
            [{"category": "TOYS", "condition": "GOOD"}]
        )
        begin_sort(batch["id"])
        triage_item(items[0]["id"], "SALABLE")
        resp = api.price_item(items[0]["id"], PRICER)
        validate_error(resp, ApiErrorId.ERR_GUIDELINE_MISSING)
        item = _get_item(api, items[0]["id"])
        assert item["status"] == "SALABLE"

    def test_hold_from_priced_returns_invalid_state(self, api):
        """PRD 3.3: "Floor staff can pull an item aside for a customer: holding moves
        `ON_FLOOR` → `ON_HOLD` and sets `hold_expires_at` to 72 hours from the clock"
        PRD 3.3: "Attempting any of these item actions from the wrong state fails
        with `ERR_ITEM_INVALID_STATE`."

        Design: Corner/state_machines/hold_from_priced_returns_invalid_state
        """
        ctx = create_priced_item("CLOTHING", "GOOD", 2000)
        resp = api.hold_item(ctx["item"]["id"], PRICER)
        validate_error(resp, ApiErrorId.ERR_ITEM_INVALID_STATE)

    def test_shrunk_item_is_terminal(self, api):
        """PRD 3.2: "Of these, `BALED`, `DISPOSED`, and `SHRUNK` are terminal"
        PRD 3.3: "The write-off snapshots `value_at_shrink_cents` — the item's
        `current_price_cents` when one is set, otherwise its
        `provisional_value_cents` — attributes the loss to the open cycle through
        `shrunk_cycle_id`, and clears any pending hold expiry."
        PRD 3.3: "Attempting any of these item actions from the wrong state fails
        with `ERR_ITEM_INVALID_STATE`."

        Design: Corner/state_machines/shrunk_item_is_terminal
        """
        ctx = create_floored_item("CLOTHING", "GOOD", 2000)
        item_id = ctx["item"]["id"]
        shrunk = get_success_data(api.shrink_item(item_id, {"reason": "THEFT"}, MGR))
        assert shrunk["status"] == "SHRUNK"
        assert shrunk["value_at_shrink_cents"] == 1600
        assert shrunk.get("shrunk_cycle_id") == ctx["cycle"]["id"]

        resp = api.hold_item(item_id, PRICER)
        validate_error(resp, ApiErrorId.ERR_ITEM_INVALID_STATE)
        item = _get_item(api, item_id)
        assert item["status"] == "SHRUNK"
        assert item["value_at_shrink_cents"] == 1600

    def test_to_floor_without_open_cycle_rejected(self, api):
        """PRD 3.3: "The move requires an OPEN weekly cycle — with none, it fails
        with `ERR_NO_OPEN_CYCLE` — and stamps the item's `floor_cycle_id` with the
        open cycle's identity and its `tag_color` with that cycle's `rotation_color`"

        Design: Corner/endpoints/to_floor_without_open_cycle_rejected
        """
        ctx = create_priced_item("CLOTHING", "GOOD", 2000)
        resp = api.to_floor_item(ctx["item"]["id"], PRICER)
        validate_error(resp, ApiErrorId.ERR_NO_OPEN_CYCLE)
        item = _get_item(api, ctx["item"]["id"])
        assert item["status"] == "PRICED"


class TestShrinkAlertPricingGate:
    def test_shrink_alert_gates_high_value_pricing(self, api):
        """PRD 3.4: "And `shrink_rate_bp` is the shrink value multiplied by ten
        thousand and divided by the sum of the shrink value and gross sales, rounded
        half up to a whole basis point — or zero when that denominator is zero."
        PRD 3.4: "`shrink_alert_active` copied from the closing cycle's posture test
        — true when the closing cycle's `shrink_rate_bp` is at least 300 basis
        points, with a rate of exactly 300 triggering the alert."
        PRD 3.3: "When the open weekly cycle's `shrink_alert_active` posture is on
        and the computed price comes to at least 10000 cents, only a `StoreManager`
        may complete the pricing; a `Pricer` attempting it is turned away with
        `ERR_HIGH_VALUE_NEEDS_MANAGER`."

        Design: Corner/calculations/shrink_alert_gates_high_value_pricing
        """
        create_guideline("ELECTRONICS", 12125)
        create_guideline("HOUSEWARES", 500)
        create_guideline("FURNITURE", 20000)
        donor = create_donor("D Shrink")
        batch = get_success_data(
            api.create_batch({"donor_id": donor["id"], "source": "WALK_IN"}, INTAKE)
        )
        sale_item = add_item(batch["id"], "ELECTRONICS", "GOOD")     # 12125x0.8=9700
        shrink_item_ = add_item(batch["id"], "HOUSEWARES", "FAIR")   # 500x0.6=300
        begin_sort(batch["id"])
        triage_item(sale_item["id"], "SALABLE")
        triage_item(shrink_item_["id"], "SALABLE")
        price_item(sale_item["id"])
        price_item(shrink_item_["id"])
        cycle1 = create_cycle()
        to_floor_item(sale_item["id"])
        to_floor_item(shrink_item_["id"])

        cashier = create_worker("W Cash", "STAFF")
        session = open_till_session(cashier["id"], 0)
        sale = ring_sale(session["id"], cashier["id"], [sale_item["id"]], "CASH")
        assert sale["total_cents"] == 9700
        get_success_data(api.shrink_item(shrink_item_["id"], {"reason": "THEFT"}, MGR))
        count_session(session["id"], 9700)
        close_till_session(session["id"])

        set_clock("2026-08-02T00:00:00Z")
        closed = close_cycle(cycle1["id"])
        assert closed["gross_sales_cents"] == 9700
        assert closed["shrink_value_cents"] == 300
        # 300 x 10000 / (300 + 9700) = 300 exactly — the inclusive alert boundary.
        assert closed["shrink_rate_bp"] == 300

        cycle2 = get_open_cycle()
        assert cycle2["shrink_alert_active"] is True, "300bp >= the 300bp alert line"

        # A 16000-cent pricing (FURNITURE/GOOD at base 20000) is gated for a Pricer.
        donor2, batch2, items2 = create_batch_with_items(
            [{"category": "FURNITURE", "condition": "GOOD"}]
        )
        begin_sort(batch2["id"])
        triage_item(items2[0]["id"], "SALABLE")

        resp = api.price_item(items2[0]["id"], PRICER)
        validate_error(resp, ApiErrorId.ERR_HIGH_VALUE_NEEDS_MANAGER)

        priced = get_success_data(
            api.price_item(items2[0]["id"], make_store_manager_headers("mgr-hv-1"))
        )
        assert priced["base_price_cents"] == 16000
        assert priced["status"] == "PRICED"
