"""Fee settlement lifecycle — PRD §3.8."""
import pytest
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId, NON_EXISTENT_UUID,
    validate_success, validate_error,
    assert_fee_settlement,
    create_settlement_payload,
    setup_approved_application, setup_finalizable_application,
    create_pending_settlement, capture_settlement, create_and_capture_settlement,
    make_approver_headers, make_adopter_headers_for,
)


class TestSettlementCreate:
    def test_create_pending_settlement(self):
        """PRD §3.8: "POST /fee-settlements creates a PENDING row"."""
        ctx = setup_approved_application()
        payload = create_settlement_payload(
            subject_type="ADOPTION",
            subject_id=ctx["application"]["id"],
            amount=ctx["application"]["pinned_fee"],
        )
        resp = api_client.create_settlement(payload, TEST_USERS["finance_officer_headers"])
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "PENDING"
        assert_fee_settlement(data)

    def test_create_settlement_bad_subject_type(self):
        """PRD §2.7: enum validation via ERR_INVALID_REQUEST."""
        payload = create_settlement_payload(
            subject_type="INVENTED", subject_id="x", amount=100)
        resp = api_client.create_settlement(payload, TEST_USERS["finance_officer_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_create_settlement_bad_method(self):
        """PRD §3.8: method in {CARD, BANK_TRANSFER, CASH}."""
        ctx = setup_approved_application()
        payload = create_settlement_payload(
            subject_type="ADOPTION", subject_id=ctx["application"]["id"],
            amount=ctx["application"]["pinned_fee"], method="BITCOIN")
        resp = api_client.create_settlement(payload, TEST_USERS["finance_officer_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


class TestSettlementCapture:
    def test_capture_succeeds_with_correct_amount(self):
        """PRD §3.8: "amount exactly match the authoritative figure — pinned_fee for
        an adoption subject ... settlement moves to COMPLETED and its settled_at is stamped"."""
        ctx = setup_approved_application()
        settlement = create_pending_settlement(
            "ADOPTION", ctx["application"]["id"],
            ctx["application"]["pinned_fee"],
        )
        resp = api_client.capture_settlement(settlement["id"],
                                             TEST_USERS["finance_officer_headers"])
        data = validate_success(resp)
        assert data["status"] == "COMPLETED"
        assert data.get("settled_at") is not None

    def test_capture_amount_mismatch(self):
        """PRD §3.8: "exact equality with the pinned figure; any drift is rejected as
        ERR_AMOUNT_MISMATCH"."""
        ctx = setup_approved_application()
        settlement = create_pending_settlement(
            "ADOPTION", ctx["application"]["id"],
            ctx["application"]["pinned_fee"] + 1,   # off by one cent
        )
        resp = api_client.capture_settlement(settlement["id"],
                                             TEST_USERS["finance_officer_headers"])
        validate_error(resp, ApiErrorId.ERR_AMOUNT_MISMATCH.value)

    def test_duplicate_settlement_rejected(self):
        """PRD §3.8: "no other COMPLETED settlement already exists for the same
        (subject_type, subject_id) pair (else ERR_DUPLICATE_SETTLEMENT)"."""
        ctx = setup_approved_application()
        # First settlement captured
        create_and_capture_settlement(
            "ADOPTION", ctx["application"]["id"], ctx["application"]["pinned_fee"])
        # Second pending + capture should fail
        second = create_pending_settlement(
            "ADOPTION", ctx["application"]["id"], ctx["application"]["pinned_fee"])
        resp = api_client.capture_settlement(second["id"],
                                             TEST_USERS["finance_officer_headers"])
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SETTLEMENT.value)


class TestSettlementRefund:
    def test_refund_rejects_approved_adoption_and_releases_animal(self):
        """PRD §3.8: "if the underlying adoption is still in APPROVED, the refund
        cascade-rejects it with ERR_FEE_REFUNDED, releasing the held animal"."""
        ctx = setup_approved_application()
        settlement = create_and_capture_settlement(
            "ADOPTION", ctx["application"]["id"], ctx["application"]["pinned_fee"])
        resp = api_client.refund_settlement(settlement["id"],
                                            TEST_USERS["finance_officer_headers"])
        data = validate_success(resp)
        assert data["status"] == "REFUNDED"
        # Application should be REJECTED
        app_resp = api_client.get_application(
            ctx["application"]["id"], TEST_USERS["adoption_reviewer_headers"])
        app = validate_success(app_resp)
        assert app["status"] == "REJECTED"
        # Animal released
        a_resp = api_client.get_animal(ctx["shelter"]["id"], ctx["animal"]["id"],
                                       TEST_USERS["adopter_headers"])
        a = validate_success(a_resp)
        assert a["status"] == "AVAILABLE"

    def test_refund_from_finalized_rejected(self):
        """PRD §3.8: "refund is available from COMPLETED provided the subject is not
        already in a terminal FINALIZED/SETTLED state"."""
        ctx = setup_finalizable_application()
        # Finalize it
        api_client.finalize_application(
            ctx["application"]["id"], make_approver_headers("approver-01"))
        # Attempt refund
        resp = api_client.refund_settlement(ctx["settlement"]["id"],
                                            TEST_USERS["finance_officer_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestSettlementRead:
    def test_get_settlement_not_found(self):
        """PRD §2.5: ERR_SETTLEMENT_NOT_FOUND for missing settlement id."""
        resp = api_client.get_settlement(NON_EXISTENT_UUID,
                                         TEST_USERS["finance_officer_headers"])
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_NOT_FOUND.value)
