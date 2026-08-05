"""Pytest fixtures exposing test_helpers infrastructure.

The prd-bench-local-runner sets PYTHONPATH so `test_helpers` is importable and manages
the server lifecycle (restarting it before every test). These fixtures only wire data.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def counselor_headers():
    return TEST_USERS["counselor_headers"]


@pytest.fixture
def lab_headers():
    return TEST_USERS["lab_headers"]


@pytest.fixture
def billing_headers():
    return TEST_USERS["billing_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]
