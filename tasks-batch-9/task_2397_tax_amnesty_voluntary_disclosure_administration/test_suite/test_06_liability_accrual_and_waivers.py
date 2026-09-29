"""Statutory accrual, the two liability variants, and the waiver rollup.

Filing is where the money is computed. PRD §3.5 selects the accrual cutoff
from the agreement's `liability_variant`, tiers the penalty rate on
`days_late`, and then re-resolves the waiver for the whole agreement — which
means one filing can rewrite the stored figures of returns filed earlier.
"""

from test_helpers import (
    AUDITOR_ONE_HEADERS,
    CANONICAL_BALANCE_DUE_CENTS,
    CANONICAL_DAYS_LATE,
    CANONICAL_GROSS_INTEREST_CENTS,
    CANONICAL_GROSS_LIABILITY_CENTS,
    CANONICAL_GROSS_PENALTY_CENTS,
    CANONICAL_PENALTY_RATE,
    CANONICAL_TOTAL_DUE_CENTS,
    CANONICAL_WAIVED_AMOUNT_CENTS,
    CANONICAL_WAIVED_INTEREST_CENTS,
    CANONICAL_WAIVED_PENALTY_CENTS,
    CANONICAL_WINDOW_CLOSE_DATE,
    assert_fields,
    draft_and_file_return,
    draft_return,
    file_return,
    read_agreement,
    read_return,
    setup_executed_agreement,
    setup_filed_return,
    setup_negotiated_agreement,
    validate_success,
)

NEGOTIATED_OFFER = {
    "offered_lookback_months": 36,
    "offered_penalty_waiver_pct": 1.00,
    "offered_interest_waiver_pct": 0.50,
}
QUARTER_2_2025 = {
    "period_start_date": "2025-04-01",
    "period_end_date": "2025-06-30",
}
QUARTER_3_2025 = {
    "period_start_date": "2025-07-01",
    "period_end_date": "2025-09-30",
}


class TestAccrualCutoffVariants:
    """One operand differs between the two variants: the accrual cutoff."""

    def test_a_walk_in_accrues_to_the_end_of_the_program_window(self, api):
        """`AMNESTY_STATUTORY` ignores when the walk-in actually filed.

        PRD §3.5: "Under `AMNESTY_STATUTORY` the return's `accrual_end_date` is
        the calendar date of the program's `window_close_at` — a walk-in accrues
        all the way to the end of the program window no matter how early it
        files, because nothing the walk-in does stops the statutory clock."

        PRD §3.5: "The base penalty rate is then selected by tier: 5 percent when
        `days_late` is at most 90; 15 percent when `days_late` is more than 90
        and at most 365; and 25 percent when `days_late` is more than 365."

        Design: Difficulty/dual_variant_calc/statutory_vs_negotiated_accrual_cutoff_divergence
        """
        ctx = setup_filed_return(
            api,
            program_overrides={"installment_max_count": 12},
            taxpayer_overrides={
                "legal_name": "Northline Supply LLC",
                "tin_last4": "4417",
            },
        )

        assert_fields(
            ctx["disclosure_return"],
            accrual_end_date=CANONICAL_WINDOW_CLOSE_DATE,
            days_late=CANONICAL_DAYS_LATE,
            penalty_rate_applied=CANONICAL_PENALTY_RATE,
            gross_penalty_cents=CANONICAL_GROSS_PENALTY_CENTS,
            gross_interest_cents=CANONICAL_GROSS_INTEREST_CENTS,
            waived_penalty_cents=CANONICAL_WAIVED_PENALTY_CENTS,
            waived_interest_cents=CANONICAL_WAIVED_INTEREST_CENTS,
            balance_due_cents=CANONICAL_BALANCE_DUE_CENTS,
        )
        assert_fields(
            ctx["agreement"],
            liability_variant="AMNESTY_STATUTORY",
            gross_liability_cents=CANONICAL_GROSS_LIABILITY_CENTS,
            waived_amount_cents=CANONICAL_WAIVED_AMOUNT_CENTS,
        )

    def test_a_negotiated_agreement_freezes_accrual_at_execution(self, api):
        """`VDA_NEGOTIATED` stops the clock on the day the department signs.

        PRD §3.5: "Under `VDA_NEGOTIATED` the return's `accrual_end_date` is the
        calendar date of the agreement's `executed_at` — executing the
        negotiated agreement freezes the clock, so whenever execution happened
        before the window closes, an otherwise identical return carries a
        strictly smaller liability than the walk-in variant would."

        PRD §3.5: "when the agreement's `liability_variant` is `VDA_NEGOTIATED`,
        the pair is the linked pre-clearance's `current_offer_penalty_waiver_pct`
        and `current_offer_interest_waiver_pct`, because the negotiated offer
        overrides everything the program published"

        Design: Difficulty/dual_variant_calc/statutory_vs_negotiated_accrual_cutoff_divergence
        """
        ctx = setup_negotiated_agreement(
            api,
            program_overrides={"installment_max_count": 12},
            taxpayer_overrides={
                "legal_name": "Cedar Point Fabrication LLC",
                "tin_last4": "9082",
            },
            pre_clearance_overrides={
                "anonymous_alias": "CLIENT-77",
                "estimated_liability_cents": 1000000,
                "earliest_unfiled_period_start": "2025-01-01",
            },
            offer_overrides=NEGOTIATED_OFFER,
            execute_at="2026-09-20T00:00:00Z",
        )
        filed = draft_and_file_return(api, ctx)

        assert_fields(
            filed,
            accrual_end_date="2026-09-20",
            days_late=328,
            penalty_rate_applied=0.15,
            gross_penalty_cents=150000,
            gross_interest_cents=82000,
            waived_penalty_cents=150000,
            waived_interest_cents=41000,
            balance_due_cents=1041000,
        )
        assert_fields(
            read_agreement(api, ctx["agreement"]["id"]),
            liability_variant="VDA_NEGOTIATED",
            gross_liability_cents=1232000,
            waived_amount_cents=191000,
        )


class TestPenaltyTierBoundary:
    """The first tier boundary is inclusive at exactly 90 days late."""

    def test_ninety_days_takes_the_first_tier_and_ninety_one_the_second(self, api):
        """Two returns one day apart land in different rate tiers.

        PRD §3.5: "The base penalty rate is then selected by tier: 5 percent when
        `days_late` is at most 90; 15 percent when `days_late` is more than 90
        and at most 365; and 25 percent when `days_late` is more than 365."

        PRD §3.5: "`days_late` is the number of whole days from
        `original_due_date` to `accrual_end_date`, floored at 0 so a cutoff
        earlier than the due date yields zero rather than a negative count."

        Design: Corner/Table 3 Calculations/penalty_tier_boundary_at_ninety_days_late
        """
        ctx = setup_executed_agreement(
            api,
            taxpayer_overrides={
                "legal_name": "Verdant Row Landscaping LLC",
                "tin_last4": "8123",
            },
        )
        return_a = draft_return(api, ctx, original_due_date="2026-09-02")
        return_b = draft_return(
            api, ctx, original_due_date="2026-09-01", **QUARTER_2_2025
        )

        filed_a = file_return(api, ctx, return_a["id"])
        assert_fields(
            filed_a,
            accrual_end_date=CANONICAL_WINDOW_CLOSE_DATE,
            days_late=90,
            penalty_rate_applied=0.05,
            gross_penalty_cents=50000,
            gross_interest_cents=22500,
            waived_penalty_cents=50000,
            waived_interest_cents=11250,
            balance_due_cents=1011250,
        )

        filed_b = file_return(api, ctx, return_b["id"])
        assert_fields(
            filed_b,
            days_late=91,
            penalty_rate_applied=0.15,
            gross_penalty_cents=150000,
            gross_interest_cents=22750,
            waived_interest_cents=11375,
            balance_due_cents=1011375,
        )

        assert_fields(
            read_agreement(api, ctx["agreement"]["id"]),
            gross_liability_cents=2245250,
            haircut_pct=0.00,
            waived_amount_cents=222625,
            total_due_cents=2022625,
        )


class TestWaiverRollup:
    """Each component is rounded once, and the rollup sums rounded values."""

    def test_each_return_rounds_its_two_components_independently(self, api):
        """A tax figure that divides badly rounds penalty and interest apart.

        PRD §3.5: "Finally, `gross_penalty_cents` is `reported_tax_cents`
        multiplied by `penalty_rate_applied`, rounded half up to whole cents; and
        `gross_interest_cents` is `reported_tax_cents` multiplied by a daily
        interest rate of 0.00025 and by `days_late`, rounded half up to whole
        cents. The two components are rounded independently and each is rounded
        exactly once."

        PRD §3.5: "`waived_interest_cents` is `gross_interest_cents` multiplied
        by `effective_interest_waiver_pct`, rounded half up to whole cents"

        Design: Difficulty/combinatorial_formula/waiver_rollup_sums_per_return_rounded_components
        """
        ctx = setup_filed_return(
            api,
            taxpayer_overrides={
                "legal_name": "Marrow Grove Cabinetry LLC",
                "tin_last4": "6650",
            },
            return_overrides={"reported_tax_cents": 67891},
        )
        return_b = draft_and_file_return(
            api, ctx, reported_tax_cents=67891, **QUARTER_2_2025
        )

        assert_fields(
            read_return(api, ctx["disclosure_return"]["id"]),
            gross_penalty_cents=16973,
            gross_interest_cents=6789,
            waived_penalty_cents=16973,
            waived_interest_cents=3395,
            payable_interest_cents=3394,
            balance_due_cents=71285,
        )
        assert_fields(
            return_b, waived_interest_cents=3395, balance_due_cents=71285
        )

    def test_the_agreement_sums_already_rounded_per_return_figures(self, api):
        """The rollup adds rounded cents rather than rounding a raw sum.

        PRD §3.5: "The agreement's `waived_amount_cents` is then the sum, over
        its qualifying returns, of `waived_penalty_cents` plus
        `waived_interest_cents` — a sum of already-rounded values, never a
        rounding of a raw sum"

        PRD §3.5: "`gross_liability_cents` is the sum, over the agreement's
        returns whose `status` is `FILED`, `ASSESSED` or `SETTLED`, of
        `reported_tax_cents` plus `gross_penalty_cents` plus
        `gross_interest_cents`."

        Design: Difficulty/combinatorial_formula/waiver_rollup_sums_per_return_rounded_components
        """
        ctx = setup_filed_return(
            api,
            taxpayer_overrides={
                "legal_name": "Marrow Grove Cabinetry LLC",
                "tin_last4": "6650",
            },
            return_overrides={"reported_tax_cents": 67891},
        )
        draft_and_file_return(api, ctx, reported_tax_cents=67891, **QUARTER_2_2025)

        assert_fields(
            read_agreement(api, ctx["agreement"]["id"]),
            gross_liability_cents=183306,
            haircut_pct=0.00,
            waived_amount_cents=40736,
            total_due_cents=142570,
        )


class TestHaircutResolutionOrder:
    """The haircut is chosen from the pre-waiver aggregate, then applied back."""

    def test_below_the_threshold_the_base_waiver_applies_untouched(self, api):
        """Two returns short of the boundary keep the published waiver pair.

        PRD §3.5: "`haircut_pct` is 0.25 when `gross_liability_cents` is at least
        250,000 dollars, otherwise 0.10 when `gross_liability_cents` is at least
        50,000 dollars, otherwise 0.00 — both comparisons inclusive at the
        boundary."

        Design: Difficulty/combinatorial_formula/haircut_resolution_order_revises_previously_filed_returns
        """
        ctx = setup_filed_return(
            api,
            taxpayer_overrides={
                "legal_name": "Alder Basin Distribution LLC",
                "tin_last4": "3390",
            },
        )
        draft_and_file_return(api, ctx, reported_tax_cents=2000000, **QUARTER_2_2025)

        assert_fields(
            read_return(api, ctx["disclosure_return"]["id"]),
            waived_penalty_cents=250000,
            waived_interest_cents=50000,
            balance_due_cents=1050000,
        )
        assert_fields(
            read_agreement(api, ctx["agreement"]["id"]),
            gross_liability_cents=4050000,
            haircut_pct=0.00,
            waived_amount_cents=900000,
            total_due_cents=3150000,
        )

    def test_crossing_the_threshold_revises_the_returns_filed_earlier(self, api):
        """The third filing rewrites rows one and two that the client never touched.

        PRD §3.5: "Because step two aggregates across every qualifying return,
        filing the Nth return can push the agreement across a haircut threshold
        and therefore **revise the already-stored waiver figures of returns one
        through N minus one**."

        PRD §3.5: "`effective_penalty_waiver_pct` is the base penalty fraction
        minus `haircut_pct`, and `effective_interest_waiver_pct` is the base
        interest fraction minus **half** of `haircut_pct`, each floored at 0.00
        so a haircut larger than the base waiver produces no waiver rather than a
        negative one."

        Design: Difficulty/combinatorial_formula/haircut_resolution_order_revises_previously_filed_returns
        """
        ctx = setup_filed_return(
            api,
            taxpayer_overrides={
                "legal_name": "Alder Basin Distribution LLC",
                "tin_last4": "3390",
            },
        )
        return_two = draft_and_file_return(
            api, ctx, reported_tax_cents=2000000, **QUARTER_2_2025
        )
        return_three = draft_and_file_return(
            api, ctx, reported_tax_cents=703704, **QUARTER_3_2025
        )

        assert_fields(
            read_agreement(api, ctx["agreement"]["id"]),
            gross_liability_cents=5000000,
            haircut_pct=0.10,
            waived_amount_cents=1000000,
            total_due_cents=4000000,
        )
        assert_fields(
            read_return(api, ctx["disclosure_return"]["id"]),
            waived_penalty_cents=225000,
            waived_interest_cents=45000,
            balance_due_cents=1080000,
        )
        assert_fields(
            read_return(api, return_two["id"]),
            waived_penalty_cents=450000,
            balance_due_cents=2160000,
        )
        assert_fields(
            read_return(api, return_three["id"]),
            waived_penalty_cents=158333,
            waived_interest_cents=31667,
            balance_due_cents=760000,
        )


class TestDraftsAreExcluded:
    """Only filed and later returns feed the agreement's aggregates."""

    def test_a_draft_return_contributes_nothing_until_it_is_filed(self, api):
        """The aggregate names three statuses and `DRAFT` is not one of them.

        PRD §3.5: "`gross_liability_cents` is the sum, over the agreement's
        returns whose `status` is `FILED`, `ASSESSED` or `SETTLED`, of
        `reported_tax_cents` plus `gross_penalty_cents` plus
        `gross_interest_cents`."

        PRD §3.5: "The return records the owning `agreement_id` from the path,
        enters with `status` `DRAFT`, and holds `filed_at`, `accrual_end_date`,
        `penalty_rate_applied` and `assessed_by_user_id` null with `days_late`,
        `gross_penalty_cents`, `gross_interest_cents`, `waived_penalty_cents`,
        `waived_interest_cents`, `payable_penalty_cents`,
        `payable_interest_cents` and `balance_due_cents` all at 0."

        Design: Corner/Table 3 Calculations/gross_liability_excludes_returns_still_in_draft
        """
        ctx = setup_filed_return(
            api,
            taxpayer_overrides={
                "legal_name": "Kilnbrook Ceramics LLC",
                "tin_last4": "9934",
            },
        )
        pending = draft_return(api, ctx, reported_tax_cents=500000, **QUARTER_2_2025)

        assert_fields(
            pending,
            status="DRAFT",
            accrual_end_date=None,
            days_late=0,
            gross_penalty_cents=0,
            gross_interest_cents=0,
            balance_due_cents=0,
        )
        assert_fields(
            validate_success(
                api.get_agreement(ctx["agreement"]["id"], AUDITOR_ONE_HEADERS)
            ),
            gross_liability_cents=CANONICAL_GROSS_LIABILITY_CENTS,
            waived_amount_cents=CANONICAL_WAIVED_AMOUNT_CENTS,
            total_due_cents=CANONICAL_TOTAL_DUE_CENTS,
        )

        filed = file_return(api, ctx, pending["id"])
        assert_fields(
            filed,
            gross_penalty_cents=125000,
            gross_interest_cents=50000,
            waived_interest_cents=25000,
            balance_due_cents=525000,
        )
        assert_fields(
            validate_success(
                api.get_agreement(ctx["agreement"]["id"], AUDITOR_ONE_HEADERS)
            ),
            gross_liability_cents=2025000,
            haircut_pct=0.00,
            waived_amount_cents=450000,
            total_due_cents=1575000,
        )
        assert_fields(
            read_return(api, ctx["disclosure_return"]["id"]),
            balance_due_cents=CANONICAL_BALANCE_DUE_CENTS,
        )
