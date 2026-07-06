"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def booker_headers():
    return TEST_USERS["booker_headers"]


@pytest.fixture
def box_office_headers():
    return TEST_USERS["box_office_headers"]


@pytest.fixture
def floor_manager_headers():
    return TEST_USERS["floor_manager_headers"]


@pytest.fixture
def patron_headers():
    return TEST_USERS["patron_headers"]


@pytest.fixture
def performer_headers():
    return TEST_USERS["performer_headers"]
