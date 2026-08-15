"""Period close and statement settlement: the marginal tiered curve with the
cap applied last, attainment floor boundaries, the pinned draw/guarantee
evaluation order, per-period accumulator reset, open-dispute gating, OCC, and
the provisional-vs-final payout variants."""
from test_helpers import (
    ApiErrorId,
    CANONICAL_CURVE_TIERS,
    TEST_USERS,
    assert_payout_statement,
    cancel_transaction,
    close_period,
    close_period_payload,
    create_program,
    file_dispute,
    get_assignment,
    get_statement_for,
    list_adjustments,
    setup_accepted_assignment,
    setup_posted_credit,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["comp_admin_headers"]


class TestCloseMechanics:
    def test_close_period_with_no_assignments(self, api):
        """PRD §3.7: "It generates one `DRAFT` payout statement per assignment
        whose lifecycle `status` is `ACTIVE` — unique per assignment and
        period."
        PRD §3.7: "And it advances the program: `current_period_index`
        increases by 1, `accrued_balance_cents` increases by the sum of the
        period's `net_payable_cents`, and the program's `version` increments
        by 1."

        Design: Corner/cross_cutting_layers/close_period_with_no_assignments
        """
        program = create_program("Prog EC2")
        closed = close_period(program["id"], program["version"])
        assert closed["current_period_index"] == 2
        assert closed["accrued_balance_cents"] == 0
        data, _meta = validate_paginated(
            api.list_statements(ADMIN, params={"period_index": 1}))
        assert data == []

    def test_close_with_stale_program_version_rejected(self, api):
        """PRD §2.7: "If the program's version no longer matches — because a
        period boundary the caller did not observe has already been crossed —
        the close is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_program_version_on_close
        """
        program = create_program("Prog OC2")
        observed_version = program["version"]

        first = api.close_period(program["id"],
                                 close_period_payload(observed_version), ADMIN)
        closed = validate_success(first, 200)
        assert closed["current_period_index"] == 2
        assert closed["version"] == observed_version + 1

        replay = api.close_period(program["id"],
                                  close_period_payload(observed_version), ADMIN)
        validate_error(replay, ApiErrorId.ERR_STALE_PROGRAM_VERSION, 412)
        assert (validate_success(api.get_program(program["id"], ADMIN))
                ["current_period_index"] == 2)

    def test_attainment_accumulator_resets_each_period(self, api):
        """PRD §3.7: "It resets each settled assignment's
        `current_period_earned_cents` to 0."
        PRD §3.7: "First, `earned_credits_cents` captures the assignment's
        `current_period_earned_cents` filtered by the plan's
        `attainment_mode`, exactly as §3.4 defines the mode filter."

        Design: Corner/cross_cutting_layers/attainment_resets_each_period
        """
        sc = setup_posted_credit(program_name="Prog RS", plan_name="Plan RS",
                                 rep_name="Rep RS", employee_ref="RS-R1",
                                 amount_cents=1200000, external_ref="RS-T1",
                                 plan_overrides={
                                     "curve_tiers": CANONICAL_CURVE_TIERS})
        close_period(sc["program"]["id"])
        stmt1 = get_statement_for(sc["assignment"]["id"], 1)
        assert stmt1["attainment_bps"] == 12000
        assert stmt1["gross_payout_cents"] == 160000

        close_period(sc["program"]["id"])
        stmt2 = get_statement_for(sc["assignment"]["id"], 2)
        assert stmt2["attainment_bps"] == 0
        assert stmt2["gross_payout_cents"] == 0, (
            "the accelerator counter resets at each epoch boundary"
        )
        assert (get_assignment(sc["assignment"]["id"])
                ["current_period_earned_cents"] == 0)


class TestCurveAndBoundaries:
    def _close_with_earned(self, api, prefix, amount_cents, **plan_overrides):
        sc = setup_posted_credit(program_name=f"Prog {prefix}",
                                 plan_name=f"Plan {prefix}",
                                 rep_name=f"Rep {prefix}",
                                 employee_ref=f"{prefix}-R1",
                                 amount_cents=amount_cents,
                                 external_ref=f"{prefix}-T1",
                                 plan_overrides=plan_overrides)
        close_period(sc["program"]["id"])
        return sc, get_statement_for(sc["assignment"]["id"], 1)

    def test_curve_straddle_uncapped_band_math(self, api):
        """PRD §3.7: "Within each band, in ascending floor order, the band
        credit is the portion of the earned amount that falls inside the band —
        nothing below the lower threshold, and nothing beyond the band's
        width — and the band payout is that band credit multiplied by the
        tier's `rate_bps` and divided by ten thousand, rounded half up to a
        whole cent. The uncapped gross is the sum of all band payouts in that
        pinned ascending order."

        Earned 1200000 at quota 1000000 straddles all three canonical tiers:
        800000*10% + 200000*15% + 200000*25% = 80000 + 30000 + 50000 = 160000.

        Design: Difficulty/combinatorial_formula/curve_marginal_tier_straddle
        """
        _sc, stmt = self._close_with_earned(
            api, "C", 1200000, curve_tiers=CANONICAL_CURVE_TIERS)
        assert_payout_statement(stmt)
        assert stmt["attainment_bps"] == 12000
        assert stmt["gross_payout_cents"] == 160000

    def test_payout_cap_applied_last(self, api):
        """PRD §3.7: "When the plan's `payout_cap_cents` is set,
        `payout_cap_applied` records whether the uncapped gross exceeded the
        cap, and the final `gross_payout_cents` is the smaller of the two; when
        no cap is set, the flag is false and the uncapped figure stands. The
        cap is always applied last, after summation."

        Design: Difficulty/combinatorial_formula/curve_marginal_tier_straddle
        """
        _sc, stmt = self._close_with_earned(
            api, "CC", 1200000, curve_tiers=CANONICAL_CURVE_TIERS,
            payout_cap_cents=150000)
        assert stmt["gross_payout_cents"] == 150000, (
            "min(uncapped 160000, cap 150000)"
        )
        assert stmt["payout_cap_applied"] is True
        assert stmt["net_payable_cents"] == 150000, (
            "no draw and no guarantee: net equals capped gross"
        )

    def test_attainment_just_below_100_percent(self, api):
        """PRD §2.6: "**Integer floor** — fractions always discarded, never
        rounded up — is applied exclusively to basis-point attainment ratios,
        so that an attainment of 9999 out of 10000 basis points cannot be
        presented as quota achieved."
        PRD §3.7: "otherwise `attainment_bps` is the earned total multiplied by
        ten thousand and divided by `quota_cents`, rounded down to a whole
        number, and the gross comes from the quota-to-payout curve with the
        plan cap applied, `deficit_cents` being zero."

        Earned 999990 -> floor(9999.9) = 9999 bps; gross
        80000 + round_half_up(199990*0.15) = 80000 + 29999 = 109999.

        Design: Difficulty/boundary_precision_check/attainment_exactly_100pct_tier_boundary
        """
        _sc, stmt = self._close_with_earned(
            api, "B1", 999990, curve_tiers=CANONICAL_CURVE_TIERS)
        assert stmt["attainment_bps"] == 9999
        assert stmt["gross_payout_cents"] == 109999

    def test_attainment_exactly_100_percent(self, api):
        """PRD §3.7: "Each tier of `curve_tiers` covers a marginal band of
        attainment measured in basis points — from its own
        `attainment_floor_bps` up to but not including the next tier's floor,
        with the highest tier open-ended."

        Earned exactly 1000000 -> 10000 bps: the 10000 floor is the top tier's
        inclusive lower bound, reached with zero band credit; gross
        80000 + 30000 + 0 = 110000.

        Design: Difficulty/boundary_precision_check/attainment_exactly_100pct_tier_boundary
        """
        _sc, stmt = self._close_with_earned(
            api, "B2", 1000000, curve_tiers=CANONICAL_CURVE_TIERS)
        assert stmt["attainment_bps"] == 10000
        assert stmt["gross_payout_cents"] == 110000

    def test_attainment_above_100_percent_top_band_rounding(self, api):
        """PRD §2.6: "**Round half up** is applied whenever a multiplication or
        division would otherwise produce a fractional cent: per-split credit
        allocation, per-band curve payouts, and roll-up amounts each round
        their own intermediate result half up to a whole cent before any
        summation takes place."

        Earned 1000010 -> 10000 bps; the top band holds 10 cents at 25%:
        round_half_up(2.5) = 3, so gross 110003.

        Design: Difficulty/boundary_precision_check/attainment_exactly_100pct_tier_boundary
        """
        _sc, stmt = self._close_with_earned(
            api, "B3", 1000010, curve_tiers=CANONICAL_CURVE_TIERS)
        assert stmt["attainment_bps"] == 10000
        assert stmt["gross_payout_cents"] == 110003


class TestDrawGuaranteeEvaluationOrder:
    def _scenario(self, api):
        sc = setup_posted_credit(
            program_name="Prog ST", plan_name="Plan ST", rep_name="Rep ST",
            employee_ref="ST-R1", amount_cents=1200000, external_ref="ST-T1",
            plan_overrides={"curve_tiers": CANONICAL_CURVE_TIERS},
            assignment_overrides={"draw_amount_cents_per_period": 50000,
                                  "draw_recoverable": True,
                                  "guarantee_amount_cents_per_period": 120000})
        close_period(sc["program"]["id"])
        return sc, get_statement_for(sc["assignment"]["id"], 1)

    def test_draw_recovery_before_guarantee_ordering(self, api):
        """PRD §3.7: "Recovery comes before guarantee: `draw_recovered_cents`
        is the smaller of the gross payout and the post-accrual
        `draw_outstanding_cents`, and the outstanding balance is reduced by the
        recovered amount."
        PRD §3.7: "`draw_paid_cents` equals the assignment's
        `draw_amount_cents_per_period`, since the assignment is `ACTIVE` at
        close. When the assignment is `draw_recoverable`, the paid draw first
        accrues: `draw_outstanding_cents` increases by the paid amount."

        Design: Difficulty/combinatorial_formula/settlement_evaluation_order_draw_guarantee
        """
        sc, stmt = self._scenario(api)
        assert stmt["gross_payout_cents"] == 160000
        assert stmt["draw_paid_cents"] == 50000
        assert stmt["draw_recovered_cents"] == 50000, (
            "min(gross 160000, post-accrual outstanding 50000)"
        )

    def test_net_payable_follows_pinned_evaluation_order(self, api):
        """PRD §3.7: "The guarantee floor then applies:
        `guarantee_trueup_cents` is the greater of zero and the assignment's
        `guarantee_amount_cents_per_period` minus the gross-net-of-recovery
        (gross payout minus draw recovered). `net_payable_cents` is the gross
        payout minus the draw recovered plus the guarantee true-up."
        PRD §3.7: "Finally the ledger syncs: `lifetime_earned_cents` increases
        by the earned total, `lifetime_paid_cents` increases by the net
        payable, and the open-period earned counter resets as described above."

        The pinned order yields 110000 + 10000 = 120000; the reversed order
        (guarantee before recovery) would yield 70000.

        Design: Difficulty/combinatorial_formula/settlement_evaluation_order_draw_guarantee
        """
        sc, stmt = self._scenario(api)
        assert stmt["guarantee_trueup_cents"] == 10000, (
            "max(0, 120000 - (160000 - 50000))"
        )
        assert stmt["net_payable_cents"] == 120000
        assignment = get_assignment(sc["assignment"]["id"])
        assert assignment["draw_outstanding_cents"] == 0, (
            "50000 accrued minus 50000 recovered"
        )
        assert assignment["lifetime_paid_cents"] == 120000


class TestZeroAndNegativeSettlement:
    def test_guarantee_trueup_covers_zero_earnings(self, api):
        """PRD §3.7: "when the earned total is zero or negative,
        `attainment_bps` is 0, `gross_payout_cents` is 0, `payout_cap_applied`
        is false, and `deficit_cents` is the negated earned total (zero when
        the earned total is exactly zero)"
        PRD §3.7: "The guarantee floor then applies: `guarantee_trueup_cents`
        is the greater of zero and the assignment's
        `guarantee_amount_cents_per_period` minus the gross-net-of-recovery
        (gross payout minus draw recovered)."

        Design: Corner/calculations/guarantee_trueup_covers_zero_earnings
        """
        sc = setup_accepted_assignment(
            program_name="Prog GT", plan_name="Plan GT", rep_name="Rep GT",
            employee_ref="GT-R1",
            assignment_overrides={"guarantee_amount_cents_per_period": 120000})
        close_period(sc["program"]["id"])
        stmt = get_statement_for(sc["assignment"]["id"], 1)
        assert stmt["gross_payout_cents"] == 0
        assert stmt["draw_paid_cents"] == 0
        assert stmt["draw_recovered_cents"] == 0
        assert stmt["guarantee_trueup_cents"] == 120000
        assert stmt["net_payable_cents"] == 120000
        assert stmt["attainment_bps"] == 0

    def test_negative_earnings_deficit_flows_to_draw_outstanding(self, api):
        """PRD §3.7: "A positive deficit settles into the draw ledger by
        recoverability: for a recoverable assignment the deficit is added to
        `draw_outstanding_cents`, and for a non-recoverable one it is added to
        `draw_forgiven_cents` instead."
        PRD §3.7: "Second, `adjustments_cents` sums the `amount_cents` of every
        `APPROVED` adjustment of this assignment whose `period_index` equals
        the closing period."

        Design: Corner/calculations/negative_earnings_deficit_flows_to_draw_outstanding
        """
        sc = setup_posted_credit(program_name="Prog DF", plan_name="Plan DF",
                                 rep_name="Rep DF", employee_ref="DF-R1",
                                 amount_cents=200000, external_ref="DF-T1")
        close_period(sc["program"]["id"])  # credit now LOCKED, period 2 open
        cancel_transaction(sc["transaction"]["id"])  # CLAWBACK -200000 in p2
        close_period(sc["program"]["id"])

        stmt = get_statement_for(sc["assignment"]["id"], 2)
        assert stmt["earned_credits_cents"] == 0
        assert stmt["adjustments_cents"] == -200000
        assert stmt["earned_total_cents"] == -200000
        assert stmt["attainment_bps"] == 0
        assert stmt["gross_payout_cents"] == 0
        assert stmt["deficit_cents"] == 200000
        assert stmt["net_payable_cents"] == 0
        assignment = get_assignment(sc["assignment"]["id"])
        assert assignment["draw_outstanding_cents"] == 200000, (
            "draw_recoverable defaults to true: the deficit accrues as debt"
        )

    def test_same_period_reversal_leaves_no_trace(self, api):
        """PRD §3.5: "Reversing a `POSTED` entry whose `posted_period_index` is
        the current open period decrements its assignment's
        `current_period_earned_cents` by the entry's amount; posted entries
        from earlier periods cannot exist, because period close has already
        locked them."
        PRD §3.5: "Reversing a `LOCKED` entry — which only transaction
        cancellation can do, since locked credits survive assignment
        termination — does not rewrite the closed period; instead it creates a
        **clawback adjustment** on that entry's assignment"

        Design: Corner/calculations/curve_input_set_excludes_same_period_reversals
        """
        sc = setup_posted_credit(program_name="Prog ISR", plan_name="Plan ISR",
                                 rep_name="Rep ISR", employee_ref="ISR-R1",
                                 amount_cents=200000, external_ref="ISR-T1")
        cancel_transaction(sc["transaction"]["id"])  # same open period
        close_period(sc["program"]["id"])

        stmt = get_statement_for(sc["assignment"]["id"], 1)
        assert stmt["earned_credits_cents"] == 0
        assert stmt["adjustments_cents"] == 0
        assert stmt["gross_payout_cents"] == 0
        assert stmt["attainment_bps"] == 0
        assert stmt["net_payable_cents"] == 0
        assert list_adjustments(assignment_id=sc["assignment"]["id"]) == [], (
            "no clawback adjustment exists for a same-period reversal"
        )


class TestCloseGatedByDisputes:
    def _scenario(self, api):
        sc = setup_posted_credit(program_name="Prog Gate", plan_name="Plan G",
                                 rep_name="Rep G", employee_ref="G-R1",
                                 amount_cents=200000, external_ref="G-T1",
                                 plan_overrides={
                                     "curve_tiers": CANONICAL_CURVE_TIERS})
        dispute = file_dispute(sc["assignment"]["id"], sc["rep"]["id"], 1,
                               "CURVE_MISAPPLIED", 10000)
        return sc, dispute

    def test_close_blocked_by_open_dispute(self, api):
        """PRD §3.7: "Before the version check runs, the close's business guard
        is evaluated: if any dispute of the program is in `SUBMITTED` or
        `UNDER_REVIEW`, the close is rejected with `ERR_OPEN_DISPUTES_EXIST`;
        only once that guard passes does the stale-version rejection
        (`ERR_STALE_PROGRAM_VERSION`) apply."

        Design: Difficulty/cross_entity_state_dependency/period_close_blocked_by_open_disputes
        """
        sc, _dispute = self._scenario(api)
        program = sc["program"]
        resp = api.close_period(program["id"],
                                close_period_payload(program["version"]), ADMIN)
        validate_error(resp, ApiErrorId.ERR_OPEN_DISPUTES_EXIST, 409)
        still_open = validate_success(api.get_program(program["id"], ADMIN))
        assert still_open["current_period_index"] == 1

    def test_close_succeeds_after_dispute_terminal(self, api):
        """PRD §3.6: "Disputes gate the fiscal calendar: as §3.7 details, any
        dispute of the program still in `SUBMITTED` or `UNDER_REVIEW` blocks
        period close outright."
        PRD §3.7: "It generates one `DRAFT` payout statement per assignment
        whose lifecycle `status` is `ACTIVE` — unique per assignment and
        period."

        Design: Difficulty/cross_entity_state_dependency/period_close_blocked_by_open_disputes
        """
        sc, dispute = self._scenario(api)
        manager = TEST_USERS["comp_manager_headers"]
        validate_success(api.reject_dispute(dispute["id"], manager), 200)

        closed = close_period(sc["program"]["id"])
        assert closed["current_period_index"] == 2
        stmt = get_statement_for(sc["assignment"]["id"], 1)
        assert stmt["earned_credits_cents"] == 200000
        assert stmt["status"] == "DRAFT"


class TestProvisionalVsFinal:
    def _scenario(self, api):
        """Accepted-never assignment (OFFERED) + 1200000 transaction parked
        PENDING."""
        sc = setup_posted_credit(program_name="Prog Prov", plan_name="Plan P",
                                 rep_name="Rep Prov", employee_ref="P-R1",
                                 amount_cents=1200000, external_ref="P-T1",
                                 accept=False,
                                 plan_overrides={
                                     "curve_tiers": CANONICAL_CURVE_TIERS})
        return sc

    def test_provisional_payout_includes_pending_credits(self, api):
        """PRD §3.4: "`provisional_period_payout_cents` is the forward-looking
        estimate: the curve of §3.7 applied to the mode-filtered sum of
        `current_period_earned_cents` **plus** all `PENDING` credits of the
        assignment, assuming future acceptance — with the plan cap, draws, and
        guarantees all ignored, since the provisional figure is a gross-curve
        estimate only."

        Canonical curve over 0 earned + 1200000 PENDING: 80000 + 30000 +
        50000 = 160000.

        Design: Difficulty/dual_variant_calc/payout_provisional_vs_final_estimate
        """
        sc = self._scenario(api)
        assert sc["credit"]["status"] == "PENDING"
        assignment = get_assignment(sc["assignment"]["id"])
        assert assignment["current_period_earned_cents"] == 0, (
            "a PENDING credit never increments the earned counter"
        )
        assert assignment["provisional_period_payout_cents"] == 160000

    def test_final_statement_excludes_pending_credits(self, api):
        """PRD §3.7: "First, `earned_credits_cents` captures the assignment's
        `current_period_earned_cents` filtered by the plan's
        `attainment_mode`, exactly as §3.4 defines the mode filter."
        PRD §3.7: "when the earned total is zero or negative, `attainment_bps`
        is 0, `gross_payout_cents` is 0, `payout_cap_applied` is false, and
        `deficit_cents` is the negated earned total (zero when the earned
        total is exactly zero)"

        The final settlement draws only on the earned counter — the PENDING
        credit is excluded — so the identical underlying credit yields
        provisional 160000 but final gross 0.

        Design: Difficulty/dual_variant_calc/payout_provisional_vs_final_estimate
        """
        sc = self._scenario(api)
        close_period(sc["program"]["id"])
        stmt = get_statement_for(sc["assignment"]["id"], 1)
        assert stmt["earned_credits_cents"] == 0
        assert stmt["gross_payout_cents"] == 0
        assignment = get_assignment(sc["assignment"]["id"])
        assert assignment["provisional_period_payout_cents"] == 160000, (
            "the PENDING credit is still assumed to post in the future"
        )
