"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def harness_engineer_headers():
    return TEST_USERS["harness_engineer_headers"]


@pytest.fixture
def process_engineer_headers():
    return TEST_USERS["process_engineer_headers"]


@pytest.fixture
def quality_manager_headers():
    return TEST_USERS["quality_manager_headers"]


@pytest.fixture
def quality_inspector_headers():
    return TEST_USERS["quality_inspector_headers"]


@pytest.fixture
def production_planner_headers():
    return TEST_USERS["production_planner_headers"]


@pytest.fixture
def materials_clerk_headers():
    return TEST_USERS["materials_clerk_headers"]


@pytest.fixture
def line_operator_headers():
    return TEST_USERS["line_operator_headers"]


@pytest.fixture
def shipping_clerk_headers():
    return TEST_USERS["shipping_clerk_headers"]
