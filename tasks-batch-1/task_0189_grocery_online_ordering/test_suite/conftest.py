"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle and PYTHONPATH, so test_helpers is importable
directly. Server is restarted (empty DB) before every individual test.
"""
import pytest
from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
    make_platform_admin_headers,
    make_store_ops_headers,
    make_customer_headers,
    make_picker_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def store_ops_headers():
    return TEST_USERS["store_ops_headers"]


@pytest.fixture
def customer_headers():
    """Shared Customer header constant. Use ONLY for non-ownership-gated calls.
    For ownership-gated calls, build per-customer headers via make_customer_headers(id)."""
    return TEST_USERS["customer_headers"]


@pytest.fixture
def picker_headers():
    """Shared Picker header constant. Use ONLY for non-ownership-gated calls."""
    return TEST_USERS["picker_headers"]


@pytest.fixture
def headers_factory():
    """Factory exposing builder functions so tests can mint per-entity headers."""
    return {
        "platform_admin": make_platform_admin_headers,
        "store_ops": make_store_ops_headers,
        "customer": make_customer_headers,
        "picker": make_picker_headers,
    }
