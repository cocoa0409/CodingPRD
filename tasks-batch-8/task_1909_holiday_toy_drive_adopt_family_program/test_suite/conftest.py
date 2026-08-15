"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (restart-before-every-test) is managed by the runner; each
test starts against an empty database and builds its own preconditions.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client bound to API_BASE_URL by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def admin2_headers():
    return TEST_USERS["admin2_headers"]


@pytest.fixture
def caseworker_headers():
    return TEST_USERS["caseworker_headers"]


@pytest.fixture
def caseworker2_headers():
    return TEST_USERS["caseworker2_headers"]


@pytest.fixture
def caseworker3_headers():
    return TEST_USERS["caseworker3_headers"]


@pytest.fixture
def volunteer_headers():
    return TEST_USERS["volunteer_headers"]


@pytest.fixture
def coordinator_headers():
    """Shared fallback for AgencyCoordinator — non-ownership tests only."""
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def donor_headers():
    """Shared fallback for Donor — non-ownership tests only."""
    return TEST_USERS["donor_headers"]
