"""Fee/filing corners: partial-then-paid accumulation, overpayment,
state-vs-fiscal priority, review requires PAID, writ fee exactness,
judgment report event gate (PRD 3.3, 3.7, 3.9, 2.7)."""
from test_helpers import (
    ApiErrorId,
    CLERK_A,
    create_rental_history_report_payload,
    create_writ_payload,
    finalize_judgment,
    get_case,
    make_landlord_headers,
    prepare_package,
    review_package,
    set_clock,
    setup_case_filed,
    setup_case_notice_expired,
    setup_judgment_entered,
    setup_judgment_final,
    validate_error,
    validate_success,
)
from test_helpers import api_client


class TestFeePaymentPartialThenPaid:
    """Corner instance: fee payments accumulate through PARTIAL to PAID."""

    def test_partial_then_paid(self, api):
        """PRD 3.3: "After each payment the fee_status is recomputed: UNPAID
        when nothing has been paid, PARTIAL while the cumulative total is
        short of the fee, and PAID once it equals the fee."

        Design: Corner/endpoints/fee_payment_partial_then_paid
        """
        ctx = setup_case_notice_expired("CA")
        ll = make_landlord_headers(ctx["landlord"]["id"])
        # CA, claim 100000, 1 defendant, no jury, paper: 24000+2500+750=27250.
        package = prepare_package(ctx, pay=False)
        assert package["filing_fee_cents"] == 27250
        assert package["fee_status"] == "UNPAID"

        first = validate_success(api.record_fee_payment(
            package["id"], {"amount_cents": 10000}, ll), 200)
        assert first["fee_status"] == "PARTIAL"
        assert first["fee_paid_cents"] == 10000

        second = validate_success(api.record_fee_payment(
            package["id"], {"amount_cents": 17250}, ll), 200)
        assert second["fee_status"] == "PAID"
        assert second["fee_paid_cents"] == 27250


class TestErrorFeeOverpaymentTrigger:
    """Corner instance: a payment above the frozen fee is rejected."""

    def test_overpayment_rejected(self, api):
        """PRD 3.3: "a payment that would push the cumulative total above the
        frozen filing_fee_cents is rejected with ERR_FEE_OVERPAYMENT
        (HTTP 422)."

        Design: Corner/errors/error_fee_overpayment_trigger
        """
        ctx = setup_case_notice_expired("CA")
        ll = make_landlord_headers(ctx["landlord"]["id"])
        package = prepare_package(ctx, pay=False)
        assert package["filing_fee_cents"] == 27250
        resp = api.record_fee_payment(package["id"], {"amount_cents": 27251}, ll)
        validate_error(resp, ApiErrorId.ERR_FEE_OVERPAYMENT, 422)


class TestFeePaymentOnAcceptedPackageStateWins:
    """Corner instance: state gate (rung 7) beats the fiscal overpayment
    rule (rung 12) on a fee payment against an ACCEPTED package."""

    def test_state_error_wins_on_accepted_package(self, api):
        """PRD 2.7: "the first failing rung determines the error returned";
        rung 7 "State admissibility — the target entity is in a status that
        permits the operation (... a DRAFT package ...); failure yields
        ERR_INVALID_STATE" precedes rung 12's fiscal rules ("fee
        overpayment").

        Design: Corner/validations/fee_payment_on_accepted_package_state_wins
        """
        ctx = setup_case_filed("CA")  # package fully paid and ACCEPTED
        ll = make_landlord_headers(ctx["landlord"]["id"])
        resp = api.record_fee_payment(
            ctx["package"]["id"], {"amount_cents": 999999}, ll)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


class TestReviewRequiresFeePaid:
    """Corner instance: review before PAID fails; after payment it
    succeeds."""

    def test_unpaid_review_rejected_then_accepted(self, api):
        """PRD 3.3: "reviewing one whose fee_status is not yet PAID is
        rejected with ERR_FEE_UNPAID (HTTP 422). An ACCEPT decision —
        available while the case is NOTICE_EXPIRED or FILING_REJECTED —
        marks the package ACCEPTED".

        Design: Corner/validations/review_requires_fee_paid
        """
        ctx = setup_case_notice_expired("CA")
        ll = make_landlord_headers(ctx["landlord"]["id"])
        package = prepare_package(ctx, pay=False)

        resp = api.review_filing_package(
            package["id"], {"decision": "ACCEPT"}, CLERK_A)
        validate_error(resp, ApiErrorId.ERR_FEE_UNPAID, 422)

        validate_success(api.record_fee_payment(
            package["id"], {"amount_cents": package["filing_fee_cents"]}, ll),
            200)
        reviewed = validate_success(api.review_filing_package(
            package["id"], {"decision": "ACCEPT"}, CLERK_A), 200)
        assert reviewed["status"] == "ACCEPTED"


class TestWritFeeExactMatch:
    """Corner instance: writ fee requires exact equality."""

    def test_one_cent_short_rejected(self, api):
        """PRD 3.7: "the writ_fee_paid_cents in the request must exactly
        equal the jurisdictional writ fee — 4000 cents in CA, 3500 in TX,
        2500 in OH — with any mismatch rejected as ERR_WRIT_FEE_MISMATCH
        (HTTP 422)."

        Design: Corner/validations/writ_fee_exact_match
        """
        ctx = setup_judgment_final("CA")
        ll = make_landlord_headers(ctx["landlord"]["id"])
        resp = api.request_writ(
            ctx["judgment"]["id"], {"writ_fee_paid_cents": 3999}, ll)
        validate_error(resp, ApiErrorId.ERR_WRIT_FEE_MISMATCH, 422)

        ok = api.request_writ(
            ctx["judgment"]["id"], {"writ_fee_paid_cents": 4000}, ll)
        assert validate_success(ok, 201)["status"] == "REQUESTED"


class TestJudgmentReportRequiresJudgmentEvent:
    """Corner instance: JUDGMENT report without a judgment fails."""

    def test_judgment_report_without_judgment_rejected(self, api):
        """PRD 3.9: "The trigger event must exist for the tenancy: a FILING
        report requires an ACCEPTED package on a case of the tenancy, a
        JUDGMENT report requires a judgment, and a SATISFACTION report
        requires a judgment in SATISFIED status; a missing trigger is
        rejected with ERR_REPORT_EVENT_MISSING (HTTP 422)."

        Design: Corner/validations/judgment_report_requires_judgment_event
        """
        ctx = setup_case_filed("CA")  # filed, but no judgment entered
        ll = make_landlord_headers(ctx["landlord"]["id"])
        resp = api.create_rental_history_report(
            ctx["tenancy"]["id"],
            create_rental_history_report_payload("JUDGMENT"),
            ll,
        )
        validate_error(resp, ApiErrorId.ERR_REPORT_EVENT_MISSING, 422)
