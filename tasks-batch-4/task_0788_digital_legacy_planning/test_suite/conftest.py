"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle, PYTHONPATH, and API_BASE_URL are owned by prd-bench-local-runner.
The harness restarts the server (empty database) before every individual test.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS, ADMIN_HEADERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def owner_headers():
    return TEST_USERS["owner_headers"]


@pytest.fixture
def deputy_headers():
    return TEST_USERS["deputy_headers"]


@pytest.fixture
def admin_headers():
    return ADMIN_HEADERS
