"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def renter_headers():
    # Shared fallback: only safe for tests that do not exercise ownership
    # (self-registration, 400/401/403 checks). Ownership-gated calls must use
    # make_renter_headers(renter_id) with the real Renter id.
    return TEST_USERS["renter_headers"]


@pytest.fixture
def dock_staff_headers():
    return TEST_USERS["dock_staff_headers"]


@pytest.fixture
def fleet_manager_headers():
    return TEST_USERS["fleet_manager_headers"]


@pytest.fixture
def mechanic_headers():
    return TEST_USERS["mechanic_headers"]
