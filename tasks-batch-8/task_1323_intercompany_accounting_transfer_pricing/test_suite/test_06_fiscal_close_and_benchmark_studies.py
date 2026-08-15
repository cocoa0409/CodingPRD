"""Fiscal-year close ceremony: preconditions, the staleness cascade, and
benchmarking-study quartiles, refresh, and OCC."""
from test_helpers import (
    ADMIN,
    ANALYST,
    MANAGER,
    TP_LEAD,
    ApiErrorId,
    assert_benchmarking_study,
    begin_closing,
    book_transaction,
    close_year,
    create_current_study,
    create_fiscal_year,
    create_run,
    create_study,
    refresh_study,
    setup_active_agreement,
    setup_agreement_with_matched_transactions,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)


class TestInterquartileRange:

    def test_iqr_nearest_rank_even_count(self):
        """PRD section 3.2: "Approval by a `TransferPricingLead` moves the
        study `DRAFT → CURRENT` and computes the interquartile range by the
        nearest-rank method: the comparables are sorted ascending; with `n`
        entries, the rank of the p-th percentile is the smallest integer
        greater than or equal to p multiplied by `n` and divided by 100,
        counting positions from 1; `p25_bp`, `median_bp`, and `p75_bp` are
        the sorted values at the ranks for 25, 50, and 75 respectively."

        Design: Corner/calculations/iqr_nearest_rank_even_count
        """
        study = create_study(transaction_type="GOODS", region="NA",
                             vintage_year=2026,
                             comparables_bp=[700, 300, 500, 350, 600, 400])
        resp = api_client.approve_benchmarking_study(study["id"], TP_LEAD)
        approved = validate_success(resp, 200)
        assert_benchmarking_study(approved)
        assert approved["status"] == "CURRENT"
        # sorted [300, 350, 400, 500, 600, 700], n=6:
        # ranks ceil(1.5)=2, ceil(3)=3, ceil(4.5)=5
        assert approved["p25_bp"] == 350
        assert approved["median_bp"] == 400
        assert approved["p75_bp"] == 600

    def test_study_with_too_few_comparables_rejected(self):
        """PRD section 3.2: "The list must contain at least five entries;
        fewer is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/calculations/study_with_too_few_comparables_rejected
        """
        resp = api_client.create_benchmarking_study(
            {"transaction_type": "GOODS", "region": "NA", "vintage_year": 2026,
             "comparables_bp": [300, 400, 500, 600]},
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestStudyRefreshOcc:

    def test_occ_stale_study_refresh_rejected(self):
        """PRD section 2.7: "Refreshing a benchmarking study requires the
        request to carry `expected_study_version`, the `version` of the study
        as the client last observed it. If the study's current `version` on
        the server differs from the supplied value — because another writer
        has advanced it since the client last read the study — the refresh is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD section 3.2: "Refresh is not a state transition of the old study:
        it creates a new `DRAFT` study whose `supersedes_study_id` points at
        the refreshed study, and it increments the refreshed study's
        `version` by 1 as the OCC witness."
        PRD section 3.2: "The studies listing supports optional filters
        `supersedes_study_id`, `status`, and `transaction_type`, so a
        reviewer can trace an entire supersession lineage."

        Design: Corner/cross_cutting_layers/occ_stale_study_refresh_rejected
        """
        study = create_current_study()
        observed_version = study["version"]

        child = refresh_study(study["id"], [350, 450, 550, 650, 750],
                              expected_study_version=observed_version)
        assert child["status"] == "DRAFT"
        assert child["supersedes_study_id"] == study["id"]

        # The first refresh advanced the study's version; the same observed
        # version is now stale.
        resp = api_client.refresh_benchmarking_study(
            study["id"],
            {"comparables_bp": [360, 460, 560, 660, 760],
             "expected_study_version": observed_version},
            TP_LEAD,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        listed, meta = validate_paginated(api_client.list_benchmarking_studies(
            MANAGER, params={"supersedes_study_id": study["id"]}))
        assert meta["total_count"] == 1, "exactly one successor line exists"
        assert listed[0]["id"] == child["id"]


class TestClosePreconditions:

    def test_year_close_blocked_by_unmatched_transaction(self):
        """PRD section 3.1: "Closing the year (`CLOSING → CLOSED`) is gated
        by three preconditions evaluated in the precedence order of §2.8: no
        transaction of the year may have an `elimination_status` other than
        `ELIMINATED` (`ERR_YEAR_HAS_OPEN_TRANSACTIONS`)"

        Design: Corner/state_machines/year_close_blocked_by_unmatched_transaction_rejected
        """
        ctx = setup_active_agreement()
        book_transaction(ctx["agreement"]["id"], ctx["fiscal_year"]["id"])
        begin_closing(ctx["fiscal_year"]["id"])

        resp = api_client.close_fiscal_year(ctx["fiscal_year"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_YEAR_HAS_OPEN_TRANSACTIONS)

        year = validate_success(
            api_client.get_fiscal_year(ctx["fiscal_year"]["id"], ADMIN), 200)
        assert year["status"] == "CLOSING"

    def test_year_close_blocked_by_open_true_up(self):
        """PRD section 3.1: "Closing the year (`CLOSING → CLOSED`) is gated
        by three preconditions evaluated in the precedence order of §2.8: no
        transaction of the year may have an `elimination_status` other than
        `ELIMINATED` (`ERR_YEAR_HAS_OPEN_TRANSACTIONS`); no true-up run of
        the year may be in a status other than `POSTED`
        (`ERR_YEAR_HAS_OPEN_TRUE_UPS`)"

        Design: Corner/errors/year_close_blocked_by_open_true_up_rejected
        """
        ctx = setup_agreement_with_matched_transactions(
            tx_specs=((1_000_000, 1_020_000),))
        begin_closing(ctx["fiscal_year"]["id"])
        # A run left in DRAFT blocks the close.
        create_run(ctx["agreement"]["id"], ctx["fiscal_year"]["id"])

        resp = api_client.close_fiscal_year(ctx["fiscal_year"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_YEAR_HAS_OPEN_TRUE_UPS)

        year = validate_success(
            api_client.get_fiscal_year(ctx["fiscal_year"]["id"], ADMIN), 200)
        assert year["status"] == "CLOSING"

    def test_year_close_blocked_by_missing_cbc_filing(self):
        """PRD section 3.1: "if `cbc_required` is true, a documentation
        package of `doc_type` `CBC_REPORT` in status `FILED` must exist for
        the year (`ERR_CBC_FILING_MISSING`)."

        Design: Corner/errors/year_close_blocked_by_missing_cbc_filing_rejected
        """
        fy = create_fiscal_year(year_index=2026, group_revenue_eur=800_000_000)
        assert fy["cbc_required"] is True
        begin_closing(fy["id"])

        resp = api_client.close_fiscal_year(fy["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_CBC_FILING_MISSING)

        year = validate_success(api_client.get_fiscal_year(fy["id"], ADMIN),
                                200)
        assert year["status"] == "CLOSING"


class TestStalenessCascade:

    def _setup_close_with_old_study(self):
        """Agreement pinned to a vintage-2024 study; year 2026 in CLOSING."""
        ctx = setup_active_agreement(vintage_year=2024)
        begin_closing(ctx["fiscal_year"]["id"])
        return ctx

    def test_year_close_stales_old_study(self):
        """PRD section 3.1: "On close the server stamps `closed_at` from the
        logical clock and fires a two-link staleness cascade: every
        benchmarking study in `CURRENT` whose `vintage_year` is less than or
        equal to the closing `year_index` minus 2 transitions to `STALE`"

        Design: Difficulty/transitive_cascade/year_close_stales_study_flags_pinned_agreements
        """
        ctx = self._setup_close_with_old_study()
        closed = close_year(ctx["fiscal_year"]["id"])
        assert closed["status"] == "CLOSED"
        assert closed["closed_at"] is not None

        study = validate_success(
            api_client.get_benchmarking_study(ctx["study"]["id"], MANAGER), 200)
        assert study["status"] == "STALE", \
            "vintage 2024 <= 2026 - 2, so the close stales the study"

    def test_year_close_flags_pinned_agreement_for_review(self):
        """PRD section 3.1: "and every agreement pinned to one of those newly
        stale studies has its `pricing_review_required` flag set to true."

        Design: Difficulty/transitive_cascade/year_close_stales_study_flags_pinned_agreements
        """
        ctx = self._setup_close_with_old_study()
        close_year(ctx["fiscal_year"]["id"])

        agreement = validate_success(
            api_client.get_agreement(ctx["agreement"]["id"], MANAGER), 200)
        assert agreement["pricing_review_required"] is True, \
            "link 2 of the cascade flags agreements pinned to the stale study"
