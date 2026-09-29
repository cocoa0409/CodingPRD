"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def grower_manager_headers():
    return TEST_USERS["grower_manager_headers"]


@pytest.fixture
def irrigation_tech_headers():
    return TEST_USERS["irrigation_tech_headers"]


@pytest.fixture
def quality_inspector_headers():
    return TEST_USERS["quality_inspector_headers"]


@pytest.fixture
def second_quality_inspector_headers():
    return TEST_USERS["second_quality_inspector_headers"]


@pytest.fixture
def ipm_scout_headers():
    return TEST_USERS["ipm_scout_headers"]


@pytest.fixture
def ipm_coordinator_headers():
    return TEST_USERS["ipm_coordinator_headers"]


@pytest.fixture
def harvest_supervisor_headers():
    return TEST_USERS["harvest_supervisor_headers"]
