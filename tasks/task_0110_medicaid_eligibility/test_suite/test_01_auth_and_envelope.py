"""Auth, RBAC, response envelope, and pagination.

Exercises cross-cutting checks from PRD §2.1 (auth/role), §2.2
(envelope), §2.3 (pagination), §2.5 (NotFound).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    PAGINATION_DEFAULT_LIMIT,
    TEST_USERS,
    build_user_headers,
    create_state_policy,
    create_state_policy_payload,
    is_iso8601_timestamp,
    random_state_code,
    validate_error,
    validate_paginated,
)


# ===========================================================================
# §2.1 Auth — missing headers / invalid role / forbidden
# ===========================================================================
class TestAuthHeaders:
    """PRD §2.1: every request must carry X-User-ID and X-User-Role."""

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: "If either header is missing or invalid, the
        request is rejected with ERR_UNAUTHENTICATED."

        Claim: a POST with neither header → ERR_UNAUTHENTICATED.
        """
        res = api.create_state_policy(
            create_state_policy_payload(state_code=random_state_code()),
            headers={},
        )
        validate_error(res, "ERR_UNAUTHENTICATED")

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "If either header is missing or invalid, the
        request is rejected with ERR_UNAUTHENTICATED."

        Claim: only X-User-Role present → ERR_UNAUTHENTICATED.
        """
        res = api.create_state_policy(
            create_state_policy_payload(state_code=random_state_code()),
            headers={"X-User-Role": "PolicyAdmin"},
        )
        validate_error(res, "ERR_UNAUTHENTICATED")

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: "If either header is missing or invalid, the
        request is rejected with ERR_UNAUTHENTICATED."

        Claim: only X-User-ID present → ERR_UNAUTHENTICATED.
        """
        res = api.create_state_policy(
            create_state_policy_payload(state_code=random_state_code()),
            headers={"X-User-ID": "pa-001"},
        )
        validate_error(res, "ERR_UNAUTHENTICATED")

    def test_invalid_role_value_rejected(self, api):
        """PRD §2.1: "If either header is missing or invalid, the
        request is rejected with ERR_UNAUTHENTICATED."

        Claim: X-User-Role="Hacker" (not one of the four valid roles)
        → ERR_UNAUTHENTICATED.
        """
        res = api.create_state_policy(
            create_state_policy_payload(state_code=random_state_code()),
            headers=build_user_headers("test-1", "Hacker"),
        )
        validate_error(res, "ERR_UNAUTHENTICATED")

    def test_unauthorized_role_for_endpoint_rejected(
            self, api, intake_worker_headers):
        """PRD §2.1: "If the supplied role is valid but lacks
        permission for the requested endpoint per the role matrix, the
        request is rejected with ERR_FORBIDDEN."

        Claim: IntakeWorker calling POST /state-policies (PolicyAdmin-
        only per PRD §4) → ERR_FORBIDDEN.
        """
        res = api.create_state_policy(
            create_state_policy_payload(state_code=random_state_code()),
            headers=intake_worker_headers,
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_caseworker_cannot_create_household(
            self, api, eligibility_caseworker_headers):
        """PRD §4: POST /households is IntakeWorker-only.
        PRD §2.1: "the request is rejected with ERR_FORBIDDEN."

        Claim: EligibilityCaseworker attempting POST /households →
        ERR_FORBIDDEN.
        """
        from test_helpers import create_household_payload
        # State-policy is a prerequisite for an IntakeWorker creating
        # a household, but role check fires before any body validation.
        res = api.create_household(
            create_household_payload(state_code="ZZ"),
            headers=eligibility_caseworker_headers,
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_appeals_officer_cannot_decide_application(
            self, api, appeals_officer_headers):
        """PRD §4: POST /households/{id}/applications/{id}/decide is
        EligibilityCaseworker-only.
        PRD §2.1: a valid role lacking permission → ERR_FORBIDDEN.

        Claim: AppealsOfficer attempting /decide → ERR_FORBIDDEN.
        """
        from test_helpers import decide_application_payload
        res = api.decide_application(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID,
            decide_application_payload(decision="APPROVE"),
            headers=appeals_officer_headers,
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_intake_worker_cannot_advance_clock(
            self, api, intake_worker_headers):
        """PRD §4: POST /_clock/advance is PolicyAdmin-only.
        PRD §2.1: ERR_FORBIDDEN on insufficient role.

        Claim: IntakeWorker calling /_clock/advance → ERR_FORBIDDEN.
        """
        from test_helpers import clock_advance_payload, iso_now
        res = api.clock_advance(
            clock_advance_payload(to=iso_now()),
            headers=intake_worker_headers,
        )
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# §2.2 Response envelope
# ===========================================================================
class TestResponseEnvelope:
    """PRD §2.2: success / error envelope shape."""

    def test_success_envelope_shape(self, api, policy_admin_headers):
        """PRD §2.2: "The api_request_id is a server-generated unique
        identifier for the request that starts with req_."
        PRD §2.2: "The api_request_timestamp is a server-generated ISO
        8601 UTC timestamp with three fractional digits."

        Claim: a successful GET returns the documented envelope shape.
        """
        policy = create_state_policy()
        res = api.get_state_policy(policy["state_code"], policy_admin_headers)
        body = res.json()
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

    def test_error_envelope_shape(self, api, policy_admin_headers):
        """PRD §2.2: error responses carry "response_type": "error"
        and data.error_id + data.message.

        Claim: 404 NotFound has the documented error envelope.
        """
        res = api.get_state_policy("ZZ", policy_admin_headers)
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
    to 0; malformed values rejected with ERR_INVALID_REQUEST."""

    def test_default_pagination_limit(self, api, policy_admin_headers):
        """PRD §2.3: "The limit parameter governs the maximum number of
        items returned and defaults to 10 when omitted."

        Claim: a list endpoint without `limit` returns meta.limit == 10.
        """
        # Seed several emergency declarations so the list is non-empty
        # but small (sanity).
        from test_helpers import issue_emergency_declaration, iso_now, iso_offset
        for _ in range(3):
            issue_emergency_declaration(
                scope="FEDERAL", state_code=None,
                declared_at=iso_now(), expires_at=iso_offset(days=30),
            )
        data, meta = validate_paginated(
            api.list_emergency_declarations(policy_admin_headers),
        )
        assert meta["limit"] == PAGINATION_DEFAULT_LIMIT, (
            f"default limit must be 10 per PRD §2.3, got {meta['limit']}"
        )

    def test_pagination_meta_fields_present(self, api, policy_admin_headers):
        """PRD §2.3: "The meta envelope on every list response carries
        four pagination fields: limit ... offset ... total_count ...
        has_more."

        Claim: every list response has all four pagination fields.
        """
        data, meta = validate_paginated(
            api.list_emergency_declarations(
                policy_admin_headers, params={"limit": 5},
            ),
        )
        for field in ("limit", "offset", "total_count", "has_more"):
            assert field in meta, f"meta missing field {field!r}"
        assert isinstance(meta["limit"], int)
        assert isinstance(meta["offset"], int)
        assert isinstance(meta["total_count"], int)
        assert isinstance(meta["has_more"], bool)

    def test_pagination_malformed_limit_rejected(
            self, api, policy_admin_headers):
        """PRD §2.3: "Malformed values for either parameter are rejected
        with ERR_INVALID_REQUEST."

        Claim: limit="abc" → ERR_INVALID_REQUEST.
        """
        res = api.list_emergency_declarations(
            policy_admin_headers, params={"limit": "abc"},
        )
        validate_error(res, "ERR_INVALID_REQUEST")

    def test_pagination_limit_above_max_rejected(
            self, api, policy_admin_headers):
        """PRD §2.3: "valid values range from a minimum of 1 to a
        maximum of 100." A value above the max is malformed.

        Claim: limit=101 → ERR_INVALID_REQUEST.
        """
        res = api.list_emergency_declarations(
            policy_admin_headers, params={"limit": 101},
        )
        validate_error(res, "ERR_INVALID_REQUEST")

    def test_pagination_negative_offset_rejected(
            self, api, policy_admin_headers):
        """PRD §2.3: "The offset parameter governs the number of items
        skipped at the start of the result and defaults to 0."
        Malformed values are rejected per PRD §2.3.

        Claim: offset=-1 → ERR_INVALID_REQUEST.
        """
        res = api.list_emergency_declarations(
            policy_admin_headers, params={"offset": -1},
        )
        validate_error(res, "ERR_INVALID_REQUEST")


# ===========================================================================
# §2.5 NotFound resolution
# ===========================================================================
class TestNotFound:
    """PRD §2.5: path identifiers resolved left-to-right; missing →
    ERR_NOT_FOUND."""

    def test_get_state_policy_unknown_state_code(
            self, api, policy_admin_headers):
        """PRD §2.5: "If the parent identifier does not refer to an
        existing resource, the request is rejected immediately with
        ERR_NOT_FOUND."

        Claim: GET /state-policies/ZZ (no such state) → ERR_NOT_FOUND.
        """
        res = api.get_state_policy("ZZ", policy_admin_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_get_household_unknown_id(self, api, intake_worker_headers):
        """PRD §2.5: unknown path id → ERR_NOT_FOUND.

        Claim: GET /households/{nonexistent UUID} → ERR_NOT_FOUND.
        """
        res = api.get_household(NON_EXISTENT_UUID, intake_worker_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_get_appeal_unknown_id(self, api, appeals_officer_headers):
        """PRD §2.5: unknown path id → ERR_NOT_FOUND.

        Claim: GET /appeals/{nonexistent UUID} → ERR_NOT_FOUND.
        """
        res = api.get_appeal(NON_EXISTENT_UUID, appeals_officer_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_parent_not_found_short_circuits_child(
            self, api, intake_worker_headers):
        """PRD §2.5: "If the parent identifier does not refer to an
        existing resource, the request is rejected immediately with
        ERR_NOT_FOUND, identifying the parent. The system does not
        attempt to resolve the child identifier until the parent has
        been confirmed to exist."

        Claim: GET /households/{unknown}/applicants/{unknown} →
        ERR_NOT_FOUND (parent fails first, child never attempted).
        """
        res = api.get_applicant(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID, intake_worker_headers,
        )
        validate_error(res, "ERR_NOT_FOUND")

    def test_dangling_fk_in_body_rejected(self, api, intake_worker_headers):
        """PRD §2.5: "body-level foreign key references such as
        determination_id on an appeal filing ... must also resolve, and
        a dangling reference is rejected with ERR_NOT_FOUND."

        Claim: POST /appeals with a determination_id that doesn't exist
        → ERR_NOT_FOUND.
        """
        from test_helpers import create_appeal_payload
        res = api.create_appeal(
            create_appeal_payload(determination_id=NON_EXISTENT_UUID),
            intake_worker_headers,
        )
        validate_error(res, "ERR_NOT_FOUND")
