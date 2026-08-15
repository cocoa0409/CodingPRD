"""Documentation exception cure loop, cure deadline boundary, repurchase price,
and repurchase-case uniqueness (PRD §3.3, §3.6)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_pool, setup_pool_with_funded_cert, flag_exception, set_clock,
    make_originator_headers, make_buyer_headers, make_cuso_officer_headers,
)

ADMIN = TEST_USERS["network_admin_headers"]


class TestCureRejectResubmitLoop:
    def _setup_open_exception(self, api):
        """Funded ACTIVE certificate under an agreement with cure_period_days 30;
        buyer flags a MISSING_NOTE exception at the default clock."""
        ctx = setup_pool_with_funded_cert(
            agreement_overrides={"cure_period_days": 30})
        exc = flag_exception(ctx["certificate"]["id"], ctx["buyers"][0]["id"],
                             exception_type="MISSING_NOTE",
                             description="Note missing from transmittal")
        return ctx, exc

    def test_cure_reject_resubmit_loop_increments_attempts(self, api):
        """PRD §3.6: "An `OriginatorUser` owning the agreement behind the certificate (else `ERR_NOT_RESOURCE_OWNER`) submits cure documentation with `cure_notes`, moving the exception from `OPEN` — or from `REJECTED`, since a rejected cure may be reattempted — to `CURE_SUBMITTED`."
        PRD §3.6: "Each submission overwrites `cure_notes` with the latest notes and increments `cure_attempt_count` by one."
        PRD §3.6: "A `BuyerUser` equal to the certificate's `buyer_id` (else `ERR_NOT_RESOURCE_OWNER`) then verifies: passing `accept` as true moves the exception from `CURE_SUBMITTED` to `CURED`, while passing false moves it to `REJECTED`, from which the originator may try again until the deadline."

        Design: Difficulty/non_linear_state_machine/documentation_exception_cure_reject_resubmit_loop
        """
        ctx, exc = self._setup_open_exception(api)
        originator, buyer = ctx["originator"], ctx["buyers"][0]

        s1 = validate_success(api.submit_cure(exc["id"], {"cure_notes": "Cure attempt 1"},
                                              make_originator_headers(originator["id"])), 200)
        assert s1["status"] == "CURE_SUBMITTED"
        s2 = validate_success(api.verify_cure(exc["id"], {"accept": False},
                                              make_buyer_headers(buyer["id"])), 200)
        assert s2["status"] == "REJECTED"
        s3 = validate_success(api.submit_cure(exc["id"], {"cure_notes": "Cure attempt 2"},
                                              make_originator_headers(originator["id"])), 200)
        assert s3["status"] == "CURE_SUBMITTED"
        assert s3["cure_attempt_count"] == 2
        assert s3["cure_notes"] == "Cure attempt 2"

    def test_final_cure_returns_certificate_to_active(self, api):
        """PRD §3.6: "A `BuyerUser` equal to the certificate's `buyer_id` (else `ERR_NOT_RESOURCE_OWNER`) then verifies: passing `accept` as true moves the exception from `CURE_SUBMITTED` to `CURED`, while passing false moves it to `REJECTED`, from which the originator may try again until the deadline."
        PRD §3.6: "When an exception is cured and no other exception of the certificate remains in `OPEN`, `CURE_SUBMITTED`, `REJECTED`, or `ESCALATED`, and no repurchase case of the certificate is in `TRIGGERED` or `DISPUTED`, the certificate returns from `EXCEPTION` to `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/documentation_exception_cure_reject_resubmit_loop
        """
        ctx, exc = self._setup_open_exception(api)
        originator, buyer = ctx["originator"], ctx["buyers"][0]
        cert_id = ctx["certificate"]["id"]

        cert_after_flag = validate_success(api.get_commitment(cert_id, ADMIN), 200)
        assert cert_after_flag["status"] == "EXCEPTION"

        api.submit_cure(exc["id"], {"cure_notes": "v1"},
                        make_originator_headers(originator["id"]))
        api.verify_cure(exc["id"], {"accept": False}, make_buyer_headers(buyer["id"]))
        api.submit_cure(exc["id"], {"cure_notes": "v2"},
                        make_originator_headers(originator["id"]))
        s4 = validate_success(api.verify_cure(exc["id"], {"accept": True},
                                              make_buyer_headers(buyer["id"])), 200)
        assert s4["status"] == "CURED"
        cert_after = validate_success(api.get_commitment(cert_id, ADMIN), 200)
        assert cert_after["status"] == "ACTIVE"


class TestCureDeadlineInclusiveBoundary:
    def _setup_two_exceptions(self, api):
        """Funded certificate (cure_period_days 30); two exceptions created at the
        default clock 2026-08-01T00:00:00Z, so cure_deadline is 2026-08-31T00:00:00Z."""
        ctx = setup_pool_with_funded_cert(
            agreement_overrides={"cure_period_days": 30})
        buyer = ctx["buyers"][0]
        e1 = flag_exception(ctx["certificate"]["id"], buyer["id"],
                            exception_type="MISSING_NOTE", description="E1")
        e2 = flag_exception(ctx["certificate"]["id"], buyer["id"],
                            exception_type="STALE_APPRAISAL", description="E2")
        return ctx, e1, e2

    def test_submit_at_exact_deadline_succeeds(self, api):
        """PRD §3.6: "Submission must arrive at or before the `cure_deadline`; the deadline is inclusive, and a submission after it is rejected with `ERR_CURE_PERIOD_EXPIRED`."
        PRD §3.6: "The exception is born `OPEN` with `detected_at` stamped from the clock, a `cure_deadline` computed as `detected_at` plus the servicing agreement's `cure_period_days` calendar days, `cure_notes` unset, and `cure_attempt_count` at zero."

        Design: Difficulty/boundary_precision_check/cure_deadline_inclusive_boundary
        """
        ctx, e1, _ = self._setup_two_exceptions(api)
        # detected 2026-08-01T00:00:00Z + 30 calendar days -> 2026-08-31T00:00:00Z
        assert e1["cure_deadline"].startswith("2026-08-31T00:00:00")
        set_clock("2026-08-31T00:00:00Z")
        res = api.submit_cure(e1["id"], {"cure_notes": "At the deadline"},
                              make_originator_headers(ctx["originator"]["id"]))
        submitted = validate_success(res, 200)
        assert submitted["status"] == "CURE_SUBMITTED"

    def test_submit_one_second_past_deadline_rejected(self, api):
        """PRD §3.6: "Submission must arrive at or before the `cure_deadline`; the deadline is inclusive, and a submission after it is rejected with `ERR_CURE_PERIOD_EXPIRED`."

        Design: Difficulty/boundary_precision_check/cure_deadline_inclusive_boundary
        """
        ctx, _, e2 = self._setup_two_exceptions(api)
        set_clock("2026-08-31T00:00:01Z")
        res = api.submit_cure(e2["id"], {"cure_notes": "One second late"},
                              make_originator_headers(ctx["originator"]["id"]))
        validate_error(res, ApiErrorId.ERR_CURE_PERIOD_EXPIRED)


class TestRepurchasePriceAndUniqueness:
    def test_repurchase_price_stamped_on_complete(self, api):
        """PRD §3.6: "The repurchase price is the certificate's `outstanding_principal_cents` plus the accrued-but-unpaid interest: accrual runs from the day after the certificate's most recent remittance `period_end` — or from the funded date when no remittances exist — through the completion date, inclusive, using the agreement's day-count convention and the offering's yield, rounded half up to whole cents."
        PRD §3.6: "Completion simultaneously moves the certificate to `REPURCHASED`, zeroes its `outstanding_principal_cents`, and recomputes the offering's `committed_principal_cents` and the buyer's `total_committed_principal_cents`, which thereafter exclude the repurchased position."

        Design: Corner/calculations/repurchase_price_stamped_on_complete
        """
        ctx = setup_pool()
        originator, buyer = ctx["originator"], ctx["buyers"][0]
        offering = ctx["offering"]
        from test_helpers import commit, approve_diligence
        cert = commit(offering["id"], buyer["id"], 10_000_000)
        approve_diligence(cert["id"], buyer["id"])
        set_clock("2026-08-15T00:00:00Z")
        validate_success(api.fund_commitment(cert["id"], make_buyer_headers(buyer["id"])), 200)

        case = validate_success(api.create_repurchase_case(
            {"certificate_id": cert["id"], "trigger_reason": "MATERIAL_BREACH"},
            make_buyer_headers(buyer["id"])), 201)
        set_clock("2026-08-31T00:00:00Z")
        completed = validate_success(api.complete_repurchase_case(
            case["id"], make_originator_headers(originator["id"])), 200)
        # Funded 2026-08-15, no remittances; THIRTY_360 window 2026-08-15..2026-08-31
        # inclusive = 17 days: 10,000,000 + round_half_up(10,000,000 x 0.06 x 17/360)
        # = 10,000,000 + 28,333 = 10,028,333.
        assert completed["repurchase_price_cents"] == 10_028_333
        assert completed["status"] == "COMPLETED"

        cert_after = validate_success(api.get_commitment(cert["id"], ADMIN), 200)
        assert cert_after["status"] == "REPURCHASED"
        assert cert_after["outstanding_principal_cents"] == 0
        offering_after = validate_success(api.get_offering(offering["id"], ADMIN), 200)
        assert offering_after["committed_principal_cents"] == 0
        buyer_after = validate_success(api.get_credit_union(buyer["id"], ADMIN), 200)
        assert buyer_after["total_committed_principal_cents"] == 0

    def test_duplicate_repurchase_case_rejected(self, api):
        """PRD §3.6: "The certificate must be `ACTIVE` or `EXCEPTION`, and at most one open case — `TRIGGERED` or `DISPUTED` — may exist per certificate, else the creation is rejected with `ERR_DUPLICATE_REPURCHASE_CASE`."

        Design: Corner/errors/duplicate_repurchase_case_rejected
        """
        ctx = setup_pool_with_funded_cert()
        buyer = ctx["buyers"][0]
        cert_id = ctx["certificate"]["id"]
        validate_success(api.create_repurchase_case(
            {"certificate_id": cert_id, "trigger_reason": "MATERIAL_BREACH"},
            make_buyer_headers(buyer["id"])), 201)
        res = api.create_repurchase_case(
            {"certificate_id": cert_id, "trigger_reason": "FRAUD"},
            make_buyer_headers(buyer["id"]))
        validate_error(res, ApiErrorId.ERR_DUPLICATE_REPURCHASE_CASE)


class TestAgreementTerminationGate:
    def test_terminate_agreement_with_open_certificates_rejected(self, api):
        """PRD §3.3: "Termination is permitted from `DRAFT` unconditionally, and from `ACTIVE` or `DELINQUENT` only when no certificate under the agreement's offerings remains in `PENDING_DILIGENCE`, `COMMITTED`, `ACTIVE`, or `EXCEPTION` — otherwise the termination is rejected with `ERR_AGREEMENT_HAS_OPEN_CERTIFICATES`."

        Design: Corner/errors/terminate_agreement_with_open_certificates_rejected
        """
        ctx = setup_pool_with_funded_cert()
        agreement_id = ctx["agreement"]["id"]
        res = api.terminate_servicing_agreement(
            agreement_id, make_cuso_officer_headers(ctx["cuso"]["id"]))
        validate_error(res, ApiErrorId.ERR_AGREEMENT_HAS_OPEN_CERTIFICATES)
        after = validate_success(api.get_servicing_agreement(agreement_id, ADMIN), 200)
        assert after["status"] == "ACTIVE"
