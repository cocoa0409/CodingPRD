"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally; each
    test still starts against a freshly restarted, empty server."""
    return api_client


@pytest.fixture
def ops_headers():
    return TEST_USERS["operations_director_headers"]


@pytest.fixture
def coordinator_headers():
    """Shared FacilityCoordinator fallback — only for non-ownership probes."""
    return TEST_USERS["facility_coordinator_headers"]


@pytest.fixture
def technologist_headers():
    """Shared Technologist fallback — only for non-ownership probes."""
    return TEST_USERS["technologist_headers"]


@pytest.fixture
def radiologist_headers():
    return TEST_USERS["reading_radiologist_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_officer_headers"]
