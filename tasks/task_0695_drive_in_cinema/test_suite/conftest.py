"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def operator_headers():
    return TEST_USERS["venue_operator_headers"]


@pytest.fixture
def gate_headers():
    return TEST_USERS["gate_attendant_headers"]


@pytest.fixture
def patron_headers():
    return TEST_USERS["patron_headers"]
