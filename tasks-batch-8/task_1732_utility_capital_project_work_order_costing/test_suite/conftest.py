"""Pytest fixtures exposing test_helpers infrastructure."""
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
def engineer_headers():
    return TEST_USERS["engineer_headers"]


@pytest.fixture
def engineer2_headers():
    return TEST_USERS["engineer2_headers"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["supervisor_headers"]


@pytest.fixture
def supervisor2_headers():
    return TEST_USERS["supervisor2_headers"]


@pytest.fixture
def controller_headers():
    return TEST_USERS["controller_headers"]


@pytest.fixture
def controller2_headers():
    return TEST_USERS["controller2_headers"]


@pytest.fixture
def clerk_headers():
    return TEST_USERS["clerk_headers"]


@pytest.fixture
def rates_headers():
    return TEST_USERS["rates_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
