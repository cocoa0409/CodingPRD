"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def farm_manager_headers():
    return TEST_USERS["farm_manager_headers"]


@pytest.fixture
def grower_headers():
    return TEST_USERS["grower_headers"]


@pytest.fixture
def sanitation_lead_headers():
    return TEST_USERS["sanitation_lead_headers"]


@pytest.fixture
def quality_assurance_headers():
    return TEST_USERS["quality_assurance_headers"]


@pytest.fixture
def contracts_manager_headers():
    return TEST_USERS["contracts_manager_headers"]


@pytest.fixture
def labor_planner_headers():
    return TEST_USERS["labor_planner_headers"]


@pytest.fixture
def worker_headers():
    return TEST_USERS["worker_headers"]
