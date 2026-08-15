"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def shop_admin_headers():
    return TEST_USERS["shop_admin_headers"]


@pytest.fixture
def qc_manager_headers():
    return TEST_USERS["qc_manager_headers"]


@pytest.fixture
def weld_lead_headers():
    return TEST_USERS["weld_lead_headers"]


@pytest.fixture
def welder_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["welder_headers"]


@pytest.fixture
def cwi_headers():
    return TEST_USERS["cwi_headers"]


@pytest.fixture
def material_controller_headers():
    return TEST_USERS["material_controller_headers"]


@pytest.fixture
def production_planner_headers():
    return TEST_USERS["production_planner_headers"]


@pytest.fixture
def quality_inspector_headers():
    return TEST_USERS["quality_inspector_headers"]


@pytest.fixture
def shipping_clerk_headers():
    return TEST_USERS["shipping_clerk_headers"]
