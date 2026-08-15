"""Mill order receiving (tolerance boundary, NOMINAL vs ACTUAL invoicing) and
progress-billing creation (tiered retainage, snapshot input set, OCC, and
creation-time gates)."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    create_awarded_job,
    create_billing,
    create_fabricating_job,
    current_job_version,
    place_mill_order,
    setup_job_with_pieces,
    submit_billing,
    validate_error,
    validate_success,
)


class TestMillReceiveTolerance:

    def test_receive_exactly_plus_ten_percent_accepted(self):
        """PRD section 3.3: "The scale weight must land within ten percent of
        the ordered weight in either direction — the absolute difference
        between `received_weight_lbs` and `ordered_weight_lbs` must not exceed
        one tenth of `ordered_weight_lbs`, with a delivery at exactly ten
        percent over or under accepted — or the receive is rejected with
        `ERR_WEIGHT_OUT_OF_TOLERANCE`."
        PRD section 3.3: "a `NOMINAL` order bills the ordered weight regardless
        of what the scale read, while an `ACTUAL` order bills the received
        scale weight."

        Design: Difficulty/boundary_precision_check/mill_receive_exactly_tolerance
        """
        job = create_awarded_job("Job V")
        order = place_mill_order(job["id"], material_grade="A36")
        received = validate_success(
            api_client.receive_mill_order(
                order["id"], {"received_weight_lbs": 110000}, ADMIN
            )
        )
        assert received["status"] == "RECEIVED", \
            f"exactly +10% must be accepted, got {received['status']}"
        # NOMINAL bills the ordered weight: 100000 lbs / 100 * 4500 cents.
        assert received["invoice_amount_cents"] == 4500000

    def test_receive_one_pound_over_tolerance_rejected(self):
        """PRD section 3.3: "The scale weight must land within ten percent of
        the ordered weight in either direction — the absolute difference
        between `received_weight_lbs` and `ordered_weight_lbs` must not exceed
        one tenth of `ordered_weight_lbs`, with a delivery at exactly ten
        percent over or under accepted — or the receive is rejected with
        `ERR_WEIGHT_OUT_OF_TOLERANCE`."

        Design: Difficulty/boundary_precision_check/mill_receive_exactly_tolerance
        """
        job = create_awarded_job("Job V2")
        order = place_mill_order(job["id"], material_grade="A36")
        resp = api_client.receive_mill_order(
            order["id"], {"received_weight_lbs": 110001}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_WEIGHT_OUT_OF_TOLERANCE)
        after = validate_success(api_client.get_mill_order(order["id"], ADMIN))
        assert after["status"] == "PLACED", \
            "a rejected receive must leave the order PLACED"


class TestMillInvoiceVariants:

    def test_nominal_invoice_bills_ordered_weight(self):
        """PRD section 3.3: "A successful receive computes
        `invoice_amount_cents` by converting the billable weight to
        hundredweight and multiplying by `unit_price_per_cwt_cents`, rounding
        half up to whole cents. The two billing modes differ only in which
        weight is billed: a `NOMINAL` order bills the ordered weight regardless
        of what the scale read, while an `ACTUAL` order bills the received
        scale weight."

        Design: Difficulty/dual_variant_calc/mill_invoice_nominal_vs_actual
        """
        job = create_awarded_job("Job M")
        order = place_mill_order(job["id"], material_grade="A36",
                                 billing_mode="NOMINAL")
        received = validate_success(
            api_client.receive_mill_order(
                order["id"], {"received_weight_lbs": 105000}, ADMIN
            )
        )
        assert received["status"] == "RECEIVED"
        # 100000 lbs ordered / 100 = 1000 cwt x 4500 cents.
        assert received["invoice_amount_cents"] == 4500000, (
            f"NOMINAL must bill the ordered weight, "
            f"got {received['invoice_amount_cents']}"
        )

    def test_actual_invoice_bills_received_weight(self):
        """PRD section 3.3: "A successful receive computes
        `invoice_amount_cents` by converting the billable weight to
        hundredweight and multiplying by `unit_price_per_cwt_cents`, rounding
        half up to whole cents. The two billing modes differ only in which
        weight is billed: a `NOMINAL` order bills the ordered weight regardless
        of what the scale read, while an `ACTUAL` order bills the received
        scale weight."

        Design: Difficulty/dual_variant_calc/mill_invoice_nominal_vs_actual
        """
        job = create_awarded_job("Job M2")
        order = place_mill_order(job["id"], material_grade="A36",
                                 billing_mode="ACTUAL")
        received = validate_success(
            api_client.receive_mill_order(
                order["id"], {"received_weight_lbs": 105000}, ADMIN
            )
        )
        assert received["status"] == "RECEIVED"
        # 105000 lbs received / 100 = 1050 cwt x 4500 cents.
        assert received["invoice_amount_cents"] == 4725000, (
            f"ACTUAL must bill the received scale weight, "
            f"got {received['invoice_amount_cents']}"
        )


class TestRetainageTierBoundary:

    def test_pct_at_threshold_uses_low_rate(self):
        """PRD section 3.9: "Third, the retainage rate is selected on the whole
        amount: five percent when the percent complete is at least one half
        (0.5000), ten percent when it is below — the selected rate applies to
        the entire cumulative earned figure, not marginally to a bracket."
        PRD section 3.9: "Finally, `net_due_cents` is `earned_cum_cents` minus
        `retainage_cum_cents` minus the job's `settled_backcharge_cents` minus
        the previously billed net, and `retainage_booked_cents` is
        `retainage_cum_cents` minus the previously booked retainage."

        Design: Difficulty/combinatorial_formula/retainage_tiered_rate_whole_amount
        """
        # 500 of 1000 lbs erected -> pct exactly 0.5000 -> 5% whole-amount.
        ctx = setup_job_with_pieces(
            "Job A", "WEIGHT", [("A-P1", 500, True), ("A-P2", 500, False)],
        )
        billing = create_billing(ctx["job"]["id"], "2026-08")
        assert billing["pct_complete_snapshot"] == pytest.approx(0.5, abs=1e-9)
        assert billing["earned_cum_cents"] == 5000000
        assert billing["retainage_cum_cents"] == 250000, (
            f"pct >= 0.5000 must select the 5% whole-amount rate, "
            f"got {billing['retainage_cum_cents']}"
        )
        assert billing["retainage_booked_cents"] == 250000
        assert billing["net_due_cents"] == 4750000

    def test_pct_below_threshold_uses_high_rate(self):
        """PRD section 3.9: "Third, the retainage rate is selected on the whole
        amount: five percent when the percent complete is at least one half
        (0.5000), ten percent when it is below — the selected rate applies to
        the entire cumulative earned figure, not marginally to a bracket."

        Design: Difficulty/combinatorial_formula/retainage_tiered_rate_whole_amount
        """
        # 499 of 1000 lbs erected -> pct 0.4990 -> 10% whole-amount.
        ctx = setup_job_with_pieces(
            "Job B", "WEIGHT", [("B-P1", 499, True), ("B-P2", 501, False)],
        )
        billing = create_billing(ctx["job"]["id"], "2026-08")
        assert billing["pct_complete_snapshot"] == pytest.approx(0.499, abs=1e-9)
        assert billing["earned_cum_cents"] == 4990000
        assert billing["retainage_cum_cents"] == 499000, (
            f"pct below 0.5000 must select the 10% whole-amount rate, "
            f"got {billing['retainage_cum_cents']}"
        )
        assert billing["net_due_cents"] == 4491000


class TestBillingSnapshotInputSet:

    def test_previously_billed_excludes_submitted(self):
        """PRD section 3.9: "Fifth, prior billings are summed — only billings
        in `APPROVED` or `PAID` count; `DRAFT`, `SUBMITTED`, and `VOIDED`
        billings are excluded — yielding the previously billed net (the sum of
        their `net_due_cents`) and the previously booked retainage (the sum of
        their `retainage_cum_cents`)."

        Design: Corner/calculations/previously_billed_excludes_submitted
        """
        # pct 0.5000 -> net 4750000 for every billing while none is APPROVED.
        ctx = setup_job_with_pieces(
            "Job CB2", "WEIGHT", [("P1", 500, True), ("P2", 500, False)],
        )
        first = create_billing(ctx["job"]["id"], "2026-08")
        assert first["net_due_cents"] == 4750000
        submit_billing(first["id"])  # SUBMITTED — excluded from prior sums
        second = create_billing(ctx["job"]["id"], "2026-09")
        assert second["net_due_cents"] == 4750000, (
            f"a merely SUBMITTED billing must not reduce the next billing's "
            f"net due, got {second['net_due_cents']}"
        )


class TestBillingCreationGates:

    def test_occ_stale_billing_rejected(self):
        """PRD section 2.7: "Creating a progress billing requires the request
        to carry `expected_job_version`, holding the job's `version` as the
        client last observed it. Billing creation snapshots the job's
        aggregates — percent complete, billed-to-date, settled backcharges — so
        a stale job view would produce a billing computed from superseded
        aggregates; a mismatch is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."
        PRD section 3.9: "a mismatch with the job's current `version` is
        rejected with `ERR_STALE_VERSION` (HTTP 412), and the act of creating a
        billing itself increments the job's `version` by one."

        Design: Corner/validations/occ_stale_billing_rejected
        """
        ctx = create_fabricating_job("Job V6")
        observed = current_job_version(ctx["job"]["id"])
        create_billing(ctx["job"]["id"], "2026-08", observed)
        # The first creation bumped the job version; replaying is stale.
        resp = api_client.create_progress_billing(
            {
                "job_id": ctx["job"]["id"], "period_label": "2026-09",
                "expected_job_version": observed,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_duplicate_period_billing_rejected(self):
        """PRD section 3.9: "Two gates apply: the job must be `FABRICATING`,
        `ERECTING`, or `COMPLETE` — billing against an `ESTIMATING` or
        `AWARDED` job fails with `ERR_JOB_NOT_BILLABLE` — and the
        `period_label` must be unique within the job among billings not in
        `VOIDED`, with duplicates rejected as `ERR_DUPLICATE_BILLING_PERIOD`."

        Design: Corner/validations/duplicate_period_billing_rejected
        """
        ctx = create_fabricating_job("Job V7")
        create_billing(ctx["job"]["id"], "2026-08")
        # A fresh OCC token: only the period-label gate can fail.
        resp = api_client.create_progress_billing(
            {
                "job_id": ctx["job"]["id"], "period_label": "2026-08",
                "expected_job_version": current_job_version(ctx["job"]["id"]),
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_BILLING_PERIOD)

    def test_billing_on_unbillable_job_rejected(self):
        """PRD section 3.9: "Two gates apply: the job must be `FABRICATING`,
        `ERECTING`, or `COMPLETE` — billing against an `ESTIMATING` or
        `AWARDED` job fails with `ERR_JOB_NOT_BILLABLE` — and the
        `period_label` must be unique within the job among billings not in
        `VOIDED`, with duplicates rejected as `ERR_DUPLICATE_BILLING_PERIOD`."

        Design: Corner/validations/billing_on_unbillable_job_rejected
        """
        job = create_awarded_job("Job V8")
        resp = api_client.create_progress_billing(
            {
                "job_id": job["id"], "period_label": "2026-08",
                "expected_job_version": current_job_version(job["id"]),
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_JOB_NOT_BILLABLE)
