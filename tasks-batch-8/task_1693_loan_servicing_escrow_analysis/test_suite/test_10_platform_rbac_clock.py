"""Platform rules: auth headers, error envelope, RBAC denials, logical clock."""
from test_helpers import (
    CO1,
    DP1,
    EA1,
    PV1,
    ApiErrorId,
    DEFAULT_CLOCK_UTC,
    advance_case_to_investigating,
    create_active_bare_loan,
    create_payee_payload,
    file_error_case,
    get_success_data,
    is_iso8601_timestamp,
    make_borrower_headers,
    validate_error,
    validate_success,
)


class TestAuthHeaders:
    def test_request_without_user_headers_rejected(self, api):
        """PRD: "A request missing either header, or carrying a malformed
        value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."

        Design: Corner/errors/missing_auth_header_returns_400
        """
        resp = api.create_payee(
            create_payee_payload(legal_name="No Auth", remit_to_address="0 Nowhere",
                                 ach_routing_mask="****0000"),
            {})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestErrorEnvelope:
    def test_error_response_envelope_shape(self, api):
        """PRD: error responses carry ""response_type": "error"" with
        ""data": { "error_id": ..., "message": ... }", and "The `meta` object
        for error responses contains only `api_request_id` and
        `api_request_timestamp`."

        Design: Corner/endpoints/error_envelope_shape
        """
        resp = api.get_payee("00000000-0000-4000-8000-000000000000", CO1)
        body = resp.json()
        assert body.get("response_type") == "error"
        meta = body.get("meta", {})
        assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"]
        assert is_iso8601_timestamp(meta.get("api_request_timestamp", ""))
        data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert isinstance(data["message"], str) and data["message"].strip(), (
            "data.message is a non-empty human-readable explanation")


class TestRoleDenial:
    def test_roles_cannot_perform_other_roles_exclusive_operations(self, api):
        """PRD: "A request whose role is well-formed but not on the endpoint's
        authorized list is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4: payee verify is authorized for PayeeVerifier; error-case
        resolve for ComplianceOfficer; payee create for DisbursementProcessor.

        Design: Corner/rbac/role_denial_sampling_cannot_perform
        """
        payee = get_success_data(api.create_payee(create_payee_payload(), DP1))
        loan = create_active_bare_loan(loan_number="LN-RBAC-1",
                                       borrower_name="Role Denied")
        case = file_error_case(loan["id"], error_type="OTHER_COVERED",
                               description="x")
        advance_case_to_investigating(case["id"], investigator="ea_9")

        # Borrower cannot verify payees (PayeeVerifier-only endpoint).
        resp1 = api.verify_payee(payee["id"], make_borrower_headers(loan["id"]))
        validate_error(resp1, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

        # EscrowAnalyst cannot resolve error cases (ComplianceOfficer-only).
        resp2 = api.resolve_case(case["id"], {"outcome": "NO_ERROR"}, EA1)
        validate_error(resp2, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

        # PayeeVerifier cannot create payees (DisbursementProcessor-only).
        resp3 = api.create_payee(
            create_payee_payload(payee_type="INSURANCE_CARRIER",
                                 legal_name="Verifier Created"),
            PV1)
        validate_error(resp3, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_borrower_acting_on_another_loan_rejected(self, api):
        """PRD: "A borrower acting on a resource owned by a different loan is
        rejected with `ERR_BORROWER_NOT_OWNER` (HTTP 403)."
        PRD: "When `X-User-Role` is `Borrower`, `X-User-ID` is the `id` of the
        acting borrower's `Loan`"

        Design: Corner/rbac/borrower_other_loan_forbidden
        """
        loan1 = create_active_bare_loan(loan_number="LN-RBAC-2A",
                                        borrower_name="Owner One")
        loan2 = create_active_bare_loan(loan_number="LN-RBAC-2B",
                                        borrower_name="Owner Two")

        # Borrower of loan 1 files a case against loan 2.
        resp = api.create_error_case(
            loan2["id"], {"error_type": "OTHER_COVERED", "description": "not my loan"},
            make_borrower_headers(loan1["id"]))
        validate_error(resp, ApiErrorId.ERR_BORROWER_NOT_OWNER)


class TestLogicalClock:
    def test_clock_reads_default_before_any_set(self, api):
        """PRD: "Before any call to the clock-setting capability, the logical
        clock reads exactly 2026-08-01T00:00:00Z and never falls back to
        wall-clock time."

        Design: Corner/cross_cutting_layers/clock_default_before_any_set
        """
        current = validate_success(api.get_clock(CO1), 200)
        assert current["current_utc"] == DEFAULT_CLOCK_UTC

        set_resp = validate_success(api.set_clock("2026-08-20T00:00:00Z", CO1), 200)
        assert set_resp["previous_utc"] == DEFAULT_CLOCK_UTC, (
            "the first set reports the default as previous")
        assert set_resp["current_utc"] == "2026-08-20T00:00:00Z"
