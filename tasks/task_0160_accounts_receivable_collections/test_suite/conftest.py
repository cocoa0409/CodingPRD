"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable, and manages the
server lifecycle (restarting it before every test against an empty database).
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle owned by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def ar_manager_headers():
    return TEST_USERS["ar_manager_headers"]


@pytest.fixture
def ar_clerk_headers():
    return TEST_USERS["ar_clerk_headers"]


@pytest.fixture
def collections_agent_headers():
    return TEST_USERS["collections_agent_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
