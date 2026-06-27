"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def parent_headers():
    return TEST_USERS["parent_headers"]


@pytest.fixture
def child_headers():
    return TEST_USERS["child_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]
