"""Fund administration: period close reconciliation, annual platform fee, and the
computed project summary read (PRD §2.6, §3.7)."""
from test_helpers import (
    ApiErrorId,
    close_period,
    close_period_payload,
    create_active_bundle,
    create_received_donation,
    create_submitted_disbursement,
    decide_refund,
    get_fund,
    make_finance_officer_headers,
    pledge_donation,
    report_incident,
    request_refund,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPeriodCloseReconciliation:
    def test_fee_reconciliation_partial_refund(self, api):
        """PRD §3.7: "Under `COMPREHENSIVE`, each period donation with `refunded_cents`
        greater than zero keeps a final fee of its original `fee_cents` scaled by the
        ratio of its unrefunded remainder — `amount_cents` minus `refunded_cents` — to
        its full `amount_cents`, rounded half up to whole cents per donation; each such
        donation's reversal is its original fee minus its kept fee, and
        `refund_reversals_cents` is the sum of those per-donation reversals"
        PRD §3.7: "A negative delta posts a `FEE_REVERSAL_CREDIT` entry for the delta's
        absolute value"
        200,000 gift (fee 16,000) with a 50,000 approved refund: kept fee
        round_half_up(16,000 x 150,000/200,000) = 12,000; reversal 4,000; delta -4,000.

        Design: Corner/calculations/c_fee_reconciliation_partial_refund
        """
        bundle = create_active_bundle("user_c_f7", project_name="F7", contact_email="f7@x.org")
        pid = bundle["project_id"]
        fid = bundle["fund_account_id"]
        donation = create_received_donation(pid, 200000)
        request_refund(donation["id"], 50000, requester="donor", reason="partial")
        decide_refund(donation["id"], "APPROVE")

        assessment = close_period(fid, "2026-05-01", "2026-05-31")
        assert assessment["status"] == "FINAL"
        assert assessment["provisional_fees_cents"] == 16000
        assert assessment["refund_reversals_cents"] == 4000
        assert assessment["final_fees_cents"] == 12000
        assert assessment["delta_cents"] == -4000

        fund = get_fund(fid)
        assert fund["total_fees_reversed_cents"] == 4000
        assert fund["available_cents"] == 138000, "200,000 - 50,000 - 16,000 + 4,000"

        entries, _ = validate_paginated(api.list_fund_ledger_entries(
            fid, make_finance_officer_headers(), params={"entry_type": "FEE_REVERSAL_CREDIT"}))
        assert len(entries) == 1
        assert entries[0]["amount_cents"] == 4000, "reversal credit posts the delta's absolute value"

    def test_grant_annual_fee_once_per_year(self, api):
        """PRD §3.7: "Under `PRE_APPROVED_GRANT` no refund reversals are computed —
        grant fees are not reversed — and instead `annual_platform_fee_cents` is 25,000
        cents when this close produces the first `FINAL` assessment whose `period_end`
        falls in a calendar year during which the fund received at least one donation,
        and zero otherwise."
        PRD §3.7: "a positive delta posts a `FEE_DEBIT` for that amount as a negative
        signed entry"

        Design: Corner/calculations/c_grant_annual_fee_once_per_year
        """
        bundle = create_active_bundle("user_c_f8", model="PRE_APPROVED_GRANT",
                                      project_name="F8", contact_email="f8@x.org")
        pid = bundle["project_id"]
        fid = bundle["fund_account_id"]
        create_received_donation(pid, 100000)  # grant fee 3,000 at receipt

        first = close_period(fid, "2026-05-01", "2026-05-31")
        assert first["provisional_fees_cents"] == 3000
        assert first["refund_reversals_cents"] == 0, "grant fees are not reversed"
        assert first["annual_platform_fee_cents"] == 25000
        assert first["final_fees_cents"] == 28000
        assert first["delta_cents"] == 25000

        entries, _ = validate_paginated(api.list_fund_ledger_entries(
            fid, make_finance_officer_headers(), params={"entry_type": "FEE_DEBIT"}))
        annual_entries = [e for e in entries if e["amount_cents"] == -25000]
        assert len(annual_entries) == 1, "positive delta posts a FEE_DEBIT as a negative entry"

        second = close_period(fid, "2026-06-01", "2026-06-30")
        assert second["provisional_fees_cents"] == 0, "no June receipts"
        assert second["annual_platform_fee_cents"] == 0, (
            "the annual fee is charged once per receipt-bearing calendar year")
        assert second["final_fees_cents"] == 0

        fund = get_fund(fid)
        assert fund["total_fees_charged_cents"] == 28000
        assert fund["available_cents"] == 72000

    def test_close_period_invalid(self, api):
        """PRD §3.7: "The `FinanceOfficer` closes a period with `period_start` and
        `period_end`, the end on or after the start (`ERR_CLOSE_PERIOD_INVALID`)"

        Design: Corner/validations/v_close_period_invalid
        """
        bundle = create_active_bundle("user_c_v12", project_name="CP", contact_email="cp@x.org")
        fid = bundle["fund_account_id"]
        resp = api.close_period(
            fid, close_period_payload(period_start="2026-06-30", period_end="2026-06-01"),
            make_finance_officer_headers())
        validate_error(resp, ApiErrorId.ERR_CLOSE_PERIOD_INVALID)
        assessments, meta = validate_paginated(api.list_fee_assessments(
            fid, make_finance_officer_headers()))
        assert assessments == [], "no FeeAssessment persisted for an invalid period"


class TestProjectSummaryRead:
    def test_project_summary_computed_read(self, api):
        """PRD §3.7: "the computed project summary read exposes `available_cents`,
        `forward_available_cents`, `committed_cents`, `reserved_cents`, `risk_score`,
        `oversight_posture`, `open_findings_count`, and `open_incident_count` — the
        last counting incidents in `REPORTED`, `TRIAGED`, or `MITIGATING`."
        PRD §2.6: "`forward_available_cents`, adds a pledge credit to the settled
        figure: eighty percent of the sum of `amount_cents` over the project's
        donations still in `PLEDGED`"
        100,000 received (fee 8,000) + 50,000 pledged + 20,000 committed + one open
        LOW incident (3 points).

        Design: Corner/endpoints/ep_project_summary_computed_read
        """
        bundle = create_active_bundle("user_c_e1", project_name="SM", contact_email="sm@x.org")
        pid = bundle["project_id"]
        create_received_donation(pid, 100000)
        pledge_donation(pid, 50000)
        create_submitted_disbursement(pid, 20000)
        report_incident(pid, severity="LOW", category="SAFETY", description="minor")

        summary = validate_success(api.get_project_summary(pid, make_finance_officer_headers()))
        assert summary["available_cents"] == 72000, "92,000 settled less 20,000 committed"
        assert summary["forward_available_cents"] == 112000, "72,000 + 0.8 x 50,000 pledged"
        assert summary["committed_cents"] == 20000
        assert summary["reserved_cents"] == 0
        assert summary["risk_score"] == 3, "one open LOW incident"
        assert summary["oversight_posture"] == "NORMAL"
        assert summary["open_incident_count"] == 1
        assert summary["open_findings_count"] == 0
