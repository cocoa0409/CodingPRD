"""Validation priority and pre-emption tests.

PRD §2.7 explicitly defines the validation priority chain. We test only the
priority pairs PRD prose explicitly names; we DO NOT test arbitrary priority
ordering between checks the PRD does not enumerate.
"""
import pytest
import uuid

from test_helpers import (
    ApiErrorId,
    api_client,
    create_reimbursement,
    create_reimbursement_payload,
    DEPT_HEADERS,
    make_principal_investigator_headers,
    NON_EXISTENT_UUID,
    now_epoch,
    setup_active_project_with_budget,
    submit_reimbursement,
    TEST_USERS,
    validate_error,
    validate_success,
)


class TestPriorityPreEmption:
    """PRD §2.7 priority chain: header → RBAC → existence → state → safety → referential
    → constraints → temporal → version → fiscal → audit/uniqueness."""

    def test_unauth_with_bad_payload_returns_missing_user_context(self, api):
        """PRD §2.7: "...so, for instance, an unauthenticated request with a malformed
        body returns ERR_MISSING_USER_CONTEXT rather than ERR_INVALID_INPUT."

        Claim: a request with neither auth header AND a malformed body returns
        ERR_MISSING_USER_CONTEXT — header presence pre-empts input shape.
        """
        # Send blatantly malformed payload + no auth headers.
        resp = api.create_project({}, {})  # empty headers, empty body
        validate_error(resp, ApiErrorId.ERR_MISSING_USER_CONTEXT.value)


class TestPathIdResolutionLeftToRight:
    """PRD §2.6: 'Resolution stops at the first segment that fails.'"""

    def test_nonexistent_project_in_nested_peer_review(self, api, peer_reviewer_headers):
        """PRD §2.6: "Path identifiers are resolved left-to-right against the database.
        If any segment fails to resolve to an existing row, the request is rejected with
        the appropriate not-found error for that resource — ERR_PROJECT_NOT_FOUND,
        ERR_BUDGET_ITEM_NOT_FOUND, ERR_BUDGET_ADJUSTMENT_NOT_FOUND,
        ERR_REIMBURSEMENT_NOT_FOUND, ERR_CLOSING_AUDIT_NOT_FOUND,
        ERR_COMPLIANCE_RULE_NOT_FOUND, ERR_ALLOCATION_RUN_NOT_FOUND, or
        ERR_PEER_REVIEW_NOT_FOUND — all returning HTTP 404. Resolution stops at the
        first segment that fails."

        Claim: GET /projects/{nonexistent}/peer-reviews returns ERR_PROJECT_NOT_FOUND
        — the first segment fails so the path stops there.
        """
        resp = api.list_peer_reviews(NON_EXISTENT_UUID, peer_reviewer_headers,
                                       params={"limit": 10, "offset": 0})
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_FOUND.value)
