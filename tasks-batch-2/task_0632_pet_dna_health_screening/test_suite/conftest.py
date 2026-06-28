"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, and manages the
server lifecycle (restart before every test).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def lab_headers():
    return TEST_USERS["lab_technician_headers"]


@pytest.fixture
def vet_headers():
    return TEST_USERS["veterinarian_headers"]


@pytest.fixture
def account_headers():
    return TEST_USERS["account_headers"]
