"""Quarterly statement cadence, DSCR/LTV covenant math, review lifecycle, and
the breach-to-watchlist posture cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_statement,
    appraise_property,
    create_borrower,
    create_loan,
    create_property,
    create_reserve_account,
    create_statement_payload,
    deposit_reserve,
    get_loan,
    get_reserve,
    get_success_data,
    list_assessments,
    list_watchlist_entries,
    make_borrower_headers,
    make_master_servicer_headers,
    newest_assessment,
    reject_statement,
    statement_assessments,
    submit_and_accept_statement,
    submit_statement,
    validate_error,
    validate_paginated,
    validate_success,
)

MS = TEST_USERS["master_servicer_headers"]

Q2_2025 = ("2025-04-01T00:00:00Z", "2025-06-30T00:00:00Z")
Q3_2025 = ("2025-07-01T00:00:00Z", "2025-09-30T00:00:00Z")
Q4_2025 = ("2025-10-01T00:00:00Z", "2025-12-31T00:00:00Z")
Q1_2026 = ("2026-01-01T00:00:00Z", "2026-03-31T00:00:00Z")
Q2_2026 = ("2026-04-01T00:00:00Z", "2026-06-30T00:00:00Z")


class TestStatementCadence:
    def test_statement_late_flag_and_due_date_computed(self, api):
        """PRD §3.2: "The system derives the statement's `due_date` — fifteen days
        after `period_end` for a rent roll, forty-five days after for an operating
        statement — and sets `submitted_late` to true when the submission's clock
        time falls after that due date."

        Design: Corner/entities/statement_late_flag_and_due_date_computed
        """
        borrower = create_borrower(legal_name="Late Co", tax_id="TX-LAT",
                                   contact_email="lat@x.com")
        loan = create_loan(borrower["id"], loan_number="LN-LAT",
                           original_principal_cents=100_000_000, note_rate=0.05,
                           origination_date="2026-01-01T00:00:00Z")
        os_stmt = submit_statement(loan["id"], borrower["id"], "OPERATING_STATEMENT",
                                   *Q1_2026, net_operating_income_cents=5_000_000)
        assert os_stmt["due_date"].startswith("2026-05-15T00:00:00"), (
            f"operating statement due_date is period_end + 45d, got {os_stmt['due_date']}")
        assert os_stmt["submitted_late"] is True, (
            "submitted at clock 2026-08-01, well past the due date")

        rr_stmt = submit_statement(loan["id"], borrower["id"], "RENT_ROLL",
                                   *Q1_2026, occupancy_pct=90)
        assert rr_stmt["due_date"].startswith("2026-04-15T00:00:00"), (
            f"rent roll due_date is period_end + 15d, got {rr_stmt['due_date']}")
        assert rr_stmt["submitted_late"] is True


class TestStatementConstraints:
    def test_duplicate_statement_period_rejected(self, api):
        """PRD §3.2: "Only one live statement may exist per loan, type, and
        quarter: while a row in `SUBMITTED` or `ACCEPTED` status exists for the
        same triple, a further submission is rejected with
        `ERR_DUPLICATE_STATEMENT_PERIOD`."

        Design: Corner/validations/duplicate_statement_period_rejected
        """
        borrower = create_borrower(legal_name="Dup Co", tax_id="TX-DUP",
                                   contact_email="dup@x.com")
        loan = create_loan(borrower["id"], loan_number="LN-DUP",
                           original_principal_cents=100_000_000, note_rate=0.05)
        submit_statement(loan["id"], borrower["id"], "OPERATING_STATEMENT",
                         *Q2_2026, net_operating_income_cents=5_000_000)
        resp = api.create_statement(
            loan["id"],
            create_statement_payload("OPERATING_STATEMENT", *Q2_2026,
                                     net_operating_income_cents=6_000_000),
            make_borrower_headers(borrower["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_STATEMENT_PERIOD)

    def test_misaligned_statement_period_rejected(self, api):
        """PRD §3.2: "a `period_start` and `period_end` that together must equal
        exactly one full calendar quarter — the quarter's first day through its
        last day, inclusive; a misaligned period is rejected with
        `ERR_STATEMENT_PERIOD_MISALIGNED` (HTTP 422)."

        Design: Corner/validations/misaligned_statement_period_rejected
        """
        borrower = create_borrower(legal_name="Mis Co", tax_id="TX-MIS",
                                   contact_email="mis@x.com")
        loan = create_loan(borrower["id"], loan_number="LN-MIS",
                           original_principal_cents=100_000_000, note_rate=0.05)
        resp = api.create_statement(
            loan["id"],
            create_statement_payload("OPERATING_STATEMENT",
                                     "2026-04-15T00:00:00Z", "2026-07-14T00:00:00Z",
                                     net_operating_income_cents=5_000_000),
            make_borrower_headers(borrower["id"]))
        validate_error(resp, ApiErrorId.ERR_STATEMENT_PERIOD_MISALIGNED)

    def test_resubmission_after_rejection_allowed(self, api):
        """PRD §3.2: "Once a statement is `REJECTED`, a resubmission for the same
        period is permitted — the duplicate rule only blocks while a submitted or
        accepted row exists."
        PRD §3.2: "The review supplies a `decision` of `ACCEPT` or `REJECT`, and a
        rejection must carry a `rejection_reason`."

        Design: Corner/validations/resubmission_after_rejection_allowed
        """
        borrower = create_borrower(legal_name="Resub Co", tax_id="TX-RES",
                                   contact_email="res@x.com")
        loan = create_loan(borrower["id"], loan_number="LN-RES",
                           original_principal_cents=100_000_000, note_rate=0.05)
        first = submit_statement(loan["id"], borrower["id"], "OPERATING_STATEMENT",
                                 *Q2_2026, net_operating_income_cents=5_000_000)
        rejected = reject_statement(first["id"], rejection_reason="unreconciled NOI")
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == "unreconciled NOI"

        second = validate_success(api.create_statement(
            loan["id"],
            create_statement_payload("OPERATING_STATEMENT", *Q2_2026,
                                     net_operating_income_cents=5_500_000),
            make_borrower_headers(borrower["id"])), 201)
        assert second["status"] == "SUBMITTED"


class TestStatementReviewLifecycle:
    def test_statement_second_review_rejected(self, api):
        """PRD §3.2: "Reviewing a statement that already stands `ACCEPTED` or
        `REJECTED` fails with `ERR_STATEMENT_ALREADY_REVIEWED`."

        Design: Corner/state_machines/statement_second_review_rejected
        """
        borrower = create_borrower(legal_name="Twice Co", tax_id="TX-TWC",
                                   contact_email="twc@x.com")
        loan = create_loan(borrower["id"], loan_number="LN-TWC",
                           dscr_basis="T3_ANNUALIZED")
        stmt = submit_and_accept_statement(
            loan["id"], borrower["id"], "OPERATING_STATEMENT", *Q2_2026,
            net_operating_income_cents=20_000_000)
        resp = api.review_statement(
            stmt["id"], {"decision": "REJECT", "rejection_reason": "duplicate"}, MS)
        validate_error(resp, ApiErrorId.ERR_STATEMENT_ALREADY_REVIEWED)
        after = get_success_data(api.get_statement(stmt["id"], MS))
        assert after["status"] == "ACCEPTED"
        assessments = list_assessments(loan["id"])
        assert len(assessments) == 1, "no duplicate assessment is created"

    def test_review_response_reflects_transition_immediately(self, api):
        """PRD §3.2: "Acceptance stamps the reviewing operator's identity into
        `reviewed_by_user_id`, the segregation-of-duties anchor for DSCR waivers."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/consistency_model/review_response_reflects_transition_immediately
        """
        borrower = create_borrower(legal_name="Imm Co", tax_id="TX-IMM",
                                   contact_email="imm@x.com")
        loan = create_loan(borrower["id"], loan_number="LN-IMM",
                           original_principal_cents=100_000_000, note_rate=0.05)
        stmt = submit_statement(loan["id"], borrower["id"], "RENT_ROLL", *Q2_2026,
                                occupancy_pct=95)
        reviewed = validate_success(api.review_statement(
            stmt["id"], {"decision": "ACCEPT"},
            make_master_servicer_headers("ms_user_9")))
        assert reviewed["status"] == "ACCEPTED"
        assert reviewed["reviewed_by_user_id"] == "ms_user_9", (
            "the review response itself carries the reviewer's identity")
        fetched = get_success_data(api.get_statement(stmt["id"], MS))
        assert fetched["status"] == "ACCEPTED", "a subsequent GET agrees — no lag"
        assert fetched["reviewed_by_user_id"] == "ms_user_9"


class TestDscrComputability:
    def test_ttm_uncomputable_before_four_quarters(self, api):
        """PRD §3.2: "For a loan covenanted on the `TTM` basis, annualized net
        operating income is the sum of the `net_operating_income_cents` of the
        four consecutive calendar quarters ending with the newly accepted
        statement's own quarter; if any of those four quarters lacks an accepted
        statement, the covenant is not computable and no assessment row is created
        at all."
        PRD §3.1: "Until the first covenant calculation of each type runs,
        `current_dscr` and `current_ltv` remain null."

        Design: Corner/calculations/ttm_uncomputable_before_four_quarters
        """
        borrower = create_borrower(legal_name="Short Co", tax_id="TX-SHO",
                                   contact_email="sho@x.com")
        loan = create_loan(borrower["id"], loan_number="LN-SHO",
                           origination_date="2026-04-01T00:00:00Z",
                           dscr_basis="TTM")
        submit_and_accept_statement(loan["id"], borrower["id"],
                                    "OPERATING_STATEMENT", *Q2_2026,
                                    net_operating_income_cents=10_000_000)
        _rows, meta = validate_paginated(api.list_loan_assessments(loan["id"], MS))
        assert meta["total_count"] == 0, (
            "TTM with a single accepted quarter creates no assessment row at all")
        loan_after = get_loan(loan["id"])
        assert loan_after["current_dscr"] is None
        assert loan_after["servicing_status"] == "PERFORMING"


class TestDscrThresholdBoundary:
    def test_dscr_equal_to_threshold_conforms(self, api):
        """PRD §3.2: "A breach exists whenever the ratio is strictly less than the
        loan's `dscr_covenant_threshold`."
        PRD §3.2: "An assessment that finds a breach opens in `OPEN` status; one
        that finds conformity stands `CONFORMING`."

        Design: Difficulty/boundary_precision_check/dscr_exactly_at_threshold_no_breach
        """
        borrower = create_borrower(legal_name="Boundary Ratio", tax_id="TX-BR1",
                                   contact_email="br1@x.com")
        loan = create_loan(borrower["id"], loan_number="LN-BR1",
                           dscr_covenant_threshold=1.20,
                           dscr_basis="T3_ANNUALIZED")
        # NOI 18,000,000 x 4 = 72,000,000 / 60,000,000 debt service == 1.2000,
        # exactly the threshold: strict less-than means NO breach.
        submit_and_accept_statement(loan["id"], borrower["id"],
                                    "OPERATING_STATEMENT", *Q2_2026,
                                    net_operating_income_cents=18_000_000)
        assessment = newest_assessment(loan["id"], params={"assessment_type": "DSCR"})
        assert assessment["computed_value"] == pytest.approx(1.2000, abs=1e-9)
        assert assessment["breach"] is False
        assert assessment["status"] == "CONFORMING"
        loan_after = get_loan(loan["id"])
        assert loan_after["servicing_status"] == "PERFORMING"
        assert list_watchlist_entries(loan["id"]) == []

    def test_dscr_just_below_threshold_breaches(self, api):
        """PRD §3.2: "A breach exists whenever the ratio is strictly less than the
        loan's `dscr_covenant_threshold`."
        PRD §3.6: "the moment any covenant assessment stands `OPEN` or any
        watchlist entry stands `ACTIVE`, a `PERFORMING` loan moves to `WATCHLIST`"

        Design: Difficulty/boundary_precision_check/dscr_exactly_at_threshold_no_breach
        """
        borrower = create_borrower(legal_name="Boundary Ratio Low", tax_id="TX-BR2",
                                   contact_email="br2@x.com")
        loan = create_loan(borrower["id"], loan_number="LN-BR2",
                           dscr_covenant_threshold=1.20,
                           dscr_basis="T3_ANNUALIZED")
        # NOI 17,999,000 x 4 = 71,996,000 / 60,000,000 == 1.1999 (4dp) < 1.20.
        submit_and_accept_statement(loan["id"], borrower["id"],
                                    "OPERATING_STATEMENT", *Q2_2026,
                                    net_operating_income_cents=17_999_000)
        assessment = newest_assessment(loan["id"], params={"assessment_type": "DSCR"})
        assert assessment["computed_value"] == pytest.approx(1.1999, abs=1e-9)
        assert assessment["breach"] is True
        assert assessment["status"] == "OPEN"
        assert get_loan(loan["id"])["servicing_status"] == "WATCHLIST"


class TestDscrBasisDivergence:
    def _board_divergence_pair(self, api):
        borrower = create_borrower(legal_name="Divergence Holdings",
                                   tax_id="TX-DIV-1", contact_email="div@x.com")
        common = dict(original_principal_cents=1_000_000_000, note_rate=0.06,
                      origination_date="2025-04-01T00:00:00Z",
                      maturity_date="2028-06-30T00:00:00Z",
                      dscr_covenant_threshold=1.25, ltv_covenant_threshold=0.90)
        loan_a = create_loan(borrower["id"], loan_number="LN-TTM",
                             dscr_basis="TTM", **common)
        loan_b = create_loan(borrower["id"], loan_number="LN-T3",
                             dscr_basis="T3_ANNUALIZED", **common)
        # Identical NOI series on both loans: 17,000,000 for three quarters,
        # then 20,000,000. Annual debt service is 1,000,000,000 x 0.06 = 60,000,000.
        final_stmts = {}
        for loan in (loan_a, loan_b):
            for period in (Q2_2025, Q3_2025, Q4_2025):
                submit_and_accept_statement(loan["id"], borrower["id"],
                                            "OPERATING_STATEMENT", *period,
                                            net_operating_income_cents=17_000_000)
            final_stmts[loan["id"]] = submit_and_accept_statement(
                loan["id"], borrower["id"],
                "OPERATING_STATEMENT", *Q1_2026,
                net_operating_income_cents=20_000_000)
        return borrower, loan_a, loan_b, final_stmts[loan_a["id"]], final_stmts[loan_b["id"]]

    def test_ttm_and_t3_diverge_on_identical_noi(self, api):
        """PRD §3.2: "For a loan covenanted on the `TTM` basis, annualized net
        operating income is the sum of the `net_operating_income_cents` of the
        four consecutive calendar quarters ending with the newly accepted
        statement's own quarter; if any of those four quarters lacks an accepted
        statement, the covenant is not computable and no assessment row is created
        at all."
        PRD §3.2: "For a loan on the `T3_ANNUALIZED` basis, the annualized figure
        is the newly accepted quarter's net operating income multiplied by four"
        PRD §3.2: "A breach exists whenever the ratio is strictly less than the
        loan's `dscr_covenant_threshold`."
        PRD §3.2: "each statement also exposes the assessments it sourced."

        Design: Difficulty/dual_variant_calc/dscr_ttm_vs_t3_quarterly_divergence
        """
        _b, loan_a, loan_b, stmt_a, stmt_b = self._board_divergence_pair(api)
        # Every assessment here shares the same logical `assessed_at` clock
        # instant (the clock never advances during setup), so select each loan's
        # Q1'26 assessment through its source statement rather than relying on
        # the tie order of the loan-level "newest first by assessed_at" list.
        # TTM: 71,000,000 / 60,000,000 = 1.1833 < 1.25 -> breach.
        rows_a = statement_assessments(stmt_a["id"])
        assert len(rows_a) == 1, "the Q1'26 TTM statement sources exactly one assessment"
        newest_a = rows_a[0]
        assert newest_a["computed_value"] == pytest.approx(1.1833, abs=1e-9)
        assert newest_a["breach"] is True
        assert newest_a["status"] == "OPEN"
        assert newest_a["basis"] == "TTM"
        # T3: 20,000,000 x 4 = 80,000,000 / 60,000,000 = 1.3333 >= 1.25 -> conform.
        rows_b = statement_assessments(stmt_b["id"])
        assert len(rows_b) == 1, "the Q1'26 T3 statement sources exactly one assessment"
        newest_b = rows_b[0]
        assert newest_b["computed_value"] == pytest.approx(1.3333, abs=1e-9)
        assert newest_b["breach"] is False
        assert newest_b["status"] == "CONFORMING"
        assert newest_b["basis"] == "T3_ANNUALIZED"
        # Identical NOI series; the basis variant alone decides breach vs conform.
        assert newest_a["computed_value"] != newest_b["computed_value"]
        assert get_loan(loan_a["id"])["servicing_status"] == "WATCHLIST"
        assert get_loan(loan_b["id"])["servicing_status"] == "PERFORMING"

    def test_t3_conforming_reassessment_auto_cures_prior_open(self, api):
        """PRD §3.2: "Conformity reaches backwards: a newly created conforming
        assessment automatically transitions every prior `OPEN` assessment of the
        same type for that loan to `CURED`."
        PRD §3.2: "if any of those four quarters lacks an accepted statement, the
        covenant is not computable and no assessment row is created at all."

        Design: Difficulty/dual_variant_calc/dscr_ttm_vs_t3_quarterly_divergence
        """
        _b, loan_a, loan_b, _stmt_a, _stmt_b = self._board_divergence_pair(api)
        rows_b = list_assessments(loan_b["id"], params={"assessment_type": "DSCR"})
        assert len(rows_b) == 4
        statuses_b = sorted(r["status"] for r in rows_b)
        assert statuses_b == ["CONFORMING", "CURED", "CURED", "CURED"], (
            "the conforming Q1'26 T3 assessment cures the three earlier OPEN ones")
        rows_a = list_assessments(loan_a["id"], params={"assessment_type": "DSCR"})
        assert len(rows_a) == 1, "TTM is uncomputable for the first three quarters"


class TestLtvCalculation:
    def test_appraisal_drop_opens_ltv_breach(self, api):
        """PRD §3.2: "Otherwise the ratio is the loan's `current_balance_cents`
        divided by the collateral base, rounded half-up to four decimal places,
        and a breach exists when it is strictly greater than the loan's
        `ltv_covenant_threshold`; the result refreshes the loan's `current_ltv`."
        PRD §3.1: "the appraisal triggers the LTV reassessment and cascades
        described in §3.2, followed by a fresh risk-score evaluation."

        Design: Corner/calculations/appraisal_drop_opens_ltv_breach
        """
        borrower = create_borrower(legal_name="LTV Co", tax_id="TX-LTV",
                                   contact_email="ltv@x.com")
        loan = create_loan(borrower["id"], loan_number="LN-LTV",
                           original_principal_cents=800_000_000, note_rate=0.05,
                           ltv_covenant_threshold=0.75)
        prop = create_property(loan["id"], address="1 Value St",
                               appraised_value_cents=2_000_000_000,
                               appraisal_date="2026-06-01T00:00:00Z")
        appraise_property(prop["id"], 900_000_000, "2026-07-01T00:00:00Z")
        # 800,000,000 / 900,000,000 = 0.8889 (4dp) > 0.75 -> breach.
        assessment = newest_assessment(loan["id"], params={"assessment_type": "LTV"})
        assert assessment["computed_value"] == pytest.approx(0.8889, abs=1e-9)
        assert assessment["breach"] is True
        assert assessment["status"] == "OPEN"
        assert assessment["threshold_value"] == pytest.approx(0.75, abs=1e-9)
        loan_after = get_loan(loan["id"])
        assert loan_after["current_ltv"] == pytest.approx(0.8889, abs=1e-9)
        assert loan_after["servicing_status"] == "WATCHLIST"

    def test_stale_appraisal_makes_ltv_uncomputable_breach(self, api):
        """PRD §3.2: "The collateral base is the sum of `appraised_value_cents`
        across the loan's properties whose `appraisal_date` lies within
        twenty-four months of the current clock; appraisals older than twenty-four
        months are stale and contribute nothing."
        PRD §3.2: "When no in-date appraisal exists the ratio is uncomputable —
        yet the assessment is still recorded, with `computed_value` null and
        `breach` set to true."

        Design: Corner/calculations/stale_appraisal_makes_ltv_uncomputable_breach
        """
        borrower = create_borrower(legal_name="Stale Co", tax_id="TX-STL",
                                   contact_email="stl@x.com")
        loan = create_loan(borrower["id"], loan_number="LN-STL",
                           original_principal_cents=500_000_000, note_rate=0.05,
                           ltv_covenant_threshold=0.90)
        prop = create_property(loan["id"], address="1 Stale St",
                               property_type="RETAIL",
                               appraised_value_cents=1_000_000_000,
                               appraisal_date="2024-06-01T00:00:00Z")
        # The only appraisal (2024-06-01) is more than 24 months behind the
        # 2026-08-01 clock; re-recording the same stale date keeps the set empty.
        appraise_property(prop["id"], 1_000_000_000, "2024-06-01T00:00:00Z")
        assessment = newest_assessment(loan["id"], params={"assessment_type": "LTV"})
        assert assessment["computed_value"] is None
        assert assessment["breach"] is True
        assert assessment["status"] == "OPEN"
        loan_after = get_loan(loan["id"])
        assert loan_after["current_ltv"] is None
        assert loan_after["servicing_status"] == "WATCHLIST"


class TestBreachPostureCascade:
    def test_statement_accept_creates_open_assessment_and_watchlists_loan(self, api):
        """PRD §3.2: "The resulting ratio — annualized net operating income
        divided by annual debt service, rounded half-up to four decimal places —
        becomes the assessment's `computed_value` and is echoed onto the loan as
        `current_dscr`, advancing the loan's `version`."
        PRD §3.6: "the moment any covenant assessment stands `OPEN` or any
        watchlist entry stands `ACTIVE`, a `PERFORMING` loan moves to `WATCHLIST`"

        Design: Difficulty/transitive_cascade/statement_breach_opens_assessment_watchlists_loan_elevates_reserves
        """
        borrower = create_borrower(legal_name="Cascade One", tax_id="TX-CAS-1",
                                   contact_email="cas@x.com")
        loan = create_loan(borrower["id"], loan_number="LN-CAS",
                           dscr_covenant_threshold=1.25, dscr_basis="T3_ANNUALIZED")
        # T3: 10,000,000 x 4 = 40,000,000 / 60,000,000 = 0.6667 < 1.25.
        stmt = submit_statement(loan["id"], borrower["id"], "OPERATING_STATEMENT",
                                *Q2_2026, net_operating_income_cents=10_000_000)
        accept_statement(stmt["id"])
        assessment = newest_assessment(loan["id"], params={"assessment_type": "DSCR"})
        assert assessment["computed_value"] == pytest.approx(0.6667, abs=1e-9)
        assert assessment["breach"] is True
        assert assessment["status"] == "OPEN"
        assert assessment["statement_id"] == stmt["id"]
        loan_after = get_loan(loan["id"])
        assert loan_after["servicing_status"] == "WATCHLIST"
        assert loan_after["current_dscr"] == pytest.approx(0.6667, abs=1e-9)

    def test_watchlist_cascade_elevates_reserve_retainage(self, api):
        """PRD §3.6: "the moment any covenant assessment stands `OPEN` or any
        watchlist entry stands `ACTIVE`, a `PERFORMING` loan moves to `WATCHLIST`
        and every reserve of the loan flips `elevated_retainage` on"
        PRD §2.5: "`version` — an integer that increments on every mutation,
        including cascaded mutations such as a reserve account's
        `elevated_retainage` flag flipping when its loan changes posture."

        Design: Difficulty/transitive_cascade/statement_breach_opens_assessment_watchlists_loan_elevates_reserves
        """
        borrower = create_borrower(legal_name="Cascade One R", tax_id="TX-CAS-1R",
                                   contact_email="cas1r@x.com")
        loan = create_loan(borrower["id"], loan_number="LN-CAS-R",
                           dscr_covenant_threshold=1.25, dscr_basis="T3_ANNUALIZED")
        reserve = create_reserve_account(loan["id"], account_type="REPLACEMENT",
                                         target_balance_cents=0)
        reserve = deposit_reserve(reserve["id"], 100_000)
        assert reserve["elevated_retainage"] is False
        pre_review_version = reserve["version"]

        stmt = submit_statement(loan["id"], borrower["id"], "OPERATING_STATEMENT",
                                *Q2_2026, net_operating_income_cents=10_000_000)
        accept_statement(stmt["id"])

        reserve_after = get_reserve(reserve["id"])
        assert reserve_after["elevated_retainage"] is True, (
            "the OPEN assessment lifts the loan to WATCHLIST, elevating the reserve")
        assert reserve_after["version"] > pre_review_version, (
            "the cascade flip advances the reserve's version")
        assert reserve_after["balance_cents"] == 100_000
