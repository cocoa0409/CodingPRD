"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def utility_admin_headers():
    return TEST_USERS["utility_admin_headers"]


@pytest.fixture
def operations_supervisor_headers():
    return TEST_USERS["operations_supervisor_headers"]


@pytest.fixture
def on_call_operator_headers():
    return TEST_USERS["on_call_operator_headers"]


@pytest.fixture
def operator_headers():
    return TEST_USERS["operator_headers"]


@pytest.fixture
def maintenance_planner_headers():
    return TEST_USERS["maintenance_planner_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def capital_program_manager_headers():
    return TEST_USERS["capital_program_manager_headers"]


@pytest.fixture
def scada_webhook_headers():
    return TEST_USERS["scada_webhook_headers"]


@pytest.fixture
def regulator_portal_headers():
    return TEST_USERS["regulator_portal_headers"]
