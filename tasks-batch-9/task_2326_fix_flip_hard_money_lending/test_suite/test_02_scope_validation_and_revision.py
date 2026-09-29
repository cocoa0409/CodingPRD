"""Rehab scope lines: the revision cycle, the concentration cap and code uniqueness."""

from test_helpers import (
    ApiErrorId,
    ApplicationStatus,
    RehabLineItemStatus,
    ScopeCode,
    api_client,
    assert_sizing_fields,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
    LOAN_OFFICER,
)

TWO_UNEVEN_LINES = [
    fixtures.ScopeSpec("ROOF", 4_000_000, 0, "Tear-off and re-deck"),
    fixtures.ScopeSpec("KITCHEN", 1_000_000, 0, "Cabinets and counters"),
]


class TestRevisionCycle:
    def test_the_line_reenters_proposed_and_a_second_revision_deapproves_it(self):
        """A line can loop PROPOSED to APPROVED and back, deapproving the budget.

        The first revision request bumps `revision_round` to 1; the resubmission
        returns the line to `PROPOSED` without bumping the counter; re-approval
        rebuilds the budget; and the second revision request is a compensating
        de-approval that strips the approved cost out again on round 2. The PRD
        states: "The same decision on a line already in `APPROVED` is a
        compensating de-approval, moving `APPROVED → REVISION_REQUESTED`; it is
        permitted only while that line's `released_cents` is still 0, clears
        `approved_cost_cents` back to null, recomputes the application's
        `approved_rehab_total_cents` downward by the cleared amount, increments
        `revision_round`, and sets `sizing_stale` to true when the application is
        `SIZED`."

        Design: Difficulty/non_linear_state_machine/rehab_line_revision_cycle_reenters_proposed_then_deapproves
        """
        ctx = fixtures.build_origination()
        kitchen = ctx.line_by_code(ScopeCode.KITCHEN.value)
        assert ctx.application["approved_rehab_total_cents"] == 10_000_000

        first = validate_success(
            api_client.review_rehab_line_item(
                kitchen["id"], factories.scope_request_revision_payload(), LOAN_OFFICER
            ),
            200,
        )
        assert first["status"] == RehabLineItemStatus.REVISION_REQUESTED.value
        assert first["revision_round"] == 1
        assert first["approved_cost_cents"] is None
        assert first["cost_cents"] == 3_500_000, (
            "the borrower's proposed cost survives a revision request"
        )
        assert ctx.refresh_application()["approved_rehab_total_cents"] == 6_500_000

        resubmitted = validate_success(
            api_client.resubmit_rehab_line_item(
                kitchen["id"],
                factories.scope_resubmit_payload(cost_cents=2_500_000),
                ctx.borrower_headers,
            ),
            200,
        )
        assert resubmitted["status"] == RehabLineItemStatus.PROPOSED.value
        assert resubmitted["cost_cents"] == 2_500_000
        assert resubmitted["revision_round"] == 1, (
            "a resubmission must not consume another revision round"
        )
        assert resubmitted["approved_cost_cents"] is None

        reapproved = fixtures.approve_scope_line(kitchen["id"], 2_500_000)
        assert reapproved["status"] == RehabLineItemStatus.APPROVED.value
        assert reapproved["approved_cost_cents"] == 2_500_000
        assert ctx.refresh_application()["approved_rehab_total_cents"] == 9_000_000

        deapproved = validate_success(
            api_client.review_rehab_line_item(
                kitchen["id"], factories.scope_request_revision_payload(), LOAN_OFFICER
            ),
            200,
        )
        assert deapproved["status"] == RehabLineItemStatus.REVISION_REQUESTED.value
        assert deapproved["revision_round"] == 2
        assert deapproved["approved_cost_cents"] is None
        assert deapproved["released_cents"] == 0
        assert ctx.refresh_application()["approved_rehab_total_cents"] == 6_500_000

    def test_the_fourth_trip_around_the_revision_loop_is_refused(self):
        """Three rounds are allowed; the resubmission on round three is refused.

        Each revision request increments the counter, so after three of them the
        line has exhausted its allowance and cannot be resubmitted again. The PRD
        states: "A line may go around the revision loop at most three times: a
        resubmission attempted when `revision_round` has already reached 3 is
        rejected with `ERR_REVISION_LIMIT_REACHED`."

        Design: Difficulty/non_linear_state_machine/rehab_line_revision_cycle_reenters_proposed_then_deapproves
        """
        ctx = fixtures.build_origination(approve_scope=False)
        line = ctx.line_by_code(ScopeCode.KITCHEN.value)

        for expected_round in (1, 2, 3):
            revised = validate_success(
                api_client.review_rehab_line_item(
                    line["id"], factories.scope_request_revision_payload(), LOAN_OFFICER
                ),
                200,
            )
            assert revised["revision_round"] == expected_round
            assert revised["status"] == RehabLineItemStatus.REVISION_REQUESTED.value
            if expected_round < 3:
                back = validate_success(
                    api_client.resubmit_rehab_line_item(
                        line["id"],
                        factories.scope_resubmit_payload(cost_cents=3_400_000),
                        ctx.borrower_headers,
                    ),
                    200,
                )
                assert back["status"] == RehabLineItemStatus.PROPOSED.value
                assert back["revision_round"] == expected_round

        validate_error(
            api_client.resubmit_rehab_line_item(
                line["id"],
                factories.scope_resubmit_payload(cost_cents=3_300_000),
                ctx.borrower_headers,
            ),
            ApiErrorId.REVISION_LIMIT_REACHED.value,
        )
        stuck = fixtures.read_line(line["id"])
        assert stuck["status"] == RehabLineItemStatus.REVISION_REQUESTED.value
        assert stuck["revision_round"] == 3
        assert stuck["cost_cents"] == 3_400_000, (
            "the refused resubmission must not apply its changes"
        )

    def test_resubmitting_a_line_that_is_not_awaiting_revision_is_a_state_error(self):
        """The resubmission edge leaves `REVISION_REQUESTED` and nowhere else.

        The PRD states: "Resubmission is only available while the line is in
        `REVISION_REQUESTED` — attempting it on a line in any other status is
        rejected with `ERR_REHAB_LINE_STATE_INVALID` — and only while the owning
        application is `DRAFT` or `SIZED`."

        Design: Corner/state_machines/action_endpoints_reject_a_wrong_source_state_on_every_machine
        """
        ctx = fixtures.build_origination(approve_scope=False)
        proposed = ctx.line_by_code(ScopeCode.ROOF.value)

        validate_error(
            api_client.resubmit_rehab_line_item(
                proposed["id"],
                factories.scope_resubmit_payload(cost_cents=3_000_000),
                ctx.borrower_headers,
            ),
            ApiErrorId.REHAB_LINE_STATE_INVALID.value,
        )

        rejected = validate_success(
            api_client.review_rehab_line_item(
                proposed["id"], factories.scope_reject_payload(), LOAN_OFFICER
            ),
            200,
        )
        assert rejected["status"] == RehabLineItemStatus.REJECTED.value
        validate_error(
            api_client.review_rehab_line_item(
                proposed["id"], factories.scope_approve_payload(), LOAN_OFFICER
            ),
            ApiErrorId.REHAB_LINE_STATE_INVALID.value,
        )


class TestDeapprovalAndRepricing:
    def test_deapproval_reverses_the_budget_and_freezes_the_credit_decision(self):
        """Stripping an approved line stales the sizing and blocks the committee.

        The de-approval takes `approved_rehab_total_cents` from 10,000,000 down
        to 6,500,000 while the sizing figures stay frozen on the numbers the
        officer computed, so the sizing is stale and the committee is locked out.
        The PRD states: "Deciding an application that was never sized is rejected
        with `ERR_SIZING_REQUIRED`, and deciding one whose `sizing_stale` reads
        true is rejected with `ERR_SIZING_STALE` — the committee is never allowed
        to approve a number computed against a stale appraisal or a since-changed
        scope."

        Design: Difficulty/compensating_invariant/scope_line_deapproval_reverses_the_budget_then_resizing_reprices_upward
        """
        ctx = fixtures.build_sized_application()
        assert_sizing_fields(
            ctx.application,
            cap_purchase_advance_cents=18_000_000,
            cap_ltc_cents=27_000_000,
            cap_ltarv_cents=24_000_000,
            max_total_loan_cents=24_000_000,
            sized_initial_funding_cents=13_195_000,
            sized_interest_reserve_cents=758_713,
            sized_committed_amount_cents=23_953_713,
            sizing_stale=False,
        )

        kitchen = ctx.line_by_code(ScopeCode.KITCHEN.value)
        deapproved = validate_success(
            api_client.review_rehab_line_item(
                kitchen["id"], factories.scope_request_revision_payload(), LOAN_OFFICER
            ),
            200,
        )
        assert deapproved["status"] == RehabLineItemStatus.REVISION_REQUESTED.value
        assert deapproved["approved_cost_cents"] is None
        assert deapproved["cost_cents"] == 3_500_000
        assert deapproved["revision_round"] == 1

        stale = ctx.refresh_application()
        assert stale["approved_rehab_total_cents"] == 6_500_000
        assert_sizing_fields(
            stale,
            sized_initial_funding_cents=13_195_000,
            sized_interest_reserve_cents=758_713,
            sized_committed_amount_cents=23_953_713,
            sizing_stale=True,
        )

        validate_error(
            api_client.decide_application(
                ctx.application_id,
                factories.decision_payload(),
                fixtures.CREDIT_COMMITTEE,
            ),
            ApiErrorId.SIZING_STALE.value,
        )
        assert ctx.refresh_application()["status"] == ApplicationStatus.SIZED.value

    def test_resizing_after_a_cheaper_resubmission_reprices_the_commitment_upward(self):
        """A smaller rehab budget frees purchase advance, so the resize goes up.

        Dropping the kitchen line from 3,500,000 to 2,500,000 leaves 9,000,000 of
        approved rehab, which lifts `sized_initial_funding_cents` from 13,195,000
        to 14,137,500 even though the after-repair ceiling is unchanged. The PRD
        states: "A re-sizing recomputes every sizing field against current
        property and scope-line values, re-snapshots both sentinels, and clears
        `sizing_stale`."

        Design: Difficulty/compensating_invariant/scope_line_deapproval_reverses_the_budget_then_resizing_reprices_upward
        """
        ctx = fixtures.build_sized_application()
        kitchen = ctx.line_by_code(ScopeCode.KITCHEN.value)

        validate_success(
            api_client.review_rehab_line_item(
                kitchen["id"], factories.scope_request_revision_payload(), LOAN_OFFICER
            ),
            200,
        )
        validate_success(
            api_client.resubmit_rehab_line_item(
                kitchen["id"],
                factories.scope_resubmit_payload(cost_cents=2_500_000),
                ctx.borrower_headers,
            ),
            200,
        )
        fixtures.approve_scope_line(kitchen["id"], 2_500_000)
        assert ctx.refresh_application()["approved_rehab_total_cents"] == 9_000_000
        assert ctx.application["sizing_stale"] is True

        fixtures.size_application(ctx)
        assert_sizing_fields(
            ctx.application,
            cap_purchase_advance_cents=18_000_000,
            cap_ltc_cents=26_100_000,
            cap_ltarv_cents=24_000_000,
            max_total_loan_cents=24_000_000,
            sized_initial_funding_cents=14_137_500,
            sized_interest_reserve_cents=812_906,
            sized_committed_amount_cents=23_950_406,
            sizing_stale=False,
        )
        assert ctx.application["sizing_arv_cents"] == 32_000_000
        assert ctx.application["sizing_rate_bps"] == 1150


class TestSingleLineConcentrationCap:
    def test_the_concentration_cap_is_measured_at_review_time(self):
        """The approved cost may not exceed half of the live scope total including itself.

        With a 1,000,000 sibling still proposed, the roof line's own approved cost
        is included in the total the cap is taken from, so 1,000,001 fails and
        1,000,000 — exactly half of the resulting 2,000,000 total — passes. The
        PRD states: "it may not exceed **half** of the application's
        proposed-plus-approved scope total measured at review time — that is,
        floor of one half of the sum of `cost_cents` across sibling lines still in
        `PROPOSED` or `REVISION_REQUESTED` plus the sum of `approved_cost_cents`
        across sibling lines already in `APPROVED`, with this line's own new
        approved cost included in that total."

        Design: Corner/calculations/the_single_line_cap_constant_is_applied_at_review_time
        """
        ctx = fixtures.build_origination(
            scope=TWO_UNEVEN_LINES, approve_scope=False
        )
        roof = ctx.line_by_code(ScopeCode.ROOF.value)

        validate_error(
            api_client.review_rehab_line_item(
                roof["id"], factories.scope_approve_payload(1_000_001), LOAN_OFFICER
            ),
            ApiErrorId.SCOPE_LINE_CAP_EXCEEDED.value,
        )
        untouched = fixtures.read_line(roof["id"])
        assert untouched["status"] == RehabLineItemStatus.PROPOSED.value
        assert untouched["approved_cost_cents"] is None
        assert ctx.refresh_application()["approved_rehab_total_cents"] == 0

        approved = fixtures.approve_scope_line(roof["id"], 1_000_000)
        assert approved["status"] == RehabLineItemStatus.APPROVED.value
        assert approved["approved_cost_cents"] == 1_000_000
        assert ctx.refresh_application()["approved_rehab_total_cents"] == 1_000_000

    def test_the_approved_cost_may_not_exceed_the_borrowers_proposed_cost(self):
        """Approving above the proposed figure breaches the other ceiling.

        Here the concentration cap is a comfortable 5,600,000, so the only rule
        the 1,200,000 approval can break is the proposed-cost ceiling on a line
        the borrower costed at 1,000,000. The PRD states: "The approved cost may
        not exceed the borrower's proposed `cost_cents`".

        Design: Corner/calculations/the_single_line_cap_constant_is_applied_at_review_time
        """
        scope = [
            fixtures.ScopeSpec("PERMITS", 1_000_000, 0, "Permit expediting"),
            fixtures.ScopeSpec("ROOF", 5_000_000, 0, "Tear-off and re-deck"),
            fixtures.ScopeSpec("ELECTRICAL", 5_000_000, 1, "Full rewire and panel"),
        ]
        ctx = fixtures.build_origination(scope=scope, approve_scope=False)
        permits = ctx.line_by_code(ScopeCode.PERMITS.value)

        validate_error(
            api_client.review_rehab_line_item(
                permits["id"], factories.scope_approve_payload(1_200_000), LOAN_OFFICER
            ),
            ApiErrorId.SCOPE_LINE_CAP_EXCEEDED.value,
        )

        defaulted = fixtures.approve_scope_line(permits["id"])
        assert defaulted["approved_cost_cents"] == 1_000_000, (
            "an omitted approved cost defaults to the proposed cost_cents"
        )


class TestScopeCodeUniqueness:
    def test_a_scope_code_is_unique_among_live_siblings_only(self):
        """A code is blocked while a live sibling holds it and freed once rejected.

        A duplicate `ROOF` is refused while the first roof line is still
        `PROPOSED`, a resubmission may not collide with a live sibling either, and
        the code becomes reusable the moment the original line is rejected. The
        PRD states: "A scope code must be unique among the application's *live*
        lines — those whose `status` is `PROPOSED`, `REVISION_REQUESTED`,
        `APPROVED` or `FULLY_RELEASED` — so a second `ROOF` line alongside a live
        one is rejected with `ERR_DUPLICATE_SCOPE_CODE`, while re-using a code
        whose earlier line was rejected or voided is permitted."

        Design: Corner/errors/scope_codes_are_unique_among_live_siblings_only
        """
        scope = [
            fixtures.ScopeSpec("ROOF", 4_000_000, 0, "Tear-off and re-deck"),
            fixtures.ScopeSpec("KITCHEN", 3_500_000, 0, "Cabinets and counters"),
        ]
        ctx = fixtures.build_origination(scope=scope, approve_scope=False)
        roof = ctx.line_by_code(ScopeCode.ROOF.value)
        kitchen = ctx.line_by_code(ScopeCode.KITCHEN.value)

        validate_error(
            api_client.create_rehab_line_item(
                ctx.application_id,
                factories.rehab_line_payload(
                    ScopeCode.ROOF.value, 1_500_000, ctx.contractor_id(0)
                ),
                LOAN_OFFICER,
            ),
            ApiErrorId.DUPLICATE_SCOPE_CODE.value,
        )

        validate_success(
            api_client.review_rehab_line_item(
                kitchen["id"], factories.scope_request_revision_payload(), LOAN_OFFICER
            ),
            200,
        )
        validate_error(
            api_client.resubmit_rehab_line_item(
                kitchen["id"],
                factories.scope_resubmit_payload(
                    scope_code=ScopeCode.ROOF.value, cost_cents=3_000_000
                ),
                ctx.borrower_headers,
            ),
            ApiErrorId.DUPLICATE_SCOPE_CODE.value,
        )
        blocked = fixtures.read_line(kitchen["id"])
        assert blocked["status"] == RehabLineItemStatus.REVISION_REQUESTED.value
        assert blocked["scope_code"] == ScopeCode.KITCHEN.value

        moved = validate_success(
            api_client.resubmit_rehab_line_item(
                kitchen["id"],
                factories.scope_resubmit_payload(
                    scope_code=ScopeCode.BATH.value, cost_cents=3_000_000
                ),
                ctx.borrower_headers,
            ),
            200,
        )
        assert moved["scope_code"] == ScopeCode.BATH.value
        assert moved["status"] == RehabLineItemStatus.PROPOSED.value
        assert moved["revision_round"] == 1

        validate_success(
            api_client.review_rehab_line_item(
                roof["id"], factories.scope_reject_payload(), LOAN_OFFICER
            ),
            200,
        )
        revived = validate_success(
            api_client.create_rehab_line_item(
                ctx.application_id,
                factories.rehab_line_payload(
                    ScopeCode.ROOF.value, 1_500_000, ctx.contractor_id(0)
                ),
                LOAN_OFFICER,
            ),
            201,
        )
        assert revived["scope_code"] == ScopeCode.ROOF.value
        assert revived["status"] == RehabLineItemStatus.PROPOSED.value

        rows, meta = validate_paginated(
            api_client.list_application_rehab_line_items(
                ctx.application_id, LOAN_OFFICER
            )
        )
        assert meta["total_count"] == 3, f"expected three scope line rows, got {meta['total_count']}"
        assert [row["scope_code"] for row in rows] == [
            ScopeCode.ROOF.value,
            ScopeCode.BATH.value,
            ScopeCode.ROOF.value,
        ], "list results are ordered by created_at ascending"
