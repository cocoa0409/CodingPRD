"""Concurrency scenarios explicitly defined in PRD §3.9.

PRD §2.6 (OCC), §3.9 (five concurrency scenarios).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    assert_exactly_one_succeeds,
    create_application,
    create_enrollment_payload,
    create_insurer,
    create_plan,
    create_plan_variant,
    list_premium_invoices,
    make_applicant_headers,
    make_insurer_headers,
    patch_plan_payload,
    post_payment_payload,
    run_race,
    setup_approved_application,
    setup_benchmark_silver_catalog,
    setup_enrollment_pending_payment,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# Approve vs deny race (PRD §3.9 scenario 1)
# ===========================================================================
class TestApproveVsDenyRace:
    """PRD §3.9: "Two operators race to approve and deny the same
    application. Exactly one transition wins on Application.status
    first-writer-wins. The loser sees ERR_INVALID_STATE because the
    application has already left ELIGIBILITY_DETERMINED.\""""

    def test_approve_and_deny_concurrent(self, api):
        """PRD §3.9: "Exactly one transition wins on Application.status
        first-writer-wins. The loser sees ERR_INVALID_STATE."
        """
        # Build ELIGIBILITY_DETERMINED with at-least-one non-Medicaid
        # member so /approve is theoretically possible.
        from test_helpers import setup_eligibility_determined_application
        determined, _p, _i, _pl = (
            setup_eligibility_determined_application(
                primary_income_cents=5_000_000,
            )
        )
        admin = TEST_USERS["admin_headers"]
        admin_alt = TEST_USERS["admin_headers_alt"]
        results = run_race(
            lambda: api.approve_application(determined["id"], admin),
            lambda: api.deny_application(determined["id"], admin_alt),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # PRD names ERR_INVALID_STATE as the loser's error.
        loser_body = outcome["failures"][0].json()
        assert loser_body["data"]["error_id"] == "ERR_INVALID_STATE"


# ===========================================================================
# Duplicate enrollment race (PRD §3.9 scenario 2)
# ===========================================================================
class TestDuplicateEnrollmentRace:
    """PRD §3.9: "The applicant submits two enrollments under the same
    application and coverage year concurrently. A uniqueness
    constraint on the (application_id, coverage_year) pair admits
    exactly one writer. The loser is rejected with
    ERR_ENROLLMENT_ALREADY_EXISTS.\""""

    def test_two_concurrent_enrollments_one_succeeds(self, api):
        """PRD §3.9: "A uniqueness constraint on the (application_id,
        coverage_year) pair admits exactly one writer. The loser is
        rejected with ERR_ENROLLMENT_ALREADY_EXISTS."
        """
        approved, _p, ins, plan = setup_approved_application(
            primary_income_cents=5_000_000,
        )
        variant = create_plan_variant(
            plan=plan, csr_level="STANDARD", actuarial_value=70.0,
            insurer=ins,
        )
        applicant_h = make_applicant_headers(approved["_applicant_id"])
        payload = create_enrollment_payload(
            application_id=approved["id"],
            plan_variant_id=variant["id"],
        )
        results = run_race(
            lambda: api.create_enrollment(payload, applicant_h),
            lambda: api.create_enrollment(payload, applicant_h),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser_body = outcome["failures"][0].json()
        assert (
            loser_body["data"]["error_id"]
            == "ERR_ENROLLMENT_ALREADY_EXISTS"
        )


# ===========================================================================
# Invoice post-payment race (PRD §3.9 scenario 4)
# ===========================================================================
class TestPostPaymentRace:
    """PRD §3.9: "Two post-payment requests race on the same invoice.
    First-writer-wins on PremiumInvoice.status. Exactly one transitions
    ISSUED to PAID; the loser is rejected with ERR_INVOICE_ALREADY_PAID.\""""

    def test_two_post_payment_races(self, api):
        """PRD §3.9: "Exactly one transitions ISSUED to PAID; the loser
        is rejected with ERR_INVOICE_ALREADY_PAID."
        """
        app, _p, ins, plan, variant, enrollment = (
            setup_enrollment_pending_payment(
                primary_income_cents=5_000_000,
                base_monthly_premium_cents=20_000,
            )
        )
        invoices = list_premium_invoices(enrollment=enrollment)
        binder = sorted(invoices, key=lambda r: r["billing_month"])[0]
        payload = post_payment_payload(
            amount_cents=binder["net_amount_cents"],
        )
        applicant_h = make_applicant_headers(app["_applicant_id"])
        results = run_race(
            lambda: api.post_payment(binder["id"], payload, applicant_h),
            lambda: api.post_payment(binder["id"], payload, applicant_h),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser_body = outcome["failures"][0].json()
        assert (
            loser_body["data"]["error_id"]
            == "ERR_INVOICE_ALREADY_PAID"
        )


# ===========================================================================
# Plan PATCH OCC version (PRD §2.6, §3.9 scenario 3)
# ===========================================================================
class TestPlanPatchOcc:
    """PRD §2.6: "When the caller supplies version, the server compares
    it to the stored version of the resource; if they differ, the
    request is rejected with ERR_STALE_VERSION and no mutation is
    applied."

    PRD §3.9 scenario 3: when an insurer's plan-update request carries
    a stale version body, the patch itself loses and the loser sees
    ERR_STALE_VERSION.
    """

    def test_patch_plan_with_stale_version_returns_err_stale_version(
        self, api,
    ):
        """PRD §2.6: ERR_STALE_VERSION when supplied version != stored.
        """
        ins = create_insurer(filing_states=["CA"])
        plan = create_plan(
            insurer=ins, filing_state="CA", coverage_year=2026,
            tier="SILVER", base_monthly_premium_cents=40_000,
        )
        ins_headers = make_insurer_headers(ins["id"])
        # Bump version first.
        api.patch_plan(
            plan["id"],
            patch_plan_payload(
                base_monthly_premium_cents=42_000,
                version=plan["version"],
            ),
            ins_headers,
        )
        # Second update with the now-stale version.
        res = api.patch_plan(
            plan["id"],
            patch_plan_payload(
                base_monthly_premium_cents=45_000,
                version=plan["version"],
            ),
            ins_headers,
        )
        validate_error(res, "ERR_STALE_VERSION")
