"""Formulas whose factors interact, and whose operation order is observable.

Three of them are exercised here: the weighted coverage cost, whose four
factors meet under a single terminal ceiling and a clamp that only bites after
it; the outcome attainment index, whose per-goal rounding happens before
aggregation rather than after; and the escalation settlement waterfall, whose
discount tier is chosen from the very total it then reduces. In each case a
plausible reordering of the same arithmetic produces a different number, so the
expected values below are the ones the ordering pins.
"""

from test_helpers import (
    ASSIGNMENT_COMMITTED,
    CASE_ACTION_RESOLVE,
    CASE_RESOLVED,
    COMMITMENT_DELIVERED,
    GOAL_WAIVED,
    HEALTH_AMBER,
    HEALTH_GREEN,
    HEALTH_RED,
    NORTHWIND,
    SEGMENT_ENTERPRISE,
    SEGMENT_MIDMARKET,
    SEVERITY_MEDIUM,
    TIER_DIGITAL,
    TIER_HIGH_TOUCH,
    TIER_LOW_TOUCH,
    add_accepted_commitment,
    add_buyer_sponsor,
    add_outcome_goal,
    add_rising_usage_rows,
    assert_capacity_conserved,
    assert_cents_fields,
    assert_credit_ledger,
    assert_field,
    assert_fields,
    assert_scores,
    assign_coverage,
    build_delivered_case,
    build_escalated_account,
    commit_case,
    create_account,
    create_csm,
    deliver_commitment,
    open_coverage,
    read_account,
    read_commitment,
    read_csm,
    read_goal,
    recompute_health,
    record_goal_progress,
    segment_account,
    transition_escalation,
)


def _account_with_rising_usage(api, csm_id, **spec_overrides):
    """Register an account and give it the three rising usage periods."""
    account = create_account(api, **{**NORTHWIND, **spec_overrides})
    add_rising_usage_rows(api, {"account_id": account["id"], "csm_id": csm_id})
    return read_account(api, account["id"])


def _staff(api, account, **overrides):
    """Segment an account and staff it, quoting the observed account version."""
    segmented = segment_account(api, account["id"])
    return assign_coverage(api, account["id"], segmented["version"], **overrides)


class TestCoverageLoadUnits:
    """The four load factors, the single terminal ceiling and the later clamp."""

    def test_segment_multiplier_alone_separates_two_high_touch_costs(
        self, api, clock
    ):
        """The same tier, tier band and health at ENTERPRISE cost 17 and at MIDMARKET 12.

        PRD §3.4: "A base figure comes from the account's coverage tier — 9 units for `HIGH_TOUCH`, 5 for `LOW_TOUCH`, 2 for `DIGITAL`."
        PRD §3.4: "That base is multiplied by a segment multiplier of 1.50 for `ENTERPRISE`, 1.00 for `MIDMARKET` or 0.50 for `SMB`, and by a risk multiplier of 1.25 when `health_tier` is `RED`, 1.10 when `AMBER` and 1.00 when `GREEN`."
        PRD §3.4: "The triple product is rounded half up to two decimal places, and then an integer revenue surcharge is added: 4 units when `arr_cents` is at least 100,000,000, otherwise 2 when it is at least 25,000,000, otherwise 1 when it is at least 5,000,000, otherwise 0."
        PRD §3.4: "The resulting figure is taken to the next whole unit by a **single** ceiling operation, and only then clamped into the range 1 to 20."
        PRD §3.4: "The single ceiling is load-bearing: a `HIGH_TOUCH`, `ENTERPRISE`, `AMBER` account at 30,000,000 cents gives 9 × 1.50 × 1.10 = 14.85, plus a surcharge of 2, giving 16.85, whose ceiling is `load_units` 17 — whereas taking a ceiling of the 13.50 sub-product before applying the risk multiplier would give 18, a different and incorrect cost."
        PRD §3.4: "Flipping only the health tier to `RED` yields 16.88 plus 2, so 19; flipping only to `GREEN` yields 13.50 plus 2, so 16; flipping only the segment to `MIDMARKET` yields 9.90 plus 2, so 12; flipping only the coverage tier to `LOW_TOUCH` yields 8.25 plus 2, so 11."
        PRD §2.10: "A CSM's `capacity_units_committed` must always equal the sum of `load_units` over that CSM's coverage assignments in state `COMMITTED`; assignments in `QUEUED`, `RELEASED` or `PREEMPTED` contribute nothing."

        Design: Difficulty/combinatorial_formula/coverage_load_units_four_factor_interaction_with_one_terminal_ceil
        """
        csm = create_csm(api, capacity_units_total=40)
        enterprise = _account_with_rising_usage(api, csm["id"])
        midmarket = _account_with_rising_usage(
            api,
            csm["id"],
            name="Contoso Retail",
            segment_band=SEGMENT_MIDMARKET,
        )
        assert_field(enterprise, "health_tier", HEALTH_AMBER)
        assert_field(midmarket, "health_tier", HEALTH_AMBER)

        enterprise_assignment = _staff(api, enterprise, csm_id=csm["id"])
        midmarket_assignment = _staff(api, midmarket, csm_id=csm["id"])

        assert_fields(
            enterprise_assignment,
            {
                "coverage_tier": TIER_HIGH_TOUCH,
                "load_units": 17,
                "state": ASSIGNMENT_COMMITTED,
            },
        )
        assert_fields(
            midmarket_assignment,
            {
                "coverage_tier": TIER_HIGH_TOUCH,
                "load_units": 12,
                "state": ASSIGNMENT_COMMITTED,
            },
        )

        manager = read_csm(api, csm["id"])
        assert_capacity_conserved(manager)
        assert_fields(
            manager,
            {"capacity_units_committed": 29, "capacity_units_available": 11},
        )

    def test_risk_multiplier_alone_separates_two_enterprise_costs(self, api, clock):
        """The same tier, band and revenue cost 19 at RED and 16 at GREEN.

        PRD §3.4: "That base is multiplied by a segment multiplier of 1.50 for `ENTERPRISE`, 1.00 for `MIDMARKET` or 0.50 for `SMB`, and by a risk multiplier of 1.25 when `health_tier` is `RED`, 1.10 when `AMBER` and 1.00 when `GREEN`."
        PRD §3.4: "The triple product is rounded half up to two decimal places, and then an integer revenue surcharge is added: 4 units when `arr_cents` is at least 100,000,000, otherwise 2 when it is at least 25,000,000, otherwise 1 when it is at least 5,000,000, otherwise 0."
        PRD §3.4: "The resulting figure is taken to the next whole unit by a **single** ceiling operation, and only then clamped into the range 1 to 20."
        PRD §3.4: "Flipping only the health tier to `RED` yields 16.88 plus 2, so 19; flipping only to `GREEN` yields 13.50 plus 2, so 16; flipping only the segment to `MIDMARKET` yields 9.90 plus 2, so 12; flipping only the coverage tier to `LOW_TOUCH` yields 8.25 plus 2, so 11."
        PRD §2.10: "`capacity_units_available` must always equal `capacity_units_total` minus `capacity_units_committed`."

        Design: Difficulty/combinatorial_formula/coverage_load_units_four_factor_interaction_with_one_terminal_ceil
        """
        csm = create_csm(api, capacity_units_total=40)
        red = create_account(api, **NORTHWIND)
        assert_field(red, "health_tier", HEALTH_RED)

        green_state = add_rising_usage_rows(
            api,
            {
                "account_id": create_account(
                    api, **{**NORTHWIND, "name": "Green Harvest Foods"}
                )["id"],
                "csm_id": csm["id"],
            },
        )
        add_buyer_sponsor(api, green_state)
        green = read_account(api, green_state["account_id"])
        assert_field(green, "health_tier", HEALTH_GREEN)

        red_assignment = _staff(api, red, csm_id=csm["id"])
        green_assignment = _staff(api, green, csm_id=csm["id"])

        assert_fields(
            red_assignment,
            {
                "coverage_tier": TIER_HIGH_TOUCH,
                "load_units": 19,
                "state": ASSIGNMENT_COMMITTED,
            },
        )
        assert_fields(
            green_assignment,
            {
                "coverage_tier": TIER_HIGH_TOUCH,
                "load_units": 16,
                "state": ASSIGNMENT_COMMITTED,
            },
        )

        manager = read_csm(api, csm["id"])
        assert_capacity_conserved(manager)
        assert_fields(
            manager,
            {"capacity_units_committed": 35, "capacity_units_available": 5},
        )

    def test_revenue_surcharge_pushes_the_ceiling_past_the_upper_clamp(
        self, api, clock
    ):
        """20.88 ceilings to 21 and only then comes back down to 20.

        PRD §3.4: "The triple product is rounded half up to two decimal places, and then an integer revenue surcharge is added: 4 units when `arr_cents` is at least 100,000,000, otherwise 2 when it is at least 25,000,000, otherwise 1 when it is at least 5,000,000, otherwise 0."
        PRD §3.4: "The resulting figure is taken to the next whole unit by a **single** ceiling operation, and only then clamped into the range 1 to 20."
        PRD §3.4: "The clamp bites after the ceiling, not before: a `HIGH_TOUCH`, `ENTERPRISE`, `RED` account at 150,000,000 cents reaches 16.88 plus a surcharge of 4, so 20.88, whose ceiling is 21, clamped down to 20."

        Design: Difficulty/combinatorial_formula/coverage_load_units_four_factor_interaction_with_one_terminal_ceil
        """
        csm = create_csm(api, capacity_units_total=40)
        account = create_account(
            api, **{**NORTHWIND, "name": "Vast Industrial", "arr_cents": 150_000_000}
        )
        assert_fields(account, {"health_tier": HEALTH_RED, "arr_cents": 150_000_000})

        assignment = _staff(api, account, csm_id=csm["id"])
        assert_fields(
            assignment,
            {
                "coverage_tier": TIER_HIGH_TOUCH,
                "load_units": 20,
                "state": ASSIGNMENT_COMMITTED,
            },
        )

        manager = read_csm(api, csm["id"])
        assert_capacity_conserved(manager)
        assert_field(manager, "capacity_units_committed", 20)

    def test_low_touch_base_lowers_the_cost_below_the_high_touch_figure(
        self, api, clock
    ):
        """A 5-unit base with a 1-unit surcharge ceilings to 10, not to 17.

        PRD §3.4: "Otherwise, if `arr_cents` is at least 5,000,000 **or** `health_tier` is `RED`, the tier is `LOW_TOUCH`."
        PRD §3.4: "A base figure comes from the account's coverage tier — 9 units for `HIGH_TOUCH`, 5 for `LOW_TOUCH`, 2 for `DIGITAL`."
        PRD §3.4: "That base is multiplied by a segment multiplier of 1.50 for `ENTERPRISE`, 1.00 for `MIDMARKET` or 0.50 for `SMB`, and by a risk multiplier of 1.25 when `health_tier` is `RED`, 1.10 when `AMBER` and 1.00 when `GREEN`."
        PRD §3.4: "The triple product is rounded half up to two decimal places, and then an integer revenue surcharge is added: 4 units when `arr_cents` is at least 100,000,000, otherwise 2 when it is at least 25,000,000, otherwise 1 when it is at least 5,000,000, otherwise 0."
        PRD §3.4: "The resulting figure is taken to the next whole unit by a **single** ceiling operation, and only then clamped into the range 1 to 20."

        Design: Difficulty/combinatorial_formula/coverage_load_units_four_factor_interaction_with_one_terminal_ceil
        """
        csm = create_csm(api, coverage_specialty=TIER_LOW_TOUCH, capacity_units_total=40)
        account = _account_with_rising_usage(
            api, csm["id"], name="Midway Logistics", arr_cents=10_000_000
        )
        assert_fields(
            account,
            {
                "health_tier": HEALTH_AMBER,
                "segment_band": SEGMENT_ENTERPRISE,
                "arr_cents": 10_000_000,
            },
        )

        assignment = _staff(api, account, csm_id=csm["id"])
        assert_fields(
            assignment,
            {
                "coverage_tier": TIER_LOW_TOUCH,
                "load_units": 10,
                "state": ASSIGNMENT_COMMITTED,
            },
        )

        manager = read_csm(api, csm["id"])
        assert_capacity_conserved(manager)
        assert_field(manager, "capacity_units_committed", 10)

    def test_digital_smb_green_account_takes_the_floor_unit(
        self, api, clock, digital_smb_account
    ):
        """A product of exactly 1.00 with no surcharge lands on the clamp floor.

        PRD §3.4: "A base figure comes from the account's coverage tier — 9 units for `HIGH_TOUCH`, 5 for `LOW_TOUCH`, 2 for `DIGITAL`."
        PRD §3.4: "The resulting figure is taken to the next whole unit by a **single** ceiling operation, and only then clamped into the range 1 to 20."
        PRD §3.4: "At the other end a `DIGITAL`, `SMB`, `GREEN` account at 100,000 cents reaches exactly 1.00 and takes the floor value 1."

        Design: Difficulty/combinatorial_formula/coverage_load_units_four_factor_interaction_with_one_terminal_ceil
        """
        account = read_account(api, digital_smb_account["account_id"])
        assert_field(account, "health_tier", HEALTH_GREEN)

        state = open_coverage(api, digital_smb_account)
        assert_fields(
            state["assignment"],
            {
                "coverage_tier": TIER_DIGITAL,
                "load_units": 1,
                "state": ASSIGNMENT_COMMITTED,
            },
        )

        manager = read_csm(api, digital_smb_account["csm_id"])
        assert_capacity_conserved(manager)
        assert_field(manager, "capacity_units_committed", 1)


class TestOutcomeAttainmentRounding:
    """Per-goal rounding before aggregation, and the weight denominator in play."""

    def test_two_weighted_goals_round_before_aggregating(self, api, clock, trending_account):
        """30.00 plus 6.67 gives 36.67, where one late rounding would give 36.66.

        PRD §3.3: "Each goal's `attainment_pct` is its `actual_value` divided by its `target_value`, multiplied by 100, capped at 100.00, and rounded half up to two decimal places."
        PRD §3.3: "The weight denominator is the sum of `weight_bp` over the input set."
        PRD §3.3: "Each goal's contribution is then its rounded `attainment_pct` multiplied by its `weight_bp`, divided by that denominator, and **rounded half up to two decimal places before aggregation**."
        PRD §3.3: "`outcome_attainment_index` is the sum of those already-rounded contributions, rounded half up to two decimal places once more."
        PRD §3.3: "Rounding each contribution first is mandatory: a goal weighted 9,000 basis points at 1 against a target of 3 contributes 30.00 (from an `attainment_pct` of 33.33), and a goal weighted 1,000 basis points at 2 against a target of 3 contributes 6.67 (from an `attainment_pct` of 66.67), giving an index of 36.67 — whereas aggregating the unrounded products and rounding once at the end would give 36.66, which is wrong."
        PRD §3.3: "A new goal enters `status` `DEFINED` with its `attainment_pct` computed immediately, and its creation recomputes the account's `outcome_attainment_index`, both health variants, `health_tier`, `renewal_likelihood` and `coverage_posture` — which is where the empty-set substitute described below stops applying."
        PRD §3.2: "Each variant is then 0.35 of its adoption term plus 0.25 of the support component plus 0.15 of the executive term plus 0.25 of the outcome term, rounded half up to two decimal places once after the entire weighted sum."

        Design: Difficulty/combinatorial_formula/outcome_attainment_rounds_per_goal_before_aggregating
        """
        account_id = trending_account["account_id"]
        csm_id = trending_account["csm_id"]
        heavy = add_outcome_goal(api, account_id, csm_id, 9_000, 3, actual_value=1)
        light = add_outcome_goal(
            api,
            account_id,
            csm_id,
            1_000,
            3,
            actual_value=2,
            title="Lift weekly active usage",
        )

        assert_scores(read_goal(api, account_id, heavy["id"]), {"attainment_pct": 33.33})
        assert_scores(read_goal(api, account_id, light["id"]), {"attainment_pct": 66.67})

        account = read_account(api, account_id)
        assert_scores(
            account,
            {
                "outcome_attainment_index": 36.67,
                "snapshot_health_score": 68.02,
                "trended_health_score": 61.37,
            },
        )
        assert_field(account, "health_tier", HEALTH_AMBER)

    def test_waiving_the_heavier_goal_rescopes_the_weight_denominator(
        self, api, clock, trending_account
    ):
        """With the 9,000-bp goal waived the survivor carries the whole index at 66.67.

        PRD §3.3: "Supplying `WAIVED` carries the goal `DEFINED → WAIVED` or `IN_PROGRESS → WAIVED`, again with no precondition; a waived goal leaves the attainment input set entirely, and its `weight_bp` leaves the weight denominator, which re-scores every remaining goal on the account."
        PRD §3.3: "Its input set is the account's goals whose `status` is `DEFINED`, `IN_PROGRESS`, `ATTAINED` or `MISSED`; waived goals are excluded from both the numerator and the weight denominator."
        PRD §3.3: "Each goal's contribution is then its rounded `attainment_pct` multiplied by its `weight_bp`, divided by that denominator, and **rounded half up to two decimal places before aggregation**."
        PRD §3.2: "It recomputes `adoption_index`, `support_risk_penalty`, `exec_engagement_score` and `outcome_attainment_index` in that order; then both health variants; then re-derives `health_tier` from the point-in-time variant; then recomputes `renewal_likelihood`; then evaluates the lifecycle transitions that depend on health; and finally recomputes `coverage_posture`."
        PRD §3.2: "`health_tier` is derived from `snapshot_health_score` **only**: the tier is `RED` when `snapshot_health_score` is below 50.00, `AMBER` when it is at least 50.00 and below 75.00, and `GREEN` when it is at least 75.00."

        Design: Difficulty/combinatorial_formula/outcome_attainment_rounds_per_goal_before_aggregating
        """
        account_id = trending_account["account_id"]
        csm_id = trending_account["csm_id"]
        heavy = add_outcome_goal(api, account_id, csm_id, 9_000, 3, actual_value=1)
        add_outcome_goal(
            api,
            account_id,
            csm_id,
            1_000,
            3,
            actual_value=2,
            title="Lift weekly active usage",
        )

        waived = record_goal_progress(api, heavy["id"], csm_id, GOAL_WAIVED)
        assert_field(waived, "status", GOAL_WAIVED)

        account = recompute_health(api, account_id)
        assert_scores(
            account,
            {
                "outcome_attainment_index": 66.67,
                "snapshot_health_score": 75.52,
                "trended_health_score": 68.87,
            },
        )
        assert_field(account, "health_tier", HEALTH_GREEN)

    def test_mirrored_weights_and_actuals_aggregate_to_63_33(
        self, api, clock, trending_account
    ):
        """60.00 plus 3.33 gives 63.33, where one late rounding would give 63.34.

        PRD §3.3: "Each goal's `attainment_pct` is its `actual_value` divided by its `target_value`, multiplied by 100, capped at 100.00, and rounded half up to two decimal places."
        PRD §3.3: "The weight denominator is the sum of `weight_bp` over the input set."
        PRD §3.3: "Each goal's contribution is then its rounded `attainment_pct` multiplied by its `weight_bp`, divided by that denominator, and **rounded half up to two decimal places before aggregation**."
        PRD §3.3: "`outcome_attainment_index` is the sum of those already-rounded contributions, rounded half up to two decimal places once more."
        PRD §3.2: "Each variant is then 0.35 of its adoption term plus 0.25 of the support component plus 0.15 of the executive term plus 0.25 of the outcome term, rounded half up to two decimal places once after the entire weighted sum."

        Design: Difficulty/combinatorial_formula/outcome_attainment_rounds_per_goal_before_aggregating
        """
        account_id = trending_account["account_id"]
        csm_id = trending_account["csm_id"]
        heavy = add_outcome_goal(api, account_id, csm_id, 9_000, 3, actual_value=2)
        light = add_outcome_goal(
            api,
            account_id,
            csm_id,
            1_000,
            3,
            actual_value=1,
            title="Lift weekly active usage",
        )

        assert_scores(read_goal(api, account_id, heavy["id"]), {"attainment_pct": 66.67})
        assert_scores(read_goal(api, account_id, light["id"]), {"attainment_pct": 33.33})

        account = read_account(api, account_id)
        assert_scores(
            account,
            {
                "outcome_attainment_index": 63.33,
                "snapshot_health_score": 74.68,
                "trended_health_score": 68.03,
            },
        )
        assert_field(account, "health_tier", HEALTH_AMBER)


class TestEscalationSettlementCredit:
    """The discount tier is chosen from the total it then reduces."""

    def test_delivered_commitment_lifts_the_total_into_the_two_thousand_bp_tier(
        self, api, clock, delivered_case
    ):
        """450,000 plus 600,000 discounts at 2,000 bp to 840,000, not to 945,000.

        PRD §3.5: "A base credit is the account's `arr_cents` multiplied by a severity rate of 300 basis points for `CRITICAL`, 150 for `HIGH` or 50 for `MEDIUM`, divided by 10,000 and rounded half up to whole cents."
        PRD §3.5: "A commitment total is the sum of `credit_cents` over this case's `DELIVERED` commitments only; `PROPOSED`, `ACCEPTED`, `REJECTED`, `BREACHED` and `WITHDRAWN` rows are excluded."
        PRD §3.5: "Those two figures add to a pre-reduction total, and the volume-discount tier is selected **from that pre-reduction total**: 2,000 basis points when it is at least 1,000,000 cents, otherwise 1,000 basis points when it is at least 250,000 cents, otherwise none."
        PRD §3.5: "The reduction is the pre-reduction total multiplied by the tier rate, divided by 10,000 and rounded half up to whole cents, and `final_credit_cents` is the pre-reduction total minus that reduction."
        PRD §3.5: "Selecting the tier from the pre-reduction total rather than from the base credit alone is mandatory: an account at 30,000,000 cents with a `HIGH` case and a single `DELIVERED` commitment of 600,000 has a base credit of 450,000 and a pre-reduction total of 1,050,000, which selects 2,000 basis points, a reduction of 210,000 and a `final_credit_cents` of 840,000 — whereas selecting the tier from the 450,000 base alone would give 1,000 basis points and a wrong answer of 945,000."
        PRD §3.5: "Resolution then increments the account's `remediation_credit_settled_cents` by `final_credit_cents`, decrements `remediation_credit_outstanding_cents` by the sum of `credit_cents` over this case's `DELIVERED` commitments, and re-derives `coverage_posture`."

        Design: Difficulty/combinatorial_formula/escalation_credit_tier_is_keyed_on_the_total_it_then_discounts
        """
        before = read_account(api, delivered_case["account_id"])
        assert_credit_ledger(before, outstanding_cents=600_000, settled_cents=0)
        assert_field(
            read_commitment(
                api, delivered_case["case_id"], delivered_case["commitment_id"]
            ),
            "state",
            COMMITMENT_DELIVERED,
        )

        case = transition_escalation(api, delivered_case["case_id"], CASE_ACTION_RESOLVE)
        assert_field(case, "state", CASE_RESOLVED)
        assert_cents_fields(case, {"final_credit_cents": 840_000})

        account = read_account(api, delivered_case["account_id"])
        assert_credit_ledger(account, outstanding_cents=0, settled_cents=840_000)

    def test_pre_reduction_total_at_exactly_the_tier_floor_takes_two_thousand_bp(
        self, api, clock
    ):
        """450,000 plus 550,000 sits on the 1,000,000 floor and still discounts at 2,000 bp.

        PRD §3.5: "A base credit is the account's `arr_cents` multiplied by a severity rate of 300 basis points for `CRITICAL`, 150 for `HIGH` or 50 for `MEDIUM`, divided by 10,000 and rounded half up to whole cents."
        PRD §3.5: "Those two figures add to a pre-reduction total, and the volume-discount tier is selected **from that pre-reduction total**: 2,000 basis points when it is at least 1,000,000 cents, otherwise 1,000 basis points when it is at least 250,000 cents, otherwise none."
        PRD §3.5: "The reduction is the pre-reduction total multiplied by the tier rate, divided by 10,000 and rounded half up to whole cents, and `final_credit_cents` is the pre-reduction total minus that reduction."
        PRD §3.5: "Resolution then increments the account's `remediation_credit_settled_cents` by `final_credit_cents`, decrements `remediation_credit_outstanding_cents` by the sum of `credit_cents` over this case's `DELIVERED` commitments, and re-derives `coverage_posture`."

        Design: Difficulty/combinatorial_formula/escalation_credit_tier_is_keyed_on_the_total_it_then_discounts
        """
        state = build_delivered_case(api, credit_cents=550_000)
        case = transition_escalation(api, state["case_id"], CASE_ACTION_RESOLVE)
        assert_field(case, "state", CASE_RESOLVED)
        assert_cents_fields(case, {"final_credit_cents": 800_000})

        account = read_account(api, state["account_id"])
        assert_credit_ledger(account, outstanding_cents=0, settled_cents=800_000)

    def test_medium_severity_total_falls_into_the_one_thousand_bp_tier(self, api, clock):
        """150,000 plus 300,000 discounts at 1,000 bp to 405,000.

        PRD §3.5: "A base credit is the account's `arr_cents` multiplied by a severity rate of 300 basis points for `CRITICAL`, 150 for `HIGH` or 50 for `MEDIUM`, divided by 10,000 and rounded half up to whole cents."
        PRD §3.5: "A commitment total is the sum of `credit_cents` over this case's `DELIVERED` commitments only; `PROPOSED`, `ACCEPTED`, `REJECTED`, `BREACHED` and `WITHDRAWN` rows are excluded."
        PRD §3.5: "Those two figures add to a pre-reduction total, and the volume-discount tier is selected **from that pre-reduction total**: 2,000 basis points when it is at least 1,000,000 cents, otherwise 1,000 basis points when it is at least 250,000 cents, otherwise none."
        PRD §3.5: "The reduction is the pre-reduction total multiplied by the tier rate, divided by 10,000 and rounded half up to whole cents, and `final_credit_cents` is the pre-reduction total minus that reduction."
        PRD §3.5: "Resolution then increments the account's `remediation_credit_settled_cents` by `final_credit_cents`, decrements `remediation_credit_outstanding_cents` by the sum of `credit_cents` over this case's `DELIVERED` commitments, and re-derives `coverage_posture`."

        Design: Difficulty/combinatorial_formula/escalation_credit_tier_is_keyed_on_the_total_it_then_discounts
        """
        state = build_escalated_account(api, severity=SEVERITY_MEDIUM)
        state = add_accepted_commitment(api, state, credit_cents=300_000)
        state = commit_case(api, state)
        state = deliver_commitment(api, state)
        assert_credit_ledger(
            read_account(api, state["account_id"]),
            outstanding_cents=300_000,
            settled_cents=0,
        )

        case = transition_escalation(api, state["case_id"], CASE_ACTION_RESOLVE)
        assert_field(case, "state", CASE_RESOLVED)
        assert_cents_fields(case, {"final_credit_cents": 405_000})

        account = read_account(api, state["account_id"])
        assert_credit_ledger(account, outstanding_cents=0, settled_cents=405_000)
