"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def hub_operator_headers():
    return TEST_USERS["hub_operator_headers"]


@pytest.fixture
def quality_officer_headers():
    return TEST_USERS["quality_officer_headers"]


@pytest.fixture
def member_headers():
    """Shared Member headers. Only for calls whose outcome does not depend on ownership."""
    return TEST_USERS["member_headers"]


@pytest.fixture
def vendor_headers():
    """Shared Vendor headers. Only for calls whose outcome does not depend on ownership."""
    return TEST_USERS["vendor_headers"]
