"""Security: SQL injection in string fields, mass assignment, error
envelope on bad JSON. Plus path-resource not-found checks.

Cites PRD §2.2, §2.5.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_agent_payload,
    create_listing_agent,
    create_listing_payload,
    make_listing_agent_headers,
    validate_error,
    validate_success,
)


SQL_INJECTION_PAYLOADS = [
    "'; DROP TABLE listings; --",
    "' OR '1'='1",
    "' UNION SELECT * FROM agents--",
]
SQL_ERROR_LEAK_PATTERNS = [
    "sql syntax", "sqlstate", "database error", "sqlite", "pg_", "mysql_",
]


class TestSqlInjection:
    """Defense-in-depth: any string field that lands in storage must
    not produce a 500 or surface a database error string."""

    @pytest.mark.parametrize("injection", SQL_INJECTION_PAYLOADS)
    def test_sql_injection_in_agent_full_name(
        self, api, mls_admin_headers, injection,
    ):
        """Defensive: SQL-like input in full_name must not crash the
        server or leak SQL errors. PRD §2.2 mandates a structured error
        envelope for all 4xx; nothing in PRD describes a 500 path.

        Claim: POST /agents with full_name = SQL-injection payload
        returns either 201 or 4xx, never 500, and the response body
        never contains common SQL-error substrings.
        """
        res = api.create_agent(
            create_agent_payload(
                full_name=injection, agent_role="LISTING_AGENT",
            ),
            mls_admin_headers,
        )
        assert res.status_code != 500, (
            f"PRD §2.2 contracts 4xx-with-envelope or 2xx-with-data; "
            f"500 with payload {injection!r} indicates an unhandled exception."
        )
        body_text = res.text.lower()
        for pat in SQL_ERROR_LEAK_PATTERNS:
            assert pat not in body_text, (
                f"SQL error string leaked in response for payload "
                f"{injection!r}: found {pat!r}"
            )


class TestMassAssignmentRejected:
    """Computed fields cannot be overridden from the request body."""

    def test_listing_status_from_input_is_ignored(self, api):
        """PRD §3.2: 'On success the listing is created in ACTIVE
        status with no accepted offer (accepted_offer_id is null) and
        a showing_count of zero'.

        Claim: An attempt to set listing.status=SOLD via POST input is
        ignored; the listing is created in ACTIVE.
        """
        la = create_listing_agent()
        payload = create_listing_payload(listing_agent_id=la["id"])
        # Inject a computed field.
        payload["status"] = "SOLD"
        payload["showing_count"] = 99
        payload["accepted_offer_id"] = NON_EXISTENT_UUID
        res = api.create_listing(
            payload, make_listing_agent_headers(la["id"]),
        )
        # The implementation may either silently ignore the extra fields
        # (most faithful to PRD) or reject as ERR_INVALID_LISTING_FIELDS.
        # PRD does NOT explicitly forbid extra fields, so we only
        # require: if it succeeds, the row is ACTIVE / count 0 / null.
        if res.status_code == 201:
            listing = validate_success(res, 201)
            assert listing["status"] == "ACTIVE", (
                "PRD §3.2: listing must be ACTIVE on creation; "
                "computed `status` must not be writable via input."
            )
            assert listing["showing_count"] == 0
            assert listing.get("accepted_offer_id") is None


class TestNotFoundPaths:
    """PRD §2.5 path resource resolution."""

    def test_get_listing_unknown_uuid(self, api, mls_admin_headers):
        """PRD §2.5: 'If any segment of the path does not resolve ...
        the response is ERR_NOT_FOUND with HTTP 404.'

        Claim: GET /listings/{non-existent-uuid} → ERR_NOT_FOUND.
        """
        res = api.get_listing(NON_EXISTENT_UUID, mls_admin_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_accept_unknown_offer_under_known_listing(self, api):
        """PRD §2.5: 'If any segment of the path does not resolve —
        or resolves to a row whose parent foreign key does not match
        the path's earlier segment — the response is ERR_NOT_FOUND
        with HTTP 404. Existence checks run after authentication and
        role-permission checks but before any state checks.'

        Claim: POST /listings/{valid}/offers/{nonexistent}/accept →
        ERR_NOT_FOUND (existence before state).
        """
        from test_helpers import create_listing
        la = create_listing_agent()
        listing = create_listing(la)
        res = api.accept_offer(
            listing["id"], NON_EXISTENT_UUID,
            make_listing_agent_headers(la["id"]),
        )
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)
