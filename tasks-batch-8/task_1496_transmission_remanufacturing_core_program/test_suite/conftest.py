"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def inventory_planner_headers():
    return TEST_USERS["inventory_planner_headers"]


@pytest.fixture
def reman_planner_headers():
    return TEST_USERS["reman_planner_headers"]


@pytest.fixture
def reman_technician_headers():
    return TEST_USERS["reman_technician_headers"]


@pytest.fixture
def calibrator_a_headers():
    return TEST_USERS["calibrator_a_headers"]


@pytest.fixture
def calibrator_b_headers():
    return TEST_USERS["calibrator_b_headers"]


@pytest.fixture
def dyno_operator_headers():
    return TEST_USERS["dyno_operator_headers"]


@pytest.fixture
def core_intake_clerk_headers():
    return TEST_USERS["core_intake_clerk_headers"]


@pytest.fixture
def core_inspector_headers():
    return TEST_USERS["core_inspector_headers"]


@pytest.fixture
def installer_headers():
    return TEST_USERS["installer_headers"]


@pytest.fixture
def warranty_adjuster_headers():
    return TEST_USERS["warranty_adjuster_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]
