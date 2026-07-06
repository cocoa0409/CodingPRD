"""Pytest fixtures exposing test_helpers infrastructure.

The server lifecycle (start/stop/restart-before-each-test) is owned by
prd-bench-local-runner; these fixtures only expose the API client and role
headers. The database is empty at the start of every test.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def ops_headers():
    return TEST_USERS["ops_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]
