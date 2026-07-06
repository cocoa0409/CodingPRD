"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def party_headers():
    return TEST_USERS["party_headers"]


@pytest.fixture
def neutral_headers():
    return TEST_USERS["neutral_headers"]


@pytest.fixture
def unknown_headers():
    return TEST_USERS["unknown_headers"]
