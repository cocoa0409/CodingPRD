"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def officer2_headers():
    return TEST_USERS["officer2_headers"]


@pytest.fixture
def utility_agent_headers():
    return TEST_USERS["utility_agent_headers"]


@pytest.fixture
def owner_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["owner_headers"]


@pytest.fixture
def tenant_rep_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["tenant_rep_headers"]


@pytest.fixture
def verifier_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["verifier_headers"]
