"""Shared pytest wiring for the Move Concierge Utility Automation suite.

The server is relaunched against an empty store before every individual
test, so nothing here caches domain state: each fixture either builds a
client or builds headers.  Every precondition a test needs is created inside
that test through declared endpoints.
"""

import os
import sys
from typing import Dict

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import ApiClient  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    COMPLIANCE_OFFICER_ALT_USER_ID,
    COMPLIANCE_OFFICER_USER_ID,
    MOVE_OPS_AGENT_ALT_USER_ID,
    make_compliance_headers,
    make_gateway_headers,
    make_move_ops_headers,
    make_platform_admin_headers,
)


@pytest.fixture()
def api() -> ApiClient:
    """A client bound to the server under test."""
    return ApiClient()


@pytest.fixture()
def admin_headers() -> Dict[str, str]:
    """`PlatformAdmin` headers; permitted on every operation in the system."""
    return make_platform_admin_headers()


@pytest.fixture()
def ops_headers() -> Dict[str, str]:
    """`MoveOpsAgent` headers; the concierge operations agent."""
    return make_move_ops_headers()


@pytest.fixture()
def ops_headers_alt() -> Dict[str, str]:
    """A second, distinct `MoveOpsAgent` identity."""
    return make_move_ops_headers(MOVE_OPS_AGENT_ALT_USER_ID)


@pytest.fixture()
def compliance_headers() -> Dict[str, str]:
    """`ComplianceOfficer` headers for the reviewer stamped on an override."""
    return make_compliance_headers(COMPLIANCE_OFFICER_USER_ID)


@pytest.fixture()
def compliance_headers_alt() -> Dict[str, str]:
    """A second `ComplianceOfficer`, who may submit a filing the first cannot."""
    return make_compliance_headers(COMPLIANCE_OFFICER_ALT_USER_ID)


@pytest.fixture()
def gateway_headers() -> Dict[str, str]:
    """`ExternalServiceGateway` headers for the inbound callback channel."""
    return make_gateway_headers()
