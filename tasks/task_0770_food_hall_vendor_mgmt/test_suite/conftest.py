"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start/stop/restart-before-each-test) is owned by
prd-bench-local-runner; these fixtures only expose the API client and role
headers. The runner sets API_BASE_URL and PYTHONPATH.
"""
import pytest
from test_helpers import (
    api_client, ApiClient, TEST_USERS, ANONYMOUS_HEADERS,
    make_vendor_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def hall_manager_headers():
    return TEST_USERS["hall_manager_headers"]


@pytest.fixture
def health_inspector_headers():
    return TEST_USERS["health_inspector_headers"]


@pytest.fixture
def pos_operator_headers():
    return TEST_USERS["pos_operator_headers"]


@pytest.fixture
def vendor_headers():
    return TEST_USERS["vendor_headers"]


@pytest.fixture
def anonymous_headers():
    return ANONYMOUS_HEADERS
