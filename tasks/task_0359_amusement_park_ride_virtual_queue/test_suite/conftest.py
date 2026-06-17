"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def park_admin_headers():
    return TEST_USERS["park_admin_headers"]


@pytest.fixture
def ride_operator_headers():
    return TEST_USERS["ride_operator_headers"]


@pytest.fixture
def guest_app_headers():
    return TEST_USERS["guest_app_headers"]
