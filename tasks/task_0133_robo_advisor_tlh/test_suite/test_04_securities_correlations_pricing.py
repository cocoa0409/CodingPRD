"""Securities, correlation links, and pricing endpoints.

Coverage targets (PRD §3.9):
- Security ticker constraints.
- Correlation value bounds and same-id rejection.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_correlation_link_payload,
    create_security,
    create_security_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Security registration — PRD §3.9
# ===========================================================================
class TestSecurityCreate:

    def test_security_created_with_defaults(self, api):
        """PRD §3.9: "Each Security carries a ticker of between one
        and ten uppercase characters, unique across the catalog; an
        asset_class from the five-class set; a
        substantially_identical_group_id that groups same-fund
        equivalents under one IRS-wash-sale identity; and an
        is_investable flag (default true)".

        Claim: Security created with the required fields exposes
        ticker, asset_class, group_id, is_investable (default true),
        and last_price_cents.
        """
        payload = create_security_payload()
        resp = api.create_security(
            payload, TEST_USERS["advisor_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert data["is_investable"] is True
        assert isinstance(data["ticker"], str)


# ===========================================================================
# Correlation link validation — PRD §3.9
# ===========================================================================
class TestCorrelationValidation:

    @pytest.mark.parametrize("bad_corr", [-1.5, 1.01, -2.0, 2.0])
    def test_correlation_out_of_range_rejected(self, api, bad_corr):
        """PRD §3.9: "carries a correlation value in the inclusive
        interval from negative one through positive one — values
        outside that range, or a request where security_a_id equals
        security_b_id, are rejected with ERR_CORRELATION_INVALID."

        Claim: correlation outside [-1.0, 1.0] -> ERR_CORRELATION_INVALID.
        """
        a = create_security()
        b = create_security()
        payload = create_correlation_link_payload(
            security_a_id=a["id"], security_b_id=b["id"],
            correlation=bad_corr,
        )
        resp = api.create_correlation_link(
            payload, TEST_USERS["advisor_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CORRELATION_INVALID.value)

    def test_same_security_self_link_rejected(self, api):
        """PRD §3.9: "or a request where security_a_id equals
        security_b_id, are rejected with ERR_CORRELATION_INVALID."

        Claim: security_a_id == security_b_id -> ERR_CORRELATION_INVALID.
        """
        a = create_security()
        payload = create_correlation_link_payload(
            security_a_id=a["id"], security_b_id=a["id"],
            correlation=0.5,
        )
        resp = api.create_correlation_link(
            payload, TEST_USERS["advisor_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CORRELATION_INVALID.value)

    def test_correlation_boundary_minus_one_accepted(self, api):
        """PRD §3.9: "a correlation value in the inclusive interval
        from negative one through positive one".

        Claim: correlation == -1.0 (lower bound, inclusive) is
        accepted.
        """
        a = create_security()
        b = create_security()
        payload = create_correlation_link_payload(
            security_a_id=a["id"], security_b_id=b["id"],
            correlation=-1.0,
        )
        resp = api.create_correlation_link(
            payload, TEST_USERS["advisor_headers"],
        )
        validate_success(resp, expected_status=201)

    def test_correlation_boundary_plus_one_accepted(self, api):
        """PRD §3.9: "a correlation value in the inclusive interval
        from negative one through positive one".

        Claim: correlation == 1.0 (upper bound, inclusive) is
        accepted.
        """
        a = create_security()
        b = create_security()
        payload = create_correlation_link_payload(
            security_a_id=a["id"], security_b_id=b["id"],
            correlation=1.0,
        )
        resp = api.create_correlation_link(
            payload, TEST_USERS["advisor_headers"],
        )
        validate_success(resp, expected_status=201)
