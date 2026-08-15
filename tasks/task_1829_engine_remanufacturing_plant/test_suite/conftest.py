"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def plant_admin_headers():
    return TEST_USERS["plant_admin_headers"]


@pytest.fixture
def core_inspector_headers():
    return TEST_USERS["core_inspector_headers"]


@pytest.fixture
def shop_technician_headers():
    return TEST_USERS["shop_technician_headers"]


@pytest.fixture
def quality_inspector_headers():
    return TEST_USERS["quality_inspector_headers"]


@pytest.fixture
def warranty_adjuster_headers():
    return TEST_USERS["warranty_adjuster_headers"]


@pytest.fixture
def distributor_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["distributor_headers"]
