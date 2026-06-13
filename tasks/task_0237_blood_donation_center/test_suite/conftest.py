"""Pytest fixtures exposing test_helpers infrastructure.

The runner handles PYTHONPATH so test_helpers is importable, and owns the server
lifecycle (it restarts the API server before every individual test).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def center_admin_headers():
    return TEST_USERS["center_admin_headers"]


@pytest.fixture
def intake_nurse_headers():
    return TEST_USERS["intake_nurse_headers"]


@pytest.fixture
def lab_technician_headers():
    return TEST_USERS["lab_technician_headers"]


@pytest.fixture
def inventory_manager_headers():
    return TEST_USERS["inventory_manager_headers"]


@pytest.fixture
def donor_headers():
    return TEST_USERS["donor_headers"]
