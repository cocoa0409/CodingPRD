"""Shared pytest fixtures for the hardwood flooring mill API suite.

The server lifecycle and the database reset between tests are owned by the
harness; these fixtures only supply the HTTP client and the role headers each
test acts through.
"""

import pytest

from test_helpers import ApiClient
from test_helpers.test_users import NO_ROLE_HEADERS, TEST_USERS


@pytest.fixture
def api() -> ApiClient:
    """A fresh client per test; every request carries its own headers.

    The harness owns the server lifecycle and may replace the process behind the
    port between tests, so a connection pool must never outlive a single test:
    a keep-alive socket held over a restart is closed by the new process and the
    first request on it fails with a bare disconnect rather than a response.
    """
    client = ApiClient()
    try:
        yield client
    finally:
        client.session.close()


@pytest.fixture
def mill_admin_headers() -> dict:
    return TEST_USERS["mill_admin_headers"]


@pytest.fixture
def procurement_clerk_headers() -> dict:
    return TEST_USERS["procurement_clerk_headers"]


@pytest.fixture
def kiln_operator_headers() -> dict:
    return TEST_USERS["kiln_operator_headers"]


@pytest.fixture
def mill_supervisor_headers() -> dict:
    return TEST_USERS["mill_supervisor_headers"]


@pytest.fixture
def grade_inspector_headers() -> dict:
    return TEST_USERS["grade_inspector_headers"]


@pytest.fixture
def prefinish_scheduler_headers() -> dict:
    return TEST_USERS["prefinish_scheduler_headers"]


@pytest.fixture
def byproduct_broker_headers() -> dict:
    return TEST_USERS["byproduct_broker_headers"]


@pytest.fixture
def warranty_adjudicator_headers() -> dict:
    return TEST_USERS["warranty_adjudicator_headers"]


@pytest.fixture
def anonymous_headers() -> dict:
    """The reserved `Anonymous` role value: an unauthenticated caller."""
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def no_role_headers() -> dict:
    """A request that carries no role header at all."""
    return dict(NO_ROLE_HEADERS)
