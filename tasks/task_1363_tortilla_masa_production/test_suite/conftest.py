"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def plant_manager_headers():
    return TEST_USERS["plant_manager_headers"]


@pytest.fixture
def miller_operator_headers():
    return TEST_USERS["miller_operator_headers"]


@pytest.fixture
def quality_inspector_headers():
    return TEST_USERS["quality_inspector_headers"]


@pytest.fixture
def line_scheduler_headers():
    return TEST_USERS["line_scheduler_headers"]


@pytest.fixture
def sanitation_tech_headers():
    return TEST_USERS["sanitation_tech_headers"]


@pytest.fixture
def packaging_lead_headers():
    return TEST_USERS["packaging_lead_headers"]


@pytest.fixture
def route_dispatcher_headers():
    return TEST_USERS["route_dispatcher_headers"]
