"""Lien waiver coverage, disputes, the payability clock and the funding-time gates."""

import pytest

from test_helpers import (
    ApiErrorId,
    DrawRequestStatus,
    LedgerEntryType,
    LienWaiverStatus,
    RehabLineItemStatus,
    WaiverDisputeAction,
    WaiverType,
    api_client,
    assert_contractor_payability,
    assert_contractor_waiver_figures,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
    make_contractor_headers,
    NON_EXISTENT_UUID,
    SERVICER,
    SERVICER_2,
)

DRAW_CLOCK = "2026-09-01T12:00:00Z"
LATER_CLOCK = "2026-09-02T12:00:00Z"
FUNDING_DATE = "2026-09-01"
LAPSING_TRADE = {
    "business_name": "Vega Roofing",
    "license_number": "LIC-4471",
    "license_expires_on": "2026-09-15",
}
JOINT_CHECK_TRADE = {
    "business_name": "Ortiz Electric",
    "license_number": "LIC-8820",
    "joint_check_required": True,
}


def _covered_loan(first_cover=3_400_000, second_cover=700_000, **kwargs):
    ctx = fixtures.build_closed_loan(**kwargs)
    waivers = [
        fixtures.file_waiver(ctx.loan_id, ctx.contractor_id(0), first_cover),
        fixtures.file_waiver(ctx.loan_id, ctx.contractor_id(1), second_cover),
    ]
    fixtures.set_clock(DRAW_CLOCK)
    return ctx, waivers


def _line_ids(ctx):
    return [ctx.line_by_code(code)["id"] for code in ("ROOF", "KITCHEN", "ELECTRICAL")]


def _fund_the_standard_draw(ctx):
    """Release 1,800,000 / 1,417,500 / 675,000 so headroom is 182,500 and 25,000."""
    lines = _line_ids(ctx)
    draw, _ = fixtures.build_inspected_draw(
        ctx,
        [(lines[0], 0.60), (lines[1], 0.45), (lines[2], 0.33)],
        [(lines[0], 0.50), (lines[1], 0.45), (lines[2], 0.30)],
    )
    fixtures.review_draw(draw["id"])
    fixtures.fund_draw(draw["id"], funding_date=FUNDING_DATE)
    return lines


def _review(draw_id):
    return api_client.review_draw_request(
        draw_id, factories.draw_review_payload(), SERVICER
    )


def _dispute(waiver_id, action):
    return validate_success(
        api_client.dispute_lien_waiver(
            waiver_id,
            factories.waiver_dispute_payload(action, note="Second-tier supplier claim"),
            SERVICER,
        ),
        200,
    )


class TestWaiverDisputeReversal:
    def test_a_dispute_withdraws_coverage_and_a_resolution_restores_it_to_the_cent(self):
        """The dispute is a reversible withdrawal, not a deletion of the paper.

        Disputing the only unconditional waiver takes coverage to 0 and headroom to
        a negative 3,217,500 because that much is already released against
        withdrawn paper; resolving puts headroom back at exactly 182,500 and the
        pending 180,000 review then fits inside it. The PRD states: "Resolving
        moves `DISPUTED → COLLECTED`, re-derives `counts_toward_coverage` from the
        waiver's `waiver_type`, and recomputes the same two contractor figures."

        Design: Difficulty/compensating_invariant/waiver_dispute_and_resolution_restore_headroom_to_the_cent
        """
        ctx, waivers = _covered_loan()
        lines = _fund_the_standard_draw(ctx)
        assert_contractor_waiver_figures(
            fixtures.read_contractor(ctx.contractor_id(0)),
            collected_waiver_coverage_cents=3_400_000,
            released_to_contractor_cents=3_217_500,
            open_waiver_headroom_cents=182_500,
        )

        fixtures.set_clock(LATER_CLOCK)
        pending, _ = fixtures.build_inspected_draw(
            ctx, [(lines[0], 0.55)], [(lines[0], 0.55)]
        )
        assert pending["requested_total_cents"] == 400_000

        disputed = _dispute(waivers[0]["id"], WaiverDisputeAction.DISPUTE.value)
        assert disputed["status"] == LienWaiverStatus.DISPUTED.value
        assert disputed["counts_toward_coverage"] is False
        assert_contractor_waiver_figures(
            fixtures.read_contractor(ctx.contractor_id(0)),
            collected_waiver_coverage_cents=0,
            released_to_contractor_cents=3_217_500,
            open_waiver_headroom_cents=-3_217_500,
        )

        validate_error(
            _review(pending["id"]), ApiErrorId.LIEN_WAIVER_DISPUTED.value
        )
        blocked = fixtures.read_draw_request(pending["id"])
        assert blocked["status"] == DrawRequestStatus.INSPECTED.value
        assert blocked["approved_release_cents"] is None
        assert blocked["reviewed_by_user_id"] is None

        resolved = _dispute(waivers[0]["id"], WaiverDisputeAction.RESOLVE.value)
        assert resolved["status"] == LienWaiverStatus.COLLECTED.value
        assert resolved["counts_toward_coverage"] is True
        assert_contractor_waiver_figures(
            fixtures.read_contractor(ctx.contractor_id(0)),
            collected_waiver_coverage_cents=3_400_000,
            open_waiver_headroom_cents=182_500,
        )

        approved = validate_success(_review(pending["id"]), 200)
        assert approved["status"] == DrawRequestStatus.APPROVED.value
        assert approved["approved_release_cents"] == 180_000, (
            "2,200,000 earned less 10 percent retainage less the 1,800,000 released"
        )
        assert_contractor_waiver_figures(
            fixtures.read_contractor(ctx.contractor_id(1)),
            open_waiver_headroom_cents=25_000,
        )
        assert fixtures.read_line(lines[0])["released_cents"] == 1_800_000
        assert ctx.refresh_loan()["commitment_balance_check_cents"] == 0

    def test_the_dispute_gate_answers_ahead_of_the_headroom_gate(self):
        """Rung 15 is read before rung 16 even when both conditions hold.

        A 2,200,000 release against 182,500 of headroom is refused on coverage
        while the waiver is `COLLECTED`; disputing the same waiver makes the same
        call answer on the dispute instead, and resolving it hands the answer back
        to the coverage rung. The PRD states: "When more than one rule would reject
        a request, the platform evaluates rules in a strict, fixed order and reports
        only the **first** rule whose condition holds; later rules are never
        reported."

        Design: Difficulty/compensating_invariant/waiver_dispute_and_resolution_restore_headroom_to_the_cent
        """
        ctx, waivers = _covered_loan()
        lines = _fund_the_standard_draw(ctx)

        fixtures.set_clock(LATER_CLOCK)
        oversized, _ = fixtures.build_inspected_draw(
            ctx, [(lines[0], 1.0)], [(lines[0], 1.0)]
        )
        validate_error(
            _review(oversized["id"]), ApiErrorId.WAIVER_HEADROOM_EXCEEDED.value
        )

        _dispute(waivers[0]["id"], WaiverDisputeAction.DISPUTE.value)
        validate_error(
            _review(oversized["id"]), ApiErrorId.LIEN_WAIVER_DISPUTED.value
        )
        assert (
            fixtures.read_contractor(ctx.contractor_id(0))[
                "open_waiver_headroom_cents"
            ]
            == -3_217_500
        ), "headroom is allowed to go negative rather than being clamped at zero"

        _dispute(waivers[0]["id"], WaiverDisputeAction.RESOLVE.value)
        validate_error(
            _review(oversized["id"]), ApiErrorId.WAIVER_HEADROOM_EXCEEDED.value
        )
        assert (
            fixtures.read_contractor(ctx.contractor_id(0))[
                "open_waiver_headroom_cents"
            ]
            == 182_500
        )

        still_waiting = fixtures.read_draw_request(oversized["id"])
        assert still_waiting["status"] == DrawRequestStatus.INSPECTED.value
        assert still_waiting["approved_release_cents"] is None
        loan = ctx.refresh_loan()
        assert loan["reserved_release_cents"] == 0
        assert loan["commitment_balance_check_cents"] == 0


class TestHeadroomBeatsRegression:
    def test_the_coverage_rule_answers_before_the_regression_rule(self):
        """One review, two fiscal breaches on two different contractors.

        The electrical line's 675,000 share overruns its 25,000 of coverage while
        the roof line regresses from 0.50 down to 0.30 and computes a negative
        release; coverage answers first, and filing fresh electrical coverage
        exposes the regression underneath. The PRD states: "If any allocation's
        computed release comes out negative — because the verified completion
        implies less earned work than has already been released against that line —
        the whole approval is rejected with `ERR_PERCENT_COMPLETE_REGRESSION`."

        Design: Difficulty/priority_pair_validation_conflict/waiver_headroom_priority_16_beats_percent_regression_priority_26
        """
        ctx, _ = _covered_loan()
        lines = _fund_the_standard_draw(ctx)
        assert_contractor_waiver_figures(
            fixtures.read_contractor(ctx.contractor_id(0)),
            open_waiver_headroom_cents=182_500,
        )
        assert_contractor_waiver_figures(
            fixtures.read_contractor(ctx.contractor_id(1)),
            open_waiver_headroom_cents=25_000,
        )

        both, _ = fixtures.build_inspected_draw(
            ctx,
            [(lines[0], 0.60), (lines[2], 0.60)],
            [(lines[0], 0.30), (lines[2], 0.60)],
        )
        validate_error(
            _review(both["id"]), ApiErrorId.WAIVER_HEADROOM_EXCEEDED.value
        )
        assert fixtures.read_draw_request(both["id"])["status"] == (
            DrawRequestStatus.INSPECTED.value
        )
        assert ctx.refresh_loan()["reserved_release_cents"] == 0

        fixtures.file_waiver(ctx.loan_id, ctx.contractor_id(1), 1_000_000)
        assert_contractor_waiver_figures(
            fixtures.read_contractor(ctx.contractor_id(1)),
            collected_waiver_coverage_cents=1_700_000,
            open_waiver_headroom_cents=1_025_000,
        )

        validate_error(
            _review(both["id"]), ApiErrorId.PERCENT_COMPLETE_REGRESSION.value
        )
        assert fixtures.read_draw_request(both["id"])["status"] == (
            DrawRequestStatus.INSPECTED.value
        )
        assert ctx.refresh_loan()["commitment_balance_check_cents"] == 0

    def test_each_of_the_two_fiscal_rules_answers_alone(self):
        """Isolating the breaches proves neither code was reported by luck.

        A draw that only overruns coverage answers on coverage, and a draw that only
        regresses a line answers on regression — the same two codes the combined
        review had to choose between. The PRD states: "And each contractor's share
        of the computed release — the sum of that contractor's per-line
        `approved_amount_cents` on this request — must be covered by that
        contractor's waiver headroom, or the approval is rejected with
        `ERR_WAIVER_HEADROOM_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/waiver_headroom_priority_16_beats_percent_regression_priority_26
        """
        ctx, _ = _covered_loan()
        lines = _fund_the_standard_draw(ctx)

        coverage_only, _ = fixtures.build_inspected_draw(
            ctx, [(lines[2], 0.60)], [(lines[2], 0.60)]
        )
        validate_error(
            _review(coverage_only["id"]), ApiErrorId.WAIVER_HEADROOM_EXCEEDED.value
        )

        regression_only, _ = fixtures.build_inspected_draw(
            ctx, [(lines[0], 0.60)], [(lines[0], 0.30)]
        )
        assert fixtures.read_draw_request(coverage_only["id"])["status"] == (
            DrawRequestStatus.SUPERSEDED.value
        )
        validate_error(
            _review(regression_only["id"]),
            ApiErrorId.PERCENT_COMPLETE_REGRESSION.value,
        )
        assert fixtures.read_line(lines[0])["released_cents"] == 1_800_000
        assert ctx.refresh_loan()["reserved_release_cents"] == 0


class TestPayabilityTracksTheClock:
    def _lapsing_loan(self):
        ctx = fixtures.build_closed_loan(
            contractor_overrides=[LAPSING_TRADE, fixtures.CONTRACTOR_TWO]
        )
        fixtures.file_waiver(ctx.loan_id, ctx.contractor_id(0), 3_400_000)
        fixtures.file_waiver(
            ctx.loan_id, ctx.contractor_id(1), 2_000_000, through_date="2026-10-31"
        )
        return ctx, _line_ids(ctx)

    def test_the_review_flips_on_the_licence_expiry_date_with_no_write_to_the_trade(self):
        """The gate lives on a third entity nobody touched; only the clock moved.

        On the expiry date itself the roofer is still `ACTIVE` and the review
        approves 3,892,500, and one day later — with no write to the contractor row
        — the same trade reads `EXPIRED` and the next review is refused. The PRD
        states: "A contractor's `license_status` is derived from the logical clock
        rather than stored: it reads `ACTIVE` when the current date is on or before
        `license_expires_on` and `EXPIRED` once the current date passes it."

        Design: Difficulty/cross_entity_state_dependency/draw_review_reads_contractor_payable_derived_from_the_clock_per_allocation
        """
        ctx, lines = self._lapsing_loan()
        fixtures.set_clock("2026-09-15T09:00:00Z")
        assert_contractor_payability(
            fixtures.read_contractor(ctx.contractor_id(0)),
            license_status="ACTIVE",
            payable=True,
        )

        first, _ = fixtures.build_inspected_draw(
            ctx,
            [(lines[0], 0.60), (lines[1], 0.45), (lines[2], 0.33)],
            [(lines[0], 0.50), (lines[1], 0.45), (lines[2], 0.30)],
            window_start="2026-09-15T10:00:00Z",
            window_end="2026-09-15T12:00:00Z",
        )
        assert fixtures.review_draw(first["id"])["approved_release_cents"] == 3_892_500
        fixtures.fund_draw(first["id"], funding_date="2026-09-15")
        assert fixtures.read_line(lines[0])["released_cents"] == 1_800_000

        fixtures.set_clock("2026-09-16T09:00:00Z")
        lapsed = fixtures.read_contractor(ctx.contractor_id(0))
        assert_contractor_payability(lapsed, license_status="EXPIRED", payable=False)
        assert lapsed["w9_on_file"] is True, "nothing about the trade row changed"
        assert fixtures.read_contractor(ctx.contractor_id(1))["payable"] is True

        second, _ = fixtures.build_inspected_draw(
            ctx,
            [(lines[0], 0.70)],
            [(lines[0], 0.70)],
            window_start="2026-09-16T10:00:00Z",
            window_end="2026-09-16T12:00:00Z",
        )
        assert second["requested_total_cents"] == 1_000_000, (
            "intake is not gated on payability, only close and review are"
        )
        validate_error(
            _review(second["id"]), ApiErrorId.CONTRACTOR_NOT_PAYABLE.value
        )
        stalled = fixtures.read_draw_request(second["id"])
        assert stalled["status"] == DrawRequestStatus.INSPECTED.value
        assert stalled["approved_release_cents"] is None
        assert ctx.refresh_loan()["commitment_balance_check_cents"] == 0

    def test_the_payability_check_is_scoped_to_this_draws_own_allocations(self):
        """A lapsed trade elsewhere on the scope does not block a draw that omits it.

        At the same expired clock the roof draw is refused on payability — ahead of
        the coverage rung its 720,000 share would also have tripped — while the
        electrical draw that supersedes it reviews to 675,000 because only the
        second trade appears on its allocations. The PRD states: "Every contractor
        referenced by an allocation must have `payable` reading true, or the
        approval is rejected with `ERR_CONTRACTOR_NOT_PAYABLE`."

        Design: Difficulty/cross_entity_state_dependency/draw_review_reads_contractor_payable_derived_from_the_clock_per_allocation
        """
        ctx, lines = self._lapsing_loan()
        fixtures.set_clock("2026-09-15T09:00:00Z")
        first, _ = fixtures.build_inspected_draw(
            ctx,
            [(lines[0], 0.60), (lines[1], 0.45), (lines[2], 0.33)],
            [(lines[0], 0.50), (lines[1], 0.45), (lines[2], 0.30)],
            window_start="2026-09-15T10:00:00Z",
            window_end="2026-09-15T12:00:00Z",
        )
        fixtures.review_draw(first["id"])
        fixtures.fund_draw(first["id"], funding_date="2026-09-15")

        fixtures.set_clock("2026-09-16T09:00:00Z")
        assert (
            fixtures.read_contractor(ctx.contractor_id(0))[
                "open_waiver_headroom_cents"
            ]
            == 182_500
        ), "the roof trade's 720,000 share would also overrun its coverage"

        roof_draw, _ = fixtures.build_inspected_draw(
            ctx,
            [(lines[0], 0.70)],
            [(lines[0], 0.70)],
            window_start="2026-09-16T10:00:00Z",
            window_end="2026-09-16T12:00:00Z",
        )
        validate_error(
            _review(roof_draw["id"]), ApiErrorId.CONTRACTOR_NOT_PAYABLE.value
        )

        fixtures.set_clock("2026-09-17T12:00:00Z")
        electrical_draw, _ = fixtures.build_inspected_draw(
            ctx,
            [(lines[2], 0.60)],
            [(lines[2], 0.60)],
            window_start="2026-09-17T14:00:00Z",
            window_end="2026-09-17T16:00:00Z",
        )
        superseded = fixtures.read_draw_request(roof_draw["id"])
        assert superseded["status"] == DrawRequestStatus.SUPERSEDED.value
        assert superseded["superseded_by_draw_request_id"] == electrical_draw["id"]

        approved = validate_success(_review(electrical_draw["id"]), 200)
        assert approved["approved_release_cents"] == 675_000, (
            "1,350,000 releasable less the 675,000 already released on that line"
        )
        loan = ctx.refresh_loan()
        assert loan["reserved_release_cents"] == 675_000
        assert loan["commitment_balance_check_cents"] == 0


class TestCoverageAggregation:
    def test_waiver_coverage_sums_only_unconditional_waivers(self):
        """A conditional waiver is stored and listed but contributes nothing.

        The roofer's 5,000,000 conditional waiver sits alongside two unconditional
        ones of 1,000,000 and 2,400,000, and coverage reads the 3,400,000 sum of the
        unconditional pair alone — so after 3,217,500 of release the headroom is
        182,500 rather than 5,182,500. The PRD states: "Its derived
        `counts_toward_coverage` flag is true only when `status` is `COLLECTED`
        **and** `waiver_type` is one of the two unconditional types — a conditional
        partial waiver never counts toward coverage, however large it is."

        Design: Corner/calculations/waiver_coverage_sums_only_unconditional_waivers
        """
        ctx = fixtures.build_closed_loan()
        conditional = fixtures.file_waiver(
            ctx.loan_id,
            ctx.contractor_id(0),
            5_000_000,
            WaiverType.PARTIAL_CONDITIONAL.value,
        )
        assert conditional["counts_toward_coverage"] is False
        assert conditional["status"] == LienWaiverStatus.COLLECTED.value
        fixtures.file_waiver(ctx.loan_id, ctx.contractor_id(0), 1_000_000)
        fixtures.file_waiver(ctx.loan_id, ctx.contractor_id(0), 2_400_000)
        fixtures.file_waiver(ctx.loan_id, ctx.contractor_id(1), 700_000)
        fixtures.set_clock(DRAW_CLOCK)

        assert_contractor_waiver_figures(
            fixtures.read_contractor(ctx.contractor_id(0)),
            collected_waiver_coverage_cents=3_400_000,
            released_to_contractor_cents=0,
            open_waiver_headroom_cents=3_400_000,
        )

        _fund_the_standard_draw(ctx)
        assert_contractor_waiver_figures(
            fixtures.read_contractor(ctx.contractor_id(0)),
            collected_waiver_coverage_cents=3_400_000,
            released_to_contractor_cents=3_217_500,
            open_waiver_headroom_cents=182_500,
        )
        assert_contractor_waiver_figures(
            fixtures.read_contractor(ctx.contractor_id(1)),
            released_to_contractor_cents=675_000,
            open_waiver_headroom_cents=25_000,
        )

        rows, meta = validate_paginated(
            api_client.list_contractor_lien_waivers(
                ctx.contractor_id(0),
                SERVICER,
                {"status": LienWaiverStatus.COLLECTED.value},
            )
        )
        assert meta["total_count"] == 3, (
            "all three waivers are COLLECTED; only two count toward coverage"
        )
        counting = [row for row in rows if row["counts_toward_coverage"]]
        assert len(counting) == 2
        assert sum(row["amount_covered_cents"] for row in counting) == 3_400_000


class TestFinalWaiverGate:
    def test_the_final_unconditional_waiver_gate_fires_at_funding(self):
        """Review clears on the amount; funding refuses on the waiver type.

        The 4,000,000 release sits exactly on the roofer's 4,000,000 of coverage so
        the review passes, and funding — which would take the line to full
        completion — is refused until a `FINAL_UNCONDITIONAL` waiver exists; the
        identical fund call then succeeds. The PRD states: "And every contractor
        whose scope line reaches full completion with this funding must already have
        a `FINAL_UNCONDITIONAL` waiver on file, or the funding is rejected with
        `ERR_FINAL_WAIVER_REQUIRED` — a check that exists only at funding time,
        since a review does not yet disburse."

        Design: Corner/validations/the_final_unconditional_waiver_gate_fires_at_funding
        """
        ctx = fixtures.build_closed_loan()
        fixtures.file_waiver(ctx.loan_id, ctx.contractor_id(0), 4_000_000)
        fixtures.set_clock(DRAW_CLOCK)
        lines = _line_ids(ctx)

        draw, _ = fixtures.build_inspected_draw(
            ctx, [(lines[0], 1.0)], [(lines[0], 1.0)]
        )
        approved = fixtures.review_draw(draw["id"])
        assert approved["approved_release_cents"] == 4_000_000, (
            "at exactly 1.00 the withheld retainage is released too"
        )

        validate_error(
            api_client.fund_draw_request(
                draw["id"],
                factories.draw_fund_payload(FUNDING_DATE, joint_check_ack=False),
                SERVICER_2,
            ),
            ApiErrorId.FINAL_WAIVER_REQUIRED.value,
        )
        assert fixtures.read_draw_request(draw["id"])["status"] == (
            DrawRequestStatus.APPROVED.value
        )
        assert ctx.refresh_loan()["funded_principal_cents"] == 13_151_375

        final = fixtures.file_waiver(
            ctx.loan_id,
            ctx.contractor_id(0),
            4_000_000,
            WaiverType.FINAL_UNCONDITIONAL.value,
        )
        assert final["counts_toward_coverage"] is True
        assert_contractor_waiver_figures(
            fixtures.read_contractor(ctx.contractor_id(0)),
            collected_waiver_coverage_cents=8_000_000,
            open_waiver_headroom_cents=8_000_000,
        )

        funded = fixtures.fund_draw(draw["id"], funding_date=FUNDING_DATE)
        assert funded["status"] == DrawRequestStatus.FUNDED.value
        assert funded["approved_release_cents"] == 4_000_000
        assert funded["funded_at"].startswith("2026-09-01T12:00:00")

        loan = ctx.refresh_loan()
        assert loan["funded_principal_cents"] == 17_151_375
        assert loan["undisbursed_holdback_cents"] == 6_000_000
        assert loan["commitment_balance_check_cents"] == 0

        roof = fixtures.read_line(lines[0])
        assert roof["released_cents"] == 4_000_000
        assert float(roof["released_percent"]) == pytest.approx(1.0)
        assert roof["status"] == RehabLineItemStatus.FULLY_RELEASED.value
        for line_id in lines[1:]:
            assert fixtures.read_line(line_id)["released_cents"] == 0

        disbursements, meta = validate_paginated(
            api_client.list_ledger_entries(
                ctx.loan_id,
                SERVICER,
                {"entry_type": LedgerEntryType.DRAW_DISBURSEMENT.value},
            )
        )
        assert meta["total_count"] == 1
        assert disbursements[0]["amount_cents"] == 4_000_000
        assert disbursements[0]["effective_date"] == FUNDING_DATE
        assert_contractor_waiver_figures(
            fixtures.read_contractor(ctx.contractor_id(0)),
            open_waiver_headroom_cents=4_000_000,
        )


class TestJointCheckGate:
    def test_the_joint_check_acknowledgement_gate_is_contractor_conditional(self):
        """One joint-check trade on one allocation demands the acknowledgement for all.

        Sending `false` and omitting the field behave identically, and sending true
        funds all three lines including the two belonging to the trade that never
        required an acknowledgement of its own. The PRD states: "When any
        allocation's contractor has `joint_check_required` set to true,
        `joint_check_ack` must be present and true, or the funding is rejected with
        `ERR_JOINT_CHECK_ACK_REQUIRED`."

        Design: Corner/validations/the_joint_check_acknowledgement_gate_is_contractor_conditional
        """
        ctx, _ = _covered_loan(
            contractor_overrides=[fixtures.CONTRACTOR_ONE, JOINT_CHECK_TRADE]
        )
        assert fixtures.read_contractor(ctx.contractor_id(0))["joint_check_required"] is False
        assert fixtures.read_contractor(ctx.contractor_id(1))["joint_check_required"] is True

        lines = _line_ids(ctx)
        draw, _ = fixtures.build_inspected_draw(
            ctx,
            [(lines[0], 0.60), (lines[1], 0.45), (lines[2], 0.33)],
            [(lines[0], 0.50), (lines[1], 0.45), (lines[2], 0.30)],
        )
        assert fixtures.review_draw(draw["id"])["approved_release_cents"] == 3_892_500

        validate_error(
            api_client.fund_draw_request(
                draw["id"],
                factories.draw_fund_payload(FUNDING_DATE, joint_check_ack=False),
                SERVICER_2,
            ),
            ApiErrorId.JOINT_CHECK_ACK_REQUIRED.value,
        )
        validate_error(
            api_client.fund_draw_request(
                draw["id"], factories.draw_fund_payload(FUNDING_DATE), SERVICER_2
            ),
            ApiErrorId.JOINT_CHECK_ACK_REQUIRED.value,
        )
        waiting = fixtures.read_draw_request(draw["id"])
        assert waiting["status"] == DrawRequestStatus.APPROVED.value
        assert waiting["funded_at"] is None
        _, no_disbursement = validate_paginated(
            api_client.list_ledger_entries(
                ctx.loan_id,
                SERVICER,
                {"entry_type": LedgerEntryType.DRAW_DISBURSEMENT.value},
            )
        )
        assert no_disbursement["total_count"] == 0

        funded = fixtures.fund_draw(
            draw["id"], funding_date=FUNDING_DATE, joint_check_ack=True
        )
        assert funded["status"] == DrawRequestStatus.FUNDED.value
        assert funded["approved_release_cents"] == 3_892_500
        assert funded["funded_by_user_id"] == SERVICER_2["X-User-ID"]

        loan = ctx.refresh_loan()
        assert loan["funded_principal_cents"] == 17_043_875
        assert loan["undisbursed_holdback_cents"] == 6_107_500
        assert loan["reserved_release_cents"] == 0
        assert_contractor_waiver_figures(
            fixtures.read_contractor(ctx.contractor_id(0)),
            open_waiver_headroom_cents=182_500,
        )
        assert_contractor_waiver_figures(
            fixtures.read_contractor(ctx.contractor_id(1)),
            open_waiver_headroom_cents=25_000,
        )


class TestWaiverAssociation:
    def test_a_lien_waiver_links_a_loan_and_a_contractor_in_one_write(self):
        """One POST populates both reverse listings and is refused if either side is missing.

        The created row is immediately load-bearing — it lifts the roofer's
        headroom from 0 to 3,400,000 — and the two failed writes, each naming the
        side that did not resolve, leave nothing behind. The PRD states: "A lien
        waiver is filed against a loan for a contractor with a `loan_id`, a
        `contractor_id`, a `waiver_type` of `PARTIAL_CONDITIONAL`,
        `PARTIAL_UNCONDITIONAL` or `FINAL_UNCONDITIONAL`, an `amount_covered_cents`
        strictly greater than zero naming the dollar value of work it releases, and
        a `through_date` through which claims are released."

        Design: Corner/endpoints/a_lien_waiver_links_a_loan_and_a_contractor_in_one_write
        """
        ctx = fixtures.build_closed_loan()
        trade_id = ctx.contractor_id(0)
        assert_contractor_waiver_figures(
            fixtures.read_contractor(trade_id),
            collected_waiver_coverage_cents=0,
            released_to_contractor_cents=0,
            open_waiver_headroom_cents=0,
        )
        headers = make_contractor_headers(trade_id)

        waiver = validate_success(
            api_client.create_lien_waiver(
                factories.lien_waiver_payload(ctx.loan_id, trade_id, 3_400_000),
                headers,
            ),
            201,
        )
        assert waiver["loan_id"] == ctx.loan_id
        assert waiver["contractor_id"] == trade_id
        assert waiver["status"] == LienWaiverStatus.COLLECTED.value
        assert waiver["counts_toward_coverage"] is True
        assert waiver["amount_covered_cents"] == 3_400_000

        validate_error(
            api_client.create_lien_waiver(
                factories.lien_waiver_payload(NON_EXISTENT_UUID, trade_id, 100_000),
                headers,
            ),
            ApiErrorId.LOAN_NOT_FOUND.value,
            404,
        )
        validate_error(
            api_client.create_lien_waiver(
                factories.lien_waiver_payload(ctx.loan_id, NON_EXISTENT_UUID, 100_000),
                headers,
            ),
            ApiErrorId.CONTRACTOR_NOT_FOUND.value,
            404,
        )

        by_loan, loan_meta = validate_paginated(
            api_client.list_loan_lien_waivers(ctx.loan_id, SERVICER)
        )
        assert loan_meta["total_count"] == 1, (
            "the two refused writes left nothing behind"
        )
        by_trade, trade_meta = validate_paginated(
            api_client.list_contractor_lien_waivers(trade_id, headers)
        )
        assert trade_meta["total_count"] == 1
        assert by_loan[0]["id"] == by_trade[0]["id"] == waiver["id"]

        assert_contractor_waiver_figures(
            fixtures.read_contractor(trade_id),
            collected_waiver_coverage_cents=3_400_000,
            open_waiver_headroom_cents=3_400_000,
        )
