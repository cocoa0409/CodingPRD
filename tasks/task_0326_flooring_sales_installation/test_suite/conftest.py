"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, injects API_BASE_URL,
and restarts the server (empty database) before every individual test.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS, ANONYMOUS_HEADERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def estimator_headers():
    return TEST_USERS["estimator_headers"]


@pytest.fixture
def scheduler_headers():
    return TEST_USERS["scheduler_headers"]


@pytest.fixture
def sales_rep_headers():
    """Shared SalesRep constant. Use make_sales_rep_headers(rep_id) for ownership-gated calls."""
    return TEST_USERS["sales_rep_headers"]


@pytest.fixture
def customer_headers():
    """Shared Customer constant. Use make_customer_headers(cust_id) for ownership-gated calls."""
    return TEST_USERS["customer_headers"]


@pytest.fixture
def anonymous_headers():
    return ANONYMOUS_HEADERS
