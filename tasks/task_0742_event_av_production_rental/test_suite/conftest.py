"""Pytest fixtures exposing test_helpers infrastructure.

The prd-bench-local-runner sets PYTHONPATH (so `test_helpers` imports cleanly) and
manages server lifecycle — restarting the API before every test against an empty
database. These fixtures only wire up the client and role headers.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def account_manager_headers():
    return TEST_USERS["account_manager_headers"]


@pytest.fixture
def warehouse_manager_headers():
    return TEST_USERS["warehouse_manager_headers"]


@pytest.fixture
def crew_chief_headers():
    return TEST_USERS["crew_chief_headers"]


@pytest.fixture
def client_headers():
    return TEST_USERS["client_headers"]
