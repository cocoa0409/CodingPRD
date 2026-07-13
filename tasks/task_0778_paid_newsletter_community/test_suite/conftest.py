"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def creator_headers():
    return TEST_USERS["creator_headers"]


@pytest.fixture
def creator_2_headers():
    return TEST_USERS["creator_2_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]


@pytest.fixture
def moderator_headers():
    return TEST_USERS["moderator_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]
