"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def security_officer_headers():
    return TEST_USERS["security_officer_headers"]


@pytest.fixture
def lobby_attendant_headers():
    return TEST_USERS["lobby_attendant_headers"]


@pytest.fixture
def host_headers():
    return TEST_USERS["host_headers"]
