"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_1_headers():
    return TEST_USERS["admin_1_headers"]


@pytest.fixture
def admin_2_headers():
    return TEST_USERS["admin_2_headers"]


@pytest.fixture
def analyst_1_headers():
    return TEST_USERS["analyst_1_headers"]


@pytest.fixture
def analyst_2_headers():
    return TEST_USERS["analyst_2_headers"]


@pytest.fixture
def lead_1_headers():
    return TEST_USERS["lead_1_headers"]


@pytest.fixture
def lead_2_headers():
    return TEST_USERS["lead_2_headers"]


@pytest.fixture
def auditor_8_headers():
    return TEST_USERS["auditor_8_headers"]


@pytest.fixture
def auditor_9_headers():
    return TEST_USERS["auditor_9_headers"]


@pytest.fixture
def prime_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["prime_headers"]
