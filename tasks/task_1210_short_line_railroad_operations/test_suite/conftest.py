"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def crew_caller_headers():
    return TEST_USERS["crew_caller_headers"]


@pytest.fixture
def track_inspector_headers():
    return TEST_USERS["track_inspector_headers"]


@pytest.fixture
def settlement_clerk_headers():
    return TEST_USERS["settlement_clerk_headers"]


@pytest.fixture
def regulator_officer_headers():
    return TEST_USERS["regulator_officer_headers"]


@pytest.fixture
def grant_manager_headers():
    return TEST_USERS["grant_manager_headers"]


@pytest.fixture
def conductor_headers():
    """Fallback Conductor headers (opaque id) — non-ownership tests only."""
    return TEST_USERS["conductor_headers"]


@pytest.fixture
def customer_rep_headers():
    """Fallback CustomerRep headers (opaque id) — non-ownership tests only."""
    return TEST_USERS["customer_rep_headers"]
