"""Account creation defaults, transaction seeding, dispute intake schema and
state rules, and account lookups."""
from test_helpers import (
    CLOCK,
    MISSING_UUID,
    ApiErrorId,
    create_card_account_payload,
    create_card_transaction_payload,
    create_dispute_payload,
    get_account,
    make_cardholder_headers,
    set_clock,
    setup_account_with_dispute,
    validate_error,
    validate_success,
)


class TestCardAccountCreation:
    def test_create_card_account_applies_defaults(self, api, bank_admin_headers):
        """PRD §3.1: "Opening an account requires the `cardholder_name` and accepts
        an optional `initial_balance_cents` that defaults to 0; the new account's
        `balance_cents` starts at that opening figure, its `status` starts at
        `ACTIVE`, and its `opened_at` is stamped with the logical clock time at
        creation."

        Design: Corner/entities/create_card_account_applies_defaults
        """
        set_clock("2026-05-01T00:00:00Z")
        resp = api.create_card_account({"cardholder_name": "Defaults"}, bank_admin_headers)
        data = validate_success(resp, expected_status=201)
        assert data["balance_cents"] == 0, (
            f"omitted initial_balance_cents must default to 0, got {data['balance_cents']}"
        )
        assert data["status"] == "ACTIVE"
        assert data["opened_at"] == "2026-05-01T00:00:00Z", (
            f"opened_at must equal the logical clock at creation, got {data['opened_at']}"
        )

    def test_get_card_account_not_found(self, api, bank_admin_headers):
        """PRD §2.8: "fourth, existence of every referenced resource
        (`ERR_NOT_FOUND`)".

        Design: Corner/entities/get_card_account_not_found
        """
        resp = api.get_card_account(MISSING_UUID, bank_admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_transaction_seeded_with_backdated_posted_at(
        self, api, bank_admin_headers
    ):
        """PRD §3.1: "A freshly seeded transaction is `POSTED`."
        PRD §3.1: "a client-supplied `posted_at` so historical transactions can be
        backdated."

        Design: Corner/entities/transaction_seeded_with_backdated_posted_at
        """
        account = validate_success(
            api.create_card_account(
                create_card_account_payload(
                    cardholder_name="Backdate", initial_balance_cents=50000
                ),
                bank_admin_headers,
            ),
            expected_status=201,
        )
        resp = api.create_card_transaction(
            create_card_transaction_payload(
                account["id"],
                merchant_name="BD",
                amount_cents=4321,
                transaction_type="ATM_WITHDRAWAL",
                network="MASTERCARD",
                posted_at="2026-07-01T10:00:00Z",
            ),
            bank_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["posted_at"] == "2026-07-01T10:00:00Z", (
            f"posted_at must echo the client-supplied value, got {data['posted_at']}"
        )
        assert data["status"] == "POSTED"


class TestDisputeIntake:
    def test_intake_with_unknown_field_returns_invalid_request(
        self, api, bank_admin_headers
    ):
        """PRD §2.8: "request-body schema — required fields present, enum members
        valid, integer amounts strictly greater than zero, unknown fields rejected
        (`ERR_INVALID_REQUEST`)".

        Design: Corner/entities/intake_with_unknown_field_returns_invalid_request
        """
        # Build account + transaction directly (no dispute yet).
        set_clock(CLOCK["ACCOUNT_OPEN"])
        account = validate_success(
            api.create_card_account(
                create_card_account_payload(
                    cardholder_name="Schema", initial_balance_cents=50000
                ),
                bank_admin_headers,
            ),
            expected_status=201,
        )
        txn = validate_success(
            api.create_card_transaction(
                create_card_transaction_payload(
                    account["id"], merchant_name="SC", amount_cents=5000
                ),
                bank_admin_headers,
            ),
            expected_status=201,
        )
        set_clock(CLOCK["DISPUTE_RECEIVED"])
        payload = create_dispute_payload(txn["id"], 5000)
        payload["received_at"] = "2026-01-01T00:00:00Z"  # system-computed smuggle
        resp = api.create_dispute(payload, make_cardholder_headers(account["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_intake_duplicate_dispute_beats_claim_exceeds(
        self, api, bank_admin_headers
    ):
        """PRD §3.2: "A transaction may carry at most one open dispute: if any
        earlier case for it still sits in `RECEIVED`, `CLASSIFIED`,
        `CHARGEBACK_FILED`, `REPRESENTMENT_REVIEW`, or `REVERSAL_PENDING`, intake
        is refused with `ERR_DUPLICATE_ACTIVE_DISPUTE`".
        PRD §2.8: "sixth, entity state preconditions for the requested transition
        (`ERR_INVALID_STATE`, with the more specific
        `ERR_DUPLICATE_ACTIVE_DISPUTE` and `ERR_ACCOUNT_RESTRICTED` where
        applicable)".
        PRD §2.8: "and eleventh, fiscal bounds — the
        claim-versus-transaction-amount bound and the
        recovery-versus-outstanding-loss bound".

        Design: Difficulty/priority_pair_validation_conflict/intake_duplicate_dispute_beats_claim_exceeds
        """
        account, txn, _case = setup_account_with_dispute(
            balance=50000, amount=9000, error_type="INCORRECT_AMOUNT",
            claim=5000, claimed_delay=5,
        )
        # Second intake on the DISPUTED transaction with a claim (99999) that
        # also exceeds the transaction amount (9000): the duplicate-dispute
        # state rule sits six tiers above the fiscal bound on the ladder.
        resp = api.create_dispute(
            create_dispute_payload(
                txn["id"], 99999,
                error_type="DUPLICATE_CHARGE", claimed_report_delay_days=5,
            ),
            make_cardholder_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_DISPUTE)

    def test_intake_duplicate_dispute_second_refused(
        self, api, bank_admin_headers
    ):
        """PRD §3.2: "A transaction may carry at most one open dispute: if any
        earlier case for it still sits in `RECEIVED`, `CLASSIFIED`,
        `CHARGEBACK_FILED`, `REPRESENTMENT_REVIEW`, or `REVERSAL_PENDING`, intake
        is refused with `ERR_DUPLICATE_ACTIVE_DISPUTE`".

        Design: Difficulty/priority_pair_validation_conflict/intake_duplicate_dispute_beats_claim_exceeds
        """
        account, txn, _case = setup_account_with_dispute(
            balance=50000, amount=9000, claim=5000, claimed_delay=5,
        )
        resp = api.create_dispute(
            create_dispute_payload(txn["id"], 5000, claimed_report_delay_days=5),
            make_cardholder_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_DISPUTE)

    def test_intake_requires_transaction_posted(self, api, bank_admin_headers):
        """PRD §3.2: "if the transaction is otherwise not `POSTED`, the refusal is
        `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/intake_requires_transaction_posted
        """
        account, txn, case = setup_account_with_dispute(
            balance=50000, amount=8000, claim=8000, claimed_delay=5,
        )
        # Withdraw the dispute: the transaction cascades DISPUTED -> SETTLED.
        resp = api.withdraw_dispute(case["id"], make_cardholder_headers(account["id"]))
        validate_success(resp)
        # A new intake against the SETTLED transaction must fail state.
        resp = api.create_dispute(
            create_dispute_payload(
                txn["id"], 8000,
                error_type="DUPLICATE_CHARGE", claimed_report_delay_days=5,
            ),
            make_cardholder_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_intake_on_settled_transaction_never_creates_case(
        self, api, bank_admin_headers
    ):
        """PRD §3.2: "if the transaction is otherwise not `POSTED`, the refusal is
        `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/intake_requires_transaction_posted
        """
        account, txn, case = setup_account_with_dispute(
            balance=50000, amount=8000, claim=8000, claimed_delay=5,
        )
        validate_success(
            api.withdraw_dispute(case["id"], make_cardholder_headers(account["id"]))
        )
        resp = api.create_dispute(
            create_dispute_payload(txn["id"], 8000, claimed_report_delay_days=5),
            make_cardholder_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        # The account must not have gained a second case.
        from test_helpers import validate_paginated
        data, meta = validate_paginated(
            api.list_disputes(
                make_cardholder_headers(account["id"]),
                params={"card_account_id": account["id"]},
            )
        )
        assert meta["total_count"] == 1, (
            f"settled-transaction intake must not create a case; found {meta['total_count']}"
        )
