"""
Endpoint-level contracts: the chair-only slate, its two separate membership codes,
the parameterised tax read, the strike branch's required reason and the pagination
bounds.
"""

from test_helpers import (
    BOARD_MEMBER,
    BOARD_MEMBER_ID,
    FISCAL_OFFICER,
    PROGRAM_OFFICER,
    api_client,
    assert_cents,
    assert_ordered_by,
    assert_score,
    cornermain_installment_one_paid,
    cornermain_slate_submitted,
    cycle_version,
    panel_version,
    read_application,
    read_award,
    read_cycle,
    read_panel,
    twoslot_applications_submitted,
    twoslot_board_review,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSlateIsTheChairsOperation:
    """Only `is_chair` separates the refused call from the accepted one."""

    def test_a_seated_non_chair_is_refused_and_the_chair_then_succeeds(self):
        """
        A seated panelist of the very same panel, sending the identical body and version, is
        refused as not the chair; nothing is created, so the chair's identical call afterwards
        still works with the unchanged expected version.

        PRD: "The acting panelist must be `SEATED` on this panel with `is_chair` true,
        otherwise `ERR_NOT_PANEL_CHAIR`."

        Design: Corner/endpoints/slate_submission_is_restricted_to_the_seated_chair
        """
        ctx = twoslot_board_review()
        expected = panel_version(ctx.tpan)
        body = {
            "ranked_application_ids": [ctx.appA, ctx.appB],
            "expected_panel_version": expected,
        }

        validate_error(
            api_client.submit_slate(ctx.tpan, dict(body), ctx.tpl2_headers),
            "ERR_NOT_PANEL_CHAIR",
        )
        _, meta = validate_paginated(
            api_client.list_slots(PROGRAM_OFFICER, {"panel_id": ctx.tpan, "limit": 100})
        )
        assert meta["total_count"] == 0, (
            f"the refusal created no slot, got {meta['total_count']}"
        )
        assert read_panel(ctx.tpan)["status"] == "DELIBERATING", (
            "the panel is still deliberating, got "
            f"{read_panel(ctx.tpan)['status']}"
        )

        submitted = validate_success(
            api_client.submit_slate(ctx.tpan, dict(body), ctx.tpl1_headers)
        )
        assert submitted["status"] == "SLATE_SUBMITTED", (
            f"the chair's identical call succeeds, got {submitted['status']}"
        )

        rows, meta = validate_paginated(
            api_client.list_slots(PROGRAM_OFFICER, {"panel_id": ctx.tpan, "limit": 100})
        )
        assert meta["total_count"] == 2, (
            f"one slot per listed application, got {meta['total_count']}"
        )
        assert_ordered_by(rows, "rank")
        assert [row["rank"] for row in rows] == [1, 2], (
            f"ranks are 1 and 2, got {[row['rank'] for row in rows]}"
        )
        assert [row["application_id"] for row in rows] == [ctx.appA, ctx.appB], (
            "the slots follow the chair's order, got "
            f"{[row['application_id'] for row in rows]}"
        )
        for row in rows:
            assert row["status"] == "PROPOSED", (
                f"a new slot begins PROPOSED, got {row['status']}"
            )
        assert_score(
            read_application(ctx.appA)["final_composite_score"],
            7.30,
            "appA.final_composite_score",
        )
        assert_score(
            read_application(ctx.appB)["final_composite_score"],
            7.00,
            "appB.final_composite_score",
        )


class TestSlateMembershipVersusCoverage:
    """Two defects on one endpoint yield two different codes."""

    def test_an_omission_a_stranger_and_a_repeat_are_each_reported_differently(self):
        """
        Omitting one of the panel's two scored applications is an incomplete slate; naming a
        third application that was never assigned to the panel is refused for membership even
        though the coverage requirement is met; a literally duplicated entry is caught as a
        shape defect; and the accepted list ranks by the chair's order rather than by score.

        PRD: "Every application assigned to this panel whose `status` is `SCORED` must appear
        exactly once in the list, and an omission or a repetition is rejected with
        `ERR_INCOMPLETE_SLATE`; a list containing literal duplicate entries is caught earlier
        still, as a shape error."

        PRD: "Extraneous entries are deliberately **not** judged by the completeness rule: an
        application whose `assigned_panel_id` names a different panel is rejected with
        `ERR_APPLICATION_NOT_ON_PANEL`."

        Design: Corner/endpoints/slate_membership_and_coverage_are_enforced_separately
        """
        ctx = twoslot_board_review()
        expected = panel_version(ctx.tpan)

        validate_error(
            api_client.submit_slate(
                ctx.tpan,
                {
                    "ranked_application_ids": [ctx.appA],
                    "expected_panel_version": expected,
                },
                ctx.tpl1_headers,
            ),
            "ERR_INCOMPLETE_SLATE",
        )
        validate_error(
            api_client.submit_slate(
                ctx.tpan,
                {
                    "ranked_application_ids": [ctx.appA, ctx.appB, ctx.appC],
                    "expected_panel_version": expected,
                },
                ctx.tpl1_headers,
            ),
            "ERR_APPLICATION_NOT_ON_PANEL",
        )
        assert read_application(ctx.appC)["assigned_panel_id"] is None, (
            "the stranger application belongs to no panel at all"
        )
        validate_error(
            api_client.submit_slate(
                ctx.tpan,
                {
                    "ranked_application_ids": [ctx.appA, ctx.appA, ctx.appB],
                    "expected_panel_version": expected,
                },
                ctx.tpl1_headers,
            ),
            "ERR_INVALID_REQUEST",
        )
        assert read_panel(ctx.tpan)["status"] == "DELIBERATING", (
            "three refusals leave the panel deliberating"
        )

        validate_success(
            api_client.submit_slate(
                ctx.tpan,
                {
                    "ranked_application_ids": [ctx.appB, ctx.appA],
                    "expected_panel_version": expected,
                },
                ctx.tpl1_headers,
            )
        )
        rows, meta = validate_paginated(
            api_client.list_slots(PROGRAM_OFFICER, {"panel_id": ctx.tpan, "limit": 100})
        )
        assert meta["total_count"] == 2, (
            f"exactly two slots exist, got {meta['total_count']}"
        )
        by_rank = {row["rank"]: row["application_id"] for row in rows}
        assert by_rank[1] == ctx.appB, (
            "rank 1 follows the chair's order, not the score order, got "
            f"{by_rank[1]}"
        )
        assert by_rank[2] == ctx.appA, f"rank 2 is the other application, got {by_rank[2]}"


class TestTaxReportIsAPureParameterisedRead:
    """Four answers off one ledger, and no mutation."""

    def test_the_same_ledger_answers_four_ways_and_is_left_untouched(self):
        """
        With one of three installments paid, the accrual view of 2027 reports the whole award,
        the cash view of 2027 reports only the paid row, the cash view of 2028 reports nothing,
        the parameterless call resolves to 2027 on the accrual basis, and the award is
        unchanged by all four reads.

        PRD: "On the **accrual** basis — the council's obligation view — the rows counted are
        every installment of the award that is not `VOIDED` whose `scheduled_date` falls in the
        requested year, paid or not."

        PRD: "It takes an optional `tax_year`, defaulting to the calendar year of the logical
        clock, and an optional `basis`, defaulting to `ACCRUAL`."

        Design: Corner/endpoints/tax_report_read_is_pure_and_variant_parameterised
        """
        ctx = cornermain_installment_one_paid()
        before = read_award(ctx.aw)

        accrual = validate_success(
            api_client.get_tax_report(
                ctx.aw, FISCAL_OFFICER, {"tax_year": 2027, "basis": "ACCRUAL"}
            )
        )
        assert_cents(accrual["reportable_gross_cents"], 1_500_000, "accrual 2027 gross")
        assert_cents(
            accrual["reportable_withholding_cents"], 0, "accrual 2027 withholding"
        )
        assert_cents(accrual["reportable_net_cents"], 1_500_000, "accrual 2027 net")
        assert accrual["installment_count"] == 3, (
            f"all three scheduled rows count, got {accrual['installment_count']}"
        )

        cash = validate_success(
            api_client.get_tax_report(
                ctx.aw, FISCAL_OFFICER, {"tax_year": 2027, "basis": "CASH"}
            )
        )
        assert_cents(cash["reportable_gross_cents"], 600_000, "cash 2027 gross")
        assert_cents(cash["reportable_net_cents"], 600_000, "cash 2027 net")
        assert cash["installment_count"] == 1, (
            f"only the paid row counts, got {cash['installment_count']}"
        )

        cash_next = validate_success(
            api_client.get_tax_report(
                ctx.aw, FISCAL_OFFICER, {"tax_year": 2028, "basis": "CASH"}
            )
        )
        assert_cents(cash_next["reportable_gross_cents"], 0, "cash 2028 gross")
        assert_cents(cash_next["reportable_net_cents"], 0, "cash 2028 net")
        assert cash_next["installment_count"] == 0, (
            f"nothing was paid in 2028, got {cash_next['installment_count']}"
        )

        defaulted = validate_success(
            api_client.get_tax_report(ctx.aw, ctx.art_headers)
        )
        assert defaulted["tax_year"] == 2027, (
            f"the year comes from the logical clock, got {defaulted['tax_year']}"
        )
        assert defaulted["basis"] == "ACCRUAL", (
            f"the basis defaults to accrual, got {defaulted['basis']}"
        )
        assert_cents(
            defaulted["reportable_gross_cents"], 1_500_000, "defaulted 2027 gross"
        )
        assert defaulted["award_id"] == ctx.aw, "the report echoes its award"

        after = read_award(ctx.aw)
        assert after["version"] == before["version"], (
            "a computed read must not bump the award version: "
            f"{after['version']} != {before['version']}"
        )
        assert after["status"] == "ACTIVE", (
            f"the award is active, got {after['status']}"
        )
        assert after["payment_status"] == "PARTIALLY_PAID", (
            f"one of three rows is paid, got {after['payment_status']}"
        )
        assert_cents(after["disbursed_gross_cents"], 600_000, "award.disbursed_gross_cents")
        assert_cents(
            after["undisbursed_gross_cents"], 900_000, "award.undisbursed_gross_cents"
        )


class TestStrikeBranchRequiresItsReason:
    """The refusal costs no version, so the retry reuses it."""

    def test_the_missing_reason_code_is_a_shape_error_that_spends_no_version(self):
        """
        A strike without a reason code is refused for its shape and leaves the slot proposed
        and the cycle version untouched, so the very same expected version carries the retry;
        the accepted strike notifies the applicant and creates no award.

        PRD: "A `STRIKE` needs its `struck_reason_code` — its absence is rejected with
        `ERR_INVALID_REQUEST` — and moves the slot `PROPOSED → BOARD_STRUCK`, records the
        reason, moves the application `SCORED → NOT_RECOMMENDED`, and stamps the application's
        `notified_at` from the logical clock, opening the appeal window."

        Design: Corner/endpoints/strike_requires_a_reason_code_before_it_notifies_the_applicant
        """
        ctx = cornermain_slate_submitted()
        expected = cycle_version(ctx.cyc)

        validate_error(
            api_client.board_action(
                ctx.slot,
                {"action": "STRIKE", "expected_cycle_version": expected},
                BOARD_MEMBER,
            ),
            "ERR_INVALID_REQUEST",
        )
        assert (
            validate_success(api_client.get_slot(ctx.slot, PROGRAM_OFFICER))["status"]
            == "PROPOSED"
        ), "the refused strike leaves the slot proposed"
        assert cycle_version(ctx.cyc) == expected, (
            "a refused action spends no cycle version: "
            f"{cycle_version(ctx.cyc)} != {expected}"
        )

        struck = validate_success(
            api_client.board_action(
                ctx.slot,
                {
                    "action": "STRIKE",
                    "expected_cycle_version": expected,
                    "struck_reason_code": "BUDGET",
                },
                BOARD_MEMBER,
            )
        )
        assert struck["status"] == "BOARD_STRUCK", (
            f"the slot should be struck, got {struck['status']}"
        )
        assert struck["struck_reason_code"] == "BUDGET", (
            f"the reason is recorded, got {struck['struck_reason_code']}"
        )
        assert struck["board_action_by"] == BOARD_MEMBER_ID, (
            f"the acting board member is stamped, got {struck['board_action_by']}"
        )

        _, meta = validate_paginated(
            api_client.list_awards(PROGRAM_OFFICER, {"cycle_id": ctx.cyc, "limit": 100})
        )
        assert meta["total_count"] == 0, (
            f"a strike creates no award, got {meta['total_count']}"
        )

        application = read_application(ctx.app)
        assert application["status"] == "NOT_RECOMMENDED", (
            f"the applicant is not recommended, got {application['status']}"
        )
        assert str(application["notified_at"]).startswith("2026-10-16"), (
            f"the appeal window opens from the clock, got {application['notified_at']}"
        )
        assert_cents(read_cycle(ctx.cyc)["funded_total_cents"], 0, "cycle.funded_total_cents")


class TestPaginationBoundsAreRejected:
    """Out-of-band values are refused, never clamped."""

    def test_zero_and_one_hundred_and_one_and_minus_one_are_all_refused(self):
        """
        A limit of zero, a limit of a hundred and one and a negative offset are each refused,
        while a limit of exactly one hundred is accepted; the paged read then returns the second
        application by creation order and the status filter counts before pagination.

        PRD: "`limit` is the maximum number of rows returned; it defaults to 10, and any
        supplied value must be at least 1 and at most 100."

        PRD: "Out-of-band values are rejected with `ERR_INVALID_REQUEST` (HTTP 400) rather
        than silently clamped."

        Design: Corner/endpoints/list_pagination_bounds_are_rejected_rather_than_clamped
        """
        ctx = twoslot_applications_submitted()

        for params in (
            {"cycle_id": ctx.tcyc, "limit": 0},
            {"cycle_id": ctx.tcyc, "limit": 101},
            {"cycle_id": ctx.tcyc, "offset": -1},
        ):
            validate_error(
                api_client.list_applications(PROGRAM_OFFICER, params),
                "ERR_INVALID_REQUEST",
            )

        rows, meta = validate_paginated(
            api_client.list_applications(
                PROGRAM_OFFICER, {"cycle_id": ctx.tcyc, "limit": 100}
            )
        )
        assert meta["total_count"] == 4, (
            f"four applications belong to the cycle, got {meta['total_count']}"
        )
        assert meta["has_more"] is False, "a hundred-row page holds all four"
        assert len(rows) == 4, f"four rows are returned, got {len(rows)}"
        assert_ordered_by(rows, "created_at")

        page, page_meta = validate_paginated(
            api_client.list_applications(
                PROGRAM_OFFICER, {"cycle_id": ctx.tcyc, "limit": 1, "offset": 1}
            )
        )
        assert len(page) == 1, f"one row per page, got {len(page)}"
        assert page[0]["id"] == ctx.appB, (
            f"the second application by creation order is appB, got {page[0]['id']}"
        )
        assert page_meta["total_count"] == 4, (
            f"total_count counts before pagination, got {page_meta['total_count']}"
        )
        assert page_meta["has_more"] is True, "three rows remain after the first page"

        drafts, draft_meta = validate_paginated(
            api_client.list_applications(
                PROGRAM_OFFICER, {"cycle_id": ctx.tcyc, "status": "DRAFT"}
            )
        )
        assert draft_meta["total_count"] == 1, (
            f"one application never left DRAFT, got {draft_meta['total_count']}"
        )
        assert drafts[0]["id"] == ctx.appC, (
            f"the draft is appC, got {drafts[0]['id']}"
        )
