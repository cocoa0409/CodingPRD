"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def agent_headers():
    return TEST_USERS["agent_headers"]


@pytest.fixture
def borrower_headers():
    return TEST_USERS["borrower_headers"]


@pytest.fixture
def participant_headers():
    return TEST_USERS["participant_headers"]
