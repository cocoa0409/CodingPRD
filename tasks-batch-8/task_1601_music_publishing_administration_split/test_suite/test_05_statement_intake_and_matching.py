"""Royalty statement intake: the auto-match selector, manual matching and its
window, pipeline ordering, tie-outs, period overlap, and list filtering."""
from test_helpers import (
    ApiErrorId,
    create_licensee,
    create_statement,
    create_work,
    list_statement_lines,
    run_statement_pipeline,
    setup_registered_work,
    statement_line,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ANALYST, Q1_2026, Q2_2026


class TestAutoMatch:
    def test_statement_match_automatch_selector(self, api):
        """PRD §3.5: "The pass examines every `UNMATCHED` line and builds a candidate set of works: any work whose `iswc` equals the line's `reported_iswc` (when that hint is present), plus any work whose `work_code` equals the line's `reported_work_code` (when that hint is present). Only works whose `registration_status` is `REGISTERED` are eligible — a work the societies do not yet know cannot receive royalties."
        PRD §3.5: "Candidates are ranked with ISWC-matched works above work-code-matched works, ties broken by ascending work `created_at`; the best candidate wins, the line's `work_id` is set, and its `match_status` becomes `AUTO_MATCHED`. A line with no candidates remains `UNMATCHED`."

        Design: Corner/state_machines/statement_match_automatch_selector
        """
        ctx = setup_registered_work(title="Match Song")
        work = ctx["work"]
        licensee = create_licensee()
        statement = create_statement(
            licensee["id"],
            [statement_line(1, "Match Song", 2000,
                            work_code=work["work_code"]),
             statement_line(2, "Mystery", 1000)],
            3000)

        matched = validate_success(
            api.match_royalty_statement(statement["id"], ANALYST))
        assert matched["status"] == "MATCHING_REVIEW"

        lines = list_statement_lines(statement["id"])
        assert lines[0]["match_status"] == "AUTO_MATCHED"
        assert lines[0]["work_id"] == work["id"]
        assert lines[1]["match_status"] == "UNMATCHED", (
            "a line with no candidates remains UNMATCHED")
        assert lines[1]["work_id"] is None


class TestPipelineOrder:
    def test_statement_finalize_from_received_rejected(self, api):
        """PRD §3.5: "Finalization — a `RoyaltyAnalyst` action from `ALLOCATED` only — locks the money."
        PRD §3.5: "A statement's full lifecycle is therefore `RECEIVED` → `MATCHING_REVIEW` → `ALLOCATED` → `FINALIZED` → `DISTRIBUTED`, with the `REJECTED` and `SUPERSEDED` branches off `RECEIVED` and `FINALIZED` respectively."

        Design: Corner/state_machines/statement_finalize_from_received_rejected
        """
        licensee = create_licensee()
        statement = create_statement(
            licensee["id"],
            [statement_line(1, "Skip Song", 500)],
            500,
            income_type="MECHANICAL")
        assert statement["status"] == "RECEIVED"

        resp = api.finalize_royalty_statement(statement["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestAllocatePreconditions:
    def test_gross_mismatch_tie_out_rejected(self, api):
        """PRD §3.5: "Four preconditions gate it, in the statement-processing order: the statement must contain at least one line (`ERR_EMPTY_STATEMENT`); the sum of every line's `gross_cents` must equal the header's `gross_amount_cents` exactly — the tie-out, else `ERR_GROSS_MISMATCH`; at least one line must be matched, else `ERR_NO_MATCHED_LINES`; and every matched line's work must have a SplitSet in `CONFIRMED` status, else `ERR_NO_CONFIRMED_SPLIT_SET`."

        Design: Corner/validations/gross_mismatch_tie_out_rejected
        """
        licensee = create_licensee()
        statement = create_statement(
            licensee["id"],
            [statement_line(1, "Short Song", 900)],
            1000,  # header declares 1000 but lines sum to 900
            income_type="MECHANICAL")
        validate_success(api.match_royalty_statement(statement["id"], ANALYST))

        resp = api.allocate_royalty_statement(statement["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_GROSS_MISMATCH)

    def test_empty_statement_match_rejected(self, api):
        """PRD §3.5: "Matching begins when a `RoyaltyAnalyst` runs the auto-match pass, moving the statement from `RECEIVED` to `MATCHING_REVIEW` — refused with `ERR_INVALID_STATE_TRANSITION` from any other state, and with `ERR_EMPTY_STATEMENT` if the statement has no lines."

        Design: Corner/validations/empty_statement_match_rejected
        """
        licensee = create_licensee()
        statement = create_statement(licensee["id"], [], 0,
                                     income_type="PRINT")
        resp = api.match_royalty_statement(statement["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_EMPTY_STATEMENT)

    def test_allocate_with_no_matched_lines_rejected(self, api):
        """PRD §3.5: "Four preconditions gate it, in the statement-processing order: the statement must contain at least one line (`ERR_EMPTY_STATEMENT`); the sum of every line's `gross_cents` must equal the header's `gross_amount_cents` exactly — the tie-out, else `ERR_GROSS_MISMATCH`; at least one line must be matched, else `ERR_NO_MATCHED_LINES`; and every matched line's work must have a SplitSet in `CONFIRMED` status, else `ERR_NO_CONFIRMED_SPLIT_SET`."

        Design: Corner/validations/allocate_with_no_matched_lines_rejected
        """
        licensee = create_licensee()
        statement = create_statement(
            licensee["id"],
            [statement_line(1, "Mystery", 500)],  # no hints -> stays UNMATCHED
            500,
            income_type="OTHER")
        validate_success(api.match_royalty_statement(statement["id"], ANALYST))

        resp = api.allocate_royalty_statement(statement["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_NO_MATCHED_LINES)


class TestManualMatch:
    def test_manual_match_requires_registered_work(self, api):
        """PRD §3.5: "This is permitted only while the line is `UNMATCHED` and the statement is in `RECEIVED` or `MATCHING_REVIEW` (else `ERR_INVALID_STATE_TRANSITION`), and only onto a work that exists (else `ERR_NOT_FOUND`) and is `REGISTERED` (else `ERR_WORK_NOT_REGISTERED`); success sets the line's `work_id` and marks it `MANUAL_MATCHED`."

        Design: Corner/validations/manual_match_requires_registered_work
        """
        work = create_work(title="Unregistered Song")
        assert work["registration_status"] == "UNREGISTERED"
        licensee = create_licensee()
        statement = create_statement(
            licensee["id"],
            [statement_line(1, "Unregistered Song", 700)],
            700,
            income_type="SYNC")
        line = list_statement_lines(statement["id"])[0]

        resp = api.match_statement_line(line["id"], work["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_WORK_NOT_REGISTERED)

    def test_manual_match_window_conditional_action(self, api):
        """PRD §3.5: "This is permitted only while the line is `UNMATCHED` and the statement is in `RECEIVED` or `MATCHING_REVIEW` (else `ERR_INVALID_STATE_TRANSITION`), and only onto a work that exists (else `ERR_NOT_FOUND`) and is `REGISTERED` (else `ERR_WORK_NOT_REGISTERED`); success sets the line's `work_id` and marks it `MANUAL_MATCHED`."

        Design: Corner/endpoints/manual_match_window_conditional_action
        """
        ctx = setup_registered_work(title="Window Match Song")
        work = ctx["work"]
        licensee = create_licensee()
        statement = create_statement(
            licensee["id"],
            [statement_line(1, "Window Match Song", 2000,
                            work_code=work["work_code"]),
             statement_line(2, "Manual One", 2000),
             statement_line(3, "Manual Two", 1000)],
            5000)
        validate_success(api.match_royalty_statement(statement["id"], ANALYST))
        lines = list_statement_lines(statement["id"])
        manual_line, late_line = lines[1], lines[2]

        matched = validate_success(
            api.match_statement_line(manual_line["id"], work["id"], ANALYST))
        assert matched["match_status"] == "MANUAL_MATCHED"
        assert matched["work_id"] == work["id"]

        run_statement_pipeline(statement["id"], through="ALLOCATED")

        resp = api.match_statement_line(late_line["id"], work["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestStatementPeriodOverlap:
    def test_statement_period_overlap_rejected_but_rejected_excluded(self, api):
        """PRD §3.5: "Two statements with the same source, income type, and territory may not cover overlapping periods: the check is closed-inclusive — a shared boundary date conflicts — and it considers every statement of that source, income type, and territory whose status is not `REJECTED` or `SUPERSEDED`, excluding the statement being amended, if any. A conflict is rejected with `ERR_STATEMENT_PERIOD_OVERLAP`."

        Design: Corner/validations/statement_period_overlap_rejected_but_rejected_excluded
        """
        licensee = create_licensee()
        first = create_statement(licensee["id"],
                                 [statement_line(1, "A", 100)], 100)
        validate_success(
            api.reject_royalty_statement(first["id"], "bad feed", ANALYST))

        # REJECTED statements are excluded from the overlap set.
        second = create_statement(licensee["id"],
                                  [statement_line(1, "B", 200)], 200)
        assert second["status"] == "RECEIVED"

        # A shared boundary date conflicts under closed-inclusive semantics.
        payload = {
            "source_type": "LICENSEE",
            "source_id": licensee["id"],
            "income_type": "PERFORMANCE",
            "territory_code": "US",
            "period_start": "2026-03-31T23:59:59Z",
            "period_end": "2026-06-30T23:59:59Z",
            "gross_amount_cents": 300,
            "lines": [statement_line(1, "C", 300)],
        }
        resp = api.create_royalty_statement(payload, ANALYST)
        validate_error(resp, ApiErrorId.ERR_STATEMENT_PERIOD_OVERLAP)


class TestStatementListing:
    def test_statement_list_filter_and_pagination(self, api):
        """PRD §3.5: "The statements list accepts optional `source_id`, `income_type`, `status`, and `amends_statement_id` filters"
        PRD §2.3: "Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order."
        PRD §2.3: "List responses carry the following fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/statement_list_filter_and_pagination
        """
        ctx = setup_registered_work(title="List Song")
        work = ctx["work"]
        licensee = create_licensee()
        s1 = create_statement(
            licensee["id"],
            [statement_line(1, "List Song", 1000,
                            work_code=work["work_code"])],
            1000, period=Q1_2026)
        run_statement_pipeline(s1["id"], through="FINALIZED")
        s2 = create_statement(
            licensee["id"],
            [statement_line(1, "List Song Q2", 2000,
                            work_code=work["work_code"])],
            2000, period=Q2_2026)
        assert s2["status"] == "RECEIVED"

        finalized, meta_f = validate_paginated(
            api.list_royalty_statements(ANALYST, params={"status": "FINALIZED"}))
        assert meta_f["total_count"] == 1
        assert [s["id"] for s in finalized] == [s1["id"]], (
            "the status filter must narrow the list to S1 (S2 is RECEIVED)")

        page1, meta_p1 = validate_paginated(
            api.list_royalty_statements(ANALYST, params={"limit": 1,
                                                         "offset": 0}))
        assert meta_p1["total_count"] == 2
        assert meta_p1["has_more"] is True
        assert page1[0]["id"] == s1["id"]

        page2, meta_p2 = validate_paginated(
            api.list_royalty_statements(ANALYST, params={"limit": 1,
                                                         "offset": 1}))
        assert page2[0]["id"] == s2["id"]
        assert meta_p2["has_more"] is False
