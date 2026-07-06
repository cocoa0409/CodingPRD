"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable and manages the
server lifecycle (a fresh server + empty database before every test).
"""
import pytest

from test_helpers import ApiClient, NO_ROLE_HEADERS, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def sales_rep_headers():
    return TEST_USERS["sales_rep_headers"]


@pytest.fixture
def scheduler_headers():
    return TEST_USERS["scheduler_headers"]


@pytest.fixture
def warranty_agent_headers():
    return TEST_USERS["warranty_agent_headers"]


@pytest.fixture
def no_role_headers():
    return NO_ROLE_HEADERS
