"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable and manages the server
lifecycle (restarted before every test), so each test starts against an empty DB.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def airport_authority_headers():
    return TEST_USERS["airport_authority_headers"]


@pytest.fixture
def curb_coordinator_headers():
    return TEST_USERS["curb_coordinator_headers"]


@pytest.fixture
def operator_headers():
    """Shared Operator constant — for non-ownership tests only. Ownership-gated
    calls must use make_operator_headers(operator_id) with the real operator id."""
    return TEST_USERS["operator_headers"]
