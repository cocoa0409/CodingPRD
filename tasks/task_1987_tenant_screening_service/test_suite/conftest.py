"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def screener_headers():
    return TEST_USERS["screener_headers"]


@pytest.fixture
def screener_1_headers():
    return TEST_USERS["screener_1_headers"]


@pytest.fixture
def screener_2_headers():
    return TEST_USERS["screener_2_headers"]


@pytest.fixture
def screener_3_headers():
    return TEST_USERS["screener_3_headers"]


@pytest.fixture
def landlord_headers():
    return TEST_USERS["landlord_headers"]


@pytest.fixture
def applicant_headers():
    return TEST_USERS["applicant_headers"]
