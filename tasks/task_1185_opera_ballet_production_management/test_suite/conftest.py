"""Pytest fixtures exposing test_helpers infrastructure.

The server lifecycle is managed by the runner; tests assume the API is
already reachable at API_BASE_URL.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def production_manager_headers():
    return TEST_USERS["production_manager_headers"]


@pytest.fixture
def casting_director_headers():
    return TEST_USERS["casting_director_headers"]


@pytest.fixture
def contracts_officer_headers():
    return TEST_USERS["contracts_officer_headers"]


@pytest.fixture
def technical_director_headers():
    return TEST_USERS["technical_director_headers"]


@pytest.fixture
def box_office_manager_headers():
    return TEST_USERS["box_office_manager_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]
