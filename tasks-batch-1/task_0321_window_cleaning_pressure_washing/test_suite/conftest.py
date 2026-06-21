"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, and manages server
lifecycle (the API server is killed and relaunched before every test, so each
test starts against an empty database).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def billing_headers():
    return TEST_USERS["billing_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def field_crew_headers():
    return TEST_USERS["field_crew_headers"]


@pytest.fixture
def customer_headers():
    """Fallback Customer headers — use only for non-ownership tests (e.g. a 401/403
    that fires before any ownership check). Ownership-gated calls build per-instance
    headers via make_customer_headers(account_id)."""
    return TEST_USERS["customer_headers"]
