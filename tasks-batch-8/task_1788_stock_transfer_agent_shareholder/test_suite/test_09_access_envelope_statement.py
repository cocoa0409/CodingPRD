"""Authentication and error-envelope shape, enum closure, and the
shareholder statement computed read."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    create_account_payload,
    create_issuer,
    make_shareholder_headers,
    make_supervisor_headers,
    setup_issuer_account_position,
    validate_error,
    validate_success,
    withdraw_certificate,
)


class TestAuthentication:
    def test_unauthenticated_call_missing_headers_rejected(self, api):
        """PRD §2.1: "A request with missing headers, or whose `X-User-Role` is
        not one of these declared role names, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.8: "1. **Authentication.** The `X-User-ID` and `X-User-Role`
        headers must be present, and the role must be one of the seven declared
        roles; failures yield `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/unauthenticated_call_missing_headers_rejected
        """
        issuer = create_issuer(name="Zeta Auth", cusip="000000049",
                               ticker="ZAUT")

        # Both auth headers omitted entirely.
        resp = api.get_issuer(issuer["id"], headers=None)
        error = validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
        assert error["error_id"] == "ERR_UNAUTHENTICATED"
        assert resp.status_code == 401
        assert "name" not in resp.json().get("data", {}), (
            "no issuer data is returned in the error response"
        )


class TestErrorEnvelope:
    def test_error_envelope_shape_on_not_found(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."
        PRD §2.8: "the request is rejected with the specific 404 for the
        leftmost segment that does not resolve"

        Design: Corner/errors/error_envelope_shape_on_not_found
        """
        resp = api.approve_transfer_request(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
            make_supervisor_headers("sup_1"),
        )
        error = validate_error(resp, ApiErrorId.ERR_TRANSFER_NOT_FOUND)
        assert resp.status_code == 404
        assert error["message"].strip(), "message is a non-empty string"

        body = resp.json()
        assert body["response_type"] == "error"
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"]
        assert isinstance(meta.get("api_request_timestamp"), str) \
            and meta["api_request_timestamp"]


class TestEnumClosure:
    def test_invalid_enum_value_rejected(self, api):
        """PRD §3.1: "`tin_status`, the W-9 certification status, which is one
        of `MISSING`, `CERTIFIED`, or `UNCERTIFIED` and defaults to `MISSING`"
        PRD §2.8: "missing required fields, malformed values, or enum values
        outside their declared sets fail with `ERR_INVALID_REQUEST`."

        Design: Corner/validations/invalid_enum_value_rejected
        """
        payload = create_account_payload(holder_name="Enum Erin",
                                         postal_code="74122",
                                         tax_id="432-12-1212",
                                         tin_status="BOGUS")
        resp = api.create_account(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400


class TestShareholderStatement:
    def test_statement_reflects_position_split(self, api):
        """PRD §3.8: "For self-service visibility, a `Shareholder` — or an
        `AgentAdmin` or `ServiceAgent` assisting them — can read the account's
        statement, which reports the account's positions and aggregate totals
        as of the current logical clock. The statement response carries the
        `account_id`, an `as_of` timestamp taken from the logical clock, the
        `positions` array, and a `totals` object."
        PRD §2.4: "Before the clock has ever been set, its value is exactly
        `2026-08-01T00:00:00Z`"
        PRD §2.10: "exposes `total_shares` as the sum of the two"

        Design: Corner/endpoints/statement_reflects_position_split
        """
        ctx = setup_issuer_account_position(shares_outstanding=500,
                                            book_entry_shares=500,
                                            holder_name="Statement Sara",
                                            tin_status="CERTIFIED")
        withdraw_certificate(ctx["position"]["id"], 200)

        statement = validate_success(api.get_statement(
            ctx["account"]["id"], make_shareholder_headers(ctx["account"]["id"])))
        assert statement["account_id"] == ctx["account"]["id"]
        assert statement["as_of"] == "2026-08-01T00:00:00.000Z", (
            "as_of is taken from the logical clock, still at its default"
        )
        assert isinstance(statement["totals"], dict), "a totals object is carried"
        positions = statement["positions"]
        assert len(positions) == 1
        entry = positions[0]
        assert entry["book_entry_shares"] == 300
        assert entry["certificated_shares"] == 200
        assert entry["total_shares"] == 500
