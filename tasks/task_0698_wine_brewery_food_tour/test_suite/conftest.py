"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start/stop/restart-before-each-test) is owned by
prd-bench-local-runner; these fixtures only expose the API client and role
headers. The runner sets API_BASE_URL and PYTHONPATH.
"""
import pytest
from test_helpers import (
    api_client, ApiClient, TEST_USERS, ANONYMOUS_HEADERS,
    make_operator_headers, make_guide_headers,
    make_partner_venue_headers, make_guest_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def operator_headers():
    return TEST_USERS["operator_headers"]


@pytest.fixture
def guide_headers():
    return TEST_USERS["guide_headers"]


@pytest.fixture
def partner_venue_headers():
    return TEST_USERS["partner_venue_headers"]


@pytest.fixture
def guest_headers():
    return TEST_USERS["guest_headers"]


@pytest.fixture
def anonymous_headers():
    return ANONYMOUS_HEADERS
