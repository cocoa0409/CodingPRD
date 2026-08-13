"""Account opening defaults, request-shape validation, retrieval rules,
pagination, list filters, and the response envelope."""
from test_helpers import (
    AUDITOR,
    MANAGER,
    NON_EXISTENT_UUID,
    OFFICER,
    ApiErrorId,
    api_client,
    assert_account_transaction,
    assert_deposit_account,
    close_with_fresh_version,
    create_account_payload,
    open_account,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAccountCreationDefaults:

    def test_account_creation_defaults_and_system_fields(self):
        """PRD section 3.1: "Creation leaves the account in lifecycle `OPEN`
        with restriction `NONE`."
        PRD section 3.1: "The server mints a unique ten-digit
        `account_number`, posts the opening deposit as a customer-initiated
        `DEPOSIT` transaction, sets `balance_cents` to the opening amount,
        and anchors interest accrual by stamping `accrual_start_date` with
        the logical clock date; that same date seeds
        `last_customer_activity_date`."
        PRD section 3.1: "Derived fields start clean — `total_held_cents`
        and `accrued_interest_cents` at zero, `available_balance_cents`
        equal to the balance, `statement_suppression` at `NONE`,
        `dormant_since_date` null, `fees_assessed_count` at zero, and both
        `closure_payout_cents` and `closure_payout_destination` null — and
        the new account's `version` is 1."
        PRD section 2.5: "Before any explicit set, the clock reads exactly
        2026-08-01T00:00:00Z."

        Design: Corner/entities/account_creation_defaults_and_system_fields
        """
        resp = api_client.create_account(
            create_account_payload(primary_owner_name="New N",
                                   owner_tax_id="C1",
                                   opening_deposit_cents=25000),
            OFFICER,
        )
        assert resp.status_code == 201, (
            f"account creation must return 201, got {resp.status_code}: "
            f"{resp.text}"
        )
        acct = validate_success(resp, expected_status=201)
        assert_deposit_account(acct)
        assert acct["version"] == 1
        assert acct["lifecycle_status"] == "OPEN"
        assert acct["restriction_status"] == "NONE"
        assert acct["balance_cents"] == 25000
        assert acct["statement_suppression"] == "NONE"
        assert acct["total_held_cents"] == 0
        assert acct["available_balance_cents"] == 25000
        assert acct["dormant_since_date"] is None
        assert acct["fees_assessed_count"] == 0
        assert acct["closure_payout_cents"] is None
        assert acct["closure_payout_destination"] is None
        assert acct["accrual_start_date"] == "2026-08-01"
        assert acct["last_customer_activity_date"] == "2026-08-01"


class TestAccountShapeValidation:

    def test_account_create_pod_beneficiary_required(self):
        """PRD section 3.1: "When — and only when — the ownership type is
        `POD`, the request must also name a `pod_beneficiary_name`;
        omitting it for a POD account, supplying an unknown enum member, a
        non-positive amount, or a rate outside the bounds fails shape
        validation with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/account_create_pod_beneficiary_required
        """
        resp = api_client.create_account(
            create_account_payload(primary_owner_name="Pod P",
                                   owner_tax_id="C2",
                                   ownership_type="POD",
                                   opening_deposit_cents=1000),
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_account_create_missing_owner_name_rejected(self):
        """PRD section 3.1: "An `OpsOfficer` or `OpsManager` opens a deposit
        account by supplying the primary owner's legal name in
        `primary_owner_name` and tax identifier in `owner_tax_id`".
        PRD section 2.10: "Request shape — required fields are present,
        enum members are valid, amounts are positive, `pod_beneficiary_name`
        is present exactly when the ownership type in play is `POD`, a
        requested type differs from the current one, and `cycle_start`
        falls strictly before `cycle_end` (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/account_create_missing_owner_name_rejected
        """
        payload = create_account_payload(owner_tax_id="C3",
                                         opening_deposit_cents=1000)
        del payload["primary_owner_name"]
        resp = api_client.create_account(payload, OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_account_create_invalid_ownership_enum(self):
        """PRD section 3.1: "choosing an `ownership_type` of `INDIVIDUAL`,
        `JOINT`, `POD`, `TRUST`, or `BUSINESS`" — and "omitting it for a POD
        account, supplying an unknown enum member, a non-positive amount, or
        a rate outside the bounds fails shape validation with
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/account_create_invalid_ownership_enum
        """
        resp = api_client.create_account(
            create_account_payload(primary_owner_name="Enum E",
                                   owner_tax_id="C4",
                                   ownership_type="CORP",
                                   opening_deposit_cents=1000),
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestRetrievalExistence:

    def test_account_retrieval_not_found(self, ops_manager_headers):
        """PRD section 2.9: "The first identifier that fails to resolve to
        an existing resource rejects the request with `ERR_NOT_FOUND`
        (HTTP 404) before any later validation runs — a request against a
        garnishment collection of a non-existent account reports the
        missing account, not the missing order."

        Design: Corner/entities/account_retrieval_not_found
        """
        resp = api_client.get_account(NON_EXISTENT_UUID, ops_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_child_create_requires_existing_account(self):
        """PRD section 2.9: "Every child collection hangs directly off an
        account, and requests that address nested resources validate path
        identifiers in strict left-to-right order: the account `id` first,
        then the child identifier."

        Design: Corner/entities/child_create_requires_existing_account
        """
        resp = api_client.submit_document(
            NON_EXISTENT_UUID,
            {"doc_type": "SIGNATURE_CARD", "reference_number": "SC-X"},
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestTransactionAppendOnly:

    def test_transaction_append_only_no_version_field(self, auditor_headers):
        """PRD section 2.4: "A posted transaction carries only `id` and
        `created_at`; `updated_at` and `version` are absent, because a
        posted transaction never changes state, has no update endpoint, and
        cannot be deleted."
        PRD section 3.1: "The server mints a unique ten-digit
        `account_number`, posts the opening deposit as a customer-initiated
        `DEPOSIT` transaction, sets `balance_cents` to the opening amount".

        Design: Corner/entities/transaction_append_only_no_version_field
        """
        acct = open_account(opening_deposit_cents=7000,
                            primary_owner_name="Evt V", owner_tax_id="C5")
        data, _meta = validate_paginated(
            api_client.list_transactions(acct["id"], auditor_headers)
        )
        assert len(data) >= 1
        opening = data[0]
        assert_account_transaction(opening)
        assert opening["txn_type"] == "DEPOSIT"
        assert opening["balance_after_cents"] == 7000
        assert "version" not in opening
        assert "updated_at" not in opening


class TestAccountListing:

    def test_account_list_pagination_envelope(self, auditor_headers):
        """PRD section 2.3: "List endpoints paginate through two query
        parameters: `limit`, the maximum number of items returned, which
        defaults to 10 and accepts a minimum of 1 and a maximum of 100; and
        `offset`, the number of items skipped, which defaults to 0."
        PRD section 2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the response
        envelope."

        Design: Corner/endpoints/account_list_pagination_envelope
        """
        for i in range(1, 4):
            open_account(opening_deposit_cents=1000,
                         primary_owner_name=f"Pg {i}", owner_tax_id=f"P{i}")

        data, meta = validate_paginated(
            api_client.list_accounts(auditor_headers, params={"limit": 2})
        )
        assert len(data) == 2, f"limit=2 must return 2 items, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0

        data2, meta2 = validate_paginated(
            api_client.list_accounts(
                auditor_headers, params={"limit": 2, "offset": 2})
        )
        assert len(data2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_account_list_filter_by_status(self, auditor_headers):
        """PRD section 3.1: "Accounts can be listed with optional `status`
        and `ownership_type` filters."

        Design: Corner/endpoints/account_list_filter_by_status
        """
        acct_open = open_account(opening_deposit_cents=1000,
                                 primary_owner_name="Fl 1", owner_tax_id="F1")
        acct_closed = open_account(opening_deposit_cents=1000,
                                   primary_owner_name="Fl 2",
                                   owner_tax_id="F2")
        close_with_fresh_version(acct_closed["id"])

        data_open, _ = validate_paginated(
            api_client.list_accounts(auditor_headers,
                                     params={"status": "OPEN"})
        )
        open_ids = [a["id"] for a in data_open]
        assert acct_open["id"] in open_ids
        assert acct_closed["id"] not in open_ids

        data_closed, _ = validate_paginated(
            api_client.list_accounts(auditor_headers,
                                     params={"status": "CLOSED"})
        )
        closed_ids = [a["id"] for a in data_closed]
        assert acct_closed["id"] in closed_ids
        assert acct_open["id"] not in closed_ids


class TestResponseEnvelope:

    def test_response_envelope_shape_on_success_and_error(self,
                                                          auditor_headers):
        """PRD section 2.2: "The `response_type` is either "object" for a
        single resource or "array" for a list of resources."
        PRD section 2.2: "The `meta` object for error responses contains
        only `api_request_id` and `api_request_timestamp`."
        PRD section 2.2: "The `error_id` is a unique, machine-readable
        string that identifies the specific error."
        PRD section 2.2: "The `message` provides a human-readable
        explanation of what went wrong."

        Design: Corner/endpoints/response_envelope_shape_on_success_and_error
        """
        acct = open_account(opening_deposit_cents=1000,
                            primary_owner_name="Env E", owner_tax_id="E1")

        ok_resp = api_client.get_account(acct["id"], auditor_headers)
        assert ok_resp.status_code == 200
        ok_body = ok_resp.json()
        assert "api_request_id" in ok_body["meta"]
        assert "api_request_timestamp" in ok_body["meta"]
        assert ok_body["response_type"] == "object"

        err_resp = api_client.get_account(NON_EXISTENT_UUID, auditor_headers)
        assert 400 <= err_resp.status_code < 500
        err_body = err_resp.json()
        assert err_body["response_type"] == "error"
        assert "api_request_id" in err_body["meta"]
        assert "api_request_timestamp" in err_body["meta"]
        assert isinstance(err_body["data"]["error_id"], str)
        assert isinstance(err_body["data"]["message"], str)

        list_resp = api_client.list_accounts(auditor_headers)
        assert list_resp.status_code == 200
        assert list_resp.json()["response_type"] == "array"
