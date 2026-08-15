"""Authentication, role-based access control, cardholder ownership,
segregation of duties, and validation-ladder ordering."""
from test_helpers import (
    CLOCK,
    MISSING_UUID,
    ApiErrorId,
    create_card_account_payload,
    create_card_transaction_payload,
    create_dispute_payload,
    make_cardholder_headers,
    make_intake_agent_headers,
    make_investigator_headers,
    resolve_payload,
    set_clock,
    setup_account_with_dispute,
    setup_reversal_pending,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS, classify_case, create_transaction, file_dispute


class TestAuthentication:
    def test_missing_auth_headers_returns_400(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role the
        system does not recognize, is rejected with `ERR_MISSING_AUTH`
        (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_returns_400
        """
        resp = api.get_card_account(MISSING_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH)


class TestValidationOrdering:
    def test_intake_missing_required_field_returns_invalid_request(
        self, api, bank_admin_headers
    ):
        """PRD §2.8: "third, request-body schema — required fields present, enum
        members valid, integer amounts strictly greater than zero, unknown fields
        rejected (`ERR_INVALID_REQUEST`); fourth, existence of every referenced
        resource (`ERR_NOT_FOUND`)".

        Design: Corner/validations/intake_missing_required_field_returns_invalid_request
        """
        resp = api.create_dispute(
            {
                "card_transaction_id": MISSING_UUID,
                "error_type": "INCORRECT_AMOUNT",
                "claimed_report_delay_days": 5,
                # claim_amount_cents omitted -> schema violation at tier 3,
                # which masks the tier-4 existence failure.
            },
            make_cardholder_headers(MISSING_UUID),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestRbac:
    def test_finance_officer_cannot_file_chargeback(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted for
        the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST `/chargebacks` is authorized for ChargebackAnalyst only.

        Design: Corner/rbac/finance_officer_cannot_file_chargeback
        """
        _account, _txn, case = setup_account_with_dispute(
            balance=50000, amount=5000, error_type="SERVICE_NOT_RECEIVED",
            claim=5000, claimed_delay=10, classify=True, verified_delay=10,
        )
        resp = api.create_chargeback(
            {"dispute_case_id": case["id"], "reason_code": "V13_1"},
            TEST_USERS["finance_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_intake_agent_cannot_reverse_credit(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted for
        the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST `/provisional-credits/{id}/reverse` is authorized for
        FinanceOfficer only.

        Design: Corner/rbac/intake_agent_cannot_reverse_credit
        """
        _account, _txn, _case, credit = setup_reversal_pending(
            balance=50000, amount=5000, claim=5000, claimed_delay=5,
        )
        resp = api.reverse_provisional_credit(
            credit["id"], TEST_USERS["intake_agent_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestCardholderOwnership:
    def test_cardholder_dispute_other_account_forbidden(self, api):
        """PRD §2.1: "a cardholder may file a dispute only against a transaction
        whose account's `id` equals their `X-User-ID`".

        Design: Corner/validations/cardholder_dispute_other_account_forbidden
        """
        set_clock(CLOCK["ACCOUNT_OPEN"])
        account_a = validate_success(
            api.create_card_account(
                create_card_account_payload(
                    cardholder_name="A", initial_balance_cents=50000
                ),
                TEST_USERS["bank_admin_headers"],
            ),
            expected_status=201,
        )
        account_b = validate_success(
            api.create_card_account(
                create_card_account_payload(
                    cardholder_name="B", initial_balance_cents=50000
                ),
                TEST_USERS["bank_admin_headers"],
            ),
            expected_status=201,
        )
        txn_b = create_transaction(account_b["id"], amount=5000)
        set_clock(CLOCK["DISPUTE_RECEIVED"])
        resp = api.create_dispute(
            create_dispute_payload(txn_b["id"], 5000, claimed_report_delay_days=5),
            make_cardholder_headers(account_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestSegregationOfDuties:
    def _intake_filed_case(self, api):
        """Case filed BY IntakeAgent ops-ia-1, classified by another operator."""
        set_clock(CLOCK["ACCOUNT_OPEN"])
        account = validate_success(
            api.create_card_account(
                create_card_account_payload(
                    cardholder_name="SoD", initial_balance_cents=50000
                ),
                TEST_USERS["bank_admin_headers"],
            ),
            expected_status=201,
        )
        txn = create_transaction(account["id"], amount=5000)
        case = file_dispute(
            txn["id"], account["id"], 5000,
            error_type="INCORRECT_AMOUNT", claimed_delay=5,
            by_intake_agent="ops-ia-1",
        )
        classify_case(case["id"], is_fraud=False, verified_delay=5,
                      investigator_id="ops-inv-7")
        return account, txn, case

    def test_sod_violation_on_resolve(self, api):
        """PRD §2.10: "When a case was filed by an `IntakeAgent` — recorded as a
        non-null `intake_agent_id` — the `DisputeInvestigator` who resolves that
        case must present an `X-User-ID` different from the intake agent's. A
        resolution attempted by the same operator identity is rejected with
        `ERR_SOD_VIOLATION` (HTTP 403)."

        Design: Corner/validations/sod_violation_on_resolve
        """
        _account, _txn, case = self._intake_filed_case(api)
        resp = api.resolve_dispute(
            case["id"], resolve_payload(outcome="NO_ERROR"),
            make_investigator_headers("ops-ia-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

    def test_different_investigator_passes_sod(self, api):
        """PRD §2.10: "the `DisputeInvestigator` who resolves that case must
        present an `X-User-ID` different from the intake agent's."
        PRD §3.4: "If no credit is open, the case resolves directly to
        `RESOLVED_MERCHANT_FAVOR` with a `RESOLUTION_LETTER`, and the
        transaction settles."

        Design: Corner/validations/sod_violation_on_resolve
        """
        _account, _txn, case = self._intake_filed_case(api)
        resp = api.resolve_dispute(
            case["id"], resolve_payload(outcome="NO_ERROR"),
            make_investigator_headers("ops-inv-7"),
        )
        data = validate_success(resp)
        assert data["status"] == "RESOLVED_MERCHANT_FAVOR"


class TestResolvePriorityOverTemporalGate:
    def test_resolve_state_error_beats_window_expired(self, api):
        """PRD §2.8: "Requests are validated against a fixed priority ladder, and
        a failure at an earlier tier masks all later checks."
        PRD §2.8: "sixth, entity state preconditions for the requested transition
        (`ERR_INVALID_STATE`, with the more specific
        `ERR_DUPLICATE_ACTIVE_DISPUTE` and `ERR_ACCOUNT_RESTRICTED` where
        applicable)".
        PRD §2.8: "ninth, temporal compliance gates — the provisional credit
        requirement, the investigation window, the network filing deadline, and
        the reversal-notice cooling period".

        Design: Difficulty/priority_pair_validation_conflict/resolve_state_error_beats_window_expired
        """
        # Case resolved NO_ERROR on 2026-08-10 -> REVERSAL_PENDING; then the
        # clock moves past the 2026-09-17 investigation deadline.
        account, txn, case, credit = setup_reversal_pending(
            balance=50000, amount=9000, claim=9000, claimed_delay=5,
            resolve_clock="2026-08-10T09:00:00Z", after_clock=None,
        )
        set_clock("2026-09-20T09:00:00Z")
        resp = api.resolve_dispute(
            case["id"], resolve_payload(outcome="NO_ERROR"),
            TEST_USERS["investigator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_resolve_terminal_case_still_state_error_past_deadline(self, api):
        """PRD §2.8: "Requests are validated against a fixed priority ladder, and
        a failure at an earlier tier masks all later checks."
        PRD §2.8: "sixth, entity state preconditions for the requested transition
        (`ERR_INVALID_STATE`, with the more specific
        `ERR_DUPLICATE_ACTIVE_DISPUTE` and `ERR_ACCOUNT_RESTRICTED` where
        applicable)".
        PRD §2.8: "ninth, temporal compliance gates — the provisional credit
        requirement, the investigation window, the network filing deadline, and
        the reversal-notice cooling period".

        Design: Difficulty/priority_pair_validation_conflict/resolve_state_error_beats_window_expired
        """
        # Case fully resolved (RESOLVED_MERCHANT_FAVOR) long before the clock
        # passes the investigation deadline; a second resolve is attempted late.
        from test_helpers import setup_resolved_merchant_favor_no_credit
        account, txn, case = setup_resolved_merchant_favor_no_credit(
            balance=50000, amount=9000,
        )
        set_clock("2026-09-20T09:00:00Z")
        resp = api.resolve_dispute(
            case["id"], resolve_payload(outcome="NO_ERROR"),
            TEST_USERS["investigator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
