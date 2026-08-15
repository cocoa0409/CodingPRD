"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def scheme_admin_headers():
    return TEST_USERS["scheme_admin_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def client_admin_headers():
    return TEST_USERS["client_admin_headers"]


@pytest.fixture
def auditor_headers_fixture():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def decision_maker_headers():
    return TEST_USERS["decision_maker_headers"]
