"""Payee onboarding, verification SoD, suspend/re-verify cascade, expiry sweep."""
from test_helpers import (
    DP1,
    EA1,
    PV1,
    PV2,
    ApiErrorId,
    assert_payee,
    create_payee_payload,
    get_success_data,
    make_payee_verifier_headers,
    set_clock,
    setup_account_with_scheduled_disbursement,
    validate_success,
    validate_error,
)


class TestPayeeCreation:
    def test_payee_born_pending_with_sod_anchor(self, api):
        """PRD: "The payee is born `PENDING_VERIFICATION` with
        `created_by_user_id` anchored to the creator's `X-User-ID`,
        `verified_by_user_id` and `verified_at` null, and
        `verification_expires_at` null."

        Design: Corner/entities/payee_created_pending_with_sod_anchor
        """
        resp = api.create_payee(create_payee_payload(), DP1)
        payee = validate_success(resp, 201)
        assert_payee(payee)
        assert payee["verification_status"] == "PENDING_VERIFICATION"
        assert payee["created_by_user_id"] == "dp_1", (
            "created_by_user_id anchors the creator's X-User-ID")
        assert payee["verified_by_user_id"] is None
        assert payee["verified_at"] is None
        assert payee["verification_expires_at"] is None


class TestPayeeVerificationSoD:
    def test_self_verification_rejected_independent_verifier_succeeds(self, api):
        """PRD: "the verifier's `X-User-ID` must differ from
        `created_by_user_id`, and a self-verification attempt is rejected with
        `ERR_SOD_VIOLATION` (HTTP 409)."
        PRD: "A successful verify moves `PENDING_VERIFICATION` → `VERIFIED`,
        stamps `verified_by_user_id` and `verified_at`"

        Design: Corner/rbac/sod_payee_self_verify_rejected
        """
        payee = get_success_data(api.create_payee(create_payee_payload(), DP1))

        # dp_1 wears the verifier hat but is the recorded creator: SoD breach.
        resp = api.verify_payee(payee["id"], make_payee_verifier_headers("dp_1"))
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

        verified = validate_success(api.verify_payee(payee["id"], PV1), 200)
        assert verified["verification_status"] == "VERIFIED"
        assert verified["verified_by_user_id"] == "pv_1"
        assert verified["verified_at"] is not None


class TestPayeeSuspendReverifyCascade:
    def test_suspend_blocks_and_reverify_restores_disbursements(self, api):
        """PRD: "Both moves carry the same conditional cascade: every
        disbursement paying this payee that is currently `SCHEDULED` flips to
        `BLOCKED`."
        PRD: "it refreshes `verified_at` and `verification_expires_at`, and
        every disbursement of this payee sitting in `BLOCKED` returns to
        `SCHEDULED`"

        Design: Corner/state_machines/payee_suspend_blocks_and_reverify_restores
        """
        ctx, disb = setup_account_with_scheduled_disbursement(
            loan_number="LN-SM-5", deposit_amount=100_000,
            due_date="2026-12-20", scheduled_release_date="2026-12-01")
        payee_id = ctx["payee"]["id"]

        suspended = validate_success(api.suspend_payee(payee_id, PV2), 200)
        assert suspended["verification_status"] == "SUSPENDED"
        disb_blocked = validate_success(api.get_disbursement(disb["id"], EA1), 200)
        assert disb_blocked["status"] == "BLOCKED", (
            "suspend cascades the SCHEDULED disbursement to BLOCKED")

        reverified = validate_success(api.verify_payee(payee_id, PV1), 200)
        assert reverified["verification_status"] == "VERIFIED"
        disb_restored = validate_success(api.get_disbursement(disb["id"], EA1), 200)
        assert disb_restored["status"] == "SCHEDULED", (
            "re-verification returns the BLOCKED disbursement to SCHEDULED")


class TestPayeeExpirySweep:
    def test_payee_expires_only_strictly_after_expiry_date(self, api):
        """PRD: "A successful verify moves `PENDING_VERIFICATION` → `VERIFIED`,
        stamps `verified_by_user_id` and `verified_at`, and sets
        `verification_expires_at` to the calendar date exactly 365 days after
        the verification date."
        PRD: "A payee in `VERIFIED` flips to `EXPIRED` when the current date is
        strictly after its `verification_expires_at`, and every disbursement
        paying that payee that is sitting in `SCHEDULED` is cascaded to
        `BLOCKED`."

        Design: Corner/cross_cutting_layers/payee_expiry_boundary_sweep
        """
        # Payee verified at the default clock 2026-08-01 -> expires 2027-08-01.
        ctx, disb = setup_account_with_scheduled_disbursement(
            loan_number="LN-SWP-1", deposit_amount=100_000,
            due_date="2027-09-20", scheduled_release_date="2027-09-01")
        payee_id = ctx["payee"]["id"]

        set_clock("2027-08-01T00:00:00Z")
        payee = validate_success(api.get_payee(payee_id, EA1), 200)
        assert payee["verification_status"] == "VERIFIED", (
            "at exactly the expiry date the payee is still VERIFIED "
            "(strictly-after rule)")
        assert payee["verification_expires_at"] == "2027-08-01"

        set_clock("2027-08-02T00:00:00Z")
        payee = validate_success(api.get_payee(payee_id, EA1), 200)
        assert payee["verification_status"] == "EXPIRED"
        disb_after = validate_success(api.get_disbursement(disb["id"], EA1), 200)
        assert disb_after["status"] == "BLOCKED", (
            "expiry cascades the payee's SCHEDULED disbursement to BLOCKED")
