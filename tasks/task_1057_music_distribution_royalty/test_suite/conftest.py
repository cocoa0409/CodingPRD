"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def ops_headers():
    return TEST_USERS["ops_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_headers"]


@pytest.fixture
def finance_closer_headers():
    return TEST_USERS["finance_closer_headers"]


@pytest.fixture
def finance_approver_headers():
    return TEST_USERS["finance_approver_headers"]


@pytest.fixture
def finance_payer_headers():
    return TEST_USERS["finance_payer_headers"]


@pytest.fixture
def fan_headers():
    return TEST_USERS["fan_headers"]


@pytest.fixture
def artist_headers():
    """Shared Artist headers. Only for calls that do not exercise ownership."""
    return TEST_USERS["artist_headers"]


@pytest.fixture
def collaborator_headers():
    """Shared Collaborator headers. Only for calls that do not exercise ownership."""
    return TEST_USERS["collaborator_headers"]
