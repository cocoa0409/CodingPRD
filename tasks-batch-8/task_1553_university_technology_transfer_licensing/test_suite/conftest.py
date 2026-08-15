"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def inventor_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["inventor_headers"]


@pytest.fixture
def tto_headers():
    return TEST_USERS["tto_headers"]


@pytest.fixture
def licensing_manager_headers():
    return TEST_USERS["licensing_manager_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance_director_headers():
    return TEST_USERS["compliance_director_headers"]


@pytest.fixture
def finance_officer_headers():
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def finance_director_headers():
    return TEST_USERS["finance_director_headers"]


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]
