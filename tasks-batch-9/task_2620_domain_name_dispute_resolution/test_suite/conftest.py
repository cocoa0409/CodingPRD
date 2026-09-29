"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def provider_admin_headers():
    return TEST_USERS["provider_admin_headers"]


@pytest.fixture
def case_manager_headers():
    return TEST_USERS["case_manager_headers"]


@pytest.fixture
def case_manager_two_headers():
    return TEST_USERS["case_manager_two_headers"]


@pytest.fixture
def complainant_headers():
    return TEST_USERS["complainant_headers"]


@pytest.fixture
def respondent_headers():
    return TEST_USERS["respondent_headers"]


@pytest.fixture
def panelist_headers():
    return TEST_USERS["panelist_headers"]


@pytest.fixture
def registrar_agent_headers():
    return TEST_USERS["registrar_agent_headers"]
