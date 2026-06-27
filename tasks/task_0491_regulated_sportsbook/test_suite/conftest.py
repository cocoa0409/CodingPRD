"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, and restarts the
server (fresh empty DB) before every test.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def bettor_headers():
    return TEST_USERS["bettor_headers"]


@pytest.fixture
def trading_ops_headers():
    return TEST_USERS["trading_ops_headers"]


@pytest.fixture
def settlement_agent_headers():
    return TEST_USERS["settlement_agent_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]
