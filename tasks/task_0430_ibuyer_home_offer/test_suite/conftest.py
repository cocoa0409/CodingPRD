"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
    make_seller_headers,
    make_pricing_analyst_headers,
    make_operations_admin_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def seller_headers():
    """Shared Seller header constant. Use ONLY for non-ownership-gated calls.
    For ownership-gated calls, mint per-seller headers with
    make_seller_headers(seller_id)."""
    return TEST_USERS["seller_headers"]


@pytest.fixture
def pricing_analyst_headers():
    return TEST_USERS["pricing_analyst_headers"]


@pytest.fixture
def operations_admin_headers():
    return TEST_USERS["operations_admin_headers"]


@pytest.fixture
def headers_factory():
    """Factory exposing builder functions so tests can mint per-identity headers."""
    return {
        "seller": make_seller_headers,
        "pricing_analyst": make_pricing_analyst_headers,
        "operations_admin": make_operations_admin_headers,
    }
