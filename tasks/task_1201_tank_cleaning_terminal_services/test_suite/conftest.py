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
def operator_headers():
    return TEST_USERS["operator_headers"]


@pytest.fixture
def chemist_headers():
    return TEST_USERS["chemist_headers"]


@pytest.fixture
def ehs_headers():
    return TEST_USERS["ehs_headers"]


@pytest.fixture
def lab_headers():
    return TEST_USERS["lab_headers"]
