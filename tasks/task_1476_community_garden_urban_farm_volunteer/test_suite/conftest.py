"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def admin_headers():
    """GardenAdmin (opaque identity)."""
    return TEST_USERS["admin_headers"]


@pytest.fixture
def coordinator_headers():
    """Coordinator shared identity — only for calls with no ownership compare."""
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def volunteer_headers():
    """Volunteer shared identity — only for calls with no ownership compare."""
    return TEST_USERS["volunteer_headers"]


@pytest.fixture
def group_leader_headers():
    """GroupLeader shared identity — only for calls with no ownership compare."""
    return TEST_USERS["group_leader_headers"]


@pytest.fixture
def officer_headers():
    """FoodSafetyOfficer shared identity — only for calls with no ownership compare."""
    return TEST_USERS["officer_headers"]
