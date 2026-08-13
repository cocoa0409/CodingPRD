"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def location_manager_headers():
    return TEST_USERS["location_manager_headers"]


@pytest.fixture
def film_office_headers():
    return TEST_USERS["film_office_headers"]


@pytest.fixture
def owner_rep_headers():
    return TEST_USERS["owner_rep_headers"]
