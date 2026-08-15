"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def em_headers():
    return TEST_USERS["emergency_manager_headers"]


@pytest.fixture
def ic_headers():
    return TEST_USERS["incident_commander_headers"]


@pytest.fixture
def pc_headers():
    return TEST_USERS["planning_chief_headers"]


@pytest.fixture
def lc_headers():
    return TEST_USERS["logistics_chief_headers"]


@pytest.fixture
def pio_headers():
    return TEST_USERS["public_information_officer_headers"]


@pytest.fixture
def lo_headers():
    return TEST_USERS["liaison_officer_headers"]


@pytest.fixture
def ha_headers():
    return TEST_USERS["hospital_administrator_headers"]


@pytest.fixture
def ocs_headers():
    """Shared OnCallStaff headers — only for calls that are not ownership-gated.
    Responding to a call-back request requires make_on_call_staff_headers(staff_id)."""
    return TEST_USERS["on_call_staff_headers"]


@pytest.fixture
def pa_headers():
    return TEST_USERS["platform_admin_headers"]
