"""Response envelope shape, list pagination, borrower/loan boarding rules,
parent-child retrieval, and freshly created entities' initial states."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_borrower,
    assert_disbursement_request,
    assert_estoppel,
    assert_inspection,
    assert_lease,
    assert_loan,
    assert_reserve_invariants,
    create_borrower_payload,
    create_disbursement_payload,
    create_lease_payload,
    create_loan_payload,
    create_property_payload,
    create_reserve_account_payload,
    create_statement_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_borrower_headers,
    schedule_inspection_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

MS = TEST_USERS["master_servicer_headers"]


class TestResponseEnvelope:
    def test_response_envelope_success_and_error_shapes(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`." and "The `response_type` is either
        "object" for a single resource or "array" for a list of resources."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error." and "The `message` provides a human-readable
        explanation of what went wrong."

        Design: Corner/endpoints/response_envelope_success_and_error_shapes
        """
        resp = api.create_borrower(
            create_borrower_payload(legal_name="Env Co", tax_id="TX-ENV",
                                    contact_email="env@x.com"), MS)
        data = validate_success(resp, 201)
        body = resp.json()
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert is_valid_uuid(data["id"])

        err_resp = api.get_loan(NON_EXISTENT_UUID, MS)
        err_body = err_resp.json()
        assert err_body["response_type"] == "error"
        validate_error(err_resp, ApiErrorId.ERR_NOT_FOUND)


class TestBorrowerAndLoanBoarding:
    def test_borrower_create_missing_required_tax_id(self, api):
        """PRD §3.1: "A `MasterServicer` onboards a borrowing entity with its
        `legal_name`, `tax_id`, and `contact_email`; the tax identifier must be
        unique across borrowers."
        PRD §2.10: "Request schema: required fields present, types valid, enum
        members valid, ranges valid (amounts strictly positive where required,
        fractions between 0 and 1, ends not before starts, non-empty line items)
        — else `ERR_INVALID_REQUEST`."

        Design: Corner/entities/borrower_create_missing_required_tax_id
        """
        payload = {"legal_name": "No Tax Co", "contact_email": "ntc@x.com"}
        resp = api.create_borrower(payload, MS)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_loan_create_defaults_current_balance_to_principal(self, api):
        """PRD §3.1: "An optional `current_balance_cents` — never negative —
        defaults to the original principal when omitted."
        PRD §3.1: "At boarding the loan's `payment_status` starts `CURRENT`, its
        `servicing_status` starts `PERFORMING`, and `capitalized_advances_cents`
        starts at zero."

        Design: Corner/entities/loan_create_defaults_current_balance_to_principal
        """
        borrower = get_success_data(api.create_borrower(
            create_borrower_payload(legal_name="Default Co", tax_id="TX-DEF",
                                    contact_email="def@x.com"), MS))
        payload = create_loan_payload(
            borrower["id"], loan_number="LN-DEF",
            original_principal_cents=750_000_000, note_rate=0.05)
        loan = validate_success(api.create_loan(payload, MS), 201)
        assert_loan(loan)
        assert loan["current_balance_cents"] == 750_000_000, (
            "current_balance_cents defaults to the original principal")
        assert loan["payment_status"] == "CURRENT"
        assert loan["servicing_status"] == "PERFORMING"
        assert loan["capitalized_advances_cents"] == 0

    def test_loan_create_system_fields_input_ignored(self, api):
        """PRD §3.1: "At boarding the loan's `payment_status` starts `CURRENT`,
        its `servicing_status` starts `PERFORMING`, and `capitalized_advances_cents`
        starts at zero."
        PRD §3.1: "Until the first covenant calculation of each type runs,
        `current_dscr` and `current_ltv` remain null."

        Design: Corner/entities/loan_create_system_fields_input_ignored
        """
        borrower = get_success_data(api.create_borrower(
            create_borrower_payload(legal_name="Smuggle Co", tax_id="TX-SMG",
                                    contact_email="smg@x.com"), MS))
        payload = create_loan_payload(
            borrower["id"], loan_number="LN-SMG",
            original_principal_cents=100_000_000, note_rate=0.05,
            payment_status="DEFAULT", servicing_status="SPECIAL_SERVICING",
            current_dscr=9.9999)
        loan = validate_success(api.create_loan(payload, MS), 201)
        assert loan["payment_status"] == "CURRENT", (
            "A smuggled payment_status is not honored at boarding")
        assert loan["servicing_status"] == "PERFORMING", (
            "A smuggled servicing_status is not honored at boarding")
        assert loan["current_dscr"] is None
        assert loan["current_ltv"] is None

    def test_loan_get_not_found_returns_404(self, api):
        """PRD §2.7: "Paths that nest identifiers are validated left to right —
        loan before child, child before grandchild — and the first identifier that
        does not resolve to an existing resource yields `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/loan_get_not_found_returns_404
        """
        resp = api.get_loan(NON_EXISTENT_UUID, MS)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_property_create_unknown_loan_returns_404(self, api):
        """PRD §2.7: "Paths that nest identifiers are validated left to right —
        loan before child, child before grandchild — and the first identifier that
        does not resolve to an existing resource yields `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/property_create_unknown_loan_returns_404
        """
        resp = api.create_property(
            NON_EXISTENT_UUID,
            create_property_payload(address="1 Nowhere",
                                    appraised_value_cents=1_000_000_000),
            MS)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_loan_create_invalid_enum_returns_400(self, api):
        """PRD §2.10: "Request schema: required fields present, types valid, enum
        members valid, ranges valid (amounts strictly positive where required,
        fractions between 0 and 1, ends not before starts, non-empty line items)
        — else `ERR_INVALID_REQUEST`."
        PRD §3.1: "the `dscr_basis` — `TTM` or `T3_ANNUALIZED` — selects which
        coverage variant the loan is tested under"

        Design: Corner/entities/loan_create_invalid_enum_returns_400
        """
        borrower = get_success_data(api.create_borrower(
            create_borrower_payload(legal_name="Enum Co", tax_id="TX-ENU",
                                    contact_email="enu@x.com"), MS))
        payload = create_loan_payload(
            borrower["id"], loan_number="LN-ENU",
            original_principal_cents=100_000_000, note_rate=0.05,
            dscr_basis="WEEKLY")
        resp = api.create_loan(payload, MS)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestLoanListingPagination:
    def test_loans_list_pagination_envelope(self, api):
        """PRD §2.3: "`limit` bounds the page size: it defaults to 10, accepts a
        minimum of 1 and a maximum of 100, and `offset` skips that many records
        from the start of the ordered result, defaulting to 0."
        PRD §2.3: "The `meta` object of every list response carries `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/loans_list_pagination_envelope
        """
        borrower = get_success_data(api.create_borrower(
            create_borrower_payload(legal_name="Pager Co", tax_id="TX-PAG",
                                    contact_email="pag@x.com"), MS))
        for number in ("LN-P1", "LN-P2", "LN-P3"):
            get_success_data(api.create_loan(
                create_loan_payload(borrower["id"], loan_number=number,
                                    original_principal_cents=100_000_000,
                                    note_rate=0.05), MS))

        page1, meta1 = validate_paginated(
            api.list_loans(MS, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2 and meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_loans(MS, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        assert meta2["offset"] == 2

        numbers = {row["loan_number"] for row in page1 + page2}
        assert numbers == {"LN-P1", "LN-P2", "LN-P3"}


class TestInitialStates:
    def test_created_entities_start_in_initial_states(self, api):
        """PRD §3.4: "The lease opens in `DRAFT` status"
        PRD §3.4: "the new certificate is filed under its parent through the
        payload's `lease_id` and opens `PENDING`."
        PRD §3.3: "the request opens in `SUBMITTED` status with `funded_cents`
        and `retained_cents` at zero and `funded_at` null until funding occurs"
        PRD §3.2: "Statements arrive in `SUBMITTED` status"
        PRD §3.3: "A new account starts with `balance_cents`, `held_cents`, and
        `retained_cents` all at zero."
        PRD §3.3: "Two posture flags ride along: `elevated_retainage`, true while
        the loan's servicing posture is anything other than `PERFORMING`, and
        `disbursement_frozen`, true while the loan stands in `SPECIAL_SERVICING`."
        PRD §3.3: "The request's `amount_cents` is derived as the sum of its line
        items"

        Design: Corner/state_machines/created_entities_start_in_initial_states
        """
        borrower = get_success_data(api.create_borrower(
            create_borrower_payload(legal_name="Init Co", tax_id="TX-INI",
                                    contact_email="ini@x.com"), MS))
        bh = make_borrower_headers(borrower["id"])
        loan = get_success_data(api.create_loan(
            create_loan_payload(borrower["id"], loan_number="LN-INI",
                                original_principal_cents=100_000_000,
                                note_rate=0.05), MS))
        prop = get_success_data(api.create_property(
            loan["id"], create_property_payload(address="1 Init St"), MS))
        reserve = get_success_data(api.create_reserve_account(
            loan["id"], create_reserve_account_payload(), MS))
        assert_reserve_invariants(reserve)
        assert reserve["balance_cents"] == 0
        assert reserve["held_cents"] == 0
        assert reserve["retained_cents"] == 0
        assert reserve["available_cents"] == 0
        assert reserve["elevated_retainage"] is False
        assert reserve["disbursement_frozen"] is False

        inspector = get_success_data(api.create_inspector(
            {"full_name": "Init Spect", "license_no": "LIC-INI"}, MS))

        lease = get_success_data(api.create_lease(
            prop["id"], create_lease_payload(suite_ref="STE-9"), bh))
        assert_lease(lease)
        assert lease["status"] == "DRAFT"

        estoppel = get_success_data(api.request_estoppel(
            lease["id"], "2026-08-20T00:00:00Z", MS))
        assert_estoppel(estoppel)
        assert estoppel["status"] == "PENDING"

        inspection = get_success_data(api.schedule_inspection(
            prop["id"],
            schedule_inspection_payload(
                inspector["id"], scheduled_start="2026-08-10T09:00:00Z",
                scheduled_end="2026-08-10T10:00:00Z"), MS))
        assert_inspection(inspection)
        assert inspection["status"] == "SCHEDULED"

        draw = get_success_data(api.create_disbursement_request(
            reserve["id"],
            create_disbursement_payload(
                "CAPITAL_REPAIR",
                [{"description": "x", "amount_cents": 1000}],
                reserve["version"]), bh))
        assert_disbursement_request(draw)
        assert draw["status"] == "SUBMITTED"
        assert draw["amount_cents"] == 1000

        statement = get_success_data(api.create_statement(
            loan["id"],
            create_statement_payload("RENT_ROLL", "2026-04-01T00:00:00Z",
                                     "2026-06-30T00:00:00Z", occupancy_pct=88),
            bh))
        assert statement["status"] == "SUBMITTED"
