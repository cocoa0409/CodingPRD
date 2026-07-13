"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def registrar_headers():
    return TEST_USERS["registrar_headers"]


@pytest.fixture
def safety_admin_headers():
    return TEST_USERS["safety_admin_headers"]


@pytest.fixture
def licensed_inspector_headers():
    return TEST_USERS["licensed_inspector_headers"]


@pytest.fixture
def building_owner_headers():
    return TEST_USERS["building_owner_headers"]
