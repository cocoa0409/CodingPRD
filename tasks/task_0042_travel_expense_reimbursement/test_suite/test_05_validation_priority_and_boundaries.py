"""Validation precedence pairs and threshold boundaries.

Queue A (Difficulty) — rules priority_pair_validation_conflict and boundary_precision_check.
"""
from test_helpers import (
    validate_error,
    get_success_data,
    ApiErrorId,
    setup_base_env,
    create_approved_trip,
    create_report,
    add_flight_line,
    add_flight_line_with_receipt,
    add_cdw_line,
    submit_report,
    decide_report,
)


class TestStateBeatsFiscal:
    def test_double_approve_returns_invalid_state_not_budget(self, api):
        """PRD §2.6: "Because state legality is evaluated before the domain business
        rules that follow it, a transition attempted from the wrong state surfaces as
        ERR_INVALID_STATE rather than as a later fiscal or chain-completeness error."
        PRD §3.8: "An approve decision moves the report from SUBMITTED to the terminal
        APPROVED state"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_double_approve
        """
        env = setup_base_env()
        trip = create_approved_trip(env, budget_total_cents=100000)
        report = create_report(env, trip, title="Approved Rpt")
        add_flight_line_with_receipt(env, report, claimed_amount_cents=30000,
                                     cabin_class="ECONOMY", scheduled_hours=4, advance_days=20)
        submit_report(env, report)
        decide_report(env, report, "APPROVE")
        # Report is now terminal APPROVED; a second decide must surface state-illegality.
        resp = api.decide_expense_report(report["id"], {"decision": "APPROVE"}, env["approver_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_reject_already_approved_returns_invalid_state(self, api):
        """PRD §2.6: "Because state legality is evaluated before the domain business
        rules that follow it, a transition attempted from the wrong state surfaces as
        ERR_INVALID_STATE rather than as a later fiscal or chain-completeness error."
        PRD §3.8: "A reject decision moves the report from SUBMITTED to the terminal
        REJECTED state and triggers the rejection cascade."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_double_approve
        """
        env = setup_base_env()
        trip = create_approved_trip(env, budget_total_cents=100000)
        report = create_report(env, trip, title="Approved Rpt")
        add_flight_line_with_receipt(env, report, claimed_amount_cents=30000,
                                     cabin_class="ECONOMY", scheduled_hours=4, advance_days=20)
        submit_report(env, report)
        decide_report(env, report, "APPROVE")
        # A REJECT after the report is already terminal APPROVED is state-illegal.
        resp = api.decide_expense_report(report["id"], {"decision": "REJECT"}, env["approver_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestReceiptBeatsEmptySet:
    def test_missing_receipt_on_nonempty_report_returns_receipt_required(self, api):
        """PRD §3.8: "The report must contain at least one expense line, or it is
        rejected with ERR_REPORT_EMPTY. And the receipt requirement of Section 3.7 must
        be satisfied for every material line, or it is rejected with ERR_RECEIPT_REQUIRED."
        PRD §3.7: "Any line whose computed reimbursable_amount_cents is at or above the
        policy's receipt_required_threshold_cents must have a VERIFIED receipt before
        its report may be submitted; a report submission with such a line lacking a
        verified receipt is rejected with ERR_RECEIPT_REQUIRED."

        Design: Difficulty/priority_pair_validation_conflict/receipt_beats_empty_set_on_submit
        """
        env = setup_base_env(lodging_cap_cents=20000, mie_cents=8000,
                             receipt_required_threshold_cents=7500)
        trip = create_approved_trip(env, budget_total_cents=100000)
        report = create_report(env, trip, title="Receipt Rpt")
        # LODGING 2 nights cap 40000; claimed 35000 reimbursable 35000 >= threshold 7500, no receipt.
        from test_helpers import add_lodging_line
        add_lodging_line(env, report, claimed_amount_cents=35000,
                         check_in_date="2026-06-01", check_out_date="2026-06-03")
        resp = api.submit_expense_report(report["id"], env["traveler_headers"])
        validate_error(resp, ApiErrorId.ERR_RECEIPT_REQUIRED.value)

    def test_verified_receipt_on_material_line_allows_submit(self, api):
        """PRD §3.7: "Any line whose computed reimbursable_amount_cents is at or above
        the policy's receipt_required_threshold_cents must have a VERIFIED receipt before
        its report may be submitted; a report submission with such a line lacking a
        verified receipt is rejected with ERR_RECEIPT_REQUIRED."
        PRD §3.8: "A valid submission moves the report from DRAFT to SUBMITTED and
        recomputes meal_reimbursable_cents and total_reimbursable_cents."

        Design: Difficulty/priority_pair_validation_conflict/receipt_beats_empty_set_on_submit
        """
        from test_helpers import add_lodging_line, upload_ocr_verified_receipt
        env = setup_base_env(lodging_cap_cents=20000, mie_cents=8000,
                             receipt_required_threshold_cents=7500)
        trip = create_approved_trip(env, budget_total_cents=100000)
        report = create_report(env, trip, title="Receipt Rpt")
        # LODGING 2 nights cap 40000; claimed 35000 -> reimbursable 35000 >= threshold.
        line = add_lodging_line(env, report, claimed_amount_cents=35000,
                                check_in_date="2026-06-01", check_out_date="2026-06-03")
        # Supply a VERIFIED receipt matching the claimed amount; submission now succeeds.
        upload_ocr_verified_receipt(env, line, ocr_amount_cents=35000)
        data = get_success_data(api.submit_expense_report(report["id"], env["traveler_headers"]))
        assert data["status"] == "SUBMITTED", "verified material line clears the receipt gate"


class TestReceiptThresholdBoundary:
    def test_reimbursable_exactly_at_threshold_requires_receipt(self, api):
        """PRD §3.7: "Any line whose computed reimbursable_amount_cents is at or above
        the policy's receipt_required_threshold_cents must have a VERIFIED receipt
        before its report may be submitted; a report submission with such a line
        lacking a verified receipt is rejected with ERR_RECEIPT_REQUIRED."
        PRD §3.5: "For a rental-CDW line, the cap is cdw_daily_cap_cents multiplied by
        rental_days; the reimbursable_amount_cents is the smaller of
        claimed_amount_cents and that cap"

        Design: Difficulty/boundary_precision_check/receipt_threshold_at_exact_boundary
        """
        env = setup_base_env(receipt_required_threshold_cents=7500, cdw_daily_cap_cents=3000)
        trip = create_approved_trip(env, budget_total_cents=100000)
        report = create_report(env, trip, title="CDW Rpt")
        # cap 3000*3=9000; claimed 7500 -> reimbursable exactly 7500 == threshold.
        line = add_cdw_line(env, report, claimed_amount_cents=7500, rental_days=3)
        assert line["reimbursable_amount_cents"] == 7500, "reimbursable sits exactly on threshold"
        resp = api.submit_expense_report(report["id"], env["traveler_headers"])
        validate_error(resp, ApiErrorId.ERR_RECEIPT_REQUIRED.value)

    def test_reimbursable_just_below_threshold_needs_no_receipt(self, api):
        """PRD §3.7: "Lines below the threshold carry no receipt requirement."
        PRD §3.8: "A valid submission moves the report from DRAFT to SUBMITTED and
        recomputes meal_reimbursable_cents and total_reimbursable_cents."

        Design: Difficulty/boundary_precision_check/receipt_threshold_at_exact_boundary
        """
        env = setup_base_env(receipt_required_threshold_cents=7500, cdw_daily_cap_cents=3000)
        trip = create_approved_trip(env, budget_total_cents=100000)
        report = create_report(env, trip, title="CDW Rpt")
        # cap 3000*3=9000; claimed 7499 -> reimbursable 7499 < threshold 7500 -> no receipt needed.
        line = add_cdw_line(env, report, claimed_amount_cents=7499, rental_days=3)
        assert line["reimbursable_amount_cents"] == 7499, "reimbursable one cent below threshold"
        data = get_success_data(api.submit_expense_report(report["id"], env["traveler_headers"]))
        assert data["status"] == "SUBMITTED", "below-threshold line needs no receipt to submit"


class TestEmptyReportBoundary:
    def test_zero_line_report_cannot_submit(self, api):
        """PRD §3.8: "The report must contain at least one expense line, or it is
        rejected with ERR_REPORT_EMPTY."

        Design: Difficulty/boundary_precision_check/empty_report_zero_lines_on_submit
        """
        env = setup_base_env()
        trip = create_approved_trip(env, budget_total_cents=100000)
        report = create_report(env, trip, title="Empty Rpt")
        resp = api.submit_expense_report(report["id"], env["traveler_headers"])
        validate_error(resp, ApiErrorId.ERR_REPORT_EMPTY.value)

    def test_one_line_report_submits(self, api):
        """PRD §3.8: "The report must contain at least one expense line, or it is
        rejected with ERR_REPORT_EMPTY."
        PRD §3.8: "A valid submission moves the report from DRAFT to SUBMITTED and
        recomputes meal_reimbursable_cents and total_reimbursable_cents."

        Design: Difficulty/boundary_precision_check/empty_report_zero_lines_on_submit
        """
        from test_helpers import add_mileage_line
        env = setup_base_env()
        trip = create_approved_trip(env, budget_total_cents=100000)
        report = create_report(env, trip, title="One Line Rpt")
        # Exactly one out-of-pocket line: the empty-set boundary is precisely at zero.
        add_mileage_line(env, report, miles=100)
        data = get_success_data(api.submit_expense_report(report["id"], env["traveler_headers"]))
        assert data["status"] == "SUBMITTED", "a single-line report clears the empty-set boundary"
