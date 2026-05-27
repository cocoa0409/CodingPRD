"""Pytest fixtures exposing test_helpers infrastructure to the test suite.

Server lifecycle is managed by prd-bench-local-runner — the runner restarts
the server before every individual pytest test, so every test starts against
an empty database.
"""
import pytest

from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
    make_member_services_headers,
    make_loyalty_manager_headers,
    make_compliance_officer_headers,
    make_member_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle handled by the runner."""
    return api_client


@pytest.fixture
def member_services_headers():
    return TEST_USERS["member_services_headers"]


@pytest.fixture
def loyalty_manager_headers():
    return TEST_USERS["loyalty_manager_headers"]


@pytest.fixture
def loyalty_manager_alice_headers():
    return TEST_USERS["loyalty_manager_alice_headers"]


@pytest.fixture
def loyalty_manager_bob_headers():
    return TEST_USERS["loyalty_manager_bob_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def member_headers_fallback():
    """Fallback Member headers for non-ownership tests; ownership-gated calls
    must use make_member_headers(member_id)."""
    return TEST_USERS["member_headers"]
