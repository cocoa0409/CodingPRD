"""Pytest fixtures exposing test_helpers infrastructure.

The prd-bench-local-runner framework injects API_BASE_URL and PYTHONPATH; the server
process is restarted before every individual test, so each test starts against an
empty database. All entity/state setup must be built from PRD-declared endpoints
inside the test itself (or via a fixture from test_helpers).
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS
from test_helpers.test_users import anonymous_headers as _anonymous_headers


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


# One fixture per role from TEST_USERS. Ownership-gated tests should NOT use these
# constants — see make_customer_headers(customer["id"]) in test_helpers.
@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]


@pytest.fixture
def fulfillment_ops_headers():
    return TEST_USERS["fulfillment_ops_headers"]


@pytest.fixture
def billing_admin_headers():
    return TEST_USERS["billing_admin_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def anonymous_headers():
    return _anonymous_headers()
