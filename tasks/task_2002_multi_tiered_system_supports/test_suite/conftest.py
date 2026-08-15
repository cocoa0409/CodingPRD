"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def district_coordinator_headers():
    return TEST_USERS["district_coordinator_headers"]


@pytest.fixture
def school_registrar_headers():
    return TEST_USERS["school_registrar_headers"]


@pytest.fixture
def teacher_headers():
    return TEST_USERS["teacher_headers"]


@pytest.fixture
def interventionist_role_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["interventionist_role_headers"]


@pytest.fixture
def team_lead_headers():
    return TEST_USERS["team_lead_headers"]


@pytest.fixture
def sped_director_headers():
    return TEST_USERS["sped_director_headers"]
