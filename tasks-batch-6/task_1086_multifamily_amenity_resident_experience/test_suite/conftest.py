"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start/stop/restart-per-test) is owned by
prd-bench-local-runner; these fixtures only surface the API client and the
pre-built role headers. The database is empty at the start of every test.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def property_manager_headers():
    return TEST_USERS["property_manager_headers"]


@pytest.fixture
def front_desk_headers():
    return TEST_USERS["front_desk_headers"]


@pytest.fixture
def resident_headers():
    return TEST_USERS["resident_headers"]


@pytest.fixture
def vendor_headers():
    return TEST_USERS["vendor_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]
