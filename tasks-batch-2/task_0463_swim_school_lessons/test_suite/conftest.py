"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable and manages server
lifecycle (the server is killed and relaunched before every test).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def school_admin_headers():
    return TEST_USERS["school_admin_headers"]


@pytest.fixture
def billing_admin_headers():
    return TEST_USERS["billing_admin_headers"]


@pytest.fixture
def instructor_headers():
    return TEST_USERS["instructor_headers"]


@pytest.fixture
def parent_headers():
    return TEST_USERS["parent_headers"]
