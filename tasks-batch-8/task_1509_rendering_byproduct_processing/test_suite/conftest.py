"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner; the server is restarted
before every test, so each test starts against an empty database and builds its
own preconditions via the helpers in test_helpers.fixtures.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def plant_manager_headers():
    return TEST_USERS["plant_manager_headers"]


@pytest.fixture
def plant_manager_2_headers():
    return TEST_USERS["plant_manager_2_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance_officer_2_headers():
    return TEST_USERS["compliance_officer_2_headers"]


@pytest.fixture
def compliance_officer_3_headers():
    return TEST_USERS["compliance_officer_3_headers"]


@pytest.fixture
def regulator_headers():
    return TEST_USERS["regulator_headers"]


@pytest.fixture
def procurement_manager_headers():
    return TEST_USERS["procurement_manager_headers"]


@pytest.fixture
def route_dispatcher_headers():
    return TEST_USERS["route_dispatcher_headers"]


@pytest.fixture
def scalehouse_operator_headers():
    return TEST_USERS["scalehouse_operator_headers"]


@pytest.fixture
def production_supervisor_headers():
    return TEST_USERS["production_supervisor_headers"]


@pytest.fixture
def quality_lab_tech_headers():
    return TEST_USERS["quality_lab_tech_headers"]


@pytest.fixture
def sales_manager_headers():
    return TEST_USERS["sales_manager_headers"]


@pytest.fixture
def finance_analyst_headers():
    return TEST_USERS["finance_analyst_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]
