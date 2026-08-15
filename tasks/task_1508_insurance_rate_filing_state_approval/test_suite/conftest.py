"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def actuary_headers():
    return TEST_USERS["actuary_headers"]


@pytest.fixture
def actuary2_headers():
    return TEST_USERS["actuary2_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def regulator_headers():
    return TEST_USERS["regulator_headers"]


@pytest.fixture
def lead_headers():
    return TEST_USERS["lead_headers"]
