"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def admin2_headers():
    return TEST_USERS["admin2_headers"]


@pytest.fixture
def admin3_headers():
    return TEST_USERS["admin3_headers"]


@pytest.fixture
def donor_coordinator_headers():
    """Shared DonorCoordinator headers — only for calls that are NOT
    ownership-gated (e.g. malformed-payload probes)."""
    return TEST_USERS["donor_coordinator_headers"]


@pytest.fixture
def volunteer_driver_headers():
    """Shared VolunteerDriver headers — non-ownership calls only."""
    return TEST_USERS["volunteer_driver_headers"]


@pytest.fixture
def agency_coordinator_headers():
    """Shared AgencyCoordinator headers — non-ownership calls only."""
    return TEST_USERS["agency_coordinator_headers"]
