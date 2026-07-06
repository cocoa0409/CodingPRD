"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def engagement_manager_headers():
    return TEST_USERS["engagement_manager_headers"]


@pytest.fixture
def bookkeeper_headers():
    return TEST_USERS["bookkeeper_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def tax_preparer_headers():
    return TEST_USERS["tax_preparer_headers"]
