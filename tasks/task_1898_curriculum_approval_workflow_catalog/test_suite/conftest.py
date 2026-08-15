"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def proposer_headers():
    return TEST_USERS["proposer_headers"]


@pytest.fixture
def chair_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["chair_headers"]


@pytest.fixture
def committee_headers():
    return TEST_USERS["committee_headers"]


@pytest.fixture
def senate_headers():
    return TEST_USERS["senate_headers"]


@pytest.fixture
def registrar_headers():
    return TEST_USERS["registrar_headers"]
