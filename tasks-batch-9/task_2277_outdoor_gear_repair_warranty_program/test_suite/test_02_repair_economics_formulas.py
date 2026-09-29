"""Repair-economics arithmetic: the repair-versus-replace threshold (PRD §3.5),
the per-line rounding discipline of the pricing rule (PRD §2.6, §3.7) and the
pinned evaluation order of the turnaround commitment (PRD §3.6).
"""

from test_helpers import (
    THRESHOLD_CEILING_PCT,
    THRESHOLD_FLOOR_PCT,
    assert_claim_decision,
    assert_estimate_breakdown,
    assert_money_cents,
    assert_multiplier,
    factories,
    get_success_data,
    validate_success,
)


class TestRepairVersusReplaceThreshold:
    """PRD §3.4 / §3.5 — the bench-standard cost, the age-decayed cap, the ratio."""

    def test_assessment_cost_is_labor_block_plus_parts_plus_capped_supply_fee(
        self, assessed_claim
    ):
        """A FABRIC 120-minute finding with 4200 cents of parts costs 22390 cents.

        "From those inputs the server computes `estimated_repair_cost_cents` on the
        assessment row using the labour block of the paid-repair pricing rule described
        in §3.7 — that is, the per-line rounded labour charges summed into a labour
        subtotal, plus `estimated_parts_cents` used directly as the parts subtotal, plus
        the capped shop supply fee."
        "It stops there: no loyalty discount, no expedite fee and no tax participate in
        an assessment estimate."
        "**Step three** applies a capped shop supply fee on labour alone:
        `shop_supply_fee_cents` is the lesser of 2500 cents and seven percent of
        `labor_subtotal_cents` rounded half up."

        Design: Difficulty/combinatorial_formula/repair_versus_replace_threshold_nonlinear_branching
        """
        assessment = assessed_claim.assessment
        assert_money_cents(assessment["estimated_repair_cost_cents"])
        assert assessment["estimated_repair_cost_cents"] == 22390, assessment

        claim = assessed_claim.scenario.read_claim(assessed_claim.claim_id)
        assert claim["latest_repair_cost_cents"] == 22390, claim

    def test_decision_threshold_is_category_allowance_less_age_decay_inside_clamps(
        self, decided_claim
    ):
        """A 37-month-old TENT_SHELTER without lifetime coverage caps repair at 55%.

        "The raw cap starts from the model's category allowance — sixty-five percent for
        `SHELL_APPAREL`, sixty percent for `INSULATION`, seventy percent for
        `TENT_SHELTER`, seventy-five percent for `PACK_HARNESS` and fifty-five percent
        for `HARDGOODS_FRAME`."
        "Ten percentage points are added when the model carries `lifetime_warranty`, and
        nothing is added otherwise."
        "Five percentage points are then subtracted for each completed year of the
        unit's age, where completed years are `age_months` divided by twelve and
        floored."
        "The resulting raw cap is clamped into a band: take the lesser of ninety and the
        raw cap, then the greater of thirty and that result."
        "The clamped value is the `decision_threshold_pct` stamped on the claim, and it
        is a whole integer percentage."

        Design: Difficulty/combinatorial_formula/repair_versus_replace_threshold_nonlinear_branching
        """
        claim = decided_claim.claim
        assert claim["decision_threshold_pct"] == 55, claim
        assert isinstance(claim["decision_threshold_pct"], int), claim
        # The raw cap of 55 sits strictly inside the band, so neither clamp bound it.
        assert THRESHOLD_FLOOR_PCT < claim["decision_threshold_pct"] < THRESHOLD_CEILING_PCT

    def test_ratio_on_successor_basis_below_threshold_yields_warranty_repair(
        self, decided_claim
    ):
        """22390 against the successor-MSRP basis is 24.90%, under the 55% cap.

        "`repair_ratio_pct` is one hundred multiplied by the claim's
        `latest_repair_cost_cents`, divided by the unit's
        `replacement_value_successor_cents`, rounded half up to two decimal places."
        "The denominator is always the successor-MSRP valuation and never the
        depreciated one — the question being asked is "what would it cost the brand to
        ship a replacement today", not "what did this customer pay"."
        "If `repair_ratio_pct` is greater than **or equal to** `decision_threshold_pct`,
        the outcome is `WARRANTY_REPLACE`; a ratio landing exactly on the threshold
        replaces rather than repairs."
        "Otherwise the outcome is `WARRANTY_REPAIR`."
        "A `WARRANTY_REPAIR` outcome moves the claim `UNDER_ASSESSMENT` →
        `WARRANTY_APPROVED` and opens the brand's exposure in a three-hop cascade."

        Design: Difficulty/combinatorial_formula/repair_versus_replace_threshold_nonlinear_branching
        """
        assert_claim_decision(
            decided_claim.claim,
            decision="WARRANTY_REPAIR",
            status="WARRANTY_APPROVED",
            threshold_pct=55,
            ratio_pct=24.90,
        )


class TestEstimatePerLineRounding:
    """PRD §2.6 / §3.7 — each labour line rounds alone before the subtotal is formed."""

    def test_labor_subtotal_rounds_each_line_before_summing(
        self, order_with_sent_estimate
    ):
        """FABRIC 25 min and ZIPPER 35 min give 3542 + 5542 = 9084, not 9083.

        "Rounding happens only at the points named in the pricing and valuation rules,
        and never anywhere else — in particular, per-line labour charges are rounded
        individually before they are summed, and the sum itself is never rounded again."
        "Taking the lines in ascending order of `work_type`, each line's charge is the
        hourly labour rate for its `work_type` multiplied by that line's `minutes`,
        divided by sixty, rounded half up to a whole cent."
        "The hourly rates are 8500 cents for `FABRIC`, 9500 cents for `ZIPPER`, 11000
        cents for `FRAME` and 9000 cents for `INSULATION`."
        "`labor_subtotal_cents` is the sum of those already-rounded per-line charges;
        the sum itself is not rounded again, and it is emphatically not the rounding of
        one big rate-times-minutes total."

        Design: Difficulty/combinatorial_formula/final_invoice_per_line_rounding_before_sum
        """
        estimate = order_with_sent_estimate.estimate
        assert_money_cents(estimate["labor_subtotal_cents"])
        assert estimate["labor_subtotal_cents"] == 9084, estimate
        assert estimate["labor_subtotal_cents"] != 9083, (
            "9083 is the sum-then-round reading the PRD rules out"
        )

    def test_full_breakdown_flows_from_the_per_line_labor_subtotal(
        self, order_with_sent_estimate
    ):
        """The 9084 labour subtotal drives a 636 supply fee, 11520 subtotal, 11223 total.

        "**Step two** handles parts exactly: `parts_subtotal_cents` is the sum over the
        parts lines of `units` multiplied by `unit_price_cents`, with no rounding because
        every term is already a whole number of cents."
        "**Step three** applies a capped shop supply fee on labour alone:
        `shop_supply_fee_cents` is the lesser of 2500 cents and seven percent of
        `labor_subtotal_cents` rounded half up."
        "**Step four** sums: `subtotal_cents` is `labor_subtotal_cents` plus
        `parts_subtotal_cents` plus `shop_supply_fee_cents`."
        "**Step five** applies loyalty: `loyalty_discount_cents` is `subtotal_cents`
        multiplied by the owner's tier rate, rounded half up, where a `STANDARD` owner's
        rate is zero percent and a `PRO` owner's rate is ten percent."
        "**Step six** applies expedite: `expedite_fee_cents` is 3500 cents on a `FINAL`
        row when the order's `expedite_requested` is true, and zero in every other case
        — a `PROVISIONAL` row always carries zero here, even on an expedited order."
        "**Step seven** taxes the discounted, expedited base: `tax_cents` is 8.25 percent
        of the quantity `subtotal_cents` minus `loyalty_discount_cents` plus
        `expedite_fee_cents`, rounded half up."
        "**Step eight** totals: `total_cents` is `subtotal_cents` minus
        `loyalty_discount_cents` plus `expedite_fee_cents` plus `tax_cents`."

        Design: Difficulty/combinatorial_formula/final_invoice_per_line_rounding_before_sum
        """
        estimate = order_with_sent_estimate.estimate
        assert_estimate_breakdown(
            estimate,
            labor_subtotal_cents=9084,
            parts_subtotal_cents=1800,
            shop_supply_fee_cents=636,
            subtotal_cents=11520,
            loyalty_discount_cents=1152,
            expedite_fee_cents=0,
            tax_cents=855,
            total_cents=11223,
        )
        assert estimate["variant"] == "PROVISIONAL", estimate
        assert estimate["status"] == "SENT", estimate


class TestTurnaroundCommitmentEvaluationOrder:
    """PRD §3.6 — snapshot before insert, take the greater multiplier, round up early."""

    def test_commitment_snapshots_the_queue_before_insert_and_rounds_up_before_parts_wait(
        self, decided_claim
    ):
        """An empty queue under a 1.50 surge window promises 21 days on 14 base days.

        "First, the queue is snapshotted **before** the new order is inserted:
        `queue_depth_snapshot` is the count of repair orders at this centre whose
        `work_status` is `QUEUED`, `IN_WORK` or `BENCH_DONE`, excluding the row being
        created."
        "Second, a congestion tier is looked up on that snapshot: a snapshot of at most 9
        yields a tier multiplier of 1.00, at most 24 yields 1.25, at most 49 yields 1.60,
        and 50 or more yields 2.00."
        "Third, the seasonal override is folded in but may never lower the tier: among
        the centre's surge windows whose `status` is `ACTIVE` and whose `start_date` is
        at or before the logical clock instant and whose `end_date` is at or after it —
        the window is inclusive at both ends — the largest `multiplier` is taken, or 1.00
        when no such window exists, and `surge_multiplier_applied` is the greater of the
        tier multiplier and that window multiplier."
        "Fourth, a parts wait is read from the model's `parts_support_status` **as it
        stands before any reservation created by this request**: zero days when
        `SUPPORTED`, seven days when `SUBSTITUTION_ONLY`, and fourteen days when
        `NO_SUPPORT`, recorded as `parts_wait_days`."
        "Fifth, base days are assembled from the model's `category` — ten days for
        `SHELL_APPAREL`, fourteen for `INSULATION`, twelve for `TENT_SHELTER`, nine for
        `PACK_HARNESS` and sixteen for `HARDGOODS_FRAME` — plus the largest work-type
        addition among the order's `required_work_types`, where fabric work adds two
        days, zipper work three, frame work five and insulation work six."
        "Sixth, `promised_days` is the base-day total multiplied by
        `surge_multiplier_applied`, rounded **up** to a whole number of days, and only
        then increased by `parts_wait_days`; the rounding up happens before the parts
        wait is added and never after."
        "`promised_return_at` is then the calendar date of the logical clock instant
        advanced by `promised_days` days, at 23:59:59.999Z on that date."

        Design: Difficulty/combinatorial_formula/turnaround_commitment_queue_snapshot_evaluation_order
        """
        scenario = decided_claim.scenario
        scenario.surge_window(decided_claim.center_id)

        order = scenario.repair_order(decided_claim.claim_id)

        assert order["queue_depth_snapshot"] == 0, order
        assert_multiplier(order["surge_multiplier_applied"], 1.50)
        assert order["parts_wait_days"] == 0, order
        assert order["promised_days"] == 21, order
        assert order["promised_return_at"] == "2026-07-06T23:59:59.999Z", order

    def test_center_queue_and_surge_are_recomputed_after_the_insert(
        self, decided_claim, api, agent_headers, admin_headers
    ):
        """The centre's active_queue_depth lands at 1, the snapshot plus one.

        "Only after the commitment is frozen onto the order is the order inserted, after
        which the centre's `active_queue_depth` and `current_surge_multiplier` are
        recomputed."
        "The consequence is observable: immediately after a create, the centre's
        `active_queue_depth` equals the order's `queue_depth_snapshot` plus one."
        "`active_queue_depth` itself is defined as the count of the centre's repair
        orders whose `work_status` is `QUEUED`, `IN_WORK` or `BENCH_DONE`."
        "The centre's `current_surge_multiplier` is the multiplier implied by the
        `active_queue_depth` congestion tier together with any `ACTIVE` surge window
        covering the logical clock date, on the same tiers and the same take-the-greater
        rule that a repair order's `surge_multiplier_applied` uses."

        Design: Difficulty/combinatorial_formula/turnaround_commitment_queue_snapshot_evaluation_order
        """
        scenario = decided_claim.scenario
        scenario.surge_window(decided_claim.center_id)

        created = api.create_repair_order(
            factories.repair_order_payload(decided_claim.claim_id), agent_headers
        )
        order = validate_success(created, 201)

        center = get_success_data(
            api.get_service_center(decided_claim.center_id, admin_headers)
        )
        assert center["active_queue_depth"] == 1, center
        assert center["active_queue_depth"] == order["queue_depth_snapshot"] + 1, center
        assert_multiplier(center["current_surge_multiplier"], 1.50)
