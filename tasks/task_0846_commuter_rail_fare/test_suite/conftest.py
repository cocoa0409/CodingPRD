"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["fareadmin_headers"]


@pytest.fixture
def conductor_headers():
    return TEST_USERS["conductor_headers"]


@pytest.fixture
def passenger_headers():
    return TEST_USERS["passenger_headers"]
