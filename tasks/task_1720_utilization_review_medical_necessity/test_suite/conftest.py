"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def ur_nurse_headers():
    return TEST_USERS["ur_nurse_headers"]


@pytest.fixture
def payer_reviewer_headers():
    return TEST_USERS["payer_reviewer_headers"]


@pytest.fixture
def case_manager_headers():
    return TEST_USERS["case_manager_headers"]


@pytest.fixture
def appeals_coordinator_headers():
    return TEST_USERS["appeals_coordinator_headers"]


@pytest.fixture
def ur_director_headers():
    return TEST_USERS["ur_director_headers"]


@pytest.fixture
def attending_headers():
    # AttendingPhysician is entity-backed: usable only for calls that are not
    # ownership-gated. Ownership-gated calls build per-instance headers.
    return TEST_USERS["attending_headers"]


@pytest.fixture
def advisor_headers():
    # PhysicianAdvisor is entity-backed: usable only for calls that are not
    # ownership-gated. SoD-gated calls build per-instance headers.
    return TEST_USERS["advisor_headers"]
