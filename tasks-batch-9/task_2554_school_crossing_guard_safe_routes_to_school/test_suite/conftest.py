"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, api_client
from test_helpers.test_users import TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    """ProgramAdmin identity headers."""
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def traffic_engineer_headers():
    """TrafficEngineer identity headers."""
    return TEST_USERS["traffic_engineer_headers"]


@pytest.fixture
def second_traffic_engineer_headers():
    """A second, distinct TrafficEngineer identity."""
    return TEST_USERS["second_traffic_engineer_headers"]


@pytest.fixture
def crossing_supervisor_headers():
    """CrossingSupervisor identity headers."""
    return TEST_USERS["crossing_supervisor_headers"]


@pytest.fixture
def public_reporter_headers():
    """PublicReporter identity headers."""
    return TEST_USERS["public_reporter_headers"]


@pytest.fixture
def crossing_guard_headers():
    """CrossingGuard headers with a placeholder identity. Ownership-gated
    calls must build headers from the real Guard.id instead."""
    return TEST_USERS["crossing_guard_headers"]


@pytest.fixture
def school_liaison_headers():
    """SchoolLiaison headers with a placeholder identity. School-scoped
    calls must build headers from the real School.id instead."""
    return TEST_USERS["school_liaison_headers"]
