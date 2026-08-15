"""Response envelope, pagination, and the foundational auth/validation errors."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    is_iso8601_timestamp,
    ApiErrorId, TEST_USERS, CLOCK_STARTUP_DEFAULT,
    create_partner_institution_payload, create_participant_payload,
    create_institution, create_participant, create_referral,
)

ADMIN = TEST_USERS["coalition_admin_headers"]
NAV = TEST_USERS["agency_navigator_headers"]
MISSING_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


class TestSuccessEnvelope:
    def test_get_institution_envelope_shape(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."
        PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits."

        Design: Corner/endpoints/response_envelope_success_shape
        """
        inst = create_institution()
        resp = api.get_partner_institution(inst["id"], ADMIN)
        body = resp.json()
        assert resp.status_code == 200
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert body["data"]["id"] == inst["id"]
        assert isinstance(body["data"]["version"], int)


class TestListPagination:
    def test_referrals_list_limit_offset(self, api):
        """PRD §2.3: "List endpoints are paginated via the `limit` and `offset` query parameters. `limit` defaults to 10 when not supplied, accepts a minimum of 1 and a maximum of 100, and `offset` defaults to 0."
        PRD §2.3: "Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/endpoints/referrals_list_pagination
        """
        for i in range(3):
            p = create_participant(full_name=f"P {i}", date_of_birth=f"1990-01-0{i + 1}")
            create_referral(p["id"])

        data, meta = validate_paginated(
            api.list_referrals(ADMIN, params={"limit": 2, "offset": 0})
        )
        assert len(data) == 2, f"page 1 must hold 2 rows, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

        data, meta = validate_paginated(
            api.list_referrals(ADMIN, params={"limit": 2, "offset": 2})
        )
        assert len(data) == 1, f"page 2 must hold 1 row, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is False


class TestNotFound:
    def test_get_nonexistent_participant_returns_404(self, api):
        """PRD §2.9: "Identifiers appearing in the URL path are resolved first, from the leftmost path parameter to the rightmost; the first identifier that does not correspond to an existing resource yields `ERR_NOT_FOUND` immediately."

        Design: Corner/entities/participant_not_found_returns_404
        """
        resp = api.get_participant(MISSING_UUID, ADMIN)
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert err["error_id"] == "ERR_NOT_FOUND"


class TestAuthentication:
    def test_missing_auth_headers_returns_401(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role string outside this enumeration, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/errors/missing_auth_header_returns_401
        """
        resp = api.get_partner_institution(MISSING_UUID, headers={})
        err = validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
        assert err["error_id"] == "ERR_UNAUTHENTICATED"

    def test_unauthenticated_outranks_invalid_payload(self, api):
        """PRD §2.10: "Authentication comes first — missing or malformed `X-User-ID` / `X-User-Role` headers surface `ERR_UNAUTHENTICATED` before anything else is examined."
        PRD §2.10: "Body well-formedness is third — a malformed payload, missing required field, wrong type, or out-of-set enum value surfaces `ERR_VALIDATION`."

        Design: Corner/errors/unauthenticated_outranks_invalid_payload
        """
        # Missing charter_type AND missing auth headers: auth wins.
        resp = api.create_partner_institution({"legal_name": "No Charter"}, headers={})
        err = validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
        assert err["error_id"] == "ERR_UNAUTHENTICATED"

    def test_out_of_enum_charter_type_returns_400(self, api):
        """PRD §3.2: "A `CoalitionAdmin` registers a **PartnerInstitution** with its `legal_name` and `charter_type` — either `BANK` or `CREDIT_UNION`."
        PRD §2.10: "Body well-formedness is third — a malformed payload, missing required field, wrong type, or out-of-set enum value surfaces `ERR_VALIDATION`."

        Design: Corner/errors/malformed_enum_returns_400
        """
        payload = create_partner_institution_payload(charter_type="SAVINGS_BANK")
        resp = api.create_partner_institution(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        data, meta = validate_paginated(api.list_partner_institutions(ADMIN))
        assert meta["total_count"] == 0, "no institution row may be created"


class TestLogicalClock:
    def test_non_monotonic_clock_set_rejected(self, api):
        """PRD §2.5: "At startup the logical clock reads exactly `2026-05-01T00:00:00Z`; before any explicit set call it never falls back to wall-clock time."
        PRD §2.5: "A coalition administrator may advance the clock by supplying a `to_iso8601` timestamp; the clock is monotonic, and an attempt to set it to a value earlier than the current reading is rejected with `ERR_VALIDATION`."

        Design: Corner/validations/non_monotonic_clock_rejected
        """
        resp = api.set_clock({"to_iso8601": "2026-04-01T00:00:00Z"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        # The failed backward set left the clock at its startup default:
        # setting to exactly that default (not earlier) is still accepted.
        resp = api.set_clock({"to_iso8601": CLOCK_STARTUP_DEFAULT}, ADMIN)
        validate_success(resp, 200)
