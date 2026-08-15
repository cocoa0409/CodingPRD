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
def supervisor_headers():
    return TEST_USERS["supervisor_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def inspector_b_headers():
    return TEST_USERS["inspector_b_headers"]


@pytest.fixture
def operator_headers():
    return TEST_USERS["operator_headers"]


@pytest.fixture
def operator_b_headers():
    return TEST_USERS["operator_b_headers"]


@pytest.fixture
def accountant_headers():
    return TEST_USERS["accountant_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def officer_b_headers():
    return TEST_USERS["officer_b_headers"]


@pytest.fixture
def officer_c_headers():
    return TEST_USERS["officer_c_headers"]
