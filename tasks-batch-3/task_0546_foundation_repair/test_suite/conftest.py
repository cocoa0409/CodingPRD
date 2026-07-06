"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable, and manages the server
lifecycle (restarting via start.sh before every test). conftest just wires fixtures.
"""
import pytest

from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
    make_customer_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def sales_agent_headers():
    return TEST_USERS["sales_agent_headers"]


@pytest.fixture
def field_engineer_headers():
    return TEST_USERS["field_engineer_headers"]


@pytest.fixture
def ops_coordinator_headers():
    return TEST_USERS["ops_coordinator_headers"]


@pytest.fixture
def claims_adjuster_headers():
    return TEST_USERS["claims_adjuster_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def customer_headers():
    """Shared Customer constant. Use ONLY for non-ownership-gated calls; for ownership-gated
    calls mint per-lead headers with make_customer_headers(lead_id)."""
    return TEST_USERS["customer_headers"]


@pytest.fixture
def customer_headers_factory():
    """Expose make_customer_headers so tests can bind a Customer identity to a Lead id."""
    return make_customer_headers
