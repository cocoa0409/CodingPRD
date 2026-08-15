"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def biologist_headers():
    return TEST_USERS["biologist_headers"]


@pytest.fixture
def atc_headers():
    return TEST_USERS["atc_headers"]


@pytest.fixture
def regulator_headers():
    return TEST_USERS["regulator_headers"]
