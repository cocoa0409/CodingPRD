"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def ops_headers():
    return TEST_USERS["ops_headers"]


@pytest.fixture
def member_headers():
    """Shared Member headers — only for calls that are not ownership-gated."""
    return TEST_USERS["member_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]
