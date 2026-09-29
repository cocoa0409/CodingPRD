"""The release walk, per-line rounding, the retainage cliff and the funding cascade."""

import pytest

from test_helpers import (
    LedgerEntryType,
    LoanConstructionStatus,
    LoanExitStatus,
    LoanPaymentStatus,
    RehabLineItemStatus,
    VerificationMethod,
    api_client,
    assert_loan_axes,
    assert_loan_buckets,
    assert_contractor_waiver_figures,
    factories,
    fixtures,
    validate_paginated,
    validate_success,
    LOAN_OFFICER,
    SERVICER,
    SERVICER_2,
)

DRAW_CLOCK = "2026-09-01T12:00:00Z"
FUNDING_DATE = "2026-09-01"
ODD_CENT_SCOPE = [
    fixtures.ScopeSpec("ROOF", 333_333, 0, "Tear-off and re-deck"),
    fixtures.ScopeSpec("KITCHEN", 333_333, 0, "Cabinets and counters"),
    fixtures.ScopeSpec("BATH", 333_335, 0, "Primary bath gut"),
]
SMALL_PROPERTY = {
    "purchase_price_cents": 10_000_000,
    "as_is_value_cents": 10_500_000,
    "arv_cents": 16_000_000,
}


def _two_line_loan():
    """A closed loan with two 2,500,000 lines and a 5,000,000 rehab holdback."""
    ctx = fixtures.build_closed_loan(scope=tuple(fixtures.TWO_LINE_SCOPE))
    fixtures.file_waiver(ctx.loan_id, ctx.contractor_id(1), 2_000_000)
    fixtures.set_clock(DRAW_CLOCK)
    return ctx


def _three_line_loan():
    """A closed loan whose two trades are covered to 3,400,000 and 700,000."""
    ctx = fixtures.build_closed_loan()
    fixtures.file_waiver(ctx.loan_id, ctx.contractor_id(0), 3_400_000)
    fixtures.file_waiver(ctx.loan_id, ctx.contractor_id(1), 700_000)
    fixtures.set_clock(DRAW_CLOCK)
    return ctx


def _standard_draw(ctx):
    """The 0.60/0.45/0.33 request verified at 0.50/0.45/0.30 — 3,892,500 releasable."""
    lines = [ctx.line_by_code(code)["id"] for code in ("ROOF", "KITCHEN", "ELECTRICAL")]
    draw, _ = fixtures.build_inspected_draw(
        ctx,
        [(lines[0], 0.60), (lines[1], 0.45), (lines[2], 0.33)],
        [(lines[0], 0.50), (lines[1], 0.45), (lines[2], 0.30)],
    )
    return lines, draw


def _allocations(draw_id):
    rows, _ = validate_paginated(
        api_client.list_draw_line_items(SERVICER, {"draw_request_id": draw_id})
    )
    return {row["rehab_line_item_id"]: row for row in rows}


class TestPhotoCapVersusInspectionRetainage:
    def test_the_photo_release_then_the_inspection_top_up_reach_the_inspection_figure(self):
        """The photo leg pays 1,000,000 of a 0.70 claim; inspection then adds 575,000.

        Both legs read the same 0.70 claim on the same 2,500,000 line, but the
        photo leg caps effective completion at 0.50 and withholds 20 percent, so it
        stops at 1,000,000 — and the later inspection draw, which is uncapped and
        withholds 10 percent, tops the line up to the 1,575,000 a single inspection
        draw would have released outright. The PRD states: "Since a photo draw caps
        effective completion at 0.50 and withholds 20 percent, it can never release
        more than 40 percent of a scope line's approved cost, whereas an inspection
        draw at full completion releases the whole approved cost."

        Design: Difficulty/dual_variant_calc/draw_release_photo_cap_vs_inspection_retainage_on_same_scope_line
        """
        ctx = _two_line_loan()
        electrical_id = ctx.line_by_code("ELECTRICAL")["id"]

        photo = fixtures.build_photo_verified_draw(
            ctx, [(electrical_id, 0.70)], [(electrical_id, 0.70)], 3
        )
        assert photo["requested_total_cents"] == 1_750_000
        photo_alloc = _allocations(photo["id"])[electrical_id]
        assert photo_alloc["effective_percent_complete"] == pytest.approx(0.50), (
            "the photo ceiling caps a 0.70 claim at 0.50"
        )

        approved_photo = fixtures.review_draw(photo["id"])
        assert approved_photo["approved_release_cents"] == 1_000_000
        fixtures.fund_draw(photo["id"], funding_date=FUNDING_DATE)
        line = fixtures.read_line(electrical_id)
        assert line["released_cents"] == 1_000_000
        assert float(line["released_percent"]) == pytest.approx(0.40)
        assert line["status"] == RehabLineItemStatus.APPROVED.value

        inspected, _ = fixtures.build_inspected_draw(
            ctx, [(electrical_id, 0.70)], [(electrical_id, 0.70)]
        )
        assert inspected["requested_total_cents"] == 750_000, (
            "intake nets the already-released 1,000,000 out of the request"
        )
        insp_alloc = _allocations(inspected["id"])[electrical_id]
        assert insp_alloc["effective_percent_complete"] == pytest.approx(0.70), (
            "the inspection leg does not cap effective completion"
        )

        approved_insp = fixtures.review_draw(inspected["id"])
        assert approved_insp["approved_release_cents"] == 575_000
        assert 1_000_000 + 575_000 == 1_575_000, (
            "the two legs together reach the single-inspection-draw figure"
        )

        loan = ctx.refresh_loan()
        assert loan["reserved_release_cents"] == 575_000
        assert loan["undisbursed_holdback_cents"] == 3_425_000
        assert loan["commitment_balance_check_cents"] == 0

    def test_the_two_legs_diverge_by_575000_from_an_identical_starting_state(self):
        """Same line, same claim, nothing released yet — only the method differs.

        Superseding the approved photo draw returns the line to a released_cents of
        0, so the inspection draw that replaces it is priced from exactly the state
        the photo draw was priced from, and it approves 1,575,000 against the photo
        leg's 1,000,000. The PRD states: "computes a releasable figure as that
        earned figure multiplied by one minus the retainage, again rounded half up
        to whole cents"

        Design: Difficulty/dual_variant_calc/draw_release_photo_cap_vs_inspection_retainage_on_same_scope_line
        """
        ctx = _two_line_loan()
        electrical_id = ctx.line_by_code("ELECTRICAL")["id"]

        photo = fixtures.build_photo_verified_draw(
            ctx, [(electrical_id, 0.70)], [(electrical_id, 0.70)], 3
        )
        photo_release = fixtures.review_draw(photo["id"])["approved_release_cents"]
        assert photo_release == 1_000_000
        assert ctx.refresh_loan()["reserved_release_cents"] == 1_000_000
        assert fixtures.read_line(electrical_id)["released_cents"] == 0, (
            "an approved but unfunded draw releases nothing"
        )

        inspected, _ = fixtures.build_inspected_draw(
            ctx, [(electrical_id, 0.70)], [(electrical_id, 0.70)]
        )
        reversed_photo = fixtures.read_draw_request(photo["id"])
        assert reversed_photo["approved_release_cents"] is None, (
            "the supersede unwinds the photo approval"
        )
        assert inspected["requested_total_cents"] == 1_750_000, (
            "the line is still at zero released, so the request is the full 0.70 claim"
        )

        inspection_release = fixtures.review_draw(inspected["id"])[
            "approved_release_cents"
        ]
        assert inspection_release == 1_575_000
        assert inspection_release - photo_release == 575_000, (
            "verification_method alone moves the release by 575,000"
        )

        loan = ctx.refresh_loan()
        assert loan["reserved_release_cents"] == 1_575_000
        assert loan["undisbursed_holdback_cents"] == 3_425_000
        assert loan["commitment_balance_check_cents"] == 0


class TestPerLineRoundingOrder:
    def _odd_cent_loan(self):
        ctx = fixtures.build_closed_loan(
            scope=ODD_CENT_SCOPE, property_overrides=SMALL_PROPERTY
        )
        assert ctx.application["approved_rehab_total_cents"] == 1_000_001
        assert ctx.loan["undisbursed_holdback_cents"] == 1_000_001
        fixtures.file_waiver(
            ctx.loan_id, ctx.contractor_id(0), 1_100_000, "FINAL_UNCONDITIONAL"
        )
        fixtures.set_clock(DRAW_CLOCK)
        return ctx, [ctx.line_by_code(code)["id"] for code in ("ROOF", "KITCHEN", "BATH")]

    def test_each_line_is_rounded_before_the_release_is_summed(self):
        """450,001, not the 450,000 that rounding the aggregate once would give.

        Two lines of 333,333 and one of 333,335 verified at exactly 0.50 round to
        150,000 / 150,000 / 150,001, while the unrounded line values sum to
        450,000.45 and would round to 450,000 — so the extra cent exists only
        because each line is rounded on its own. The PRD states: "Each line is
        rounded to whole cents first and the rounded line amounts are then summed;
        summing unrounded line values and rounding the total once is a different
        number and is wrong."

        Design: Difficulty/combinatorial_formula/mode_b_per_line_retainage_rounding_vs_sum_then_round
        """
        ctx, lines = self._odd_cent_loan()
        claims = [(line_id, 0.50) for line_id in lines]
        draw, _ = fixtures.build_inspected_draw(ctx, claims, claims)

        approved = fixtures.review_draw(draw["id"])
        allocations = _allocations(draw["id"])
        assert allocations[lines[0]]["approved_amount_cents"] == 150_000
        assert allocations[lines[1]]["approved_amount_cents"] == 150_000
        assert allocations[lines[2]]["approved_amount_cents"] == 150_001, (
            "the 333,335 line rounds up where its 333,333 siblings round down"
        )
        assert approved["approved_release_cents"] == 450_001, (
            "the per-line sum is 450,001; a single rounding of the aggregate gives 450,000"
        )

        loan = ctx.refresh_loan()
        assert loan["reserved_release_cents"] == 450_001
        assert loan["undisbursed_holdback_cents"] == 550_000
        assert loan["commitment_balance_check_cents"] == 0

    def test_intake_rounds_each_allocation_before_summing_the_request(self):
        """The same rounding order governs the requested figures, then the 1.00 top-up.

        Intake produces 166,667 / 166,667 / 166,668 for a total of 500,002 where a
        single rounding of the 1,000,001 aggregate would give 500,001, and the
        retainage-free second draw releases exactly the 550,000 that remains, so
        the odd cent lands on the 333,335 line and nowhere else. The PRD states:
        "The request's `requested_total_cents` is the sum of its allocations'
        `requested_amount_cents`"

        Design: Difficulty/combinatorial_formula/mode_b_per_line_retainage_rounding_vs_sum_then_round
        """
        ctx, lines = self._odd_cent_loan()
        claims = [(line_id, 0.50) for line_id in lines]
        first, _ = fixtures.build_inspected_draw(ctx, claims, claims)

        requested = _allocations(first["id"])
        assert requested[lines[0]]["requested_amount_cents"] == 166_667
        assert requested[lines[1]]["requested_amount_cents"] == 166_667
        assert requested[lines[2]]["requested_amount_cents"] == 166_668
        assert first["requested_total_cents"] == 500_002, (
            "500,002 per line against the 500,001 a single aggregate rounding gives"
        )

        fixtures.review_draw(first["id"])
        fixtures.fund_draw(first["id"], funding_date=FUNDING_DATE)
        released = {line_id: fixtures.read_line(line_id)["released_cents"] for line_id in lines}
        assert released == {lines[0]: 150_000, lines[1]: 150_000, lines[2]: 150_001}

        top_up_claims = [(line_id, 1.0) for line_id in lines]
        second, _ = fixtures.build_inspected_draw(ctx, top_up_claims, top_up_claims)
        finish = fixtures.review_draw(second["id"])
        final = _allocations(second["id"])
        assert final[lines[0]]["approved_amount_cents"] == 183_333
        assert final[lines[1]]["approved_amount_cents"] == 183_333
        assert final[lines[2]]["approved_amount_cents"] == 183_334
        assert finish["approved_release_cents"] == 550_000, (
            "the retainage-free finish clears the holdback to the cent"
        )

        fixtures.fund_draw(second["id"], funding_date=FUNDING_DATE)
        loan = ctx.refresh_loan()
        assert loan["undisbursed_holdback_cents"] == 0
        assert loan["reserved_release_cents"] == 0
        assert loan["commitment_balance_check_cents"] == 0
        for line_id, approved_cost in zip(lines, (333_333, 333_333, 333_335)):
            line = fixtures.read_line(line_id)
            assert line["released_cents"] == approved_cost
            assert line["status"] == RehabLineItemStatus.FULLY_RELEASED.value


class TestRetainageCliff:
    def _partly_released_loan(self):
        ctx = fixtures.build_closed_loan()
        fixtures.cover_all_contractors(ctx, 10_000_000)
        fixtures.set_clock(DRAW_CLOCK)
        lines, draw = _standard_draw(ctx)
        fixtures.review_draw(draw["id"])
        fixtures.fund_draw(draw["id"], funding_date=FUNDING_DATE)
        assert fixtures.read_line(lines[0])["released_cents"] == 1_800_000
        assert ctx.refresh_loan()["undisbursed_holdback_cents"] == 6_107_500
        return ctx, lines

    def test_the_last_one_percent_of_completion_is_worth_436000(self):
        """0.99 approves 1,764,000; 1.00 approves 2,200,000 on the same line.

        Retainage is withheld in full at 0.99 and vanishes at exactly 1.00, so the
        final hundredth of the roof line carries 40,000 of new work plus the
        396,000 of retainage held back on the 3,960,000 earned to date. The PRD
        states: "Because retainage falls away entirely at 1.00, the last dollar of
        completion on a line releases both the final increment of work and all
        previously withheld retainage."

        Design: Difficulty/boundary_precision_check/retainage_cliff_at_exactly_one_hundred_percent_complete
        """
        ctx, lines = self._partly_released_loan()
        roof_id = lines[0]

        nearly, _ = fixtures.build_inspected_draw(
            ctx, [(roof_id, 0.99)], [(roof_id, 0.99)]
        )
        assert nearly["requested_total_cents"] == 2_160_000
        nearly_approved = fixtures.review_draw(nearly["id"])
        assert nearly_approved["approved_release_cents"] == 1_764_000, (
            "10 percent of the 3,960,000 earned is still withheld at 0.99"
        )
        assert ctx.refresh_loan()["reserved_release_cents"] == 1_764_000

        complete, _ = fixtures.build_inspected_draw(
            ctx, [(roof_id, 1.0)], [(roof_id, 1.0)]
        )
        superseded = fixtures.read_draw_request(nearly["id"])
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["superseded_by_draw_request_id"] == complete["id"]
        assert superseded["approved_release_cents"] is None

        full_approved = fixtures.review_draw(complete["id"])
        assert full_approved["approved_release_cents"] == 2_200_000
        assert 2_200_000 - 1_764_000 == 436_000, (
            "one extra hundredth of completion is worth 436,000"
        )

        loan = ctx.refresh_loan()
        assert loan["reserved_release_cents"] == 2_200_000
        assert loan["undisbursed_holdback_cents"] == 3_907_500
        assert loan["commitment_balance_check_cents"] == 0
        still_open = fixtures.read_line(roof_id)
        assert still_open["released_cents"] == 1_800_000
        assert still_open["status"] == RehabLineItemStatus.APPROVED.value

    def test_the_retainage_is_paid_out_only_once_the_line_actually_reaches_1_00(self):
        """Funding at 0.99 leaves the line short; the follow-on draw is exactly 436,000.

        A funded 0.99 draw takes the line to 3,564,000 and a released_percent of
        0.8910 while it stays `APPROVED`, and the next draw at 1.00 releases the
        436,000 balance in one go — the same cliff figure, now reached by two
        separate disbursements. The PRD states: "sets retainage to zero when the
        effective completion is exactly 1.00, and otherwise to 10 percent on an
        `INSPECTION` request or 20 percent on a `PHOTO` request"

        Design: Difficulty/boundary_precision_check/retainage_cliff_at_exactly_one_hundred_percent_complete
        """
        ctx, lines = self._partly_released_loan()
        roof_id = lines[0]

        nearly, _ = fixtures.build_inspected_draw(
            ctx, [(roof_id, 0.99)], [(roof_id, 0.99)]
        )
        fixtures.review_draw(nearly["id"])
        fixtures.fund_draw(nearly["id"], funding_date=FUNDING_DATE)
        partial = fixtures.read_line(roof_id)
        assert partial["released_cents"] == 3_564_000
        assert float(partial["released_percent"]) == pytest.approx(0.8910)
        assert partial["status"] == RehabLineItemStatus.APPROVED.value, (
            "0.99 of completion never fully releases a line"
        )
        assert ctx.refresh_loan()["construction_status"] == (
            LoanConstructionStatus.IN_PROGRESS.value
        )

        fixtures.file_waiver(
            ctx.loan_id, ctx.contractor_id(0), 10_000_000, "FINAL_UNCONDITIONAL"
        )
        finish, _ = fixtures.build_inspected_draw(
            ctx, [(roof_id, 1.0)], [(roof_id, 1.0)]
        )
        assert finish["requested_total_cents"] == 436_000
        approved = fixtures.review_draw(finish["id"])
        assert approved["approved_release_cents"] == 436_000, (
            "the withheld 396,000 plus the final 40,000 of work"
        )

        fixtures.fund_draw(finish["id"], funding_date=FUNDING_DATE)
        done = fixtures.read_line(roof_id)
        assert done["released_cents"] == 4_000_000
        assert float(done["released_percent"]) == pytest.approx(1.0)
        assert done["status"] == RehabLineItemStatus.FULLY_RELEASED.value

        loan = ctx.refresh_loan()
        assert loan["undisbursed_holdback_cents"] == 3_907_500
        assert loan["construction_status"] == LoanConstructionStatus.IN_PROGRESS.value, (
            "two of the three lines are still open, so construction is not complete"
        )
        assert loan["commitment_balance_check_cents"] == 0


class TestFundingCascade:
    def _two_line_loan_with_final_waivers(self):
        ctx = fixtures.build_closed_loan(scope=tuple(fixtures.TWO_LINE_SCOPE))
        for index in (0, 1):
            fixtures.file_waiver(
                ctx.loan_id, ctx.contractor_id(index), 2_500_000, "FINAL_UNCONDITIONAL"
            )
        fixtures.set_clock(DRAW_CLOCK)
        return ctx, ctx.line_by_code("ROOF")["id"], ctx.line_by_code("ELECTRICAL")["id"]

    def test_one_fund_call_walks_allocation_to_line_to_construction_status(self):
        """Three levels of cascade, and the loan crosses two construction states at once.

        The retainage-free 1.00 release pays both lines out in full, so the
        allocations, both scope lines and the loan's construction axis all move
        inside a single fund call — `NOT_STARTED` to `IN_PROGRESS` to `COMPLETE` —
        while the payment and exit axes stay put. The PRD states: "One level deeper
        again, any scope line whose `released_cents` now equals its
        `approved_cost_cents` moves `APPROVED → FULLY_RELEASED`, and when no
        `APPROVED` line remains on the loan's application — every one of them
        having become `FULLY_RELEASED` — the loan's `construction_status` advances
        `IN_PROGRESS → COMPLETE`."

        Design: Difficulty/transitive_cascade/fund_cascade_allocation_to_line_completion_to_construction_complete
        """
        ctx, roof_id, electrical_id = self._two_line_loan_with_final_waivers()
        assert ctx.loan["construction_status"] == (
            LoanConstructionStatus.NOT_STARTED.value
        )

        claims = [(roof_id, 1.0), (electrical_id, 1.0)]
        draw, _ = fixtures.build_inspected_draw(ctx, claims, claims)
        approved = fixtures.review_draw(draw["id"])
        assert approved["approved_release_cents"] == 5_000_000, (
            "retainage is zero at 1.00, so both lines release their full cost"
        )

        funded = fixtures.fund_draw(draw["id"], funding_date=FUNDING_DATE)
        assert funded["status"] == "FUNDED"
        allocations = _allocations(draw["id"])
        assert allocations[roof_id]["released_cents"] == 2_500_000
        assert allocations[electrical_id]["released_cents"] == 2_500_000

        for line_id in (roof_id, electrical_id):
            line = fixtures.read_line(line_id)
            assert line["status"] == RehabLineItemStatus.FULLY_RELEASED.value
            assert line["released_cents"] == 2_500_000
            assert float(line["released_percent"]) == pytest.approx(1.0)

        loan = ctx.refresh_loan()
        assert_loan_axes(
            loan,
            payment_status=LoanPaymentStatus.CURRENT.value,
            construction_status=LoanConstructionStatus.COMPLETE.value,
            exit_status=LoanExitStatus.NOT_LISTED.value,
        )
        assert_loan_buckets(
            loan,
            committed_amount_cents=22_442_141,
            funded_principal_cents=21_439_218,
            interest_reserve_balance_cents=1_002_923,
            undisbursed_holdback_cents=0,
            reserved_release_cents=0,
        )

        entries, meta = validate_paginated(
            api_client.list_ledger_entries(loan["id"], SERVICER)
        )
        assert meta["total_count"] == 2
        assert [entry["entry_type"] for entry in entries] == [
            LedgerEntryType.INITIAL_FUNDING.value,
            LedgerEntryType.DRAW_DISBURSEMENT.value,
        ]
        assert entries[1]["amount_cents"] == 5_000_000

    def test_the_third_level_waits_until_no_approved_line_remains(self):
        """Completing one of two lines is not enough; construction stops at IN_PROGRESS.

        The first funding fully releases the roof line yet leaves the electrical
        line `APPROVED`, so the loan holds at `IN_PROGRESS` with 2,500,000 of
        holdback still sitting there, and only the second funding trips the
        aggregate test. The PRD states: "Reaching `COMPLETE` does **not** sweep any
        residual `undisbursed_holdback_cents`; that money stays available in case a
        further scope re-approval reopens work."

        Design: Difficulty/transitive_cascade/fund_cascade_allocation_to_line_completion_to_construction_complete
        """
        ctx, roof_id, electrical_id = self._two_line_loan_with_final_waivers()

        first, _ = fixtures.build_inspected_draw(
            ctx, [(roof_id, 1.0)], [(roof_id, 1.0)]
        )
        assert fixtures.review_draw(first["id"])["approved_release_cents"] == 2_500_000
        fixtures.fund_draw(first["id"], funding_date=FUNDING_DATE)

        assert fixtures.read_line(roof_id)["status"] == (
            RehabLineItemStatus.FULLY_RELEASED.value
        )
        assert fixtures.read_line(electrical_id)["status"] == (
            RehabLineItemStatus.APPROVED.value
        )
        halfway = ctx.refresh_loan()
        assert halfway["construction_status"] == (
            LoanConstructionStatus.IN_PROGRESS.value
        ), "one open line keeps construction short of COMPLETE"
        assert halfway["undisbursed_holdback_cents"] == 2_500_000
        assert halfway["funded_principal_cents"] == 18_939_218

        second, _ = fixtures.build_inspected_draw(
            ctx, [(electrical_id, 1.0)], [(electrical_id, 1.0)]
        )
        assert fixtures.review_draw(second["id"])["approved_release_cents"] == 2_500_000
        fixtures.fund_draw(second["id"], funding_date=FUNDING_DATE)

        done = ctx.refresh_loan()
        assert done["construction_status"] == LoanConstructionStatus.COMPLETE.value
        assert done["undisbursed_holdback_cents"] == 0
        assert done["funded_principal_cents"] == 21_439_218
        assert done["commitment_balance_check_cents"] == 0
        assert done["interest_reserve_balance_cents"] == 1_002_923, (
            "the construction axis does not touch the interest reserve"
        )


class TestApprovedButUnfundedDraw:
    def test_an_approved_but_unfunded_draw_earmarks_the_pool_without_spending_it(self):
        """Review reshuffles the pool; it does not disburse a cent.

        The 3,892,500 approval moves out of holdback and into reserved release, so
        the forward-looking pool is unchanged at 10,000,000, funded principal has
        not moved, no scope line shows any release and no waiver headroom has been
        consumed. The PRD states: "On success, `approved_release_cents` moves out
        of the loan's `undisbursed_holdback_cents` and into its
        `reserved_release_cents`."

        Design: Corner/calculations/an_approved_but_unfunded_draw_earmarks_the_pool_without_spending_it
        """
        ctx = _three_line_loan()
        lines, draw = _standard_draw(ctx)
        assert ctx.loan["available_rehab_pool_cents"] == 10_000_000

        approved = validate_success(
            api_client.review_draw_request(
                draw["id"],
                factories.draw_review_payload(reviewer_note="Photos and report agree"),
                SERVICER,
            ),
            200,
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_release_cents"] == 3_892_500
        assert approved["reviewed_by_user_id"] == SERVICER["X-User-ID"]

        loan = ctx.refresh_loan()
        assert loan["reserved_release_cents"] == 3_892_500
        assert loan["undisbursed_holdback_cents"] == 6_107_500
        assert loan["available_rehab_pool_cents"] == 10_000_000, (
            "holdback plus reserved is invariant across the review"
        )
        assert loan["funded_principal_cents"] == 13_151_375
        assert loan["construction_status"] == LoanConstructionStatus.NOT_STARTED.value
        assert loan["commitment_balance_check_cents"] == 0

        roof = fixtures.read_line(lines[0])
        assert roof["released_cents"] == 0
        assert float(roof["released_percent"]) == pytest.approx(0.0)

        allocation = _allocations(draw["id"])[lines[0]]
        assert allocation["approved_amount_cents"] == 1_800_000
        assert allocation["released_cents"] == 0

        assert_contractor_waiver_figures(
            fixtures.read_contractor(ctx.contractor_id(0)),
            collected_waiver_coverage_cents=3_400_000,
            released_to_contractor_cents=0,
            open_waiver_headroom_cents=3_400_000,
        )


class TestFundingLedgerAndReconciliation:
    def test_funding_a_draw_writes_the_disbursement_entry_and_reconciles_the_loan(self):
        """A synchronised triple: the buckets, the ledger and the scope lines.

        The 3,892,500 leaves reserved release for funded principal, exactly one
        `DRAW_DISBURSEMENT` entry of that amount joins the append-only ledger
        behind the `INITIAL_FUNDING` row, and each scope line's release rises by
        its own share. The PRD states: "Finally, funding writes a
        `DRAW_DISBURSEMENT` ledger entry for `approved_release_cents` and records
        `funded_by_user_id` and `funded_at`, the latter as the logical-clock
        instant."

        Design: Corner/state_machines/funding_a_draw_writes_the_disbursement_entry_and_reconciles_the_loan
        """
        ctx = _three_line_loan()
        lines, draw = _standard_draw(ctx)
        fixtures.review_draw(draw["id"])

        funded = fixtures.fund_draw(draw["id"], funding_date=FUNDING_DATE)
        assert funded["status"] == "FUNDED"
        assert funded["approved_release_cents"] == 3_892_500
        assert funded["funded_by_user_id"] == SERVICER_2["X-User-ID"]
        assert funded["funded_at"].startswith("2026-09-01T12:00:00")

        loan = ctx.refresh_loan()
        assert loan["funded_principal_cents"] == 17_043_875
        assert loan["reserved_release_cents"] == 0
        assert loan["undisbursed_holdback_cents"] == 6_107_500
        assert loan["committed_amount_cents"] == 23_953_713, (
            "funding moves money between buckets; it does not create commitment"
        )
        assert loan["commitment_balance_check_cents"] == 0
        assert_loan_axes(
            loan,
            payment_status=LoanPaymentStatus.CURRENT.value,
            construction_status=LoanConstructionStatus.IN_PROGRESS.value,
            exit_status=LoanExitStatus.NOT_LISTED.value,
        )

        disbursements, disb_meta = validate_paginated(
            api_client.list_ledger_entries(
                loan["id"], SERVICER, {"entry_type": LedgerEntryType.DRAW_DISBURSEMENT.value}
            )
        )
        assert disb_meta["total_count"] == 1
        assert disbursements[0]["amount_cents"] == 3_892_500
        assert disbursements[0]["effective_date"] == FUNDING_DATE

        entries, meta = validate_paginated(
            api_client.list_ledger_entries(loan["id"], SERVICER)
        )
        assert meta["total_count"] == 2
        assert entries[0]["entry_type"] == LedgerEntryType.INITIAL_FUNDING.value
        assert entries[0]["amount_cents"] == 13_151_375

        kitchen = fixtures.read_line(lines[1])
        assert kitchen["released_cents"] == 1_417_500
        assert float(kitchen["released_percent"]) == pytest.approx(0.4050)
        assert kitchen["status"] == RehabLineItemStatus.APPROVED.value

        allocations = _allocations(draw["id"])
        shares = [allocations[line_id]["released_cents"] for line_id in lines]
        assert shares == [1_800_000, 1_417_500, 675_000]
        assert sum(shares) == funded["approved_release_cents"]

        assert_contractor_waiver_figures(
            fixtures.read_contractor(ctx.contractor_id(0)),
            released_to_contractor_cents=3_217_500,
            open_waiver_headroom_cents=182_500,
        )
        assert_contractor_waiver_figures(
            fixtures.read_contractor(ctx.contractor_id(1)),
            released_to_contractor_cents=675_000,
            open_waiver_headroom_cents=25_000,
        )


class TestDerivedFieldsAreImmediate:
    def test_every_derived_field_is_correct_in_the_response_that_caused_it(self):
        """No lag, no recompute-on-read drift, no background reconciliation.

        The funding response already carries the final figures, and follow-up reads
        of the loan, a sibling scope line, the contractor and the ledger agree with
        it exactly — then repeat the same values on a second read. The PRD states:
        "One level deeper, each allocation's released amount is added to its scope
        line's `released_cents` and that line's `released_percent` is re-derived as
        `released_cents` divided by `approved_cost_cents` carried to four decimal
        places, reading 0 while `approved_cost_cents` is null."

        Design: Corner/consistency_model/every_derived_field_is_correct_in_the_response_that_caused_it
        """
        ctx = _three_line_loan()
        lines, draw = _standard_draw(ctx)
        fixtures.review_draw(draw["id"])

        funded = fixtures.fund_draw(draw["id"], funding_date=FUNDING_DATE)
        assert funded["approved_release_cents"] == 3_892_500
        assert funded["status"] == "FUNDED"
        assert funded["funded_at"].startswith("2026-09-01T12:00:00")

        loan_first = fixtures.read_loan(ctx.loan_id)
        assert loan_first["funded_principal_cents"] == 17_043_875
        assert loan_first["undisbursed_holdback_cents"] == 6_107_500
        assert loan_first["reserved_release_cents"] == 0
        assert loan_first["available_rehab_pool_cents"] == 6_107_500
        assert loan_first["commitment_balance_check_cents"] == 0

        kitchen_first = fixtures.read_line(lines[1])
        assert kitchen_first["released_cents"] == 1_417_500
        assert float(kitchen_first["released_percent"]) == pytest.approx(0.4050)

        contractor_first = fixtures.read_contractor(ctx.contractor_id(0))
        assert contractor_first["open_waiver_headroom_cents"] == 182_500

        ledger_first, ledger_meta = validate_paginated(
            api_client.list_ledger_entries(ctx.loan_id, SERVICER)
        )
        assert ledger_meta["total_count"] == 2
        assert ledger_first[0]["entry_type"] == LedgerEntryType.INITIAL_FUNDING.value
        assert ledger_first[1]["entry_type"] == LedgerEntryType.DRAW_DISBURSEMENT.value
        assert ledger_first[1]["amount_cents"] == 3_892_500

        assert fixtures.read_loan(ctx.loan_id) == loan_first, (
            "re-reading the loan returns identical values; nothing converged after the fact"
        )
        assert (
            validate_success(
                api_client.get_rehab_line_item(lines[1], LOAN_OFFICER), 200
            )
            == kitchen_first
        )
        assert fixtures.read_contractor(ctx.contractor_id(0)) == contractor_first
        repeat, _ = validate_paginated(
            api_client.list_ledger_entries(ctx.loan_id, SERVICER)
        )
        assert repeat == ledger_first
