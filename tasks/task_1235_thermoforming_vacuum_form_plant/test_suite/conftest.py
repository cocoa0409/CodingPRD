"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; this module only bridges
test_helpers into pytest fixtures.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def planner_headers():
    return TEST_USERS["materials_planner_headers"]


@pytest.fixture
def tooling_engineer_headers():
    return TEST_USERS["tooling_engineer_headers"]


@pytest.fixture
def packaging_engineer_headers():
    return TEST_USERS["packaging_engineer_headers"]


@pytest.fixture
def plant_manager_headers():
    return TEST_USERS["plant_manager_headers"]


@pytest.fixture
def scheduler_headers():
    return TEST_USERS["production_scheduler_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["quality_inspector_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]
