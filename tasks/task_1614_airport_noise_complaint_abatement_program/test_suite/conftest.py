"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import NO_AUTH_HEADERS, TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def noise_office_admin_headers():
    return TEST_USERS["noise_office_admin_headers"]


@pytest.fixture
def noise_analyst_headers():
    return TEST_USERS["noise_analyst_headers"]


@pytest.fixture
def community_liaison_headers():
    return TEST_USERS["community_liaison_headers"]


@pytest.fixture
def study_coordinator_headers():
    return TEST_USERS["study_coordinator_headers"]


@pytest.fixture
def board_member_headers():
    return TEST_USERS["board_member_headers"]


@pytest.fixture
def operator_rep_headers():
    return TEST_USERS["operator_rep_headers"]


@pytest.fixture
def complainant_headers():
    return TEST_USERS["complainant_headers"]


@pytest.fixture
def no_auth_headers():
    return dict(NO_AUTH_HEADERS)
