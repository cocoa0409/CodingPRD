"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin"]


@pytest.fixture
def rep_headers():
    return TEST_USERS["rep"]


@pytest.fixture
def board_director_headers():
    return TEST_USERS["board_director"]


@pytest.fixture
def board_secretary_headers():
    return TEST_USERS["board_secretary"]


@pytest.fixture
def rate_analyst_headers():
    return TEST_USERS["rate_analyst"]


@pytest.fixture
def billing_clerk_headers():
    return TEST_USERS["billing_clerk"]


@pytest.fixture
def field_ops_headers():
    return TEST_USERS["field_ops"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher"]


@pytest.fixture
def legal_counsel_headers():
    return TEST_USERS["legal_counsel"]
