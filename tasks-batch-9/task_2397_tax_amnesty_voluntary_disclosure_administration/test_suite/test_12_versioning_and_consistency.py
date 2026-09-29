"""Row versioning and the absence of any settling delay.

PRD §2.4 starts every row at version 1 and advances it by exactly one per
mutation of that row, and PRD §2.9 requires multi-row mutations to be complete
before the response is returned, so a caller never has to read twice.
"""

from test_helpers import (
    ADMIN_HEADERS,
    AUDITOR_ONE_HEADERS,
    CANONICAL_BALANCE_DUE_CENTS,
    CANONICAL_CLOCK,
    CANONICAL_CLOCK_RENDERED,
    CANONICAL_DAYS_LATE,
    CANONICAL_GROSS_INTEREST_CENTS,
    CANONICAL_GROSS_LIABILITY_CENTS,
    CANONICAL_GROSS_PENALTY_CENTS,
    CANONICAL_PENALTY_RATE,
    CANONICAL_REVENUE_FORECAST_CENTS,
    CANONICAL_TOTAL_DUE_CENTS,
    CANONICAL_WAIVED_AMOUNT_CENTS,
    CANONICAL_WAIVED_INTEREST_CENTS,
    CANONICAL_WAIVED_PENALTY_CENTS,
    CANONICAL_WINDOW_CLOSE_DATE,
    add_tax_type_term,
    assert_audit_fields,
    assert_fields,
    create_program,
    draft_return,
    open_window,
    read_program,
    read_revenue_summary,
    set_clock,
    setup_executed_agreement,
    validate_success,
)

CLOSE_INSTANT = "2026-12-01T00:00:00Z"
CLOSE_INSTANT_RENDERED = "2026-12-01T00:00:00.000Z"
LATE_WINDOW_INSTANT = "2026-11-30T23:59:59Z"
LATE_WINDOW_INSTANT_RENDERED = "2026-11-30T23:59:59.000Z"
CONSISTENCY_TAXPAYER = {"legal_name": "Larkspur Textiles LLC", "tin_last4": "6677"}


class TestVersionLadder:
    """Each lifecycle write advances the program's own version by exactly one."""

    def test_the_program_version_advances_once_per_lifecycle_write(self, api):
        """Creation, opening, closing and reconciling walk 1 to 4.

        PRD §2.4: "Almost every resource additionally carries `updated_at`, an
        ISO 8601 UTC instant refreshed on every mutation, and `version`, an
        integer that starts at 1 on creation and increases by exactly one on every
        mutation of that row."

        PRD §3.8: "Reconciling sets `final_realization_pct` to the realization
        percentage computed at that instant, frozen there permanently, and
        advances the program's `version` by one. Before reconciliation
        `final_realization_pct` is null."

        Design: Corner/Cross-Cutting Complexity Layers/version_increments_on_every_write_and_only_on_the_written_row
        """
        set_clock(api, CANONICAL_CLOCK)
        program = create_program(api)
        assert_audit_fields(program, expected_version=1)
        assert_fields(
            program,
            status="DRAFT",
            created_at=CANONICAL_CLOCK_RENDERED,
            updated_at=CANONICAL_CLOCK_RENDERED,
            final_realization_pct=None,
        )
        add_tax_type_term(api, program["id"])

        opened = open_window(api, program["id"])
        assert_fields(opened, status="OPEN", version=2)

        set_clock(api, CLOSE_INSTANT)
        closed = validate_success(api.close_program(program["id"], ADMIN_HEADERS))
        assert_fields(
            closed,
            status="CLOSED",
            version=3,
            closed_at=CLOSE_INSTANT_RENDERED,
            updated_at=CLOSE_INSTANT_RENDERED,
        )

        reconciled = validate_success(
            api.reconcile_program(program["id"], ADMIN_HEADERS)
        )
        assert_fields(
            reconciled,
            status="RECONCILED",
            version=4,
            final_realization_pct=0.0000,
            collected_cents=0,
        )
        assert_fields(
            read_revenue_summary(api, program["id"]),
            revenue_forecast_cents=CANONICAL_REVENUE_FORECAST_CENTS,
            realization_pct=0.0000,
            forecast_status="SHORTFALL",
        )

    def test_a_child_row_write_leaves_the_parent_version_alone(self, api):
        """Publishing a term writes the term row and nothing else.

        PRD §2.4: "`version`, an integer that starts at 1 on creation and
        increases by exactly one on every mutation of that row."

        PRD §2.9: "On an `AmnestyProgram` these are `collected_cents` (the sum of
        `amount_cents` over payments whose `status` is `APPLIED` across all
        agreements of the program), `waived_total_cents` (the sum of
        `waived_amount_cents` over agreements of the program whose `status` is
        `EXECUTED`, `FULFILLED` or `SUPERSEDED`), `reinstated_total_cents` (the sum
        of `reinstated_amount_cents` over agreements of the program whose `status`
        is `BREACHED`), `participant_count` (the number of distinct `taxpayer_id`
        values over agreements of the program whose `status` is `EXECUTED`,
        `FULFILLED`, `BREACHED` or `SUPERSEDED`) and `nonparticipant_count` (the
        number of distinct taxpayers whose `nonparticipant_flag` was set true by
        this program's closing cascade)."

        Design: Corner/Cross-Cutting Complexity Layers/version_increments_on_every_write_and_only_on_the_written_row
        """
        set_clock(api, CANONICAL_CLOCK)
        program = create_program(api)
        term = add_tax_type_term(api, program["id"])

        assert_audit_fields(term, expected_version=1)
        assert_fields(
            term,
            created_at=CANONICAL_CLOCK_RENDERED,
            updated_at=CANONICAL_CLOCK_RENDERED,
        )
        assert_fields(read_program(api, program["id"]), version=1, status="DRAFT")

        # PRD §3.1 refuses opening at or after `window_close_at`, so the second
        # write lands on the last instant that is still strictly inside the window
        set_clock(api, LATE_WINDOW_INSTANT)
        opened = open_window(api, program["id"])
        assert_fields(opened, version=2, updated_at=LATE_WINDOW_INSTANT_RENDERED)
        assert_fields(
            validate_success(api.get_tax_type_term(term["id"], ADMIN_HEADERS)),
            version=1,
            updated_at=CANONICAL_CLOCK_RENDERED,
        )


class TestImmediateVisibility:
    """The response that causes a derived change already shows it."""

    def test_the_filing_response_carries_its_own_accrual_figures(self, api):
        """Nothing has to be re-read to see what filing computed.

        PRD §2.9: "Several operations in this system mutate more than one row.
        When they do, the mutation is immediate and complete before the response is
        returned: there is no deferred or eventual reconciliation."

        PRD §3.5: "It stamps `filed_at` with the current instant and then runs
        the **statutory liability** computation in two variants selected by the
        agreement's `liability_variant`."

        Design: Corner/Consistency Model/derived_fields_are_visible_in_the_same_response_that_causes_them
        """
        ctx = setup_executed_agreement(api, taxpayer_overrides=CONSISTENCY_TAXPAYER)
        drafted = draft_return(api, ctx)

        filed = validate_success(
            api.file_return(drafted["id"], ctx["taxpayer_headers"])
        )
        assert_fields(
            filed,
            status="FILED",
            filed_at=CANONICAL_CLOCK_RENDERED,
            version=2,
            accrual_end_date=CANONICAL_WINDOW_CLOSE_DATE,
            days_late=CANONICAL_DAYS_LATE,
            penalty_rate_applied=CANONICAL_PENALTY_RATE,
            gross_penalty_cents=CANONICAL_GROSS_PENALTY_CENTS,
            gross_interest_cents=CANONICAL_GROSS_INTEREST_CENTS,
            waived_penalty_cents=CANONICAL_WAIVED_PENALTY_CENTS,
            waived_interest_cents=CANONICAL_WAIVED_INTEREST_CENTS,
            payable_penalty_cents=0,
            payable_interest_cents=CANONICAL_WAIVED_INTEREST_CENTS,
            balance_due_cents=CANONICAL_BALANCE_DUE_CENTS,
        )

    def test_the_agreement_totals_are_current_on_the_very_next_read(self, api):
        """The collaterally revised agreement row needs no settling time.

        PRD §2.9: "Each row the server touches has its `updated_at` refreshed and
        its `version` incremented by one, including rows the client did not address
        and rows whose only change was to a derived field."

        PRD §3.5: "`gross_liability_cents` is the sum, over the agreement's
        returns whose `status` is `FILED`, `ASSESSED` or `SETTLED`, of
        `reported_tax_cents` plus `gross_penalty_cents` plus
        `gross_interest_cents`."

        Design: Corner/Consistency Model/derived_fields_are_visible_in_the_same_response_that_causes_them
        """
        ctx = setup_executed_agreement(api, taxpayer_overrides=CONSISTENCY_TAXPAYER)
        drafted = draft_return(api, ctx)
        validate_success(api.file_return(drafted["id"], ctx["taxpayer_headers"]))

        assert_fields(
            validate_success(
                api.get_agreement(ctx["agreement"]["id"], AUDITOR_ONE_HEADERS)
            ),
            gross_liability_cents=CANONICAL_GROSS_LIABILITY_CENTS,
            waived_amount_cents=CANONICAL_WAIVED_AMOUNT_CENTS,
            total_due_cents=CANONICAL_TOTAL_DUE_CENTS,
            payment_status="UNPAID",
            paid_total_cents=0,
        )

    def test_the_program_revenue_report_reflects_the_waiver_at_once(self, api):
        """The program-level rollup is live the moment the return is filed.

        PRD §2.9: "The derived counters and totals named on programs, taxpayers
        and agreements are not free-standing state that clients may set; they are
        recomputed from their definitions whenever a contributing fact changes."

        PRD §3.8: "The same report carries `waived_total_cents`,
        `reinstated_total_cents`, `participant_count` and `nonparticipant_count`,
        plus the compliance behavior analysis: `avg_historical_score` is the mean of
        the `HISTORICAL` scores of the program's participant taxpayers and
        `avg_program_adjusted_score` is the mean of their `PROGRAM_ADJUSTED`
        scores, each rounded half up to a whole integer."

        Design: Corner/Consistency Model/derived_fields_are_visible_in_the_same_response_that_causes_them
        """
        ctx = setup_executed_agreement(api, taxpayer_overrides=CONSISTENCY_TAXPAYER)
        drafted = draft_return(api, ctx)
        validate_success(api.file_return(drafted["id"], ctx["taxpayer_headers"]))

        assert_fields(
            read_revenue_summary(api, ctx["program"]["id"]),
            waived_total_cents=CANONICAL_WAIVED_AMOUNT_CENTS,
            reinstated_total_cents=0,
            collected_cents=0,
            realization_pct=0.0000,
            forecast_status="SHORTFALL",
            participant_count=1,
            nonparticipant_count=0,
        )
