"""Pytest fixtures exposing the shared test infrastructure."""
import pytest

from test_helpers import (
    api_client, ApiClient, TEST_USERS, ANONYMOUS_HEADERS,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def gate_headers():
    return TEST_USERS["gate_staff_headers"]


@pytest.fixture
def gate_headers_2():
    return TEST_USERS["gate_staff_headers_2"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def finance_headers_2():
    return TEST_USERS["finance_officer_headers_2"]


@pytest.fixture
def anonymous_headers():
    return ANONYMOUS_HEADERS


@pytest.fixture
def organizer_headers():
    """Shared constant. Only for tests that never exercise ownership."""
    return TEST_USERS["organizer_headers"]


@pytest.fixture
def buyer_headers():
    """Shared constant. Only for tests that never exercise ownership."""
    return TEST_USERS["buyer_headers"]
