"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def principal_headers():
    return TEST_USERS["principal_headers"]


@pytest.fixture
def principal_b_headers():
    return TEST_USERS["principal_b_headers"]


@pytest.fixture
def client_rep_headers():
    return TEST_USERS["client_rep_headers"]


@pytest.fixture
def other_client_rep_headers():
    return TEST_USERS["other_client_rep_headers"]


@pytest.fixture
def project_manager_headers():
    return TEST_USERS["project_manager_headers"]


@pytest.fixture
def staff_architect_headers():
    return TEST_USERS["staff_architect_headers"]


@pytest.fixture
def consultant_rep_headers():
    return TEST_USERS["consultant_rep_headers"]
