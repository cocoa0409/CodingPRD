"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def system_admin_headers():
    """SystemAdmin identity: board configuration, clock, and audit sampling."""
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def licensure_analyst_headers():
    """LicensureAnalyst identity: nurses, applications, credentials, renewals."""
    return TEST_USERS["licensure_analyst_headers"]


@pytest.fixture
def investigator_headers():
    """Investigator identity: complaint intake through disposition."""
    return TEST_USERS["investigator_headers"]


@pytest.fixture
def board_member_headers():
    """BoardMember identity: board decisions, monitoring offers, proceedings."""
    return TEST_USERS["board_member_headers"]


@pytest.fixture
def monitoring_coordinator_headers():
    """MonitoringCoordinator identity: monitoring events."""
    return TEST_USERS["monitoring_coordinator_headers"]


@pytest.fixture
def applicant_headers():
    """Applicant identity not bound to any nurse row.

    Ownership-gated calls must instead use `make_applicant_headers(nurse_id)`,
    because the `Applicant` role's `X-User-ID` is the acting nurse's own `id`.
    """
    return TEST_USERS["applicant_headers"]
