"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def committee_admin_headers():
    return TEST_USERS["committee_admin_headers"]


@pytest.fixture
def entry_office_headers():
    return TEST_USERS["entry_office_headers"]


@pytest.fixture
def veterinarian_headers():
    return TEST_USERS["veterinarian_headers"]


@pytest.fixture
def box_office_headers():
    return TEST_USERS["box_office_headers"]
