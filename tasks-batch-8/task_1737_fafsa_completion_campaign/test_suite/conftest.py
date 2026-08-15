"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; tests assume the API is
already reachable at API_BASE_URL.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["campaign_admin_headers"]


@pytest.fixture
def coordinator_headers():
    """Shared fallback coordinator identity — non-ownership probes only."""
    return TEST_USERS["school_coordinator_headers"]


@pytest.fixture
def staff_member_headers():
    """Shared fallback staff identity — non-ownership probes only."""
    return TEST_USERS["staff_member_headers"]


@pytest.fixture
def specialist_headers():
    """Shared fallback specialist identity — non-ownership probes only."""
    return TEST_USERS["specialist_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["match_reviewer_headers"]


@pytest.fixture
def importer_headers():
    return TEST_USERS["data_importer_headers"]
