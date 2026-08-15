"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def consultant_headers():
    return TEST_USERS["consultant_headers"]


@pytest.fixture
def facility_manager_headers():
    return TEST_USERS["facility_manager_headers"]


@pytest.fixture
def capital_planner_headers():
    return TEST_USERS["capital_planner_headers"]


@pytest.fixture
def approver_headers():
    return TEST_USERS["approver_headers"]
