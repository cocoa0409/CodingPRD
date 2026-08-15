"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the test runner."""
    return api_client


@pytest.fixture
def admin_headers():
    """PlanAdministrator headers (X-User-ID admin-1)."""
    return TEST_USERS["admin_headers"]


@pytest.fixture
def admin2_headers():
    """A second PlanAdministrator identity (X-User-ID admin-2)."""
    return TEST_USERS["admin2_headers"]


@pytest.fixture
def fiduciary_headers():
    """IndependentFiduciary headers (X-User-ID fid-1)."""
    return TEST_USERS["fiduciary_headers"]


@pytest.fixture
def recordkeeper_headers():
    """Recordkeeper headers (X-User-ID rk-1)."""
    return TEST_USERS["recordkeeper_headers"]


@pytest.fixture
def participant_headers():
    """Participant-role fallback headers for non-ownership assertions only."""
    return TEST_USERS["participant_headers"]
