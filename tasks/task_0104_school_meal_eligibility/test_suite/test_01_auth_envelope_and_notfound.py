"""Cross-cutting checks: auth, envelope, NotFound.

PRD §2.1 (headers / RBAC), §2.2 (envelope shape), §2.7 (left-to-right
path resolution and cross-aggregate scoping).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    build_user_headers,
    create_district_payload,
    create_meal_serving_payload,
    create_menu_item,
    create_parent_account_payload,
    create_student_payload,
    is_iso8601_timestamp,
    make_parent_headers,
    setup_district_with_family,
    setup_paid_serving_with_balance,
    validate_error,
    validate_success,
)


# ===========================================================================
# §2.1 Auth — missing headers / unauthorised role
# ===========================================================================
class TestAuthHeaders:
    """PRD §2.1: every request must carry X-User-ID and X-User-Role."""

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: "Missing or empty headers result in
        ERR_UNAUTHENTICATED."

        Claim: a POST with neither header set → ERR_UNAUTHENTICATED.
        """
        res = api.create_district(
            create_district_payload(), headers={},
        )
        validate_error(res, "ERR_UNAUTHENTICATED")

    def test_missing_user_id_rejected(self, api):
        """PRD §2.1: "Missing or empty headers result in
        ERR_UNAUTHENTICATED."

        Claim: omitting X-User-ID while supplying X-User-Role →
        ERR_UNAUTHENTICATED.
        """
        res = api.create_district(
            create_district_payload(),
            headers={"X-User-Role": "AuditOfficer"},
        )
        validate_error(res, "ERR_UNAUTHENTICATED")

    def test_missing_user_role_rejected(self, api):
        """PRD §2.1: "Missing or empty headers result in
        ERR_UNAUTHENTICATED."

        Claim: omitting X-User-Role while supplying X-User-ID →
        ERR_UNAUTHENTICATED.
        """
        res = api.create_district(
            create_district_payload(),
            headers={"X-User-ID": "audit-001"},
        )
        validate_error(res, "ERR_UNAUTHENTICATED")

    def test_empty_headers_rejected(self, api):
        """PRD §2.1: "Missing or empty headers result in
        ERR_UNAUTHENTICATED."

        Claim: empty-string X-User-ID and X-User-Role headers →
        ERR_UNAUTHENTICATED.
        """
        res = api.create_district(
            create_district_payload(),
            headers={"X-User-ID": "", "X-User-Role": ""},
        )
        validate_error(res, "ERR_UNAUTHENTICATED")

    def test_unauthorised_role_for_endpoint_rejected(self, api, audit_headers):
        """PRD §2.1: "an authenticated request from a role that the
        endpoint does not permit is rejected with ERR_FORBIDDEN."
        PRD §4 endpoint table: POST /districts is AuditOfficer only.

        Claim: a Parent caller hitting POST /districts → ERR_FORBIDDEN.
        """
        res = api.create_district(
            create_district_payload(),
            headers=build_user_headers("parent-1", "Parent"),
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_cafeteria_cannot_create_district(self, api):
        """PRD §4 endpoint table: POST /districts is restricted to
        AuditOfficer.
        PRD §2.1: "an authenticated request from a role that the
        endpoint does not permit is rejected with ERR_FORBIDDEN."

        Claim: CafeteriaManager calling POST /districts → ERR_FORBIDDEN.
        """
        res = api.create_district(
            create_district_payload(),
            headers=build_user_headers("cafeteria-1", "CafeteriaManager"),
        )
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# §2.2 Response envelope
# ===========================================================================
class TestResponseEnvelope:
    """PRD §2.2: success / error envelope shape."""

    def test_success_envelope_shape(self, api, audit_headers):
        """PRD §2.2: "The api_request_id is a server-generated unique
        identifier for the request that starts with req_."
        PRD §2.2: "The api_request_timestamp is a server-generated ISO
        8601 UTC timestamp with three fractional digits."

        Claim: a successful POST returns the documented envelope shape.
        """
        res = api.create_district(
            create_district_payload(), audit_headers,
        )
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

    def test_error_envelope_shape(self, api, audit_headers):
        """PRD §2.2: "The error_id is a unique, machine-readable string
        that identifies the specific error."
        PRD §2.2: "The message provides a human-readable explanation of
        what went wrong."

        Claim: a 404 NotFound carries the documented error envelope.
        """
        res = api.get_district(NON_EXISTENT_UUID, audit_headers)
        body = res.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str)
        assert body["data"]["message"]  # non-empty


# ===========================================================================
# §2.7 NotFound — left-to-right path resolution and cross-aggregate
# ===========================================================================
class TestNotFound:
    """PRD §2.7: path identifiers resolved left-to-right; missing → 404."""

    def test_get_district_nonexistent_returns_404(self, api, audit_headers):
        """PRD §2.7: "The request is rejected immediately with
        ERR_NOT_FOUND corresponding to the first identifier in the path
        that does not correspond to an existing resource within the
        enclosing scope."

        Claim: GET /districts/{unknown UUID} → ERR_NOT_FOUND.
        """
        res = api.get_district(NON_EXISTENT_UUID, audit_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_get_student_nonexistent_returns_404(self, api, audit_headers):
        """PRD §2.7: a path id that does not resolve to an existing
        resource within the enclosing scope → ERR_NOT_FOUND.

        Claim: GET /districts/{district}/students/{unknown} →
        ERR_NOT_FOUND.
        """
        district, _, _ = setup_district_with_family()
        res = api.get_student(district["id"], NON_EXISTENT_UUID, audit_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_left_to_right_district_first(self, api, audit_headers):
        """PRD §2.7: "the system validates each identifier in a
        sequential, left-to-right order. The request is rejected
        immediately with ERR_NOT_FOUND corresponding to the first
        identifier in the path that does not correspond to an existing
        resource within the enclosing scope."

        Claim: when both the district id (path[0]) and the student id
        (path[1]) are unknown, the rejection is still ERR_NOT_FOUND
        (the first path id resolves first).
        """
        res = api.get_student(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID, audit_headers,
        )
        validate_error(res, "ERR_NOT_FOUND")

    def test_cross_aggregate_student_in_wrong_district(
        self, api, audit_headers,
    ):
        """PRD §2.7: "A student_id that exists in a different district
        from the one named in the path is treated as not found in the
        addressed district."

        Claim: GET /districts/{district_b}/students/{student_in_district_a}
        → ERR_NOT_FOUND.
        """
        district_a, _, student_a = setup_district_with_family()
        district_b, _, _ = setup_district_with_family()
        res = api.get_student(
            district_b["id"], student_a["id"], audit_headers,
        )
        validate_error(res, "ERR_NOT_FOUND")

    def test_meal_serving_cross_district_body_references(
        self, api, cafeteria_headers,
    ):
        """PRD §2.7: "When a meal-serving payload names a student_id and
        a menu_item_id, the system requires both to belong to the same
        district_id that appears in the URL — a payload that references
        a student in district A and a menu item in district B is
        rejected as ERR_NOT_FOUND."

        Claim: cross-district meal-serving body → ERR_NOT_FOUND.
        """
        # District A: student S exists.
        district_a, parent_a, student_a, menu_item_a = (
            setup_paid_serving_with_balance()
        )
        # District B: menu item M exists.
        district_b, _, _, menu_item_b = setup_paid_serving_with_balance()
        # Try to serve student_a (district A) with menu_item_b (district B)
        # under URL pointing to district A.
        res = api.create_meal_serving(
            district_a["id"],
            create_meal_serving_payload(
                student_id=student_a["id"], menu_item_id=menu_item_b["id"],
            ),
            cafeteria_headers,
        )
        validate_error(res, "ERR_NOT_FOUND")
