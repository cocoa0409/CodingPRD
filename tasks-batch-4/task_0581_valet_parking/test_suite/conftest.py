"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["supervisor_headers"]


@pytest.fixture
def cashier_headers():
    return TEST_USERS["cashier_headers"]


@pytest.fixture
def attendant_headers():
    return TEST_USERS["attendant_headers"]


@pytest.fixture
def unknown_role_headers():
    return TEST_USERS["unknown_role_headers"]
