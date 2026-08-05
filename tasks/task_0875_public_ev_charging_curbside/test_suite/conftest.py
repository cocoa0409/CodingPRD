"""Pytest fixtures exposing test_helpers infrastructure.

The prd-bench-local-runner sets PYTHONPATH so `test_helpers` is importable, and
manages server lifecycle (restarting the server + resetting the database and the
logical clock before every test).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def tech():
    return TEST_USERS["tech_headers"]


@pytest.fixture
def driver():
    return TEST_USERS["driver_headers"]
