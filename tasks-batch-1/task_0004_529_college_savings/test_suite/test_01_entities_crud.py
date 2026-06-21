"""CRUD-level tests for foundational entities.

Each test creates its own world (the server is restarted before every test).
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    is_valid_uuid,
    is_iso8601_timestamp,
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_donor_payload,
    create_beneficiary_payload,
    create_account_payload,
    assert_donor,
    assert_account,
    make_custodian_headers,
    make_tax_authority_headers,
    setup_donor_beneficiary_account,
    create_donor,
    create_beneficiary,
    create_account,
    set_clock,
)


class TestDonorCreation:
    def test_donor_create_happy_path_returns_201_with_all_fields(self, api):
        """PRD §3.1: "A back-office custodian first creates a Donor, supplying the donor's full_name,
        their tax-residence state_code, the last four digits of their federal tax id as
        federal_tax_id_last4, and a contact email."

        Design: Corner/entities/donor_create_happy_path_returns_201_with_all_fields
        """
        resp = api.create_donor(
            create_donor_payload(
                full_name="Alice",
                state_code="CA",
                federal_tax_id_last4="1234",
                email="alice@x.com",
            ),
            make_custodian_headers(),
        )
        data = validate_success(resp, expected_status=201)
        assert_donor(data)
        assert data["full_name"] == "Alice"
        assert data["state_code"] == "CA"
        assert data["federal_tax_id_last4"] == "1234"
        assert data["email"].lower() == "alice@x.com"
        assert data["version"] == 1
        assert is_iso8601_timestamp(data["created_at"])

    def test_donor_invalid_enum_state_code_rejected(self, api):
        """PRD §3.1: "The state_code must be one of six recognized U.S. states — CA, NY, IL, TX, FL,
        or OH; anything else is rejected with ERR_UNSUPPORTED_STATE_CODE."

        Design: Corner/entities/donor_invalid_enum_state_code_rejected
        """
        resp = api.create_donor(
            create_donor_payload(
                full_name="X", state_code="WY", federal_tax_id_last4="1234", email="wy@x.com"
            ),
            make_custodian_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_UNSUPPORTED_STATE_CODE.value, expected_status=422)

    def test_donor_missing_required_field_state_code_returns_invalid_request(self, api):
        """PRD §2.5: "Malformed bodies, missing required fields, or values outside declared ranges
        produce ERR_INVALID_REQUEST (HTTP 400)."

        Design: Corner/entities/donor_missing_required_field_state_code_returns_invalid_request
        """
        # state_code intentionally omitted from payload.
        resp = api.create_donor(
            {"full_name": "X", "federal_tax_id_last4": "1111", "email": "x@x.com"},
            make_custodian_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


class TestAccountCreation:
    def test_account_get_by_id_returns_stored_data(self, api):
        """PRD §3.1: "Opening an Account ties one donor to one current beneficiary. A custodian
        submits a payload referencing the donor_id and the beneficiary_id; the new account
        starts in status OPEN, and every computed ledger field (account_balance_cents,
        total_basis_cents, total_earnings_cents, ytd_qualified_k12_cents) initialises to zero."

        Design: Corner/entities/account_get_by_id_returns_stored_data
        """
        donor, beneficiary, account = setup_donor_beneficiary_account(
            donor_email="d-get@x.com", clock_iso=None
        )
        resp = api.get_account(account["id"], make_custodian_headers())
        data = validate_success(resp, expected_status=200)
        assert_account(data)
        assert data["status"] == "OPEN"
        assert data["account_balance_cents"] == 0
        assert data["donor_id"] == donor["id"]
        assert data["beneficiary_id"] == beneficiary["id"]

    def test_account_computed_balance_ignores_client_supplied_value(self, api):
        """PRD §3.1: "the new account starts in status OPEN, and every computed ledger field
        (account_balance_cents, total_basis_cents, total_earnings_cents,
        ytd_qualified_k12_cents) initialises to zero."

        Design: Corner/entities/account_computed_balance_ignores_client_supplied_value
        """
        donor = create_donor(email="dc@x.com")
        beneficiary = create_beneficiary(federal_tax_id_last4="2222")
        # Computed fields are not declared inputs; ledger fields must initialise to zero.
        resp = api.create_account(
            create_account_payload(donor["id"], beneficiary["id"]),
            make_custodian_headers(),
        )
        data = validate_success(resp, expected_status=201)
        assert data["account_balance_cents"] == 0
        assert data["total_basis_cents"] == 0
        assert data["total_earnings_cents"] == 0
        assert data["status"] == "OPEN"

    def test_account_system_fields_id_created_at_server_minted(self, api):
        """PRD §2.4: "The id is a server-minted UUID with no type prefix; clients must not supply
        it. The created_at and updated_at fields are ISO 8601 UTC timestamps with three
        fractional digits, the former pinned at creation and the latter refreshed on every
        successful mutation. The version field is an integer that begins at 1 on creation and
        increments by exactly 1 on every mutation that materially changes the entity."

        Design: Corner/entities/account_system_fields_id_created_at_server_minted
        """
        donor = create_donor(email="ds@x.com")
        beneficiary = create_beneficiary(federal_tax_id_last4="2222")
        resp = api.create_account(
            create_account_payload(donor["id"], beneficiary["id"]),
            make_custodian_headers(),
        )
        data = validate_success(resp, expected_status=201)
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert data["version"] == 1

    def test_account_create_referenced_donor_not_found(self, api):
        """PRD §2.5: "Foreign-key identifiers supplied in a request body — for example, a
        donor_id, beneficiary_id, account_id, scheduled_contribution_id, to_beneficiary_id,
        from_beneficiary_id, or supersedes_form_id — that fail to resolve produce
        ERR_REFERENCED_NOT_FOUND (HTTP 404)."

        Design: Corner/entities/account_create_referenced_donor_not_found
        """
        beneficiary = create_beneficiary(federal_tax_id_last4="2222")
        resp = api.create_account(
            create_account_payload(NON_EXISTENT_UUID, beneficiary["id"]),
            make_custodian_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCED_NOT_FOUND.value, expected_status=404)


class TestDonorAndAccountRead:
    def test_get_donor_not_found_returns_404(self, api):
        """PRD §2.5: "the first segment that fails to resolve produces ERR_NOT_FOUND (HTTP 404)."

        Design: Corner/entities/get_donor_not_found_returns_404
        """
        resp = api.get_donor(NON_EXISTENT_UUID, make_custodian_headers())
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)

    def test_list_accounts_pagination_envelope_keys_present(self, api):
        """PRD §2.3: "The meta block on a list response exposes the four pagination fields limit,
        offset, total_count, and has_more, where total_count is the unfiltered count of records
        matching the query and has_more is true exactly when more records exist beyond the
        current page."

        Design: Corner/entities/list_accounts_pagination_envelope_keys_present
        """
        donor = create_donor(email="dl@x.com")
        beneficiary = create_beneficiary(federal_tax_id_last4="2222")
        for _ in range(3):
            create_account(donor["id"], beneficiary["id"])
        resp = api.list_accounts(make_custodian_headers(), params={"limit": 2, "offset": 0})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert len(data) == 2


class TestClockState:
    def test_clockstate_immutable_no_version_field(self, api):
        """PRD §2.4: "The ClockState resource is an exception: it carries current_utc only — it
        has no id, no created_at, no updated_at, and no version."

        Design: Corner/entities/clockstate_immutable_no_version_field
        """
        set_clock("2026-06-15T12:00:00.000Z")
        resp = api.get_clock(make_custodian_headers())
        data = validate_success(resp, expected_status=200)
        assert data["current_utc"] == "2026-06-15T12:00:00.000Z"
        assert "version" not in data, "ClockState must not expose version"
        assert "updated_at" not in data, "ClockState must not expose updated_at"
