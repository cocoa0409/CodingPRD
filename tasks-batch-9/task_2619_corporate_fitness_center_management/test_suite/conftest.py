"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client
from test_helpers import fixtures as scenarios


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def operator_admin_headers():
    return TEST_USERS["operator_admin_headers"]


@pytest.fixture
def compliance_auditor_headers():
    return TEST_USERS["compliance_auditor_headers"]


@pytest.fixture
def site_manager_headers():
    return TEST_USERS["site_manager_headers"]


@pytest.fixture
def fitness_staff_headers():
    return TEST_USERS["fitness_staff_headers"]


@pytest.fixture
def client_sponsor_headers():
    return TEST_USERS["client_sponsor_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]


@pytest.fixture(autouse=True)
def _reset_helper_sequence():
    """Each test runs against a fresh database, so the helper-side uniqueness
    counter restarts with it."""
    scenarios.reset_sequence()
    yield


@pytest.fixture
def clock():
    """Pin the logical clock to its documented startup instant."""
    scenarios.set_clock()
    return scenarios.set_clock


@pytest.fixture
def draft_contract():
    """Clock pinned, one DRAFT contract with a credentialed site manager."""
    return scenarios.setup_draft_contract()


@pytest.fixture
def active_contract():
    """An ACTIVE contract with a credentialed site manager."""
    return scenarios.setup_active_contract()


@pytest.fixture
def active_site():
    """An ACTIVE contract with one OPEN room and one READY defibrillator."""
    return scenarios.setup_active_site()


@pytest.fixture
def active_program():
    """An ACTIVE contract, room, defibrillator, credentialed instructor and one
    ACTIVE offering led by that instructor."""
    return scenarios.setup_active_program()
