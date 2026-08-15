"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def network_ops_headers():
    return TEST_USERS["network_ops_headers"]


@pytest.fixture
def sales_manager_headers():
    return TEST_USERS["sales_manager_headers"]


@pytest.fixture
def sales_manager_2_headers():
    return TEST_USERS["sales_manager_2_headers"]


@pytest.fixture
def theater_ops_headers():
    return TEST_USERS["theater_ops_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def auditor_2_headers():
    return TEST_USERS["auditor_2_headers"]
