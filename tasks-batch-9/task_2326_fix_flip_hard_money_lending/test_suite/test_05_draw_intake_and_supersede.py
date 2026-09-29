"""Draw intake: allocation validation, the supersede-create and its compensating reversal."""

from test_helpers import (
    ApiErrorId,
    DrawRequestStatus,
    InspectionVisitStatus,
    NON_EXISTENT_UUID,
    RehabLineItemStatus,
    ScopeCode,
    api_client,
    assert_loan_buckets,
    assert_system_fields,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
    INSPECTOR,
    LOAN_OFFICER,
    SERVICER,
)

DRAW_CLOCK = "2026-09-01T12:00:00Z"
FIRST_WINDOW = ("2026-09-01T09:00:00Z", "2026-09-01T11:00:00Z")
FOUR_LINE_SCOPE = [
    fixtures.ScopeSpec("ROOF", 4_000_000, 0, "Tear-off and re-deck"),
    fixtures.ScopeSpec("KITCHEN", 3_500_000, 0, "Cabinets and counters"),
    fixtures.ScopeSpec("ELECTRICAL", 2_500_000, 1, "Full rewire and panel"),
    fixtures.ScopeSpec("PERMITS", 1_000_000, 0, "Permit expediting"),
]


def _live_loan_with_coverage():
    """A closed loan with generous unconditional waiver coverage for both trades."""
    ctx = fixtures.build_closed_loan()
    fixtures.set_clock(DRAW_CLOCK)
    fixtures.cover_all_contractors(ctx)
    return ctx


class TestApprovedSupersedeReversal:
    def test_superseding_an_approved_draw_returns_the_reservation_to_the_holdback(self):
        """The reservation is unwound exactly, not merely marked superseded.

        Approval had moved 3,892,500 into `reserved_release_cents`; the
        supersede-create puts every cent back into `undisbursed_holdback_cents`,
        nulls the request and per-allocation approved figures, and leaves funded
        principal untouched because nothing was ever disbursed. The PRD states:
        "Superseding a request that was already `APPROVED` performs the
        compensating reversal of §2.10: the request's `approved_release_cents`
        returns from the loan's `reserved_release_cents` to its
        `undisbursed_holdback_cents`, and `approved_release_cents` together with
        every allocation's `approved_amount_cents` is cleared back to null, so
        `commitment_balance_check_cents` still reads zero."

        Design: Difficulty/compensating_invariant/superseding_an_approved_draw_unreserves_the_holdback_exactly
        """
        ctx = _live_loan_with_coverage()
        allocations = [
            (ctx.line_by_code(ScopeCode.ROOF.value)["id"], 0.50),
            (ctx.line_by_code(ScopeCode.KITCHEN.value)["id"], 0.45),
            (ctx.line_by_code(ScopeCode.ELECTRICAL.value)["id"], 0.30),
        ]
        first, _visit = fixtures.build_inspected_draw(
            ctx, allocations, window_start=FIRST_WINDOW[0], window_end=FIRST_WINDOW[1]
        )
        approved = fixtures.review_draw(first["id"])
        assert approved["status"] == DrawRequestStatus.APPROVED.value
        assert approved["approved_release_cents"] == 3_892_500

        reserved = ctx.refresh_loan()
        assert_loan_buckets(
            reserved,
            reserved_release_cents=3_892_500,
            undisbursed_holdback_cents=6_107_500,
            funded_principal_cents=13_151_375,
        )
        assert reserved["available_rehab_pool_cents"] == 10_000_000

        second = fixtures.submit_draw(
            ctx, [(ctx.line_by_code(ScopeCode.ROOF.value)["id"], 0.60)]
        )
        superseded = fixtures.read_draw_request(first["id"])
        assert superseded["status"] == DrawRequestStatus.SUPERSEDED.value
        assert superseded["superseded_by_draw_request_id"] == second["id"]
        assert superseded["approved_release_cents"] is None

        rows, meta = validate_paginated(
            api_client.list_draw_line_items(
                SERVICER, {"draw_request_id": first["id"]}
            )
        )
        assert meta["total_count"] == 3
        for row in rows:
            assert row["approved_amount_cents"] is None, (
                "every allocation's approved amount is cleared back to null"
            )
            assert row["released_cents"] == 0

        restored = ctx.refresh_loan()
        assert_loan_buckets(
            restored,
            reserved_release_cents=0,
            undisbursed_holdback_cents=10_000_000,
            funded_principal_cents=13_151_375,
        )
        assert restored["commitment_balance_check_cents"] == 0

    def test_two_successive_approved_supersedes_restore_the_holdback_without_drift(self):
        """Approve, supersede, approve again, supersede again: the same figure returns.

        The holdback comes back to 10,000,000 after each reversal — not to a
        slightly different number each round — proving the reversal is the exact
        inverse of the reservation rather than an approximation. The PRD states:
        "Whenever a cascade or a supersede undoes an approval that had already
        reserved cash, the platform performs an explicit compensating reversal so
        that `commitment_balance_check_cents` still reads zero afterwards".

        Design: Difficulty/compensating_invariant/superseding_an_approved_draw_unreserves_the_holdback_exactly
        """
        ctx = _live_loan_with_coverage()
        roof_id = ctx.line_by_code(ScopeCode.ROOF.value)["id"]

        first, _v1 = fixtures.build_inspected_draw(
            ctx,
            [(roof_id, 0.50)],
            window_start=FIRST_WINDOW[0],
            window_end=FIRST_WINDOW[1],
        )
        assert fixtures.review_draw(first["id"])["approved_release_cents"] == 1_800_000
        assert ctx.refresh_loan()["reserved_release_cents"] == 1_800_000

        second, _v2 = fixtures.build_inspected_draw(
            ctx,
            [(roof_id, 0.60)],
            window_start="2026-09-05T09:00:00Z",
            window_end="2026-09-05T11:00:00Z",
        )
        after_first_reversal = ctx.refresh_loan()
        assert_loan_buckets(
            after_first_reversal,
            reserved_release_cents=0,
            undisbursed_holdback_cents=10_000_000,
        )
        assert fixtures.read_draw_request(first["id"])["status"] == (
            DrawRequestStatus.SUPERSEDED.value
        )

        assert fixtures.review_draw(second["id"])["approved_release_cents"] == 2_160_000
        assert_loan_buckets(
            ctx.refresh_loan(),
            reserved_release_cents=2_160_000,
            undisbursed_holdback_cents=7_840_000,
        )

        third = fixtures.submit_draw(ctx, [(roof_id, 0.30)])
        after_second_reversal = ctx.refresh_loan()
        assert_loan_buckets(
            after_second_reversal,
            reserved_release_cents=0,
            undisbursed_holdback_cents=10_000_000,
            funded_principal_cents=13_151_375,
        )
        assert after_second_reversal["undisbursed_holdback_cents"] == (
            after_first_reversal["undisbursed_holdback_cents"]
        ), "the restored holdback must not drift between reversals"
        assert third["sequence_number"] == 3


class TestSupersedeCreateConcurrency:
    def test_the_supersede_create_is_guarded_by_the_loan_version(self):
        """Replaying a consumed loan version is refused and supersedes nothing.

        The first create consumes the version and bumps the loan; replaying that
        same number is 412 and — critically — does not cancel the earlier request,
        which the caller never saw. Echoing the fresh version then performs the
        supersede the stale call was denied. The PRD states: "If
        `expected_loan_version` does not equal the loan's current `version`, the
        request is rejected with `ERR_STALE_LOAN_VERSION` (HTTP 412) and no draw
        request is created."

        Design: Corner/cross_cutting_complexity_layers/the_draw_supersede_create_is_guarded_by_the_loan_version
        """
        ctx = fixtures.build_closed_loan()
        roof_id = ctx.line_by_code(ScopeCode.ROOF.value)["id"]
        stale_version = ctx.refresh_loan()["version"]

        first = validate_success(
            api_client.create_draw_request(
                ctx.loan_id,
                factories.draw_request_payload(
                    [factories.line_allocation(roof_id, 0.60)], stale_version
                ),
                ctx.borrower_headers,
            ),
            201,
        )
        assert first["status"] == DrawRequestStatus.SUBMITTED.value
        assert first["sequence_number"] == 1
        assert first["requested_total_cents"] == 2_400_000
        assert ctx.refresh_loan()["version"] == stale_version + 1, (
            "an accepted create bumps the parent loan exactly once"
        )

        validate_error(
            api_client.create_draw_request(
                ctx.loan_id,
                factories.draw_request_payload(
                    [factories.line_allocation(roof_id, 0.40)], stale_version
                ),
                ctx.borrower_headers,
            ),
            ApiErrorId.STALE_LOAN_VERSION.value,
            412,
        )
        untouched = fixtures.read_draw_request(first["id"])
        assert untouched["status"] == DrawRequestStatus.SUBMITTED.value
        assert untouched["superseded_by_draw_request_id"] is None, (
            "a rejected supersede-create must not cancel the earlier request"
        )
        fresh_version = ctx.refresh_loan()["version"]
        assert fresh_version == stale_version + 1, (
            "a rejected write must not increment the loan version"
        )

        second = validate_success(
            api_client.create_draw_request(
                ctx.loan_id,
                factories.draw_request_payload(
                    [factories.line_allocation(roof_id, 0.40)], fresh_version
                ),
                ctx.borrower_headers,
            ),
            201,
        )
        assert second["sequence_number"] == 2
        assert fixtures.read_draw_request(first["id"])[
            "superseded_by_draw_request_id"
        ] == second["id"]
        assert fixtures.read_draw_request(first["id"])["status"] == (
            DrawRequestStatus.SUPERSEDED.value
        )
        assert ctx.refresh_loan()["version"] == fresh_version + 1


class TestAllocationIntakeValidation:
    def test_draw_intake_rejects_foreign_duplicate_and_unapproved_allocations(self):
        """Three structurally different bad arrays each get their own refusal.

        A line belonging to another application is a mismatch, the same line twice
        is a duplicate, and a rejected sibling line is not approved — while the
        clean single-line array is accepted, so none of the three is a blanket
        refusal of intake. The PRD states: "An allocation naming a scope line that
        does not belong to the loan's originating application is rejected with
        `ERR_LINE_ITEM_MISMATCH`, and one naming a line whose `status` is anything
        other than `APPROVED` is rejected with `ERR_SCOPE_LINE_NOT_APPROVED`."

        Design: Corner/validations/draw_intake_rejects_foreign_duplicate_and_unapproved_allocations
        """
        ctx = fixtures.build_origination(scope=FOUR_LINE_SCOPE, approve_scope=False)
        roof = ctx.line_by_code(ScopeCode.ROOF.value)
        permits = ctx.line_by_code(ScopeCode.PERMITS.value)
        for code in (ScopeCode.ROOF, ScopeCode.KITCHEN, ScopeCode.ELECTRICAL):
            spec = next(s for s in FOUR_LINE_SCOPE if s.scope_code == code.value)
            fixtures.approve_scope_line(
                ctx.line_by_code(code.value)["id"], spec.cost_cents
            )
        validate_success(
            api_client.review_rehab_line_item(
                permits["id"], factories.scope_reject_payload(), LOAN_OFFICER
            ),
            200,
        )
        ctx.refresh_lines()
        fixtures.size_application(ctx)
        fixtures.decide_application(ctx)
        fixtures.close_application(ctx)

        other_property = fixtures.register_property(address_line="42 Cholla Way")
        other_application = fixtures.open_application(
            ctx.borrower_id, other_property["id"]
        )
        foreign_line = fixtures.add_scope_line(
            other_application["id"],
            fixtures.ScopeSpec("ROOF", 2_000_000, 0, "Tear-off and re-deck"),
            ctx.contractor_id(0),
        )
        # The concentration cap is measured across the application's live lines, so
        # the foreign application carries a sibling of equal cost before its ROOF
        # line is approved at the full proposed figure.
        fixtures.add_scope_line(
            other_application["id"],
            fixtures.ScopeSpec("KITCHEN", 2_000_000, 0, "Cabinets and counters"),
            ctx.contractor_id(0),
        )
        fixtures.approve_scope_line(foreign_line["id"], 2_000_000)

        version = ctx.refresh_loan()["version"]
        validate_error(
            api_client.create_draw_request(
                ctx.loan_id,
                factories.draw_request_payload(
                    [factories.line_allocation(foreign_line["id"], 0.50)], version
                ),
                ctx.borrower_headers,
            ),
            ApiErrorId.LINE_ITEM_MISMATCH.value,
        )
        validate_error(
            api_client.create_draw_request(
                ctx.loan_id,
                factories.draw_request_payload(
                    [
                        factories.line_allocation(roof["id"], 0.50),
                        factories.line_allocation(roof["id"], 0.30),
                    ],
                    version,
                ),
                ctx.borrower_headers,
            ),
            ApiErrorId.LINE_ALLOCATION_DUPLICATE.value,
        )
        assert fixtures.read_line(permits["id"])["status"] == (
            RehabLineItemStatus.REJECTED.value
        )
        validate_error(
            api_client.create_draw_request(
                ctx.loan_id,
                factories.draw_request_payload(
                    [factories.line_allocation(permits["id"], 0.50)], version
                ),
                ctx.borrower_headers,
            ),
            ApiErrorId.SCOPE_LINE_NOT_APPROVED.value,
        )
        assert ctx.refresh_loan()["version"] == version, (
            "none of the three refusals may bump the loan version"
        )

        accepted = validate_success(
            api_client.create_draw_request(
                ctx.loan_id,
                factories.draw_request_payload(
                    [factories.line_allocation(roof["id"], 0.60)], version
                ),
                ctx.borrower_headers,
            ),
            201,
        )
        assert accepted["status"] == DrawRequestStatus.SUBMITTED.value
        assert accepted["verification_method"] == "INSPECTION"
        assert accepted["requested_total_cents"] == 2_400_000
        _, meta = validate_paginated(
            api_client.list_draw_line_items(
                SERVICER, {"draw_request_id": accepted["id"]}
            )
        )
        assert meta["total_count"] == 1


class TestDrawLineItemJunction:
    def test_draw_line_items_bridge_draw_requests_and_scope_lines(self):
        """One scope line accumulates allocations from more than one draw request.

        Filtering the junction by scope line returns the funded allocation and the
        later open one; filtering by request returns only that request's three
        allocations. The PRD states: "Each allocation records its owning
        `draw_request_id`, its `rehab_line_item_id`, the submitted
        `claimed_percent_complete`, and a `requested_amount_cents` computed at
        creation time as the scope line's `approved_cost_cents` multiplied by
        `claimed_percent_complete`, rounded half up to whole cents, less that scope
        line's `released_cents` at that moment."

        Design: Corner/entities/draw_line_items_bridge_draw_requests_and_scope_lines
        """
        ctx = _live_loan_with_coverage()
        roof_id = ctx.line_by_code(ScopeCode.ROOF.value)["id"]
        kitchen_id = ctx.line_by_code(ScopeCode.KITCHEN.value)["id"]
        electrical_id = ctx.line_by_code(ScopeCode.ELECTRICAL.value)["id"]

        first, _visit = fixtures.build_inspected_draw(
            ctx,
            [(roof_id, 0.60), (kitchen_id, 0.45), (electrical_id, 0.33)],
            verifications=[(roof_id, 0.50), (kitchen_id, 0.45), (electrical_id, 0.33)],
            window_start=FIRST_WINDOW[0],
            window_end=FIRST_WINDOW[1],
        )
        assert first["requested_total_cents"] == 4_800_000
        fixtures.review_draw(first["id"])
        fixtures.fund_draw(first["id"], funding_date="2026-09-01")
        funded = fixtures.read_draw_request(first["id"])
        assert funded["status"] == DrawRequestStatus.FUNDED.value
        assert funded["approved_release_cents"] == 3_960_000

        second = fixtures.submit_draw(ctx, [(roof_id, 0.70)])
        assert second["sequence_number"] == 2
        assert fixtures.read_draw_request(first["id"])["status"] == (
            DrawRequestStatus.FUNDED.value
        ), "a FUNDED request is terminal and is never superseded"

        by_line, line_meta = validate_paginated(
            api_client.list_draw_line_items(SERVICER, {"rehab_line_item_id": roof_id})
        )
        assert line_meta["total_count"] == 2, (
            "the junction is many-to-many: one scope line, two allocations"
        )
        by_request = {row["draw_request_id"]: row for row in by_line}
        assert by_request[first["id"]]["approved_amount_cents"] == 1_800_000
        assert by_request[first["id"]]["released_cents"] == 1_800_000
        assert by_request[second["id"]]["approved_amount_cents"] is None
        assert by_request[second["id"]]["released_cents"] == 0

        rows, request_meta = validate_paginated(
            api_client.list_draw_line_items(SERVICER, {"draw_request_id": first["id"]})
        )
        assert request_meta["total_count"] == 3
        assert sum(row["requested_amount_cents"] for row in rows) == (
            first["requested_total_cents"]
        )
        assert sorted(row["requested_amount_cents"] for row in rows) == [
            825_000,
            1_575_000,
            2_400_000,
        ]
        for row in rows:
            assert_system_fields(row)
            one = validate_success(
                api_client.get_draw_line_item(row["id"], SERVICER), 200
            )
            assert one["draw_request_id"] == first["id"]


class TestSupersedeVisitCascade:
    def test_superseding_cancels_only_the_visits_that_are_still_scheduled(self):
        """Same trigger, two child outcomes, decided by the visit's own status.

        Superseding an `INSPECTED` draw leaves its `COMPLETED` visit and its
        `reported_at` alone, while superseding an `INSPECTION_ORDERED` draw
        cancels the `SCHEDULED` visit and frees the inspector's calendar. The PRD
        states: "Superseding a request that was `INSPECTION_ORDERED` also cascades
        every `SCHEDULED` inspection visit of that request to `CANCELLED`, which
        frees the inspector's calendar slot for future conflict checks."

        Design: Corner/state_machines/superseding_cancels_only_the_visits_that_are_still_scheduled
        """
        ctx = _live_loan_with_coverage()
        roof_id = ctx.line_by_code(ScopeCode.ROOF.value)["id"]
        kitchen_id = ctx.line_by_code(ScopeCode.KITCHEN.value)["id"]
        electrical_id = ctx.line_by_code(ScopeCode.ELECTRICAL.value)["id"]

        first, completed_visit = fixtures.build_inspected_draw(
            ctx,
            [(roof_id, 0.50), (kitchen_id, 0.45), (electrical_id, 0.30)],
            window_start=FIRST_WINDOW[0],
            window_end=FIRST_WINDOW[1],
        )
        assert first["status"] == DrawRequestStatus.INSPECTED.value
        reported, _ = validate_paginated(
            api_client.list_inspection_visits(first["id"], SERVICER)
        )
        finished = reported[0]
        assert finished["id"] == completed_visit["id"]
        assert finished["status"] == InspectionVisitStatus.COMPLETED.value
        assert finished["reported_at"] is not None

        second = fixtures.submit_draw(ctx, [(roof_id, 0.60)])
        assert fixtures.read_draw_request(first["id"])["status"] == (
            DrawRequestStatus.SUPERSEDED.value
        )
        assert fixtures.read_draw_request(first["id"])[
            "superseded_by_draw_request_id"
        ] == second["id"]
        after_supersede, _ = validate_paginated(
            api_client.list_inspection_visits(first["id"], SERVICER)
        )
        still_completed = after_supersede[0]
        assert still_completed["status"] == InspectionVisitStatus.COMPLETED.value
        assert still_completed["reported_at"] == finished["reported_at"], (
            "the cascade skips visits that are not SCHEDULED"
        )

        reused_window = fixtures.order_visit(
            second["id"],
            INSPECTOR,
            window_start=FIRST_WINDOW[0],
            window_end=FIRST_WINDOW[1],
        )
        assert reused_window["status"] == InspectionVisitStatus.SCHEDULED.value, (
            "the buffered window of a COMPLETED visit no longer occupies the calendar"
        )
        assert fixtures.read_draw_request(second["id"])["status"] == (
            DrawRequestStatus.INSPECTION_ORDERED.value
        )

        third = fixtures.submit_draw(ctx, [(kitchen_id, 0.40)])
        assert fixtures.read_draw_request(second["id"])["status"] == (
            DrawRequestStatus.SUPERSEDED.value
        )
        cancelled, _ = validate_paginated(
            api_client.list_inspection_visits(second["id"], SERVICER)
        )
        cancelled_row = cancelled[0]
        assert cancelled_row["id"] == reused_window["id"]
        assert cancelled_row["status"] == InspectionVisitStatus.CANCELLED.value, (
            "a SCHEDULED visit is cancelled by the same cascade"
        )

        chain, chain_meta = validate_paginated(
            api_client.list_draw_requests(
                SERVICER, {"superseded_by_draw_request_id": third["id"]}
            )
        )
        assert chain_meta["total_count"] == 1, "the supersede pointer is queryable"
        assert chain[0]["id"] == second["id"]


class TestNestedParentResolution:
    def test_child_creation_requires_a_resolvable_parent_and_referenced_contractor(self):
        """The nested route resolves the parent before it looks at the body.

        A scope line posted under an unknown application id answers with the
        application's own not-found code, and one naming an unknown contractor
        answers with the contractor's; a line created under the right parent is
        reachable from both the application route and the contractor-side reverse
        route. The PRD states: "A scope line is added under an application with a
        `scope_code`, a `description` narrative, a proposed `cost_cents` strictly
        greater than zero, and the `contractor_id` of the trade assigned to it;
        the owning application is taken from the path and recorded as
        `application_id`."

        Design: Corner/entities/child_creation_requires_a_resolvable_parent_and_referenced_contractor
        """
        fixtures.set_clock("2026-08-10T09:00:00Z")
        borrower = fixtures.build_approved_sponsor()
        subject = fixtures.register_property()
        first_trade = fixtures.register_contractor()
        second_trade = fixtures.register_contractor(**fixtures.CONTRACTOR_TWO)
        application = fixtures.open_application(borrower["id"], subject["id"])

        validate_error(
            api_client.create_rehab_line_item(
                NON_EXISTENT_UUID,
                factories.rehab_line_payload(
                    ScopeCode.ROOF.value, 4_000_000, first_trade["id"]
                ),
                LOAN_OFFICER,
            ),
            ApiErrorId.APPLICATION_NOT_FOUND.value,
            404,
        )
        validate_error(
            api_client.create_rehab_line_item(
                application["id"],
                factories.rehab_line_payload(
                    ScopeCode.ROOF.value, 4_000_000, NON_EXISTENT_UUID
                ),
                LOAN_OFFICER,
            ),
            ApiErrorId.CONTRACTOR_NOT_FOUND.value,
            404,
        )
        _, empty_meta = validate_paginated(
            api_client.list_application_rehab_line_items(
                application["id"], LOAN_OFFICER
            )
        )
        assert empty_meta["total_count"] == 0, (
            "neither refused create may leave a row behind"
        )

        roof = validate_success(
            api_client.create_rehab_line_item(
                application["id"],
                factories.rehab_line_payload(
                    ScopeCode.ROOF.value, 4_000_000, first_trade["id"]
                ),
                LOAN_OFFICER,
            ),
            201,
        )
        assert roof["application_id"] == application["id"]
        assert roof["contractor_id"] == first_trade["id"]
        electrical = validate_success(
            api_client.create_rehab_line_item(
                application["id"],
                factories.rehab_line_payload(
                    ScopeCode.ELECTRICAL.value, 2_500_000, second_trade["id"]
                ),
                LOAN_OFFICER,
            ),
            201,
        )

        rows, meta = validate_paginated(
            api_client.list_application_rehab_line_items(
                application["id"], LOAN_OFFICER
            )
        )
        assert meta["total_count"] == 2
        assert {row["application_id"] for row in rows} == {application["id"]}

        mine, mine_meta = validate_paginated(
            api_client.list_contractor_rehab_line_items(
                first_trade["id"], LOAN_OFFICER
            )
        )
        assert mine_meta["total_count"] == 1, (
            "the reverse route is filtered to that contractor's lines"
        )
        assert mine[0]["id"] == roof["id"]
        assert electrical["id"] != roof["id"]
