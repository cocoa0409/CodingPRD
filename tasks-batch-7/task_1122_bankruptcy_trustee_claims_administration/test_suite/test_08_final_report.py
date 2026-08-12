"""Final report: ledger reconciliation totals and the immutability contract."""
from test_helpers import (
    api_client, validate_success, get_success_data,
    ApiErrorId, TEST_USERS, create_sale_payload, assert_final_report,
    file_claim, review_and_allow_claim, create_judgment_action,
    file_fee_application, set_clock, propose_plan, confirm_plan,
    get_plan_dividends, setup_case_in_claims_administration,
)

TRUSTEE = TEST_USERS["trustee_headers"]
CLERK = TEST_USERS["clerk_headers"]
COURT = TEST_USERS["court_headers"]


class TestFinalReportTotals:
    def test_final_report_totals_reconcile_to_ledger(self, api):
        """PRD §3.8: "Entry into the `FINAL_REPORT` posture creates the case's
        final report automatically, in `DRAFT` status, with its four totals
        computed from the terminal ledger: `total_receipts_cents` is the sum of
        `POSTED` sale net proceeds plus the sum of `POSTED` recovery deposits;
        `total_dividends_cents` is the sum of `POSTED` dividends;
        `total_fees_cents` is the sum of the approved amounts of `PAID` fee
        applications; and `unclaimed_funds_cents` is receipts minus dividends
        minus fees — which by the ledger invariant equals the case's
        `estate_cash_on_hand_cents` at report time, the amount to be remitted
        to the court registry."

        Ledger: sale net 300,000 + judgment recovery 100,000 = receipts
        400,000; one dividend 350,000; counsel fee 50,000 paid; unclaimed 0.
        The fee is paid before the plan completes, so the report is created
        only after every ledger movement has settled.

        Design: Corner/calculations/final_report_totals_reconcile_to_ledger
        """
        ctx = setup_case_in_claims_administration(case_number="26-20017",
                                                  objection_window_days=1,
                                                  scheduled_value_cents=500000)
        case_id = ctx["case"]["id"]
        cred_id = ctx["creditor"]["id"]
        claim = file_claim(case_id, cred_id, filed_amount_cents=350000)
        review_and_allow_claim(claim["id"])
        create_judgment_action(case_id, cred_id, transfer_amount_cents=100000,
                               demand_amount_cents=100000)
        set_clock("2026-06-02T00:00:00Z")
        get_success_data(api_client.begin_liquidation(case_id, TRUSTEE))
        get_success_data(api_client.mark_asset_for_sale(ctx["asset"]["id"], TRUSTEE))
        sale = get_success_data(api_client.create_sale(
            case_id, create_sale_payload(asset_id=ctx["asset"]["id"],
                                         hammer_price_cents=400000,
                                         sale_costs_cents=100000), TRUSTEE))
        get_success_data(api_client.approve_sale(sale["id"], COURT))
        set_clock("2026-06-04T00:00:00Z")
        get_success_data(api_client.consummate_sale(sale["id"], TRUSTEE))
        get_success_data(api_client.begin_distribution(case_id, TRUSTEE))

        fee = file_fee_application(case_id, applicant_role="COUNSEL",
                                   requested_amount_cents=50000)
        get_success_data(api_client.approve_fee(fee["id"], 50000, COURT))
        set_clock("2026-06-06T00:00:00Z")
        get_success_data(api_client.pay_fee(fee["id"], TRUSTEE))

        plan = propose_plan(case_id)
        confirm_plan(plan["id"], case_id)
        dividends = get_plan_dividends(plan["id"])
        assert len(dividends) == 1
        get_success_data(api_client.post_dividend(dividends[0]["id"], TRUSTEE))

        resp = api.get_final_report(case_id, TRUSTEE)
        report = validate_success(resp)
        assert isinstance(report, list) and len(report) == 1
        report = report[0]
        assert_final_report(report)
        assert report["status"] == "DRAFT"
        assert report["total_receipts_cents"] == 400000
        assert report["total_dividends_cents"] == 350000
        assert report["total_fees_cents"] == 50000
        assert report["unclaimed_funds_cents"] == 0


class TestFinalReportShape:
    def test_final_report_immutable_entity_has_no_version(self, api):
        """PRD §2.5: "The `FinalReport` is the single exception to this
        convention: it carries only `id` and `created_at`, and both
        `updated_at` and `version` are absent from it."
        PRD §3.8: "Entry into the `FINAL_REPORT` posture creates the case's
        final report automatically, in `DRAFT` status, with its four totals
        computed from the terminal ledger"

        Design: Corner/entities/final_report_immutable_entity_has_no_version
        """
        ctx = setup_case_in_claims_administration(case_number="26-20008",
                                                  objection_window_days=1)
        case_id = ctx["case"]["id"]
        claim = file_claim(case_id, ctx["creditor"]["id"],
                           filed_amount_cents=50000)
        review_and_allow_claim(claim["id"])
        set_clock("2026-06-02T00:00:00Z")
        get_success_data(api_client.begin_liquidation(case_id, TRUSTEE))
        get_success_data(api_client.mark_asset_for_sale(ctx["asset"]["id"], TRUSTEE))
        sale = get_success_data(api_client.create_sale(
            case_id, create_sale_payload(asset_id=ctx["asset"]["id"],
                                         hammer_price_cents=100000,
                                         sale_costs_cents=0), TRUSTEE))
        get_success_data(api_client.approve_sale(sale["id"], COURT))
        set_clock("2026-06-04T00:00:00Z")
        get_success_data(api_client.consummate_sale(sale["id"], TRUSTEE))
        get_success_data(api_client.begin_distribution(case_id, TRUSTEE))
        plan = propose_plan(case_id)
        confirm_plan(plan["id"], case_id)
        dividends = get_plan_dividends(plan["id"])
        get_success_data(api_client.post_dividend(dividends[0]["id"], TRUSTEE))

        resp = api.get_final_report(case_id, TRUSTEE)
        report = validate_success(resp)
        assert isinstance(report, list) and len(report) == 1
        assert_final_report(report[0])  # asserts absence of version/updated_at
        assert report[0]["status"] == "DRAFT"
