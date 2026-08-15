"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def reserve_specialist_headers():
    return TEST_USERS["reserve_specialist_headers"]


@pytest.fixture
def board_member_headers():
    return TEST_USERS["board_member_headers"]


@pytest.fixture
def association_manager_headers():
    return TEST_USERS["association_manager_headers"]
