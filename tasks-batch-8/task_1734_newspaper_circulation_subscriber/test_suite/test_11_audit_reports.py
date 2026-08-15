"""Audit bureau reports: certification gate, totals filtering, period overlap."""
from test_helpers import (
    DIRECTOR,
    MGR,
    REP,
    ApiErrorId,
    cancel_and_get_offer,
    create_audit,
    create_plan,
    create_rack_location,
    create_rack_report,
    create_subscriber,
    create_subscription,
    pay_and_clear,
    run_daily_cycle,
    set_clock,
    set_clock_and_cycle,
    validate_error,
    validate_success,
)


class TestCertifyGate:
    def test_audit_certify_requires_reconciled_rack_reports(self, api):
        """PRD §3.10: "Certifying requires the report still be `DRAFT`
        (`ERR_AUDIT_NOT_DRAFT`) and requires that every rack sales report
        with a `week_start_date` inside the period has reached `RECONCILED` —
        a single straggler blocks certification with
        `ERR_UNRECONCILED_RACK_VARIANCE`."
        PRD §3.10: "On certification, all three totals are **recomputed**
        against current data — the stale `DRAFT` snapshot is discarded — and
        `certified_at` is stamped."
        PRD §3.10: "`single_copy_copies` sums `copies_sold` over rack sales
        reports in `RECONCILED` status whose `week_start_date` falls inside
        the period — `DRAFT`, `SUBMITTED`, and `DISPUTED` reports are
        excluded."

        Design: Difficulty/cross_entity_state_dependency/audit_certify_requires_reconciled_rack_reports
        """
        rack = create_rack_location(
            location_name="QuickStop", address="5 Rt 9", price_per_copy_cents=150
        )
        report = create_rack_report(
            rack["id"], week_start_date="2026-08-03",
            copies_delivered=50, copies_returned=8,
        )
        validate_success(api.submit_rack_sales_report(report["id"], MGR))

        audit = create_audit("2026-08-01", "2026-08-31")
        assert audit["status"] == "DRAFT"
        assert audit["single_copy_copies"] == 0, (
            "SUBMITTED (unreconciled) reports are excluded from the draft snapshot"
        )

        blocked = api.certify_audit_report(audit["id"], DIRECTOR)
        validate_error(blocked, ApiErrorId.ERR_UNRECONCILED_RACK_VARIANCE, 409)
        still_draft = validate_success(api.get_audit_report(audit["id"], DIRECTOR))
        assert still_draft["status"] == "DRAFT"

        validate_success(api.reconcile_rack_sales_report(report["id"], DIRECTOR))
        certified = validate_success(api.certify_audit_report(audit["id"], DIRECTOR))
        assert certified["status"] == "CERTIFIED"
        assert certified["single_copy_copies"] == 42, (
            "totals recomputed at certification over RECONCILED reports"
        )

    def test_audit_certify_recompute_discards_stale_snapshot(self, api):
        """PRD §3.10: "On certification, all three totals are **recomputed**
        against current data — the stale `DRAFT` snapshot is discarded — and
        `certified_at` is stamped."

        Design: Difficulty/cross_entity_state_dependency/audit_certify_requires_reconciled_rack_reports
        """
        # Draft the audit FIRST (no in-period rack reports yet), then file
        # and reconcile one: certification must recompute to include it.
        audit = create_audit("2026-08-01", "2026-08-31")
        assert audit["single_copy_copies"] == 0

        rack = create_rack_location(
            location_name="LateStop", address="6 Rt 9", price_per_copy_cents=150
        )
        report = create_rack_report(
            rack["id"], week_start_date="2026-08-03",
            copies_delivered=20, copies_returned=5,
        )
        validate_success(api.submit_rack_sales_report(report["id"], MGR))
        validate_success(api.reconcile_rack_sales_report(report["id"], DIRECTOR))

        certified = validate_success(api.certify_audit_report(audit["id"], DIRECTOR))
        assert certified["status"] == "CERTIFIED"
        assert certified["single_copy_copies"] == 15, (
            "certification recomputes over current data, not the draft snapshot"
        )
        assert certified["certified_at"] is not None


class TestAuditStateErrors:
    def test_certify_twice_rejected(self, api):
        """PRD §3.10: "Certifying requires the report still be `DRAFT`
        (`ERR_AUDIT_NOT_DRAFT`) and requires that every rack sales report
        with a `week_start_date` inside the period has reached `RECONCILED` —
        a single straggler blocks certification with
        `ERR_UNRECONCILED_RACK_VARIANCE`."

        Design: Corner/errors/certify_twice_rejected
        """
        audit = create_audit("2026-08-01", "2026-08-31")
        certified = validate_success(api.certify_audit_report(audit["id"], DIRECTOR))
        assert certified["status"] == "CERTIFIED"

        resp = api.certify_audit_report(audit["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_AUDIT_NOT_DRAFT, 409)

    def test_submit_uncertified_audit_rejected(self, api):
        """PRD §3.10: "Submitting then requires `CERTIFIED`
        (`ERR_AUDIT_NOT_CERTIFIED`) and lands the report in its terminal
        `SUBMITTED` state, off to the bureau."

        Design: Corner/errors/submit_uncertified_audit_rejected
        """
        audit = create_audit("2026-08-01", "2026-08-31")
        assert audit["status"] == "DRAFT"

        resp = api.submit_audit_report(audit["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_AUDIT_NOT_CERTIFIED, 409)


class TestAuditPeriodOverlap:
    def test_audit_period_overlap_rejected(self, api):
        """PRD §3.10: "A new period may not overlap any existing audit report
        in `DRAFT`, `CERTIFIED`, or `SUBMITTED` status
        (`ERR_AUDIT_PERIOD_OVERLAP`)."

        Design: Corner/validations/audit_period_overlap_rejected
        """
        create_audit("2026-08-01", "2026-08-31")
        resp = api.create_audit_report(
            {"period_start": "2026-08-15", "period_end": "2026-09-15"}, DIRECTOR
        )
        validate_error(resp, ApiErrorId.ERR_AUDIT_PERIOD_OVERLAP, 409)

    def test_audit_period_adjacent_allowed(self, api):
        """PRD §2.8: "**Audit periods** are inclusive at both ends:
        `period_start` through `period_end`, and a new audit report's period
        may not overlap any existing audit report in `DRAFT`, `CERTIFIED`, or
        `SUBMITTED` status."

        Design: Corner/validations/audit_period_overlap_rejected
        """
        create_audit("2026-08-01", "2026-08-31")
        adjacent = api.create_audit_report(
            {"period_start": "2026-09-01", "period_end": "2026-09-30"}, DIRECTOR
        )
        validate_success(adjacent, 201)


class TestAuditTotalsFiltering:
    def test_audit_totals_status_filtering(self, api):
        """PRD §3.10: "`paid_print_subscribers` counts subscriptions on
        `PRINT` or `BUNDLE` plans whose billing state is `ACTIVE`, `GRACE`,
        or `CANCEL_PENDING` — `SUSPENDED`, `LAPSED`, and `CANCELLED` are not
        paid circulation — and whose service span overlaps the period:
        `start_date` no later than `period_end`, and either no `ended_at` or
        an `ended_at` no earlier than `period_start`."
        PRD §3.10: "`paid_digital_subscribers` applies the same filter with
        `DIGITAL` or `BUNDLE` plans."

        Design: Corner/calculations/audit_totals_status_filtering
        """
        set_clock("2026-08-03T00:00:00Z")
        plan_print = create_plan(
            name="AP", plan_type="PRINT", issues_per_week=7,
            base_weekly_rate_cents=600, proration_method="PER_DAY",
            min_weekly_rate_cents=0,
        )
        plan_digital = create_plan(
            name="AD", plan_type="DIGITAL", issues_per_week=0,
            base_weekly_rate_cents=400, proration_method="PER_DAY",
            min_weekly_rate_cents=0,
        )
        plan_bundle = create_plan(
            name="AB", plan_type="BUNDLE", issues_per_week=7,
            base_weekly_rate_cents=900, proration_method="PER_DAY",
            min_weekly_rate_cents=0,
        )
        s1 = create_subscriber(display_name="S1", email="s1@x.com", service_address="1 Elm St")
        s2 = create_subscriber(display_name="S2", email="s2@x.com", service_address="2 Elm St")
        s3 = create_subscriber(display_name="S3", email="s3@x.com")
        s4 = create_subscriber(display_name="S4", email="s4@x.com", service_address="4 Elm St")

        sub1 = create_subscription(s1["id"], plan_print["id"], start_date="2026-08-03")
        sub2 = create_subscription(s2["id"], plan_print["id"], start_date="2026-08-03")
        sub4 = create_subscription(s4["id"], plan_bundle["id"], start_date="2026-08-03")
        run_daily_cycle()

        # sub4: cancel + decline -> CANCELLED.
        offer4 = cancel_and_get_offer(sub4["id"], reason="quit")
        validate_success(api.decline_save_offer(offer4["id"], REP))

        # sub3: DIGITAL started 2026-08-17; unpaid -> GRACE by 2026-09-08
        # (first charge due 2026-08-31, 8 days past due).
        set_clock("2026-08-17T00:00:00Z")
        sub3 = create_subscription(s3["id"], plan_digital["id"], start_date="2026-08-17")
        run_daily_cycle()

        # Age everything to 2026-09-08: sub2 (never paid) is SUSPENDED.
        set_clock_and_cycle("2026-09-08T00:00:00Z")

        # sub1: pay every generated charge in full -> back to ACTIVE.
        pay_and_clear(s1["id"], 3000)

        audit = validate_success(
            api.create_audit_report(
                {"period_start": "2026-08-01", "period_end": "2026-09-30"}, DIRECTOR
            ),
            201,
        )
        assert audit["paid_print_subscribers"] == 1, (
            "only the ACTIVE print sub counts; SUSPENDED print and CANCELLED bundle excluded"
        )
        assert audit["paid_digital_subscribers"] == 1, (
            "the GRACE digital sub counts; the CANCELLED bundle does not"
        )
        assert audit["single_copy_copies"] == 0, (
            "no RECONCILED rack reports exist in the period"
        )

    def test_audit_totals_exclude_out_of_period_subscriptions(self, api):
        """PRD §3.10: "`paid_print_subscribers` counts subscriptions on
        `PRINT` or `BUNDLE` plans whose billing state is `ACTIVE`, `GRACE`,
        or `CANCEL_PENDING` — `SUSPENDED`, `LAPSED`, and `CANCELLED` are not
        paid circulation — and whose service span overlaps the period:
        `start_date` no later than `period_end`, and either no `ended_at` or
        an `ended_at` no earlier than `period_start`."

        Design: Corner/calculations/audit_totals_status_filtering
        """
        set_clock("2026-08-03T00:00:00Z")
        plan = create_plan(
            name="APX", plan_type="PRINT", issues_per_week=7,
            base_weekly_rate_cents=600, proration_method="PER_DAY",
            min_weekly_rate_cents=0,
        )
        subscriber = create_subscriber(
            display_name="PX", email="px@x.com", service_address="9 Elm St"
        )
        subscription = create_subscription(subscriber["id"], plan["id"], start_date="2026-08-03")
        run_daily_cycle()

        # Audit period entirely before the subscription's start_date.
        audit = validate_success(
            api.create_audit_report(
                {"period_start": "2026-07-01", "period_end": "2026-07-31"}, DIRECTOR
            ),
            201,
        )
        assert audit["paid_print_subscribers"] == 0
        assert audit["paid_digital_subscribers"] == 0
