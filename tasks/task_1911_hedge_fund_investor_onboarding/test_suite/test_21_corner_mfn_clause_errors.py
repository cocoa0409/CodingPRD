"""Queue B — errors: MFN clause retirement and capacity threshold.

Instances:
  - error_clause_retired_triggered
  - error_below_capacity_threshold_triggered
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_mfn_clause,
    make_investor_headers,
    setup_accepted_subscription,
    setup_executed_side_letter,
    validate_error,
    validate_success,
)

FA = TEST_USERS["fund_admin_headers"]


class TestClauseRetiredError:
    def test_error_clause_retired_triggered(self, api, fund_admin_headers):
        """PRD §3.5: "Election is guarded by two checks: the named clause
        must still be in ACTIVE status (a retired clause is rejected with
        ERR_CLAUSE_RETIRED)."

        Design: Corner/errors/error_clause_retired_triggered
        """
        ctx = setup_accepted_subscription(commitment_amount_cents=200000)
        fund = ctx["fund"]
        clause = create_mfn_clause(
            fund["id"], clause_tag="FEE_REBATE", clause_text="r",
            capacity_threshold_cents=0, fee_rebate_bps=100, notice_days_reduction=0,
        )
        ctx = setup_executed_side_letter(ctx)
        api.retire_mfn_clause(fund["id"], clause["id"], fund_admin_headers)

        investor_headers = make_investor_headers(ctx["investor"]["id"])
        resp = api.elect_mfn(
            fund["id"], ctx["side_letter"]["id"],
            {"mfn_clause_id": clause["id"]},
            investor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CLAUSE_RETIRED)


class TestBelowCapacityThresholdError:
    def test_error_below_capacity_threshold_triggered(self, api, fund_admin_headers):
        """PRD §3.5: "the subscription's commitment_amount_cents must be at
        least the clause's capacity_threshold_cents (otherwise the election
        is rejected with ERR_BELOW_CAPACITY_THRESHOLD)."

        Design: Corner/errors/error_below_capacity_threshold_triggered
        """
        ctx = setup_accepted_subscription(commitment_amount_cents=200000)
        fund = ctx["fund"]
        clause = create_mfn_clause(
            fund["id"], clause_tag="FEE_REBATE", clause_text="big only",
            capacity_threshold_cents=1000000, fee_rebate_bps=500, notice_days_reduction=0,
        )
        ctx = setup_executed_side_letter(ctx)

        investor_headers = make_investor_headers(ctx["investor"]["id"])
        resp = api.elect_mfn(
            fund["id"], ctx["side_letter"]["id"],
            {"mfn_clause_id": clause["id"]},
            investor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_BELOW_CAPACITY_THRESHOLD)
