"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def legal_headers():
    return TEST_USERS["legal_headers"]


@pytest.fixture
def eng_manager_headers():
    return TEST_USERS["eng_manager_headers"]


@pytest.fixture
def security_headers():
    return TEST_USERS["security_headers"]


@pytest.fixture
def release_manager_headers():
    return TEST_USERS["release_manager_headers"]


@pytest.fixture
def ciso_headers():
    return TEST_USERS["ciso_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]
