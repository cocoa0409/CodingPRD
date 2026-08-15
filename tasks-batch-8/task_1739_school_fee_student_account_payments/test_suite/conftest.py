"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def bookkeeper_headers():
    return TEST_USERS["bookkeeper_headers"]


@pytest.fixture
def family_headers():
    return TEST_USERS["family_headers"]


@pytest.fixture
def superintendent_headers():
    return TEST_USERS["superintendent_headers"]
