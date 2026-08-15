"""Fee payments: late-fee boundary, overpayment guard, immediate consistency,
denial-triggered refund, and the variant filter on assessment lists."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_assessment,
    assert_payment,
    get_single_assessment,
    list_application_assessments,
    pay_assessment,
    record_payment_payload,
    render_decision_now,
    setup_approved_application,
    setup_decision_pending_application,
    setup_submitted_application,
    validate_error,
    validate_paginated,
    validate_success,
)

FIVE_UNITS = {
    "land_use_type": "RESIDENTIAL",
    "dwelling_units": 5,
    "affordable_units": 0,
    "floor_area_sqft": 0,
    "prior_use_basis": {},
}
# Five residential units under the canonical V1 rates price at
# 5 × (3200+2100+800+2600+2900) = 58000.00.
FIVE_UNIT_NET = 58000.00


class TestLateFeeBoundary:
    def test_late_fee_29_vs_30_days(self, api):
        """PRD 3.7: "the days late are the whole-day difference between the two
        instants, floored at zero; the full months late are the whole 30-day
        months contained in that span; and the late fee is the tendered
        `amount` multiplied by 1.5 percent for each full month, rounded half-up
        to two decimal places. A payment 29 days late therefore incurs no late
        fee at all, while a payment 30 days late incurs 1.5 percent of that
        payment's amount."
        PRD 3.3: for the provisional variant the due_date is "the instant the
        application was submitted".

        Design: Corner/calculations/late_fee_boundary_29_vs_30_days
        """
        ctx = setup_submitted_application(project_overrides=FIVE_UNITS)
        assessment = get_single_assessment(
            ctx["application"]["id"], ctx["applicant_headers"], variant="PROVISIONAL"
        )
        # Submitted at the default instant 2026-08-01T00:00:00Z.

        pay29 = pay_assessment(
            assessment["id"], ctx["applicant"], 1000.00, paid_at="2026-08-30T00:00:00Z"
        )
        assert_payment(pay29)
        assert pay29["late_fee"] == pytest.approx(0.00, abs=0.005), (
            f"29 days late is 0 full months, late_fee must be 0.00, "
            f"got {pay29['late_fee']}"
        )

        pay30 = pay_assessment(
            assessment["id"], ctx["applicant"], 1000.00, paid_at="2026-08-31T00:00:00Z"
        )
        assert_payment(pay30)
        assert pay30["late_fee"] == pytest.approx(15.00, abs=0.005), (
            f"30 days late is 1 full month: 1.5% of 1000.00 = 15.00, "
            f"got {pay30['late_fee']}"
        )
        assert pay30["applied_amount"] == pytest.approx(1000.00, abs=0.005), (
            "the late fee is charged in addition to the amount tendered, "
            "never netted from it"
        )


class TestOverpayment:
    def test_payment_to_nonexistent_assessment_reports_not_found(self, api, applicant_headers):
        """PRD 2.9: "every operation passes through eight ordered validation
        gates, and a failure at an earlier gate masks every later check" — the
        existence gate ("3. **Existence.** Path identifiers resolve left to
        right, else `ERR_NOT_FOUND` (404)") precedes the fiscal gate
        ("8. **Fiscal checks.** Assessments settled or deferred before permit
        issuance, and payment amounts held within the outstanding balance.
        Violations report `ERR_FEES_UNPAID` (402).").
        PRD 2.5: "The first identifier that does not resolve to an existing
        resource aborts the request with `ERR_NOT_FOUND` (404)".

        A payment that would also exceed any balance, posted to a nonexistent
        assessment id, must surface the existence failure.

        Design: Difficulty/priority_pair_validation_conflict/payment_existence_vs_fiscal_overpay_priority
        """
        payload = record_payment_payload(
            amount=99999999.00, paid_at="2026-08-01T00:00:00Z"
        )
        response = api.record_payment(NON_EXISTENT_UUID, payload, applicant_headers)
        validate_error(response, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    def test_payment_exceeding_balance_rejected(self, api):
        """PRD 3.7: "A payment may not exceed the assessment's outstanding
        balance; an overpayment is refused with `ERR_PAYMENT_EXCEEDS_BALANCE`."

        Design: Difficulty/priority_pair_validation_conflict/payment_existence_vs_fiscal_overpay_priority
        """
        ctx = setup_submitted_application(project_overrides=FIVE_UNITS)
        assessment = get_single_assessment(
            ctx["application"]["id"], ctx["applicant_headers"], variant="PROVISIONAL"
        )
        assert assessment["outstanding_balance"] == pytest.approx(FIVE_UNIT_NET, abs=0.005)

        payload = record_payment_payload(amount=99999.00, paid_at="2026-08-02T00:00:00Z")
        response = api.record_payment(
            assessment["id"], payload, ctx["applicant_headers"]
        )
        validate_error(response, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE)

    def test_payment_exceeds_balance_corner(self, api):
        """PRD 3.7: "A payment may not exceed the assessment's outstanding
        balance; an overpayment is refused with `ERR_PAYMENT_EXCEEDS_BALANCE`."
        PRD 5: `ERR_PAYMENT_EXCEEDS_BALANCE` carries HTTP status 402.

        Design: Corner/errors/error_payment_exceeds_balance
        """
        ctx = setup_submitted_application(project_overrides=FIVE_UNITS)
        assessment = get_single_assessment(
            ctx["application"]["id"], ctx["applicant_headers"], variant="PROVISIONAL"
        )
        payload = record_payment_payload(amount=99999.00, paid_at="2026-08-02T00:00:00Z")
        response = api.record_payment(
            assessment["id"], payload, ctx["applicant_headers"]
        )
        validate_error(response, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE, expected_status=402)


def test_payment_immediately_reflects_assessment_status(api):
    """PRD 3.7: "While the cumulative applied total remains below `net_total`,
    a payment moves the assessment from `OPEN` to `PARTIALLY_PAID` and
    recomputes the `outstanding_balance`" — the very next read shows the new
    state, with no lag.

    Design: Corner/consistency_model/payment_immediately_reflects_assessment_status
    """
    ctx = setup_submitted_application(project_overrides=FIVE_UNITS)
    assessment = get_single_assessment(
        ctx["application"]["id"], ctx["applicant_headers"], variant="PROVISIONAL"
    )
    assert assessment["status"] == "OPEN"

    pay_assessment(assessment["id"], ctx["applicant"], 10000.00)

    after = validate_success(
        api.get_assessment(assessment["id"], ctx["applicant_headers"])
    )
    assert after["status"] == "PARTIALLY_PAID", (
        f"partial payment must move the assessment to PARTIALLY_PAID "
        f"immediately, got {after['status']}"
    )
    assert after["outstanding_balance"] == pytest.approx(48000.00, abs=0.005), (
        f"outstanding must recompute to 58000−10000=48000, got "
        f"{after['outstanding_balance']}"
    )


def test_partial_payment_then_denial_refunds_assessment(api):
    """PRD 3.6: "On `DENY`, the application moves to `DENIED`, the recorded
    decision carries the denial, and every fee assessment still `OPEN` or
    `PARTIALLY_PAID` is moved to `REFUNDED` — the provisional assessment is
    voided and its payments refunded."
    PRD 3.3: an assessment carries "an `outstanding_balance` of `net_total`
    minus the sum of `applied_amount` across payments that have not been
    refunded" — once the payment is refunded the balance returns to the full
    net, so the applicant's net outlay is zero.

    Design: Difficulty/compensating_invariant/fee_assessment_net_equals_gross_minus_credits_conservation
    """
    ctx = setup_decision_pending_application(
        project_overrides=FIVE_UNITS, with_authority=True
    )
    assessment = get_single_assessment(
        ctx["application"]["id"], ctx["applicant_headers"], variant="PROVISIONAL"
    )
    pay_assessment(assessment["id"], ctx["applicant"], 10000.00)
    partial = validate_success(
        api.get_assessment(assessment["id"], ctx["applicant_headers"])
    )
    assert partial["status"] == "PARTIALLY_PAID"

    render_decision_now(ctx, decision="DENY")

    after = validate_success(
        api.get_assessment(assessment["id"], ctx["reviewer_headers"])
    )
    assert after["status"] == "REFUNDED", (
        f"denial must refund the PARTIALLY_PAID assessment, got {after['status']}"
    )
    assert after["outstanding_balance"] == pytest.approx(FIVE_UNIT_NET, abs=0.005), (
        "with its payments refunded, the outstanding balance returns to the "
        f"full net_total, got {after['outstanding_balance']}"
    )
    app = validate_success(
        api.get_application(ctx["application"]["id"], ctx["reviewer_headers"])
    )
    assert app["status"] == "DENIED"


def test_assessment_list_filtered_by_variant(api):
    """PRD 2.3: "assessments filter by `variant`, `status`, `application_id`,
    or `fee_schedule_id`" and "Filters combine with pagination rather than
    replacing it."
    PRD 3.6: "On `APPROVE` ... the system computes `final_fee_total` by running
    the impact-fee assessment a second time with variant `FINAL`".

    Design: Corner/endpoints/assessment_list_filtered_by_variant
    """
    ctx = setup_approved_application(project_overrides=FIVE_UNITS)
    app_id = ctx["application"]["id"]

    data, meta = validate_paginated(
        api.list_assessments(app_id, ctx["reviewer_headers"], params={"variant": "FINAL"})
    )
    assert len(data) >= 1, "an approved application must carry a FINAL assessment"
    for row in data:
        assert row["variant"] == "FINAL", (
            f"variant filter must exclude non-FINAL rows, got {row['variant']}"
        )
    assert_assessment(data[0])

    all_rows = list_application_assessments(app_id, ctx["reviewer_headers"])
    variants = {row["variant"] for row in all_rows}
    assert "PROVISIONAL" in variants and "FINAL" in variants, (
        f"unfiltered list must hold both variants, got {variants}"
    )
