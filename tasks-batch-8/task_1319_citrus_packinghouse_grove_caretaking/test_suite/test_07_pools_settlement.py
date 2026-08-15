"""Pools and settlement: the provisional-vs-final dual price variants, tiered
packing charge boundaries, projection input filtering, close-intake and
settle state gates, the pinned settlement evaluation order, reversal
reconciliation, and pool OCC."""
from test_helpers import (
    ApiErrorId,
    create_and_approve_advance,
    create_completed_order,
    create_draft_invoice,
    dom_fresh_spec,
    get_advance,
    get_channel,
    get_delivery,
    get_grower,
    get_pool,
    get_sort_run,
    get_statements,
    get_success_data,
    juice_spec,
    set_clock,
    set_pool_price,
    settle_pool,
    setup_posted_scenario,
    statement_amounts,
    sort_run_lifecycle,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.fixtures import (
    close_intake_and_set_price,
    create_channel,
    create_pool,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


class TestProvisionalVsFinalPrice:
    def test_provisional_price_is_forward_looking_without_packing_charge(self, api):
        """PRD §3.6: "projected proceeds are the pool's
        `posted_proceeds_cents` plus eighty percent of the sum, over those
        channels, of each channel's `remaining_boxes` multiplied by its
        `price_cents_per_box`; projected grade-equivalent boxes are the pool's
        `posted_ge_boxes` plus eighty percent of the sum of those channels'
        `remaining_boxes`; and the provisional price is the projected proceeds
        divided by the larger of the projected grade-equivalent boxes and 1,
        rounded half-up to whole cents."

        Design: Difficulty/dual_variant_calc/pool_price_provisional_vs_final
        """
        scenario = setup_posted_scenario("DV1")
        run = scenario["sort_run"]
        assert run["proceeds_cents"] == 49760
        assert run["ge_boxes"] == 96.8
        pool = scenario["pool"]
        assert pool["status"] == "OPEN"
        # Both finite channels were exhausted by the waterfall, so the
        # projection adds nothing: round_half_up(49760 / 96.8) = 514.
        assert pool["provisional_price_cents_per_ge_box"] == 514
        assert pool["final_price_cents_per_ge_box"] is None

    def test_final_price_is_actuals_only_minus_tiered_charge(self, api):
        """PRD §3.6: "Pricing uses actuals only — no fill projection — and
        computes a tiered packing charge keyed on the pool's total
        `sorted_field_boxes`: 150 cents per box when the total is below
        10,000" and "the `final_price_cents_per_ge_box` is the pool's
        `posted_proceeds_cents` minus that packing charge, divided by the
        larger of `posted_ge_boxes` and 1, rounded half-up to whole cents."

        Design: Difficulty/dual_variant_calc/pool_price_provisional_vs_final
        """
        scenario = setup_posted_scenario("DV1B")
        pool_id = scenario["pool"]["id"]
        validate_success(api_client.close_pool_intake(pool_id, ACCOUNTANT))
        priced = set_pool_price(pool_id)
        # 100 sorted boxes < 10,000 -> charge 100 * 150 = 15,000;
        # final = round_half_up((49760 - 15000) / 96.8) = 359.
        assert priced["status"] == "PRICED"
        assert priced["final_price_cents_per_ge_box"] == 359
        provisional_before = 514  # forward-looking variant on identical data
        assert provisional_before != priced["final_price_cents_per_ge_box"], \
            "the two price variants must differ on identical posted data"


class TestFinalPriceTierBoundary:
    def test_pool_final_price_tier_boundary(self, api):
        """PRD §3.6: "computes a tiered packing charge keyed on the pool's
        total `sorted_field_boxes`: 150 cents per box when the total is below
        10,000; 140 cents per box when it is at least 10,000 and below
        50,000; and 125 cents per box when it is at least 50,000 — the tier
        edges include their lower bound."

        Design: Corner/calculations/pool_final_price_tier_boundary
        """
        # Pool A: 9,999 sorted CHOICE boxes @500 (week 2026-07-27).
        scenario_a = setup_posted_scenario(
            "CA2A", gross_boxes=9999, fancy_boxes=0, choice_boxes=9999,
            standard_boxes=0, juice_boxes=0, cull_boxes=0,
            color_score=8, defect_pct=5, planned_boxes=9999, crew_capacity=20000,
            acreage=500,
            channel_specs=[
                dom_fresh_spec("DOM-CA2A", "HAMLIN", boxes=9999, price=500, rank=1),
                juice_spec("JU-CA2A", "HAMLIN"),
            ])
        # Pool B: 10,000 sorted CHOICE boxes @500 (week 2026-08-03).
        set_clock("2026-08-03T00:00:00Z")
        grove = scenario_a["grove"]
        crew = scenario_a["crew"]
        pool_b = create_pool("HAMLIN", "2026-08-03")
        create_channel("DOM-CA2B", "DOMESTIC_FRESH", "DOMESTIC", "HAMLIN",
                       week_start="2026-08-03", allocation_boxes=10000,
                       price_cents_per_box=500, priority_rank=1,
                       accepts_grades=("FANCY", "CHOICE", "STANDARD"))
        create_channel("JU-CA2B", "JUICE", "NONE", "HAMLIN",
                       week_start="2026-08-03", allocation_boxes=0,
                       price_cents_per_box=220, priority_rank=9)
        assignment_b = get_success_data(api_client.create_assignment(
            {"crew_id": crew["id"], "grove_id": grove["id"],
             "window_start": "2026-08-03T00:00:00Z",
             "window_end": "2026-08-03T12:00:00Z", "planned_boxes": 10000},
            SUPERVISOR))
        get_success_data(api_client.start_assignment(assignment_b["id"], SUPERVISOR))
        delivery_b = get_success_data(api_client.create_delivery(
            {"grove_id": grove["id"], "assignment_id": assignment_b["id"],
             "gross_boxes": 10000, "tare_boxes": 0}, SUPERVISOR))
        assert delivery_b["pool_id"] == pool_b["id"]
        run_b = sort_run_lifecycle(delivery_b["id"], 0, 10000, 0, 0, 0, 8, 5,
                                   operator_id="op-ca2", inspector_id="qi-ca2")
        assert run_b["proceeds_cents"] == 5000000
        # Price both pools.
        pool_a_id = scenario_a["pool"]["id"]
        validate_success(api_client.close_pool_intake(pool_a_id, ACCOUNTANT))
        validate_success(api_client.close_pool_intake(pool_b["id"], ACCOUNTANT))
        priced_a = set_pool_price(pool_a_id)
        priced_b = set_pool_price(pool_b["id"])
        # A: 9,999 boxes < 10,000 -> rate 150; (4,999,500 - 1,499,850) / 9,999 = 350.
        assert priced_a["sorted_field_boxes"] == 9999
        assert priced_a["posted_proceeds_cents"] == 4999500
        assert priced_a["final_price_cents_per_ge_box"] == 350
        # B: 10,000 boxes >= 10,000 (inclusive-low edge) -> rate 140;
        # (5,000,000 - 1,400,000) / 10,000 = 360.
        assert priced_b["sorted_field_boxes"] == 10000
        assert priced_b["final_price_cents_per_ge_box"] == 360


class TestPoolStateGates:
    def test_pool_settle_before_price_rejected(self, api):
        """PRD §3.6: "Settlement moves the pool `PRICED` → the terminal
        `SETTLED`" — settle is defined only from PRICED. PRD §2.6 tier 6:
        "the target resource's current state permits the requested transition,
        including terminal-state lockdown" and "other state violations surface
        as `ERR_INVALID_STATE_TRANSITION` (HTTP 409)".

        Design: Corner/state_machines/pool_settle_before_price_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        pool = create_pool("HAMLIN", "2026-07-27")
        validate_success(api_client.close_pool_intake(pool["id"], ACCOUNTANT))
        resp = api_client.settle_pool(pool["id"], ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert get_pool(pool["id"])["status"] == "INTAKE_CLOSED"


class TestSettlementEvaluationOrder:
    def _setup_offset_recoup_scenario(self, tag):
        """Posted 100-box scenario + a 20,000-cent ISSUED caretaking invoice +
        a 10,000-cent ISSUED NEXT_SETTLEMENT_FULL advance + pool PRICED."""
        scenario = setup_posted_scenario(tag, caretaking_enrolled=True, acreage=30)
        order = create_completed_order(scenario["grove"]["id"], "MOW",
                                       "2026-08-01", 11.111)
        assert order["line_amount_cents"] == 20000
        invoice = create_draft_invoice(scenario["grower"]["id"])
        get_success_data(api_client.issue_caretaking_invoice(
            invoice["id"], ACCOUNTANT))
        advance = create_and_approve_advance(
            scenario["grower"]["id"], scenario["pool"]["id"], 10000,
            recoup_policy="NEXT_SETTLEMENT_FULL")
        close_intake_and_set_price(scenario["pool"]["id"])
        scenario["advance"] = advance
        return scenario

    def test_settlement_offset_recoup_evaluation_order_statement(self, api):
        """PRD §3.6: "Step one: the grower's share is the grower's posted
        grade-equivalent boxes in this pool multiplied by
        `final_price_cents_per_ge_box`, rounded half-up to whole cents. Step
        two: the caretaking offset is the lesser of the grower's
        `caretaking_balance_cents` and one half of the share rounded half-up
        to whole cents. Step three: the residual — the share minus the offset
        — is applied to recoup the grower's advances on this pool that stand
        in `ISSUED` or `PARTIALLY_RECOUPED`". PRD §3.6: "The per-grower
        settlement statements of a pool — share, offset, recoupment, and
        amount paid — are readable by a `PackinghouseAdmin`, a
        `PoolAccountant`, and the `Grower` for its own statement."

        Design: Difficulty/combinatorial_formula/settlement_offset_recoup_evaluation_order
        """
        scenario = self._setup_offset_recoup_scenario("SW1")
        settled = settle_pool(scenario["pool"]["id"])
        assert settled["status"] == "SETTLED"
        # final price 359 (proceeds 49760 - charge 15000, over ge 96.8).
        assert settled["final_price_cents_per_ge_box"] == 359
        payload = get_statements(scenario["pool"]["id"])
        statements = payload["statements"]
        assert len(statements) == 1, "only one grower has posted ge in the pool"
        share, offset, recouped, paid = statement_amounts(statements[0])
        # share = round_half_up(96.8 * 359) = 34751
        assert share == 34751
        # offset = min(20000, round_half_up(0.5 * 34751) = 17376) — computed
        # BEFORE recoupment, capped by the share.
        assert offset == 17376
        # recoup = min(10000 outstanding, 34751 - 17376 residual) = 10000
        assert recouped == 10000
        # paid = 34751 - 17376 - 10000 = 7375
        assert paid == 7375

    def test_settlement_offset_recoup_evaluation_order_ledgers(self, api):
        """PRD §3.6: "Across the settlement, each grower's
        `caretaking_balance_cents` falls by the applied offset and
        `advance_outstanding_cents` falls by the total recouped, and every
        touched grower's `version` increments." and "an advance recouped in
        full becomes `RECOUPED`".

        Design: Difficulty/combinatorial_formula/settlement_offset_recoup_evaluation_order
        """
        scenario = self._setup_offset_recoup_scenario("SW1B")
        advance_id = scenario["advance"]["id"]
        settle_pool(scenario["pool"]["id"])
        advance = get_advance(advance_id)
        assert advance["status"] == "RECOUPED"
        assert advance["recouped_cents"] == 10000
        assert advance["outstanding_cents"] == 0
        grower = get_grower(scenario["grower"]["id"])
        assert grower["caretaking_balance_cents"] == 2624, "20000 - 17376 offset"
        assert grower["advance_outstanding_cents"] == 0


class TestSortRunReversal:
    def test_sort_run_reversal_reconciles_delivery_and_run(self, api):
        """PRD §3.5: "A `PoolAccountant` may reverse a `POSTED` run — moving
        it `POSTED` → `VOIDED`" and "the delivery returns `SORTED` →
        `READY_TO_SORT` with a version bump."

        Design: Difficulty/transitive_cascade/sort_run_reversal_reconciles_pool
        """
        scenario = setup_posted_scenario("TC1")
        run_id = scenario["sort_run"]["id"]
        reversed_run = validate_success(api_client.reverse_sort_run(
            run_id, ACCOUNTANT))
        assert reversed_run["status"] == "VOIDED"
        assert get_delivery(scenario["delivery"]["id"])["processing_status"] == \
            "READY_TO_SORT"

    def test_sort_run_reversal_reconciles_pool_and_channels(self, api):
        """PRD §3.5: "Reversal is exact: every touched channel's
        `remaining_boxes` is restored, the pool's `posted_ge_boxes`,
        `posted_proceeds_cents`, and `sorted_field_boxes` are decremented by
        exactly the amounts the post added, the provisional price is
        recomputed and the pool's `version` bumps". Pre-post provisional was
        round_half_up(0.8*(25*900 + 40*500) / (0.8*65)) = 654.

        Design: Difficulty/transitive_cascade/sort_run_reversal_reconciles_pool
        """
        scenario = setup_posted_scenario("TC1B")
        pool_before_reverse = scenario["pool"]
        assert pool_before_reverse["posted_ge_boxes"] == 96.8
        validate_success(api_client.reverse_sort_run(
            scenario["sort_run"]["id"], ACCOUNTANT))
        pool = get_pool(scenario["pool"]["id"])
        assert pool["posted_ge_boxes"] == 0
        assert pool["posted_proceeds_cents"] == 0
        assert pool["sorted_field_boxes"] == 0
        assert pool["provisional_price_cents_per_ge_box"] == 654, \
            "the pre-post forward-looking value is exactly restored"
        assert pool["version"] > pool_before_reverse["version"]
        channels = scenario["channels"]
        assert get_channel(channels["JP-TC1B"]["id"])["remaining_boxes"] == 25
        assert get_channel(channels["DOM-TC1B"]["id"])["remaining_boxes"] == 40


class TestPoolTotalsConserved:
    def test_post_moves_pool_aggregates_forward(self, api):
        """PRD §3.5: posting "increases the pool's `posted_ge_boxes`,
        `posted_proceeds_cents`, and `sorted_field_boxes`, recomputes the
        pool's provisional price, and bumps the pool's `version`" and
        "decrements `remaining_boxes` on every channel the waterfall touched".

        Design: Difficulty/compensating_invariant/pool_totals_conserved_under_post_and_reverse
        """
        scenario = setup_posted_scenario(
            "CI1", variety="VALENCIA", gross_boxes=10, fancy_boxes=10,
            choice_boxes=0, standard_boxes=0, juice_boxes=0, cull_boxes=0,
            color_score=8, defect_pct=5, planned_boxes=50,
            channel_specs=[
                dom_fresh_spec("DOM-CI1", "VALENCIA", boxes=10, price=600, rank=1,
                               grades=("FANCY",)),
                juice_spec("JU-CI1", "VALENCIA"),
            ])
        pool = scenario["pool"]
        assert pool["posted_ge_boxes"] == 11.5
        assert pool["posted_proceeds_cents"] == 6000
        assert pool["sorted_field_boxes"] == 10
        # (6000 + 0.8 * 0) / (11.5 + 0.8 * 0) = 521.73... -> 522
        assert pool["provisional_price_cents_per_ge_box"] == 522
        assert scenario["channels"]["DOM-CI1"]["remaining_boxes"] == 0

    def test_reverse_restores_pool_aggregates_bit_for_bit(self, api):
        """PRD §3.5: "Reversal is exact: every touched channel's
        `remaining_boxes` is restored, the pool's `posted_ge_boxes`,
        `posted_proceeds_cents`, and `sorted_field_boxes` are decremented by
        exactly the amounts the post added, the provisional price is
        recomputed and the pool's `version` bumps, and the delivery returns
        `SORTED` → `READY_TO_SORT` with a version bump."

        Design: Difficulty/compensating_invariant/pool_totals_conserved_under_post_and_reverse
        """
        scenario = setup_posted_scenario(
            "CI1B", variety="VALENCIA", gross_boxes=10, fancy_boxes=10,
            choice_boxes=0, standard_boxes=0, juice_boxes=0, cull_boxes=0,
            color_score=8, defect_pct=5, planned_boxes=50,
            channel_specs=[
                dom_fresh_spec("DOM-CI1B", "VALENCIA", boxes=10, price=600, rank=1,
                               grades=("FANCY",)),
                juice_spec("JU-CI1B", "VALENCIA"),
            ])
        validate_success(api_client.reverse_sort_run(
            scenario["sort_run"]["id"], ACCOUNTANT))
        pool = get_pool(scenario["pool"]["id"])
        assert pool["posted_ge_boxes"] == 0
        assert pool["posted_proceeds_cents"] == 0
        assert pool["sorted_field_boxes"] == 0
        # Pre-post projection restored: 0.8 * 10 * 600 / (0.8 * 10) = 600.
        assert pool["provisional_price_cents_per_ge_box"] == 600
        assert get_channel(scenario["channels"]["DOM-CI1B"]["id"])[
            "remaining_boxes"] == 10
        assert get_delivery(scenario["delivery"]["id"])["processing_status"] == \
            "READY_TO_SORT"
        assert get_sort_run(scenario["sort_run"]["id"])["status"] == "VOIDED"


class TestReverseGate:
    def test_reverse_blocked_once_pool_priced(self, api):
        """PRD §3.5: "A `PoolAccountant` may reverse a `POSTED` run — moving
        it `POSTED` → `VOIDED` — only while the delivery's pool is `OPEN` or
        `INTAKE_CLOSED` (`ERR_POOL_NOT_ACCEPTING` once it has moved on)."

        Design: Corner/errors/reverse_blocked_once_pool_priced
        """
        scenario = setup_posted_scenario(
            "ER9", gross_boxes=10, fancy_boxes=10, choice_boxes=0,
            standard_boxes=0, juice_boxes=0, cull_boxes=0,
            color_score=4, defect_pct=5, planned_boxes=50,
            channel_specs=[juice_spec("JU-ER9", "HAMLIN")])
        close_intake_and_set_price(scenario["pool"]["id"])
        resp = api_client.reverse_sort_run(scenario["sort_run"]["id"], ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_POOL_NOT_ACCEPTING)
        assert get_sort_run(scenario["sort_run"]["id"])["status"] == "POSTED"
        assert get_pool(scenario["pool"]["id"])["posted_proceeds_cents"] == 2200


class TestPoolOcc:
    def test_occ_pool_reprice_stale_version(self, api):
        """PRD §2.8: "Setting or re-setting a pool's final price requires
        `expected_pool_version` matching the pool's current `version`; a
        request whose value is behind — for example because a re-price landed
        after the caller's read — is rejected with `ERR_STALE_VERSION`
        (HTTP 412)." PRD §3.6: "Setting the price moves `INTAKE_CLOSED` →
        `PRICED`, and may be repeated as a re-price `PRICED` → `PRICED`".

        Design: Corner/cross_cutting_layers/occ_pool_reprice_stale_version
        """
        set_clock("2026-08-01T00:00:00Z")
        pool = create_pool("HAMLIN", "2026-07-27")
        validate_success(api_client.close_pool_intake(pool["id"], ACCOUNTANT))
        priced = set_pool_price(pool["id"])
        assert priced["status"] == "PRICED"
        # An empty pool prices at 0: (0 - 0 * 150) / max(0, 1).
        assert priced["final_price_cents_per_ge_box"] == 0
        stale_version = priced["version"] - 1  # the version observed pre-pricing
        resp = api_client.set_pool_price(
            pool["id"], {"expected_pool_version": stale_version}, ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        # Re-price with the fresh version succeeds and bumps the version again.
        repriced = set_pool_price(pool["id"])
        assert repriced["status"] == "PRICED"
        assert repriced["version"] == priced["version"] + 1
