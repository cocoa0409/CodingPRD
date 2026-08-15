"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def practice_admin_headers():
    return TEST_USERS["practice_admin_headers"]


@pytest.fixture
def parent_headers():
    return TEST_USERS["parent_headers"]


@pytest.fixture
def consultant_headers():
    return TEST_USERS["consultant_headers"]
