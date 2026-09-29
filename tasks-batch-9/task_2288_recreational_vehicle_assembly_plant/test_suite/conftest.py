"""Pytest fixtures exposing the plant test infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def plant_admin_headers():
    return TEST_USERS["plant_admin_headers"]


@pytest.fixture
def scheduler_headers():
    return TEST_USERS["production_scheduler_headers"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["line_supervisor_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["quality_inspector_headers"]


@pytest.fixture
def inspector_2_headers():
    return TEST_USERS["quality_inspector_2_headers"]


@pytest.fixture
def warranty_admin_headers():
    return TEST_USERS["warranty_admin_headers"]


@pytest.fixture
def warranty_admin_2_headers():
    return TEST_USERS["warranty_admin_2_headers"]


@pytest.fixture
def recall_coordinator_headers():
    return TEST_USERS["recall_coordinator_headers"]
