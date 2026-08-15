"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def member_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["member_headers"]


@pytest.fixture
def membership_officer_headers():
    return TEST_USERS["membership_officer_headers"]


@pytest.fixture
def membership_officer_2_headers():
    return TEST_USERS["membership_officer_2_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance_officer_2_headers():
    return TEST_USERS["compliance_officer_2_headers"]


@pytest.fixture
def regulator_headers():
    return TEST_USERS["regulator_headers"]


@pytest.fixture
def board_director_headers():
    return TEST_USERS["board_director_headers"]


@pytest.fixture
def operations_officer_headers():
    return TEST_USERS["operations_officer_headers"]


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]
