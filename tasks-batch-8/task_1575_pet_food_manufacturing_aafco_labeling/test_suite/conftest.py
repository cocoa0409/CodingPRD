"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def formulation_scientist_headers():
    return TEST_USERS["formulation_scientist_headers"]


@pytest.fixture
def qa_approver_headers():
    return TEST_USERS["qa_approver_headers"]


@pytest.fixture
def quality_analyst_headers():
    return TEST_USERS["quality_analyst_headers"]


@pytest.fixture
def trial_coordinator_headers():
    return TEST_USERS["trial_coordinator_headers"]


@pytest.fixture
def production_planner_headers():
    return TEST_USERS["production_planner_headers"]


@pytest.fixture
def line_operator_headers():
    return TEST_USERS["line_operator_headers"]


@pytest.fixture
def regulatory_affairs_headers():
    return TEST_USERS["regulatory_affairs_headers"]


@pytest.fixture
def state_regulator_headers():
    return TEST_USERS["state_regulator_headers"]
