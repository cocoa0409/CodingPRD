"""Rack sales reports: reconciliation, variance tolerance, dispute cycle, week rules."""
from test_helpers import (
    DIRECTOR,
    MGR,
    ApiErrorId,
    create_rack_location,
    create_rack_report,
    validate_error,
    validate_success,
)


class TestVarianceTolerance:
    def test_rack_variance_exactly_at_tolerance(self, api):
        """PRD §3.9: "`copies_sold` is delivered minus returned;
        `amount_due_cents` is copies sold times the rack's
        `price_per_copy_cents`; `variance_copies` is the reported count minus
        the computed sold count, or zero when no reported count was supplied;
        and `variance_flag` turns true only when the absolute variance
        strictly exceeds two copies — a variance of exactly two is within
        tolerance and does not flag."

        Design: Difficulty/boundary_precision_check/rack_variance_exactly_at_tolerance
        """
        rack = create_rack_location(
            location_name="GasMart", address="1 Rt 9", price_per_copy_cents=150
        )
        report1 = create_rack_report(
            rack["id"], week_start_date="2026-08-03",
            copies_delivered=50, copies_returned=8, reported_sold_copies=44,
        )
        report2 = create_rack_report(
            rack["id"], week_start_date="2026-08-10",
            copies_delivered=50, copies_returned=8, reported_sold_copies=45,
        )

        submitted1 = validate_success(api.submit_rack_sales_report(report1["id"], MGR))
        assert submitted1["copies_sold"] == 42
        assert submitted1["amount_due_cents"] == 6300
        assert submitted1["variance_copies"] == 2
        assert submitted1["variance_flag"] is False, (
            "exactly at the two-copy tolerance is not flagged"
        )

        submitted2 = validate_success(api.submit_rack_sales_report(report2["id"], MGR))
        assert submitted2["copies_sold"] == 42
        assert submitted2["amount_due_cents"] == 6300
        assert submitted2["variance_copies"] == 3
        assert submitted2["variance_flag"] is True

    def test_rack_variance_negative_side_symmetric(self, api):
        """PRD §3.9: "and `variance_flag` turns true only when the absolute
        variance strictly exceeds two copies — a variance of exactly two is
        within tolerance and does not flag."

        Design: Difficulty/boundary_precision_check/rack_variance_exactly_at_tolerance
        """
        rack = create_rack_location(
            location_name="GasMart2", address="2 Rt 9", price_per_copy_cents=150
        )
        at_tolerance = create_rack_report(
            rack["id"], week_start_date="2026-08-03",
            copies_delivered=50, copies_returned=8, reported_sold_copies=40,
        )
        over_tolerance = create_rack_report(
            rack["id"], week_start_date="2026-08-10",
            copies_delivered=50, copies_returned=8, reported_sold_copies=39,
        )

        submitted_at = validate_success(api.submit_rack_sales_report(at_tolerance["id"], MGR))
        assert submitted_at["variance_copies"] == -2
        assert submitted_at["variance_flag"] is False

        submitted_over = validate_success(api.submit_rack_sales_report(over_tolerance["id"], MGR))
        assert submitted_over["variance_copies"] == -3
        assert submitted_over["variance_flag"] is True


class TestDisputeCycle:
    def test_rack_copies_conservation_through_dispute_cycle(self, api):
        """PRD §3.9: "Submission — from `DRAFT`, or resubmission from
        `DISPUTED` after correction — runs the reconciliation computation and
        freezes `copies_delivered`."
        PRD §3.9: "Resubmission from `DISPUTED` recomputes from the corrected
        `copies_returned` with `copies_delivered` untouched."

        Design: Difficulty/compensating_invariant/rack_copies_conservation_through_dispute_cycle
        """
        rack = create_rack_location(
            location_name="Deli", address="9 Rt 9", price_per_copy_cents=150
        )
        report = create_rack_report(
            rack["id"], week_start_date="2026-08-03",
            copies_delivered=50, copies_returned=8,
        )
        submitted = validate_success(api.submit_rack_sales_report(report["id"], MGR))
        assert submitted["copies_sold"] == 42
        assert submitted["amount_due_cents"] == 6300
        assert submitted["copies_sold"] + submitted["copies_returned"] == 50

        disputed = validate_success(api.dispute_rack_sales_report(report["id"], DIRECTOR))
        assert disputed["status"] == "DISPUTED"

        corrected = validate_success(
            api.update_rack_sales_report(report["id"], {"copies_returned": 10}, MGR)
        )
        assert corrected["copies_returned"] == 10

        resubmitted = validate_success(api.submit_rack_sales_report(report["id"], MGR))
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["copies_delivered"] == 50, "delivered count is frozen at submit"
        assert resubmitted["copies_returned"] == 10
        assert resubmitted["copies_sold"] == 40
        assert resubmitted["amount_due_cents"] == 6000
        assert resubmitted["copies_sold"] + resubmitted["copies_returned"] == 50

    def test_rack_dispute_rejects_delivered_edit(self, api):
        """PRD §3.9: "Correction rights are asymmetric once submitted: a
        `DISPUTED` report accepts edits to `copies_returned` only, and
        attempting to edit `copies_delivered` there is `ERR_INVALID_REQUEST`;
        editing anything on a report outside `DRAFT` or `DISPUTED` is
        `ERR_REPORT_NOT_EDITABLE`."

        Design: Difficulty/compensating_invariant/rack_copies_conservation_through_dispute_cycle
        """
        rack = create_rack_location(
            location_name="Deli2", address="10 Rt 9", price_per_copy_cents=150
        )
        report = create_rack_report(
            rack["id"], week_start_date="2026-08-03",
            copies_delivered=50, copies_returned=8,
        )
        validate_success(api.submit_rack_sales_report(report["id"], MGR))
        validate_success(api.dispute_rack_sales_report(report["id"], DIRECTOR))

        resp = api.update_rack_sales_report(report["id"], {"copies_delivered": 60}, MGR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestRackReportStateErrors:
    def test_reconcile_draft_report_rejected(self, api):
        """PRD §3.9: "Reconciling flips the report to its terminal
        `RECONCILED` state (requiring `SUBMITTED`, else
        `ERR_REPORT_NOT_RECONCILABLE`); disputing kicks it back to `DISPUTED`
        for correction with an optional `reason` (requiring `SUBMITTED`, else
        `ERR_INVALID_STATE`)."

        Design: Corner/errors/reconcile_draft_report_rejected
        """
        rack = create_rack_location(location_name="RD", address="4 Rt 9", price_per_copy_cents=150)
        report = create_rack_report(
            rack["id"], week_start_date="2026-08-03", copies_delivered=10, copies_returned=1
        )
        assert report["status"] == "DRAFT"

        resp = api.reconcile_rack_sales_report(report["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_RECONCILABLE, 409)

    def test_submit_after_reconcile_rejected(self, api):
        """PRD §3.9: "Submitting from any status other than `DRAFT` or
        `DISPUTED` is `ERR_REPORT_NOT_SUBMITTABLE`."

        Design: Corner/errors/submit_after_reconcile_rejected
        """
        rack = create_rack_location(location_name="SR", address="6 Rt 9", price_per_copy_cents=150)
        report = create_rack_report(
            rack["id"], week_start_date="2026-08-03", copies_delivered=10, copies_returned=1
        )
        validate_success(api.submit_rack_sales_report(report["id"], MGR))
        reconciled = validate_success(api.reconcile_rack_sales_report(report["id"], DIRECTOR))
        assert reconciled["status"] == "RECONCILED"

        resp = api.submit_rack_sales_report(report["id"], MGR)
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_SUBMITTABLE, 409)

    def test_patch_submitted_report_rejected(self, api):
        """PRD §3.9: "Correction rights are asymmetric once submitted: a
        `DISPUTED` report accepts edits to `copies_returned` only, and
        attempting to edit `copies_delivered` there is `ERR_INVALID_REQUEST`;
        editing anything on a report outside `DRAFT` or `DISPUTED` is
        `ERR_REPORT_NOT_EDITABLE`."

        Design: Corner/errors/patch_submitted_report_rejected
        """
        rack = create_rack_location(location_name="PS", address="7 Rt 9", price_per_copy_cents=150)
        report = create_rack_report(
            rack["id"], week_start_date="2026-08-03", copies_delivered=10, copies_returned=1
        )
        validate_success(api.submit_rack_sales_report(report["id"], MGR))

        resp = api.update_rack_sales_report(report["id"], {"copies_returned": 3}, MGR)
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_EDITABLE, 409)

        after = validate_success(api.get_rack_sales_report(report["id"], MGR))
        assert after["copies_returned"] == 1, "rejected edit must not persist"


class TestRackWeekRules:
    def test_report_week_conflict_rejected(self, api):
        """PRD §3.9: "One report per rack per week: a second report for the
        same rack and week collides with `ERR_REPORT_WEEK_CONFLICT`."

        Design: Corner/validations/report_week_conflict_rejected
        """
        rack = create_rack_location(location_name="WC", address="3 Rt 9", price_per_copy_cents=150)
        create_rack_report(
            rack["id"], week_start_date="2026-08-03", copies_delivered=20, copies_returned=2
        )

        resp = api.create_rack_sales_report(
            {
                "rack_location_id": rack["id"],
                "week_start_date": "2026-08-03",
                "copies_delivered": 30,
                "copies_returned": 5,
            },
            MGR,
        )
        validate_error(resp, ApiErrorId.ERR_REPORT_WEEK_CONFLICT, 409)

    def test_non_monday_week_start_rejected(self, api):
        """PRD §3.9: "Weekly, distribution files a **rack sales report** for
        a location with its `rack_location_id`, a Monday-anchored
        `week_start_date` (non-Mondays are `ERR_INVALID_REQUEST`), the
        `copies_delivered` drop count, the `copies_returned` pickup count
        (which may not exceed delivered), and optionally the location-reported
        `reported_sold_copies`."

        Design: Corner/validations/report_week_conflict_rejected
        """
        rack = create_rack_location(location_name="NM", address="5 Rt 9", price_per_copy_cents=150)
        resp = api.create_rack_sales_report(
            {
                "rack_location_id": rack["id"],
                "week_start_date": "2026-08-04",  # Tuesday
                "copies_delivered": 20,
                "copies_returned": 2,
            },
            MGR,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
