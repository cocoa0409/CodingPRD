"""Distribution runs: the inclusive payout threshold, snapshot clearing on
reopen, segregation of duties, and the staleness checkpoint at approval."""
from test_helpers import (
    ApiErrorId,
    create_distribution_run,
    create_licensee,
    create_statement,
    make_finance_manager_headers,
    make_royalty_analyst_headers,
    run_statement_pipeline,
    setup_finalized_statement,
    setup_registered_work,
    statement_line,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN, ANALYST, Q1_2026, Q2_2026


def _boundary_scenario(api):
    """Writers WA and WB with their own REGISTERED works; one statement whose
    lines give WA a payable of exactly 2500 and WB exactly 2499."""
    ctx_a = setup_registered_work(writer_specs=[("WA", 10000)],
                                  title="Song A", iswc="T-900000040-1",
                                  society_code="ASCAP")
    ctx_b = setup_registered_work(writer_specs=[("WB", 10000)],
                                  title="Song B", iswc="T-900000041-2",
                                  society_code="BMI")
    licensee = create_licensee()
    statement = create_statement(
        licensee["id"],
        [statement_line(1, "Song A", 5000,
                        work_code=ctx_a["work"]["work_code"]),
         statement_line(2, "Song B", 4998,
                        work_code=ctx_b["work"]["work_code"])],
        9998)
    run_statement_pipeline(statement["id"], through="FINALIZED")
    return ctx_a, ctx_b, statement


class TestMinimumPayoutBoundary:
    def test_payable_exactly_2500_is_included(self, api):
        """PRD §3.8: "Every writer whose `payable_balance_cents` is at least $25.00 (2500 cents) earns a payout entry, the boundary included: a writer at exactly 2500 cents is paid. The snapshot's `writer_payouts` lists each eligible `writer_id` with an `amount_cents` equal to their full payable balance, ordered by ascending writer `created_at`; `included_statement_ids` lists the ids of every statement in `FINALIZED` status at that moment, ordered by ascending statement `created_at`; and `total_payable_cents` is the sum of the payout amounts."

        Design: Difficulty/boundary_precision_check/minimum_payout_threshold_inclusive_boundary
        """
        ctx_a, ctx_b, statement = _boundary_scenario(api)
        run = create_distribution_run()
        calculated = validate_success(api.calculate_distribution_run(
            run["id"], make_royalty_analyst_headers("ra-1")))

        assert calculated["status"] == "CALCULATED"
        payouts = calculated["writer_payouts"]
        assert len(payouts) == 1
        assert payouts[0]["writer_id"] == ctx_a["writers"][0]["id"]
        assert payouts[0]["amount_cents"] == 2500, (
            "a writer at exactly 2500 cents is paid — the boundary is "
            "inclusive")
        assert calculated["total_payable_cents"] == 2500
        assert calculated["included_statement_ids"] == [statement["id"]]
        assert calculated["calculated_by_user_id"] == "ra-1"

    def test_payable_2499_is_excluded(self, api):
        """PRD §3.8: "Every writer whose `payable_balance_cents` is at least $25.00 (2500 cents) earns a payout entry, the boundary included: a writer at exactly 2500 cents is paid."

        Design: Difficulty/boundary_precision_check/minimum_payout_threshold_inclusive_boundary
        """
        ctx_a, ctx_b, statement = _boundary_scenario(api)
        run = create_distribution_run()
        calculated = validate_success(api.calculate_distribution_run(
            run["id"], make_royalty_analyst_headers("ra-1")))

        payout_ids = [p["writer_id"] for p in calculated["writer_payouts"]]
        assert ctx_b["writers"][0]["id"] not in payout_ids, (
            "one cent below the 2500-cent threshold excludes the writer")
        assert payout_ids == [ctx_a["writers"][0]["id"]]


class TestReopen:
    def test_distribution_run_reopen_clears_snapshot(self, api):
        """PRD §3.8: "If the numbers look wrong before approval, a `RoyaltyAnalyst` may reopen a `CALCULATED` run, returning it to `OPEN` and clearing the snapshot entirely — `writer_payouts` and `included_statement_ids` emptied, `total_payable_cents` reset to zero, `calculated_by_user_id` cleared to null — ready to be calculated afresh."

        Design: Corner/state_machines/distribution_run_reopen_clears_snapshot
        """
        setup_finalized_statement(line_grosses=(5000,), title="Reopen Song")
        run = create_distribution_run()
        calculated = validate_success(api.calculate_distribution_run(
            run["id"], make_royalty_analyst_headers("ra-1")))
        assert calculated["writer_payouts"], "setup must yield a payout"

        reopened = validate_success(
            api.reopen_distribution_run(run["id"], ANALYST))
        assert reopened["status"] == "OPEN"
        assert reopened["writer_payouts"] == []
        assert reopened["included_statement_ids"] == []
        assert reopened["total_payable_cents"] == 0
        assert reopened["calculated_by_user_id"] is None

        fetched = validate_success(api.get_distribution_run(run["id"], ADMIN))
        assert fetched["status"] == "OPEN"
        assert fetched["writer_payouts"] == []


class TestApprovalGates:
    def test_segregation_of_duties_same_user_rejected(self, api):
        """PRD §3.8: "A `FinanceManager` approves a `CALCULATED` run, but the approver's `X-User-ID` must differ from `calculated_by_user_id` — the operator who calculated a run may never approve it, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). A clean approval records `approved_by_user_id` and moves the run to `APPROVED`."

        Design: Corner/rbac/segregation_of_duties_same_user_rejected
        """
        setup_finalized_statement(line_grosses=(5000,), title="SoD Song")
        run = create_distribution_run()
        validate_success(api.calculate_distribution_run(
            run["id"], make_royalty_analyst_headers("ra-1")))

        # The same person may not approve even wearing the FinanceManager hat.
        resp = api.approve_distribution_run(
            run["id"], make_finance_manager_headers("ra-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        approved = validate_success(api.approve_distribution_run(
            run["id"], make_finance_manager_headers("fm-1")))
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "fm-1"

    def test_stale_distribution_run_blocked_on_approve(self, api):
        """PRD §3.8: "Approval also enforces freshness: if any statement in `FINALIZED` status exists whose id is not in the snapshot's `included_statement_ids`, the run has gone stale and approval is rejected with `ERR_STALE_DISTRIBUTION_RUN`."

        Design: Corner/validations/stale_distribution_run_blocked_on_approve
        """
        ctx = setup_finalized_statement(line_grosses=(5000,),
                                        title="Stale Song", period=Q1_2026)
        run = create_distribution_run()
        validate_success(api.calculate_distribution_run(
            run["id"], make_royalty_analyst_headers("ra-1")))

        # A statement finalized AFTER the calculate is outside the snapshot.
        s2 = create_statement(
            ctx["licensee"]["id"],
            [statement_line(1, "Stale Song Q2", 5000,
                            work_code=ctx["work"]["work_code"])],
            5000, period=Q2_2026)
        run_statement_pipeline(s2["id"], through="FINALIZED")

        resp = api.approve_distribution_run(
            run["id"], make_finance_manager_headers("fm-1"))
        validate_error(resp, ApiErrorId.ERR_STALE_DISTRIBUTION_RUN)
