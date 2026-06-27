"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable, sets API_BASE_URL,
and restarts the server before every test (each test starts against an empty DB).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def apiary_manager_headers():
    return TEST_USERS["apiary_manager_headers"]


@pytest.fixture
def state_apiarist_headers():
    return TEST_USERS["state_apiarist_headers"]


@pytest.fixture
def contract_coordinator_headers():
    return TEST_USERS["contract_coordinator_headers"]
