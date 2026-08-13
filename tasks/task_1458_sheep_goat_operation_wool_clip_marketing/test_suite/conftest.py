"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def ranch_manager_headers():
    return TEST_USERS["ranch_manager_headers"]


@pytest.fixture
def range_hand_headers():
    return TEST_USERS["range_hand_headers"]


@pytest.fixture
def wool_pool_operator_headers():
    return TEST_USERS["wool_pool_operator_headers"]


@pytest.fixture
def grazing_client_headers():
    return TEST_USERS["grazing_client_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
