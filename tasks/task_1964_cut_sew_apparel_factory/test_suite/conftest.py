"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def merchandiser_headers():
    return TEST_USERS["merchandiser_headers"]


@pytest.fixture
def materials_planner_headers():
    return TEST_USERS["materials_planner_headers"]


@pytest.fixture
def cutting_manager_headers():
    return TEST_USERS["cutting_manager_headers"]


@pytest.fixture
def production_planner_headers():
    return TEST_USERS["production_planner_headers"]


@pytest.fixture
def line_supervisor_headers():
    return TEST_USERS["line_supervisor_headers"]


@pytest.fixture
def quality_inspector_headers():
    return TEST_USERS["quality_inspector_headers"]


@pytest.fixture
def payroll_clerk_headers():
    return TEST_USERS["payroll_clerk_headers"]


@pytest.fixture
def plant_manager_headers():
    return TEST_USERS["plant_manager_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]
