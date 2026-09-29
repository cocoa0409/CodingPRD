"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def plant_admin_headers():
    return TEST_USERS["plant_admin_headers"]


@pytest.fixture
def design_engineer_headers():
    return TEST_USERS["design_engineer_headers"]


@pytest.fixture
def reliability_engineer_headers():
    return TEST_USERS["reliability_engineer_headers"]


@pytest.fixture
def reliability_engineer_2_headers():
    return TEST_USERS["reliability_engineer_2_headers"]


@pytest.fixture
def certification_engineer_headers():
    return TEST_USERS["certification_engineer_headers"]


@pytest.fixture
def certification_engineer_2_headers():
    return TEST_USERS["certification_engineer_2_headers"]


@pytest.fixture
def regulatory_auditor_headers():
    return TEST_USERS["regulatory_auditor_headers"]


@pytest.fixture
def supply_planner_headers():
    return TEST_USERS["supply_planner_headers"]


@pytest.fixture
def production_planner_headers():
    return TEST_USERS["production_planner_headers"]


@pytest.fixture
def production_technician_headers():
    return TEST_USERS["production_technician_headers"]


@pytest.fixture
def quality_technician_headers():
    return TEST_USERS["quality_technician_headers"]


@pytest.fixture
def quality_technician_2_headers():
    return TEST_USERS["quality_technician_2_headers"]


@pytest.fixture
def distributor_rep_headers():
    return TEST_USERS["distributor_rep_headers"]


@pytest.fixture
def distributor_rep_2_headers():
    return TEST_USERS["distributor_rep_2_headers"]


@pytest.fixture
def distributor_rep_3_headers():
    return TEST_USERS["distributor_rep_3_headers"]


@pytest.fixture
def warranty_analyst_headers():
    return TEST_USERS["warranty_analyst_headers"]
