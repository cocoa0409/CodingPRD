"""Authentication, role authorisation, entity ownership, split duties and rule order."""

from test_helpers import (
    ApiErrorId,
    ApplicationStatus,
    DrawRequestStatus,
    InspectionVisitStatus,
    LedgerEntryType,
    LienWaiverStatus,
    LoanExitStatus,
    MilestoneType,
    NON_EXISTENT_UUID,
    api_client,
    assert_allocation_fields,
    assert_contractor_waiver_figures,
    assert_exit_monitoring,
    assert_loan_buckets,
    assert_sizing_fields,
    factories,
    fixtures,
    headers_with_unknown_role,
    headers_without_role,
    make_borrower_headers,
    make_contractor_headers,
    make_credit_committee_headers,
    make_loan_officer_headers,
    validate_error,
    validate_paginated,
    validate_success,
    CREDIT_COMMITTEE,
    INSPECTOR,
    INSPECTOR_2,
    LOAN_OFFICER,
    SERVICER,
    SERVICER_2,
)

CLOSING_DATE = "2026-08-10"
DRAW_CLOCK = "2026-09-01T12:00:00Z"
FUNDING_DATE = "2026-09-01"


def _three_line_allocations(ctx):
    return [
        (ctx.line_by_code("ROOF")["id"], 0.60),
        (ctx.line_by_code("KITCHEN")["id"], 0.45),
        (ctx.line_by_code("ELECTRICAL")["id"], 0.33),
    ]


def _three_line_verifications(ctx):
    return [
        (ctx.line_by_code("ROOF")["id"], 0.50),
        (ctx.line_by_code("KITCHEN")["id"], 0.45),
        (ctx.line_by_code("ELECTRICAL")["id"], 0.30),
    ]


def _submitted_draw(ctx):
    fixtures.set_clock(DRAW_CLOCK)
    return fixtures.submit_draw(ctx, _three_line_allocations(ctx))


class TestAuthenticationBeforeAuthorisation:
    def test_a_missing_or_unknown_role_is_401_and_a_declared_wrong_role_is_403(self):
        """Two 401s on header shape, three 403s on the endpoint's role list.

        The 401 is decided from the header alone, so it also outranks the not-found
        lookup on an identifier that does not exist, while the contractor's attempt at
        a draw request stops at the role row and never reaches the ownership row it
        would also have failed. The PRD states: "If `X-User-Role` is absent, empty, or
        not one of the seven declared role names, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/an_absent_or_unknown_role_is_401_while_a_wrong_role_is_403
        """
        ctx = fixtures.build_closed_loan()
        draw = _submitted_draw(ctx)
        assert draw["status"] == DrawRequestStatus.SUBMITTED.value

        validate_error(
            api_client.get_borrower(ctx.borrower_id, headers_without_role()),
            ApiErrorId.UNAUTHENTICATED.value,
            401,
        )
        validate_error(
            api_client.get_borrower(ctx.borrower_id, headers_with_unknown_role()),
            ApiErrorId.UNAUTHENTICATED.value,
            401,
        )
        unknown_id = validate_error(
            api_client.get_borrower(NON_EXISTENT_UUID, headers_without_role()),
            ApiErrorId.UNAUTHENTICATED.value,
            401,
        )
        assert unknown_id["error_id"] == ApiErrorId.UNAUTHENTICATED.value, (
            "authentication precedes the not-found lookup"
        )

        validate_error(
            api_client.decide_application(
                ctx.application_id, factories.decision_payload(), LOAN_OFFICER
            ),
            ApiErrorId.FORBIDDEN_ROLE.value,
            403,
        )
        validate_error(
            api_client.fund_draw_request(
                draw["id"], factories.draw_fund_payload(FUNDING_DATE), INSPECTOR
            ),
            ApiErrorId.FORBIDDEN_ROLE.value,
            403,
        )
        validate_error(
            api_client.create_draw_request(
                ctx.loan_id,
                factories.draw_request_payload(
                    [factories.line_allocation(ctx.line_id(0), 0.60)],
                    fixtures.read_loan(ctx.loan_id)["version"],
                ),
                make_contractor_headers(ctx.contractor_id(0)),
            ),
            ApiErrorId.FORBIDDEN_ROLE.value,
            403,
        )

        assert fixtures.read_draw_request(draw["id"])["status"] == (
            DrawRequestStatus.SUBMITTED.value
        )
        assert ctx.refresh_application()["status"] == ApplicationStatus.CLOSED.value
        requests, meta = validate_paginated(
            api_client.list_draw_requests(SERVICER, {"loan_id": ctx.loan_id})
        )
        assert meta["total_count"] == 1, (
            f"the refused create wrote nothing, got {meta['total_count']}"
        )
        assert requests[0]["id"] == draw["id"]


class TestOriginationChainRoles:
    def test_sizing_deciding_and_closing_each_refuse_the_neighbouring_role(self):
        """Three steps, three owners, and each refusal leaves the status untouched.

        The same request body that is refused from an adjacent internal role succeeds
        from the owning one, so the chain advances exactly three times even though all
        three roles are trusted. The PRD states: "When the header names a valid role
        that is not permitted on the requested operation, the rejection is
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/the_origination_chain_is_three_role_exclusive_steps
        """
        ctx = fixtures.build_origination()
        assert ctx.application["status"] == ApplicationStatus.DRAFT.value

        validate_error(
            api_client.size_application(
                ctx.application_id, factories.size_payload(), CREDIT_COMMITTEE
            ),
            ApiErrorId.FORBIDDEN_ROLE.value,
            403,
        )
        assert ctx.refresh_application()["status"] == ApplicationStatus.DRAFT.value

        sized = fixtures.size_application(ctx, LOAN_OFFICER).application
        assert sized["status"] == ApplicationStatus.SIZED.value
        assert_sizing_fields(
            sized,
            max_total_loan_cents=24_000_000,
            sized_committed_amount_cents=23_953_713,
        )

        validate_error(
            api_client.decide_application(
                ctx.application_id, factories.decision_payload(), SERVICER
            ),
            ApiErrorId.FORBIDDEN_ROLE.value,
            403,
        )
        assert ctx.refresh_application()["status"] == ApplicationStatus.SIZED.value

        approved = fixtures.decide_application(ctx, CREDIT_COMMITTEE).application
        assert approved["status"] == ApplicationStatus.APPROVED.value
        assert_allocation_fields(
            approved,
            alloc_initial_funding_cents=13_151_375,
            alloc_interest_reserve_cents=802_338,
            alloc_rehab_holdback_cents=10_000_000,
        )

        validate_error(
            api_client.close_application(
                ctx.application_id, factories.close_payload(CLOSING_DATE), LOAN_OFFICER
            ),
            ApiErrorId.FORBIDDEN_ROLE.value,
            403,
        )
        assert ctx.refresh_application()["status"] == ApplicationStatus.APPROVED.value

        loan = fixtures.close_application(ctx, SERVICER, CLOSING_DATE).loan
        assert loan["committed_amount_cents"] == 23_953_713
        assert ctx.refresh_application()["status"] == ApplicationStatus.CLOSED.value


class TestEntityBackedOwnership:
    def test_a_peer_sponsor_and_a_peer_contractor_are_both_scoped_out(self):
        """Reads and writes alike compare the caller's own id to the row's foreign key.

        Both callers carry an authorised role for the endpoint they hit, so only the
        identifier separates the refusal from the success, and the read side is scoped
        exactly like the write side. The PRD states: "Ownership checks compare the
        `contractor_id` of the contractor record being read or the lien waiver being
        filed to `X-User-ID`, and a mismatch is likewise rejected with
        `ERR_NOT_OWNER`."

        Design: Corner/rbac/peers_of_the_same_role_cannot_reach_each_others_rows
        """
        ctx = fixtures.build_closed_loan()
        peer = fixtures.register_borrower(legal_entity_name="Saguaro Flips LLC")
        fixtures.execute_guarantee(peer["id"])
        peer_headers = make_borrower_headers(peer["id"])

        validate_error(
            api_client.get_loan(ctx.loan_id, peer_headers),
            ApiErrorId.NOT_OWNER.value,
            403,
        )
        own_read = validate_success(
            api_client.get_loan(ctx.loan_id, ctx.borrower_headers), 200
        )
        assert own_read["funded_principal_cents"] == 13_151_375

        first = ctx.contractor_id(0)
        second = ctx.contractor_id(1)
        waiver_body = factories.lien_waiver_payload(ctx.loan_id, first, 500_000)
        validate_error(
            api_client.create_lien_waiver(
                waiver_body, make_contractor_headers(second)
            ),
            ApiErrorId.NOT_OWNER.value,
            403,
        )
        filed = validate_success(
            api_client.create_lien_waiver(
                waiver_body, make_contractor_headers(first)
            ),
            201,
        )
        assert filed["status"] == LienWaiverStatus.COLLECTED.value
        assert filed["contractor_id"] == first
        assert filed["amount_covered_cents"] == 500_000

        validate_error(
            api_client.get_contractor(first, make_contractor_headers(second)),
            ApiErrorId.NOT_OWNER.value,
            403,
        )
        own_row = validate_success(
            api_client.get_contractor(first, make_contractor_headers(first)), 200
        )
        assert_contractor_waiver_figures(
            own_row,
            collected_waiver_coverage_cents=500_000,
            released_to_contractor_cents=0,
            open_waiver_headroom_cents=500_000,
        )

        waivers, meta = validate_paginated(
            api_client.list_loan_lien_waivers(ctx.loan_id, SERVICER)
        )
        assert meta["total_count"] == 1, (
            f"only the owner's write landed, got {meta['total_count']}"
        )
        assert waivers[0]["id"] == filed["id"]


class TestSplitDuties:
    def test_neither_control_pair_may_be_closed_by_a_single_user_id(self):
        """The sizing user cannot decide, and the reviewing user cannot fund.

        Segregation is keyed on `X-User-ID` rather than on role, so swapping in a
        second operator of the identical role clears both refusals with the identical
        bodies, and each refusal is a 403 that leaves the row in its prior state. The
        PRD states: "Any attempt to perform both halves of a split-duty pair under the
        same user id is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and that
        rejection applies to `PlatformAdmin` exactly as it applies to everyone else."

        Design: Corner/rbac/one_user_may_not_hold_both_sides_of_either_control_pair
        """
        ctx = fixtures.build_origination()
        fixtures.size_application(ctx, make_loan_officer_headers("dual-01"))

        validate_error(
            api_client.decide_application(
                ctx.application_id,
                factories.decision_payload(),
                make_credit_committee_headers("dual-01"),
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES.value,
            403,
        )
        assert ctx.refresh_application()["status"] == ApplicationStatus.SIZED.value

        approved = fixtures.decide_application(ctx, CREDIT_COMMITTEE).application
        assert approved["status"] == ApplicationStatus.APPROVED.value
        fixtures.close_application(ctx, SERVICER, CLOSING_DATE)
        fixtures.file_waiver(ctx.loan_id, ctx.contractor_id(0), 3_400_000)
        fixtures.file_waiver(ctx.loan_id, ctx.contractor_id(1), 700_000)

        fixtures.set_clock(DRAW_CLOCK)
        draw, _ = fixtures.build_inspected_draw(
            ctx, _three_line_allocations(ctx), _three_line_verifications(ctx)
        )
        assert draw["requested_total_cents"] == 4_800_000
        reviewed = fixtures.review_draw(draw["id"], SERVICER)
        assert reviewed["status"] == DrawRequestStatus.APPROVED.value
        assert reviewed["reviewed_by_user_id"] == "svc-01"
        assert reviewed["approved_release_cents"] == 3_892_500

        validate_error(
            api_client.fund_draw_request(
                draw["id"], factories.draw_fund_payload(FUNDING_DATE), SERVICER
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES.value,
            403,
        )
        held = fixtures.read_draw_request(draw["id"])
        assert held["status"] == DrawRequestStatus.APPROVED.value
        assert held["funded_at"] is None
        assert held["funded_by_user_id"] is None
        assert ctx.refresh_loan()["reserved_release_cents"] == 3_892_500

        funded = fixtures.fund_draw(draw["id"], SERVICER_2, FUNDING_DATE)
        assert funded["status"] == DrawRequestStatus.FUNDED.value
        assert funded["funded_by_user_id"] == "svc-02"
        assert funded["reviewed_by_user_id"] == "svc-01"
        assert funded["approved_release_cents"] == 3_892_500
        loan = ctx.refresh_loan()
        assert_loan_buckets(
            loan,
            funded_principal_cents=17_043_875,
            reserved_release_cents=0,
            undisbursed_holdback_cents=6_107_500,
        )


class TestSharedOperations:
    def test_the_sponsor_and_the_servicer_write_into_one_shared_history(self):
        """One milestone and one payment from each party, and four roles read one projection.

        The two milestone writes land in a single ordered log and the two payments
        accumulate into one principal figure, so neither endpoint is quietly
        partitioned by caller, and the derived exit fields are identical whichever
        authorised role performs the read. The PRD states: "`days_on_market` is 0 when
        the governing listing is null, and otherwise the whole number of days from the
        governing listing's `effective_date` to the logical-clock date, with no
        partial-day arithmetic."

        Design: Corner/rbac/shared_operations_accept_either_authorised_party
        """
        ctx = fixtures.build_closed_loan()
        fixtures.set_clock("2026-08-25T09:00:00Z")

        by_sponsor = validate_success(
            api_client.create_exit_milestone(
                ctx.loan_id,
                factories.milestone_payload(
                    MilestoneType.LISTED.value,
                    "2026-08-20",
                    listing_price_cents=30_000_000,
                ),
                ctx.borrower_headers,
            ),
            201,
        )
        assert by_sponsor["derived_exit_status"] == LoanExitStatus.LISTED.value

        by_servicer = validate_success(
            api_client.create_exit_milestone(
                ctx.loan_id,
                factories.milestone_payload(
                    MilestoneType.PRICE_REDUCED.value,
                    "2026-08-25",
                    listing_price_cents=28_500_000,
                ),
                SERVICER,
            ),
            201,
        )
        assert by_servicer["derived_exit_status"] == LoanExitStatus.LISTED.value
        assert by_servicer["id"] != by_sponsor["id"]

        after_milestones = fixtures.read_loan(ctx.loan_id)
        assert after_milestones["exit_status"] == LoanExitStatus.LISTED.value
        assert_exit_monitoring(after_milestones, days_on_market=5, exit_watch_flag=False)

        sponsor_payment = validate_success(
            api_client.create_payment(
                ctx.loan_id,
                factories.payment_payload(50_000, "2026-08-25"),
                ctx.borrower_headers,
            ),
            200,
        )
        assert sponsor_payment["funded_principal_cents"] == 13_101_375
        assert sponsor_payment["repaid_principal_cents"] == 50_000

        servicer_payment = validate_success(
            api_client.create_payment(
                ctx.loan_id, factories.payment_payload(50_000, "2026-08-25"), SERVICER
            ),
            200,
        )
        assert_loan_buckets(
            servicer_payment,
            funded_principal_cents=13_051_375,
            repaid_principal_cents=100_000,
            undisbursed_holdback_cents=10_000_000,
        )

        entries, _ = validate_paginated(
            api_client.list_ledger_entries(
                ctx.loan_id,
                SERVICER,
                {"entry_type": LedgerEntryType.BORROWER_PAYMENT.value},
            )
        )
        assert len(entries) == 2, f"both writes are journalled, got {len(entries)}"
        assert [entry["amount_cents"] for entry in entries] == [50_000, 50_000]

        committee_read = validate_success(
            api_client.get_loan(ctx.loan_id, CREDIT_COMMITTEE), 200
        )
        officer_read = validate_success(
            api_client.get_loan(ctx.loan_id, LOAN_OFFICER), 200
        )
        for viewer, label in ((committee_read, "CreditCommittee"), (officer_read, "LoanOfficer")):
            assert viewer["days_on_market"] == 5, f"{label} saw a different day count"
            assert viewer["exit_status"] == LoanExitStatus.LISTED.value
            assert viewer["funded_principal_cents"] == 13_051_375, (
                f"{label} saw a different principal"
            )
            assert viewer["repaid_principal_cents"] == 100_000
            assert viewer["commitment_balance_check_cents"] == 0

        rows, meta = validate_paginated(
            api_client.list_exit_milestones(ctx.loan_id, ctx.borrower_headers)
        )
        assert meta["total_count"] == 2
        assert [row["effective_date"] for row in rows] == ["2026-08-20", "2026-08-25"]


class TestFirstMatchWins:
    def test_three_double_violations_each_report_the_lower_numbered_rule(self):
        """Rung 6 beats 7, rung 3 beats 4, rung 5 beats 8, and 8 then surfaces alone.

        Every one of the first three calls breaks two rules at once, and the fourth
        repeats the third with only the caller changed, which proves the outranked
        stale version was genuinely stale rather than absent. The PRD states: "When
        more than one rule would reject a request, the platform evaluates rules in a
        strict, fixed order and reports only the **first** rule whose condition holds;
        later rules are never reported."

        Design: Corner/validations/first_match_wins_across_three_priority_pairs
        """
        ctx = fixtures.build_closed_loan()
        stale_version = ctx.loan["version"]
        draw = _submitted_draw(ctx)
        assert ctx.refresh_loan()["version"] > stale_version, (
            "the create must move the loan past the captured version"
        )
        visit = fixtures.order_visit(
            draw["id"], INSPECTOR, "2026-09-01T13:00:00Z", "2026-09-01T15:00:00Z"
        )
        assert visit["status"] == InspectionVisitStatus.SCHEDULED.value

        validate_error(
            api_client.report_inspection_visit(
                visit["id"],
                factories.inspection_report_payload(
                    [factories.line_verification(ctx.line_by_code("ROOF")["id"], 0.50)]
                ),
                INSPECTOR_2,
            ),
            ApiErrorId.NOT_ASSIGNED_INSPECTOR.value,
            403,
        )
        assert fixtures.read_draw_request(draw["id"])["status"] == (
            DrawRequestStatus.INSPECTION_ORDERED.value
        ), "the refused report left the request awaiting its inspection"

        validate_error(
            api_client.create_application(
                factories.application_payload(
                    NON_EXISTENT_UUID, ctx.property_id, **factories.omit("term_months")
                ),
                LOAN_OFFICER,
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

        peer = fixtures.register_borrower(legal_entity_name="Saguaro Flips LLC")
        fixtures.execute_guarantee(peer["id"])
        stale_body = factories.draw_request_payload(
            [factories.line_allocation(ctx.line_by_code("ROOF")["id"], 0.60)],
            stale_version,
        )
        validate_error(
            api_client.create_draw_request(
                ctx.loan_id, stale_body, make_borrower_headers(peer["id"])
            ),
            ApiErrorId.NOT_OWNER.value,
            403,
        )
        validate_error(
            api_client.create_draw_request(
                ctx.loan_id, stale_body, ctx.borrower_headers
            ),
            ApiErrorId.STALE_LOAN_VERSION.value,
            412,
        )

        requests, request_meta = validate_paginated(
            api_client.list_draw_requests(SERVICER, {"loan_id": ctx.loan_id})
        )
        assert request_meta["total_count"] == 1, (
            f"no refusal created a draw request, got {request_meta['total_count']}"
        )
        assert requests[0]["id"] == draw["id"]
        _, application_meta = validate_paginated(
            api_client.list_applications(LOAN_OFFICER, {"borrower_id": ctx.borrower_id})
        )
        assert application_meta["total_count"] == 1, (
            "the rejected application write left no row behind"
        )
        visits, _ = validate_paginated(
            api_client.list_inspection_visits(draw["id"], SERVICER)
        )
        assert visits[0]["status"] == InspectionVisitStatus.SCHEDULED.value
        assert visits[0]["site_notes"] is None
