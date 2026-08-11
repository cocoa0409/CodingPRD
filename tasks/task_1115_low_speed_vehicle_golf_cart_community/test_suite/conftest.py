"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle, API_BASE_URL injection and PYTHONPATH;
this module only wires test_helpers objects into pytest fixtures.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def community_admin_headers():
    return TEST_USERS["community_admin_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def enforcement_officer_headers():
    return TEST_USERS["enforcement_officer_headers"]


@pytest.fixture
def permit_holder_headers():
    """Shared fallback for non-ownership tests only. For ownership-gated calls,
    use test_helpers.make_permit_holder_headers(holder_id)."""
    return TEST_USERS["permit_holder_headers"]
