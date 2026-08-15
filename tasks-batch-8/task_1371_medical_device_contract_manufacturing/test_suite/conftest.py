"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def quality_engineer_headers():
    return TEST_USERS["quality_engineer_headers"]


@pytest.fixture
def quality_manager_headers():
    return TEST_USERS["quality_manager_headers"]


@pytest.fixture
def production_operator_headers():
    return TEST_USERS["production_operator_headers"]


@pytest.fixture
def supplier_quality_engineer_headers():
    return TEST_USERS["supplier_quality_engineer_headers"]


@pytest.fixture
def regulatory_affairs_headers():
    return TEST_USERS["regulatory_affairs_headers"]


@pytest.fixture
def qms_admin_headers():
    return TEST_USERS["qms_admin_headers"]
