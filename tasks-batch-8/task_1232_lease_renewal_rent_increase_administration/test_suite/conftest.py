"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by the runner; tests assume the API is reachable
at API_BASE_URL and the database is empty at the start of every test.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def rd_1_headers():
    return TEST_USERS["rd_1_headers"]


@pytest.fixture
def pm_1_headers():
    return TEST_USERS["pm_1_headers"]


@pytest.fixture
def pm_2_headers():
    return TEST_USERS["pm_2_headers"]


@pytest.fixture
def la_1_headers():
    return TEST_USERS["la_1_headers"]


@pytest.fixture
def la_2_headers():
    return TEST_USERS["la_2_headers"]


@pytest.fixture
def resident_headers():
    return TEST_USERS["resident_headers"]
