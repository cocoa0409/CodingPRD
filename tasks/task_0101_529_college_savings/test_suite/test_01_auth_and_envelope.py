"""Auth, RBAC, response envelope, and pagination.

These tests exercise the cross-cutting checks defined in PRD §2.1
(auth/role), §2.2 (envelope), §2.3 (pagination), §2.6 (NotFound),
which apply across every endpoint.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_MAX_LIMIT,
    TEST_USERS,
    build_user_headers,
    create_donor_payload,
    create_state_rule_payload,
    ensure_state_rule,
    is_iso8601_timestamp,
    setup_donor_beneficiary_account,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# §2.1 Auth — missing / invalid role / forbidden
# ===========================================================================
class TestAuthHeaders:
    """PRD §2.1: every request must carry X-User-ID and X-User-Role."""

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: "Requests missing either header are rejected with
        ERR_AUTH_MISSING."

        Claim: a POST with neither header set → ERR_AUTH_MISSING.
        """
        res = api.create_state_rule(
            create_state_rule_payload(state_code="AA"), headers={},
        )
        validate_error(res, "ERR_AUTH_MISSING")

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "Requests missing either header are rejected with
        ERR_AUTH_MISSING."

        Claim: omitting X-User-ID while supplying X-User-Role →
        ERR_AUTH_MISSING.
        """
        res = api.create_state_rule(
            create_state_rule_payload(state_code="AB"),
            headers={"X-User-Role": "PlanAdministrator"},
        )
        validate_error(res, "ERR_AUTH_MISSING")

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: "Requests missing either header are rejected with
        ERR_AUTH_MISSING."

        Claim: omitting X-User-Role while supplying X-User-ID →
        ERR_AUTH_MISSING.
        """
        res = api.create_state_rule(
            create_state_rule_payload(state_code="AC"),
            headers={"X-User-ID": "admin-001"},
        )
        validate_error(res, "ERR_AUTH_MISSING")

    def test_invalid_role_value_rejected(self, api):
        """PRD §2.1: "Requests whose X-User-Role is not one of those
        three exact strings are rejected with ERR_AUTH_INVALID_ROLE."

        Claim: X-User-Role="Hacker" (not Donor/Beneficiary/
        PlanAdministrator) → ERR_AUTH_INVALID_ROLE.
        """
        res = api.list_state_rules(
            headers=build_user_headers("test-1", "Hacker"),
        )
        validate_error(res, "ERR_AUTH_INVALID_ROLE")

    def test_unauthorized_role_for_endpoint_rejected(self, api):
        """PRD §2.1: "When the role is valid but the role is not
        authorized for the endpoint per Section 4, the request is
        rejected with ERR_FORBIDDEN."

        Claim: Beneficiary calling POST /state-rules (admin-only per
        PRD §4) → ERR_FORBIDDEN.
        """
        res = api.create_state_rule(
            create_state_rule_payload(state_code="AD"),
            headers=build_user_headers("ben-1", "Beneficiary"),
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_donor_cannot_settle_contribution(self, api):
        """PRD §4 endpoint table: POST /contributions/{id}/settle is
        Authorized Role: PlanAdministrator.
        PRD §2.1: "When the role is valid but the role is not
        authorized for the endpoint per Section 4, the request is
        rejected with ERR_FORBIDDEN."

        Claim: Donor attempting to settle their own contribution →
        ERR_FORBIDDEN (segregation of duties).
        """
        from test_helpers import (
            create_pending_contribution,
            make_donor_headers,
        )
        donor, _ben, account = setup_donor_beneficiary_account()
        contribution = create_pending_contribution(
            account=account, donor=donor, amount_cents=10_000,
        )
        res = api.settle_contribution(
            contribution["id"], make_donor_headers(donor["id"]),
        )
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# §2.2 Response envelope
# ===========================================================================
class TestResponseEnvelope:
    """PRD §2.2: success / error envelope shape."""

    def test_success_envelope_shape(self, api, admin_headers):
        """PRD §2.2: success responses carry meta with api_request_id
        starting with `req_` and api_request_timestamp as ISO 8601 UTC
        with three fractional digits.

        Claim: a successful POST returns the documented envelope shape.
        """
        ensure_state_rule("BA")
        body = api.list_state_rules(admin_headers, params={"limit": 1}).json()
        meta = body["meta"]
        assert meta["api_request_id"].startswith("req_"), (
            f"api_request_id must start with 'req_', got "
            f"{meta['api_request_id']!r}"
        )
        assert is_iso8601_timestamp(meta["api_request_timestamp"]), (
            f"api_request_timestamp must be ISO 8601, got "
            f"{meta['api_request_timestamp']!r}"
        )
        assert body["response_type"] in {"object", "array"}

    def test_error_envelope_shape(self, api, admin_headers):
        """PRD §2.2: error responses have response_type=error and
        data.error_id + data.message.

        Claim: a 404 NotFound carries the documented error envelope.
        """
        res = api.get_donor(NON_EXISTENT_UUID, admin_headers)
        body = res.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str)
        assert body["data"]["message"]  # non-empty


# ===========================================================================
# §2.3 Pagination
# ===========================================================================
class TestPagination:
    """PRD §2.3: limit defaults to 10, min 1, max 100; offset defaults
    to 0 and must be non-negative."""

    def test_default_pagination_limit(self, api, admin_headers):
        """PRD §2.3: "The limit parameter defaults to 10 when omitted."

        Claim: a list endpoint without `limit` returns at most 10
        items and `meta.limit == 10`.
        """
        for _ in range(12):
            ensure_state_rule(f"X{chr(65 + (_ % 26))}")
        data, meta = validate_paginated(api.list_state_rules(admin_headers))
        assert meta["limit"] == PAGINATION_DEFAULT_LIMIT
        assert len(data) <= PAGINATION_DEFAULT_LIMIT

    def test_pagination_meta_fields_present(self, api, admin_headers):
        """PRD §2.3: response's meta block carries `limit`, `offset`,
        `total_count`, and `has_more`.

        Claim: every list response has all four pagination fields.
        """
        ensure_state_rule("YA")
        data, meta = validate_paginated(
            api.list_state_rules(admin_headers, params={"limit": 1}),
        )
        for field in ("limit", "offset", "total_count", "has_more"):
            assert field in meta, f"meta missing field {field!r}"
        assert isinstance(meta["limit"], int)
        assert isinstance(meta["offset"], int)
        assert isinstance(meta["total_count"], int)
        assert isinstance(meta["has_more"], bool)

    def test_pagination_offset_skips_items(self, api, admin_headers):
        """PRD §2.3: "List endpoints sort their results by created_at
        ascending."

        Claim: with offset>0 the returned items skip the first N rows.
        """
        # Seed several state rules; track the codes.
        codes = []
        for code in ("PA", "PB", "PC", "PD", "PE"):
            ensure_state_rule(code)
            codes.append(code)
        first_page, _ = validate_paginated(
            api.list_state_rules(admin_headers, params={"limit": 2, "offset": 0}),
        )
        second_page, _ = validate_paginated(
            api.list_state_rules(admin_headers, params={"limit": 2, "offset": 2}),
        )
        ids_first = {r["id"] for r in first_page}
        ids_second = {r["id"] for r in second_page}
        # Sets must be disjoint (offset shifts the window cleanly).
        assert ids_first.isdisjoint(ids_second), (
            "offset window must not overlap the previous page"
        )


# ===========================================================================
# §2.6 Not-found resolution
# ===========================================================================
class TestNotFound:
    """PRD §2.6: path identifiers resolved left-to-right; missing → 404."""

    def test_get_donor_nonexistent_returns_404(self, api, admin_headers):
        """PRD §2.6 + §5: "Path id or body-referenced id does not resolve
        to a row" → ERR_NOT_FOUND (404).

        Claim: GET /donors/{unknown UUID} → ERR_NOT_FOUND.
        """
        res = api.get_donor(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_get_account_nonexistent_returns_404(self, api, admin_headers):
        """PRD §2.6 + §5: "Path id ... does not resolve to a row" →
        ERR_NOT_FOUND.

        Claim: GET /accounts/{unknown UUID} → ERR_NOT_FOUND.
        """
        res = api.get_account(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_get_withdrawal_nonexistent_returns_404(self, api, admin_headers):
        """PRD §2.6 + §5: NotFound on unknown id.

        Claim: GET /withdrawals/{unknown UUID} → ERR_NOT_FOUND.
        """
        res = api.get_withdrawal(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, "ERR_NOT_FOUND")
