"""Pytest fixtures exposing the plant test_helpers infrastructure."""

import pytest
from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def plant_admin_headers():
    return TEST_USERS["plant_admin_headers"]


@pytest.fixture
def production_supervisor_headers():
    return TEST_USERS["production_supervisor_headers"]


@pytest.fixture
def qc_technician_headers():
    return TEST_USERS["qc_technician_headers"]


@pytest.fixture
def quality_engineer_headers():
    return TEST_USERS["quality_engineer_headers"]


@pytest.fixture
def yard_foreman_headers():
    return TEST_USERS["yard_foreman_headers"]


@pytest.fixture
def permit_coordinator_headers():
    return TEST_USERS["permit_coordinator_headers"]
