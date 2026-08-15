"""Batch disburse cascade and PHW remittance reports."""
from test_helpers import (
    CLERK,
    SUPERVISOR,
    ApiErrorId,
    assert_pay_batch,
    assert_remittance_report,
    create_remittance_report_payload,
    get_engagement,
    get_garnishment_order,
    get_performer,
    get_success_data,
    get_timecard,
    list_pay_lines,
    setup_approved_batch_with_tca,
    setup_closed_batch_with_tca,
    setup_disbursed_batch_with_tca,
    validate_error,
    validate_success,
)


class TestDisburseCascade:
    def test_disburse_flips_batch_line_and_source(self, api):
        """PRD §3.11: "Disburse is the cascade point: every pay line of the batch
        flips from `UNPAID` to `PAID`; each flip cascades to the source, moving
        timecards from `BATCHED` to `PAID` and residuals from `BATCHED` to
        `PAID`".

        Design: Difficulty/transitive_cascade/batch_disburse_four_link_cascade
        """
        ctx = setup_approved_batch_with_tca(with_garnishments=True)
        disbursed = get_success_data(api.disburse_pay_batch(ctx["bat"]["id"],
                                                            SUPERVISOR))
        assert_pay_batch(disbursed)
        assert disbursed["status"] == "DISBURSED"
        lines = list_pay_lines()
        assert len(lines) == 1
        assert lines[0]["status"] == "PAID", "link 1: batch -> pay line"
        tc_after = get_timecard(ctx["tc"]["id"])
        assert tc_after["payment_status"] == "PAID", "link 2: line -> source"
        assert tc_after["review_status"] == "APPROVED"

    def test_disburse_recomputes_engagement_performer_and_orders(self, api):
        """PRD §3.11: "each source flip triggers a recompute of the parent
        engagement's `ytd_paid_cents` as the sum of `net_cents` over its `PAID`
        pay lines; each engagement recompute triggers a recompute of the
        performer's `ytd_gross_cents` (sum of `gross_cents` over `PAID` pay lines
        belonging to the performer) and `ytd_garnished_cents` (sum of
        `garnished_cents` over the same set); and every garnishment order that
        received an allocation during the waterfall has its `total_withheld_cents`
        updated."

        Design: Difficulty/transitive_cascade/batch_disburse_four_link_cascade
        """
        ctx = setup_disbursed_batch_with_tca(with_garnishments=True)
        eng_after = get_engagement(ctx["eng"]["id"])
        assert eng_after["ytd_paid_cents"] == 102550, (
            "link 3: engagement ytd = sum of net_cents over PAID lines")
        perf_after = get_performer(ctx["perf"]["id"])
        assert perf_after["ytd_gross_cents"] == 149375, (
            "link 4: performer ytd gross = sum of gross over PAID lines")
        assert perf_after["ytd_garnished_cents"] == 31887
        g1 = get_garnishment_order(ctx["g1"]["id"])
        g2 = get_garnishment_order(ctx["g2"]["id"])
        assert g1["total_withheld_cents"] == 26887
        assert g2["total_withheld_cents"] == 5000


class TestRemittanceReports:
    def test_remittance_aggregation_matches_line_sums(self, api):
        """PRD §3.16: "it selects every pay line of the batch whose engagement is
        governed by the named agreement, and for each of the three funds sums the
        per-line rounded amounts — pension is the sum over matching lines of each
        line's gross multiplied by the agreement's `phw_pension_pct` and rounded
        half-up; health and welfare follow the same pattern with their respective
        percentages. Because per-line rounding matches the pay-line computation,
        `pension_cents` plus `health_cents` plus `welfare_cents` equals the sum of
        `phw_cents` over the matching lines."
        PRD §3.16: "The report is created in `DRAFT` status."

        Design: Corner/calculations/remittance_aggregation_matches_line_sums
        """
        ctx = setup_disbursed_batch_with_tca()
        resp = api.create_remittance_report(
            create_remittance_report_payload(ctx["bat"]["id"], ctx["agr"]["id"]),
            CLERK)
        report = validate_success(resp, expected_status=201)
        assert_remittance_report(report)
        assert report["pension_cents"] == 8963, "round_half_up(149375 x 0.06)"
        assert report["health_cents"] == 12697, "round_half_up(149375 x 0.085)"
        assert report["welfare_cents"] == 1793, "round_half_up(149375 x 0.012)"
        total = (report["pension_cents"] + report["health_cents"]
                 + report["welfare_cents"])
        assert total == 23453
        assert total == ctx["bat"]["total_phw_cents"], (
            "single agreement covers every line, so the fund sum matches the batch")
        assert report["status"] == "DRAFT"

    def test_remittance_create_before_disburse_rejected(self, api):
        """PRD §3.16: "Creation requires the referenced batch to be `DISBURSED`; a
        batch in any other state is rejected with `ERR_BATCH_NOT_DISBURSED`."

        Design: Corner/validations/remittance_create_before_disburse_rejected
        """
        ctx = setup_closed_batch_with_tca()  # CLOSED, never approved/disbursed
        resp = api.create_remittance_report(
            create_remittance_report_payload(ctx["bat"]["id"], ctx["agr"]["id"]),
            CLERK)
        validate_error(resp, ApiErrorId.ERR_BATCH_NOT_DISBURSED)
