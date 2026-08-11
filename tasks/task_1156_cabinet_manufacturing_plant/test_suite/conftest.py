"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def plant_admin_headers():
    return TEST_USERS["plant_admin_headers"]


@pytest.fixture
def dealer_headers():
    # Entity-backed role: shared constant is only valid for tests whose
    # success does not depend on owning the subject resource.
    return TEST_USERS["dealer_headers"]


@pytest.fixture
def engineer_headers():
    return TEST_USERS["engineer_headers"]


@pytest.fixture
def finish_supervisor_headers():
    return TEST_USERS["finish_supervisor_headers"]


@pytest.fixture
def production_planner_headers():
    return TEST_USERS["production_planner_headers"]


@pytest.fixture
def shipping_coordinator_headers():
    return TEST_USERS["shipping_coordinator_headers"]
