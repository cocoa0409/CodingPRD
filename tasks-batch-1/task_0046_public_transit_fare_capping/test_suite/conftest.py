"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, injects API_BASE_URL,
and restarts the server before each test. These fixtures just wire helpers in.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def fare_admin_headers():
    return TEST_USERS["fare_admin_headers"]


@pytest.fixture
def employer_admin_headers():
    return TEST_USERS["employer_admin_headers"]


@pytest.fixture
def payment_gateway_headers():
    return TEST_USERS["payment_gateway_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def rider_headers():
    """Shared Rider fallback header (non-ownership tests only). For ownership-gated
    calls, build headers with the real rider id via make_rider_headers()."""
    return TEST_USERS["rider_headers"]
