"""Corner section: validations — the standard "violation → error" pattern
exercised across the auth/auth/existence/business surface.
"""
from test_helpers import (
    validate_success,
    validate_error,
    setup_actors,
    setup_active_agreement,
    setup_under_contract_agreement,
    setup_ready_for_clear_to_close,
    create_purchase_agreement_payload,
    create_earnest_money_deposit_payload,
    create_ccr_review_payload,
    bootstrap_compliance_officer,
    register_user,
    make_title_agent_headers,
    NON_EXISTENT_UUID,
    build_user_headers,
    TEST_USERS,
)


class TestUnauthenticatedNoRoleHeader:
    def test_request_without_x_user_role_returns_401_err_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two headers. ``X-User-ID`` carries the caller's identifier. ``X-User-Role`` declares the caller's role and must be one of three exact strings: ``EscrowOfficer``, ``TitleAgent``, or ``ComplianceOfficer``. A request that omits ``X-User-Role``, or that supplies a value not in this set, is rejected with ``ERR_UNAUTHENTICATED`` (HTTP 401)."

        Design: Corner/validations/error_unauthenticated_missing_role
        """
        # Empty headers (no X-User-Role at all)
        res = api.create_purchase_agreement(
            create_purchase_agreement_payload(property_address="1 Auth St"),
            headers={},
        )
        validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


class TestForbiddenWrongRoleForEndpoint:
    def test_title_agent_cannot_create_purchase_agreement_returns_403_err_forbidden(self, api):
        """PRD §2.1: "A request whose role is recognised but not permitted on the called endpoint is rejected with ``ERR_FORBIDDEN`` (HTTP 403)."
        PRD §4: lists POST /purchase-agreements as restricted to EscrowOfficer.

        Design: Corner/validations/error_forbidden_title_agent_cannot_create_agreement
        """
        co_id, co_headers = bootstrap_compliance_officer()
        ta_id = register_user("TitleAgent", "Title Agent", co_headers)
        ta_headers = make_title_agent_headers(ta_id)
        res = api.create_purchase_agreement(
            create_purchase_agreement_payload(property_address="1 FB St"),
            ta_headers,
        )
        validate_error(res, "ERR_FORBIDDEN", expected_status=403)


class TestFkNotFoundOnEmd:
    def test_emd_with_nonexistent_escrow_account_returns_404_err_fk_not_found(self, api):
        """PRD §2.8: "Foreign-key fields appearing in a request body (for example, the ``agreement_id`` on a Closing Disclosure create, the ``escrow_account_id`` on an earnest money deposit, or the ``wire_instruction_id`` on a disbursement) are likewise resolved against their target type before any business check runs; a foreign key that does not resolve is rejected with ``ERR_FK_NOT_FOUND`` (HTTP 404)."

        Design: Corner/validations/error_fk_not_found_emd_with_bogus_escrow
        """
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        res = api.create_earnest_money_deposit(
            create_earnest_money_deposit_payload(
                escrow_account_id=NON_EXISTENT_UUID,
                amount_cents=1_000_000,
                depositor_role="BUYER",
            ),
            actors["eo"],
        )
        validate_error(res, "ERR_FK_NOT_FOUND", expected_status=404)


class TestInvalidAmountZeroDepositRejected:
    def test_deposit_with_amount_zero_returns_422_err_invalid_amount(self, api):
        """PRD §3.1: "Each deposit carries an ``escrow_account_id``, an ``amount_cents`` (which must be strictly greater than zero; a non-positive amount is rejected with ``ERR_INVALID_AMOUNT``)"

        Design: Corner/validations/error_invalid_amount_zero_deposit_rejected
        """
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        base = setup_active_agreement(actors=actors)
        res = api.create_earnest_money_deposit(
            create_earnest_money_deposit_payload(
                escrow_account_id=base["escrow"]["id"],
                amount_cents=0,
                depositor_role="BUYER",
            ),
            actors["eo"],
        )
        validate_error(res, "ERR_INVALID_AMOUNT", expected_status=422)


class TestCcrNotAcknowledgedBlocksClearToClose:
    def test_clear_to_close_with_unacknowledged_ccr_returns_409_err_ccr_not_acknowledged(self, api):
        """PRD §3.5: "A missing CD acknowledgement raises ``ERR_CD_NOT_ACKNOWLEDGED``; a missing CC&R acknowledgement raises ``ERR_CCR_NOT_ACKNOWLEDGED``; any unlocked wire raises ``ERR_WIRE_NOT_LOCKED``; the title gate failures surface as ``ERR_INVALID_STATE`` (because the agreement's ``UNDER_CONTRACT → CLEARED_TO_CLOSE`` precondition is not met)."

        Design: Corner/validations/error_ccr_not_acknowledged_blocks_clear_to_close
        """
        # Build the full stack but with the CCRReview buyer_acknowledged=false.
        ready = setup_ready_for_clear_to_close(
            ccr_buyer_acknowledged=False,
        )
        res = api.clear_to_close_purchase_agreement(
            ready["agreement_id"], ready["actors"]["co"]
        )
        validate_error(res, "ERR_CCR_NOT_ACKNOWLEDGED", expected_status=409)
