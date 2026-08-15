"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def gm_headers():
    return TEST_USERS["gm_headers"]


@pytest.fixture
def sm_1_headers():
    return TEST_USERS["sm_1_headers"]


@pytest.fixture
def sm_2_headers():
    return TEST_USERS["sm_2_headers"]


@pytest.fixture
def fdl_headers():
    return TEST_USERS["fdl_headers"]


@pytest.fixture
def cash_1_headers():
    return TEST_USERS["cash_1_headers"]


@pytest.fixture
def cash_2_headers():
    return TEST_USERS["cash_2_headers"]
