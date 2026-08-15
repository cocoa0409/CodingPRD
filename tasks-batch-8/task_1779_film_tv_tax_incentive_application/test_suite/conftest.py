"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def reviewer1_headers():
    return TEST_USERS["reviewer1_headers"]


@pytest.fixture
def reviewer2_headers():
    return TEST_USERS["reviewer2_headers"]


@pytest.fixture
def reviewer3_headers():
    return TEST_USERS["reviewer3_headers"]


@pytest.fixture
def cpa1_headers():
    return TEST_USERS["cpa1_headers"]


@pytest.fixture
def cpa2_headers():
    return TEST_USERS["cpa2_headers"]


@pytest.fixture
def producer_headers():
    # Shared fallback: only safe for calls that do not exercise ownership
    # (self-registration, malformed-payload rejections, missing resources).
    return TEST_USERS["producer_headers"]


@pytest.fixture
def buyer_headers():
    # Shared fallback: only safe for calls that do not exercise ownership.
    return TEST_USERS["buyer_headers"]
